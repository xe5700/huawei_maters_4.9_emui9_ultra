#!/usr/bin/env python3
"""abi-guard: detect struct-layout (ABI) drift between vendor prebuilt
assembly and the kernel you are actually building.

WHY THIS EXISTS
---------------
Some Huawei/HiSilicon kernel drivers are shipped as *pre-generated assembly*
(`*.S`) rather than C. Those files still contain full DWARF (`.file`/`.loc`
directives plus a `.debug_info` section), so the vendor's compiler baked in
numeric struct offsets as immediate operands. The assembler does NOT
recompute them, so if your build's `struct` layout differs from the config
the vendor CI used, the code silently reads the wrong fields.

This is exactly how the MateRS NEO (Kirin 970, EMUI 9.1, 4.9.148) panic
`net_hw_hook_localout+0x170` happened: enabling CONFIG_NET_NS=y grew
`possible_net_t` from 0 to 8 bytes, shifting every later `struct sock`
member by +8, and the frozen `ldr x0,[x0,#744]` then dereferenced garbage.

HOW IT WORKS
------------
For each prebuilt object:
  1. Read the *vendor's* struct layouts from the object's own DWARF.
  2. Read *your kernel's* layouts from out/vmlinux DWARF.
  3. Diff field offsets for every struct present in both.
  4. List the numeric immediates in the corresponding .S that equal a
     stale (vendor) offset, tagged with the function and source line.

One `pahole <binary>` dump per binary is parsed for every struct at once;
per-struct `pahole -C` calls were ~500x slower and are not used.

WHAT THIS TOOL DOES *NOT* PROVE  -- read this before trusting the output
-----------------------------------------------------------------------
Step 4 produces CANDIDATES, never verdicts. A numeric offset is shared by
dozens of unrelated structs, so "offset 216 appears in the .S and
struct foo has a field at 216" does NOT mean that instruction touches
foo. Two real examples from nf_hw_hook.S:

  * `ldr w0, [x21,80]` matches `dl_info.dlid` (module-local struct, 4 bytes)
    AND `struct net.exit_list` (8 bytes) AND `sock_common.skc_cookie`.
    Its true owner is the module-local `dl_info`; `struct net` is noise.
  * `ldr x0, [x0,216]` in net_hw_hook_localout matches `net.proc_net`
    (drifted) and `request_sock.saved_syn` (drifted), but its true owner
    is `struct file.f_cred`, which is NOT drifted.

So this tool finds where to LOOK; it cannot decide what you are looking at.
To attribute an offset to a struct you need one of:

  * `.loc` attribution -- the .S embeds the original C path and line
    numbers, so you can read the C expression the instruction came from
    (tools/abi-locattr.py; HUAWEI_ABI_GUIDE.md section 4).
  * Data-flow tracing -- follow the base register back to its producer.
    This is what proved the MateRS bug was exactly 4 instructions
    (tools/abi-sockflow.py; HUAWEI_ABI_GUIDE.md section 5).

The `--candidates` view lists concrete .S sites so those two checks are
quick. Treat every candidate as unproven until one of them confirms it.

DUPLICATE STRUCT NAMES
----------------------
`out/vmlinux` DWARF merges every linked object, including the vendor
blobs, so a struct can appear with SEVERAL layouts. The real `struct sock`
is 944 bytes (935 blocks) while the vendor blobs contribute a stale
936-byte copy (2 blocks). This tool picks the layout with the most blocks
and reports the alternatives, so the drift is measured against the
definition the kernel actually compiles with.

Usage:
    python3 tools/abi-guard.py                 # scan every prebuilt .S
    python3 tools/abi-guard.py --obj PATH      # scan one object
    python3 tools/abi-guard.py --summary       # one line per drifted struct
    python3 tools/abi-guard.py --candidates    # also list .S sites

Exit code 1 if any drift is found, so it can gate a build.
"""

import argparse
import collections
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
while not os.path.exists(os.path.join(HERE, 'drivers')) and HERE != '/':
    HERE = os.path.dirname(HERE)
KERNEL = os.path.join(HERE, 'out/vmlinux')

# Assembly files that contain no struct accesses at all; skipping keeps
# the scan fast (crypto/arch/lib routines are pure register code).
SKIP_DIRS = ('arch/arm64/crypto', 'arch/arm64/kernel', 'arch/arm64/lib',
             'arch/arm64/mm', 'usr/')

# One struct field line, e.g.
#   struct list_head *         next;                 /*     0     8 */
#   unsigned int               cap[2];               /*     0     8 */
#   void                       (*sk_error_report)(struct sock *); /* 848 8 */
#   } sk_backlog;                                    /*   256    24 */
# The field name is recovered from the text BEFORE the trailing
# /* offset size */ comment: function pointers need a separate pattern
# (`(*name)(...)`), which a single `name;` regex cannot match. Getting this
# wrong silently drops every function-pointer field from the comparison --
# exactly how sk_error_report's 840->848 drift first went unnoticed.
FIELD_RE = re.compile(r'^(?P<body>.*?)/\*\s*(?P<off>\d+)\s+(?P<size>\d+)\s*\*/')
FUNCPTR_RE = re.compile(r'\(\s*\*\s*([A-Za-z_]\w*)\s*\)')
NAME_RE = re.compile(r'([A-Za-z_]\w*)\s*(?:\[\d+\])?\s*;\s*$')
HDR_RE = re.compile(r'^(struct|union|class)\s+([A-Za-z_]\w*)\s*\{')
SIZE_RE = re.compile(r'^\s*/\*\s*size:\s*(\d+),')


def field_of(line):
    """(name, offset, size) for one pahole field line, or None."""
    m = FIELD_RE.match(line)
    if not m:
        return None
    body = m.group('body')
    if ';' not in body:          # hole/padding annotation, not a field
        return None
    fm = FUNCPTR_RE.search(body)
    if fm:
        name = fm.group(1)
    else:
        nm = NAME_RE.search(body)
        if not nm:
            return None
        name = nm.group(1)
    return name, int(m.group('off')), int(m.group('size'))

# Capture the mnemonic AND the destination register so we can infer access
# width, which is the key disambiguator between unrelated structs that
# happen to share an offset.
OFF_RE = re.compile(
    r'\b(ldrb|strb|ldrh|strh|ldrsw|ldrsb|ldrsh|ldr|str)\s+'
    r'(x\d+|w\d+)\s*,\s*\[\s*(x\d+|w\d+|sp)\s*,\s*#?(\d+)\s*\]')

# mnemonic -> access width in bytes
WIDTH = {
    'ldrb': 1, 'strb': 1,
    'ldrh': 2, 'strh': 2,
    'ldrsb': 1, 'ldrsh': 2,
    'ldrsw': 4,
    'ldr': None, 'str': None,   # decided by destination register
}


def run(cmd, timeout=600):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except Exception:
        return ''


def parse_layouts(path):
    """One `pahole` dump -> {name: (size, {field: (offset, size)}, nblocks)}.

    When the same struct name appears with different sizes (vmlinux merges
    the vendor blobs' DWARF), the layout with the most blocks wins and the
    losing sizes are recorded so the caller can flag the conflict.
    """
    out = run(['pahole', path])
    if not out:
        return {}
    groups = collections.defaultdict(list)      # name -> [(size, fields)]
    name = None
    fields = None
    size = None
    for line in out.split('\n'):
        if name is None:
            m = HDR_RE.match(line)
            if m:
                name, fields, size = m.group(2), {}, None
            continue
        if line.startswith('};'):
            groups[name].append((size, fields))
            name = fields = size = None
            continue
        if size is None:
            m = SIZE_RE.match(line)
            if m:
                size = int(m.group(1))
        f = field_of(line)
        if f and f[0] not in fields:
            fields[f[0]] = (f[1], f[2])

    result = {}
    for nm, blocks in groups.items():
        # A forward declaration or an opaque type has no size line.
        blocks = [(s, f) for s, f in blocks if s is not None]
        if not blocks:
            continue
        counts = collections.Counter(s for s, _ in blocks)
        best_size = counts.most_common(1)[0][0]
        for s, f in blocks:
            if s == best_size:
                result[nm] = (s, f, len(blocks), sorted(counts))
                break
    return result


def access_width(mnemonic, dst):
    """Infer the number of bytes an instruction reads/writes."""
    w = WIDTH.get(mnemonic)
    if w is not None:
        return w
    return 8 if dst.startswith('x') else 4


def asm_offsets(path):
    """offset -> Counter of (mnemonic, width) used in a .S file.

    Only non-stack bases are considered. Width matters: an offset that is
    only ever touched as a byte/word cannot be a pointer-sized field.
    """
    c = collections.defaultdict(collections.Counter)
    for line in open(path, errors='replace'):
        s = line.lstrip()
        if s.startswith(('.', '#', '/*', '*')):
            continue
        for m in OFF_RE.finditer(line):
            mnem, dst, base, off = m.groups()
            if base in ('sp', 'x29'):
                continue
            c[int(off)][(mnem, access_width(mnem, dst))] += 1
    return c


def asm_uses(path):
    """offset -> [(line_no, function, mnemonic, width)] for candidate sites.

    Function attribution matters: knowing an offset appears inside
    net_hw_hook_localout (which dereferences skb->sk) is far more useful
    than knowing it appears somewhere in a 62k-line file.
    """
    uses = collections.defaultdict(list)
    func = '?'
    for n, line in enumerate(open(path, errors='replace'), 1):
        s = line.lstrip()
        if s and not s[0].isspace() and s.rstrip().endswith(':'):
            cand = s.rstrip()[:-1]
            if cand and not cand.startswith('.') and '(' not in cand:
                func = cand
        if s.startswith(('.', '#', '/*', '*')):
            continue
        for m in OFF_RE.finditer(line):
            mnem, dst, base, off = m.groups()
            if base in ('sp', 'x29'):
                continue
            uses[int(off)].append(
                (n, func, mnem, access_width(mnem, dst)))
    return uses


def find_prebuilt():
    out = []
    for root, dirs, files in os.walk(HERE):
        rel = os.path.relpath(root, HERE)
        if rel.startswith(('out', '.git', '.scratch')):
            dirs[:] = []
            continue
        if any(rel.startswith(s.rstrip('/')) for s in SKIP_DIRS):
            continue
        for f in files:
            if f.endswith('.S'):
                out.append(os.path.join(root, f))
    return sorted(out)


def scan_object(obj, kernel_cache):
    """Return {struct: (bad_fields, alt_sizes)} for drifted structs.

    bad_fields is [(field, vendor_off, kernel_off), ...].
    """
    vlay = parse_layouts(obj)
    if not vlay:
        return None
    if KERNEL not in kernel_cache:
        kernel_cache[KERNEL] = parse_layouts(KERNEL)
    klay = kernel_cache[KERNEL]

    drift = {}
    for st, (vsz, vf, _nb, _alts) in vlay.items():
        if st.startswith('_'):
            continue
        entry = klay.get(st)
        if entry is None:
            continue
        ksz, kf, _knb, kalts = entry
        bad = [(f, off, kf[f][0]) for f, (off, _s) in vf.items()
               if f in kf and off != kf[f][0]]
        if bad:
            drift[st] = (bad, kalts if len(kalts) > 1 else [])
    return drift


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obj', help='scan a single object')
    ap.add_argument('--summary', action='store_true',
                    help='only one line per drifted struct')
    ap.add_argument('--candidates', action='store_true',
                    help='also list every .S site using a drifted offset')
    args = ap.parse_args()

    if not os.path.exists(KERNEL):
        sys.exit('ERROR: %s not found; build the kernel first' % KERNEL)

    if args.obj:
        targets = [args.obj]
    else:
        targets = []
        for s in find_prebuilt():
            o = os.path.join(HERE, 'out', os.path.relpath(
                os.path.splitext(s)[0], HERE) + '.o')
            if os.path.exists(o):
                targets.append(o)

    cache = {}
    total_drift = 0
    total_stale = 0
    print('abi-guard: comparing vendor prebuilt objects against %s'
          % os.path.relpath(KERNEL, HERE))
    print('=' * 78)

    for obj in targets:
        drift = scan_object(obj, cache)
        if drift is None:
            continue
        rel = os.path.relpath(obj, HERE)
        if not drift:
            if not args.summary:
                print('\n--- %s : OK (no struct drift)' % rel)
            continue

        # Which stale immediates actually appear in the matching .S?
        # These are CANDIDATES only -- see the module docstring for why an
        # offset value can never by itself attribute a field to a struct.
        sfile = os.path.join(HERE, os.path.splitext(
            os.path.relpath(obj, os.path.join(HERE, 'out')))[0] + '.S')
        used = asm_offsets(sfile) if os.path.exists(sfile) else {}
        uses = asm_uses(sfile) if (args.candidates and os.path.exists(sfile)) \
            else {}

        print('\n--- %s' % rel)
        kfields_all = cache[KERNEL]
        for st in sorted(drift):
            bad, alts = drift[st]
            kfields = kfields_all.get(st, (0, {}, 0, []))[1]
            # offset -> set of field sizes that live at that offset in the
            # kernel layout. Used to decide whether an instruction that uses
            # the VENDOR offset could still be correct here.
            koff_sizes = collections.defaultdict(set)
            for (_o, _s) in kfields.values():
                koff_sizes[_o].add(_s)
            stale = []
            ambiguous = []
            for f, vo, ko in bad:
                accesses = used.get(vo)
                if not accesses:
                    continue
                fsize = kfields.get(f, (0, 0))[1]
                widths = set(w for _m, w in accesses)
                # width-compatible => plausible candidate (still unproven)
                if not (fsize and fsize in widths):
                    continue
                n = sum(c for (_m, w), c in accesses.items() if w == fsize)
                rec = (f, vo, ko, n, sorted(widths))
                # The vendor offset is also a valid KERNEL offset at the SAME
                # access width => an instruction using it may already be
                # correct (e.g. a tree where the .S has been fixed: 752 is
                # kernel sk_socket but vendor sk_user_data, both 8 bytes).
                # Value matching alone cannot decide, so flag separately.
                if fsize in koff_sizes.get(vo, ()):
                    ambiguous.append(rec)
                else:
                    stale.append(rec)
            flags = []
            if stale:
                flags.append('%d stale candidate field(s)' % len(stale))
            if ambiguous:
                flags.append('%d ambiguous field(s)' % len(ambiguous))
            total_stale += len(stale)
            flag = ('  <-- ' + '; '.join(flags)) if flags else ''
            print('    struct %-26s %d field(s) drifted%s'
                  % (st, len(bad), flag))
            if alts:
                print('        NOTE: vmlinux has several layouts for this '
                      'struct (sizes %s); used the most common one.'
                      % ', '.join(str(a) for a in alts))
            if args.summary:
                continue
            tag_of = {}
            for rec in stale:
                tag_of[rec[1]] = 'STALE'
            for rec in ambiguous:
                tag_of.setdefault(rec[1], 'AMBIG')
            cand_map = dict((vo, (n, ws)) for _f, vo, _k, n, ws in
                            stale + ambiguous)
            for f, vo, ko in bad:
                info = cand_map.get(vo)
                note = ''
                if info:
                    note = '   offset used x%d (widths %s) [%s]' % (
                        info[0], info[1], tag_of.get(vo, '?'))
                print('        %-28s vendor=%-6d kernel=%-6d delta=%+d%s'
                      % (f, vo, ko, ko - vo, note))
                if args.candidates and info:
                    for (ln, fn, mn, w) in uses.get(vo, []):
                        if w in info[1]:
                            print('            %s:%d  in %s()  [%d bytes]'
                                  % (os.path.basename(sfile), ln, fn, w))
        total_drift += len(drift)

    print()
    print('=' * 78)
    if total_drift:
        print('RESULT: %d struct(s) show layout drift.' % total_drift)
        print('        %d STALE candidate field(s): the .S uses the vendor '
              'offset,' % total_stale)
        print('        which is NOT a valid offset in your kernel layout -- '
              'these are')
        print('        the ones that can actually be wrong. AMBIG fields use '
              'a number')
        print('        that is valid for BOTH layouts, so a value match '
              'cannot decide:')
        print('        e.g. after a successful fix, 752 is kernel sk_socket '
              'but vendor')
        print('        sk_user_data, and the instruction is already correct.')
        print('NOTE: even a STALE hit is a place to LOOK, not a verdict -- '
              'the same')
        print('      numeric offset is shared by many unrelated structs. '
              'Confirm with')
        print('      .loc attribution (tools/abi-locattr.py) or data-flow '
              'tracing')
        print('      (tools/abi-sockflow.py) before changing anything '
              '(HUAWEI_ABI_GUIDE.md 4-5).')
        return 1
    print('RESULT: no struct layout drift detected.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
