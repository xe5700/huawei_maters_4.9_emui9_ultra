#!/usr/bin/env python3
"""abi-sockflow: prove WHICH instructions in a prebuilt .S really touch a
given struct, by tracing how the pointer got into the base register.

WHY YOU NEED THIS
-----------------
`abi-guard.py` says "offset 744 appears in nf_hw_hook.S and struct sock has
a field at 744" -- a candidate. `abi-locattr.py` narrows it to a header.
This tool settles it: it follows the actual data flow, so an offset is only
reported if the register holding it provably came from the struct in
question.

HOW IT WORKS (the struct sock case)
-----------------------------------
The vendor netfilter modules only ever receive `struct sk_buff *` plus
pointers to their own module-local structs. The single way to reach a
`struct sock` is `skb->sk`, which is `sk_buff` offset 24. So:

  1. Any `ldr xN, [xM, #24]` (xM not sp/fp) marks xN as "points to sock".
  2. Any later access `[xN, #OFF]` where OFF is a field offset of the
     vendor's `struct sock` is a real sock dereference.
  3. Report it and show the corrected offset (OFF + SHIFT).

Registers are conservatively invalidated when they are reassigned, so the
output can in principle miss an access, but it does not invent one. Cross
check the total against `abi-locattr.py`.

ADAPTING TO ANOTHER STRUCT
--------------------------
Change VENDOR_SOCK_OFFS to the vendor field offsets, SKB_SK_OFF to the
offset of the pointer you start from, and SHIFT to the layout delta. Keep
the "root" load (step 1) as narrow as you can -- the narrower it is, the
more trustworthy the output.

Usage:
    python3 tools/abi-sockflow.py                    # all hw_netfilter .S
    python3 tools/abi-sockflow.py FILE.S [FILE.S ...]
    python3 tools/abi-sockflow.py --shift 8 FILE.S

Exit code 1 if any real access is found, so it can gate a build.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
while not os.path.exists(os.path.join(HERE, 'drivers')) and HERE != '/':
    HERE = os.path.dirname(HERE)

# Vendor (CONFIG_NET_NS=n) struct sock offsets that are real fields.
VENDOR_SOCK_OFFS = {
    616: 'sk_err',
    744: 'sk_socket',
    840: 'sk_error_report',
}
SKB_SK_OFF = 24     # sk_buff.sk -- the only entry point to struct sock
SHIFT = 8           # this build's layout is +8 vs the vendor's

LD_RE = re.compile(r'^\s*(ldr|ldrb|ldrh|ldrsb|ldrsh|ldrsw)\s+'
                   r'(x\d+|w\d+)\s*,\s*\[\s*(x\d+)\s*(?:,\s*#?(\d+))?\s*\]')
ST_RE = re.compile(r'^\s*(str|strb|strh)\s+(x\d+|w\d+)\s*,\s*'
                   r'\[\s*(x\d+)\s*(?:,\s*#?(\d+))?\s*\]')
FUNC_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*):\s*$')

# Data-processing forms whose FIRST operand is the destination.
DP_RE = re.compile(r'^\s*([a-z][a-z0-9.]*)\s+(x\d+|w\d+)\s*,')
MOV_RE = re.compile(r'^\s*mov\s+(x\d+|w\d+)\s*,\s*(x\d+|w\d+)\s*$')
# Instructions that branch-with-link: they clobber the caller-saved x0-x18.
BL_RE = re.compile(r'^\s*(bl|blr|blx)\b')
# Reads-only: never a destination.
READONLY = ('cbz', 'cbnz', 'tbz', 'tbnz', 'cmp', 'cmn', 'tst', 'b.', 'b\t',
            'ret', 'br', 'b', 'nop', 'adrp')


# Conditional branch on a register: `cbnz xN, .Lfoo`
CBR_RE = re.compile(r'^\s*(cbz|cbnz)\s+(x\d+|w\d+)\s*,\s*(\S+)\s*$')
# Unconditional branch to a label: `b .Lfoo`
B_RE = re.compile(r'^\s*b\s+(\S+)\s*$')
LABEL_RE = re.compile(r'^(\.L[A-Za-z0-9_.$]+):\s*$')


def norm(reg):
    """Map w0..w30 onto x0..x30 so both spellings share one slot."""
    return 'x' + re.sub(r'\D', '', reg)


def writes_of(ins):
    """Registers (normalised) that this instruction may overwrite.

    Being accurate here is what keeps the trace from losing real sites:
    an over-eager "any mention invalidates" rule drops the base register
    as soon as it is used as a source operand.
    """
    s = ins.strip()
    m = MOV_RE.match(s)
    if m:
        return [norm(m.group(1))]
    if BL_RE.match(s):
        return ['x%d' % i for i in range(0, 19)]
    if s.startswith('ret') or s.startswith('br '):
        return []
    op = s.split()[0] if s.split() else ''
    if op in READONLY or op.startswith('b.') or op.startswith('cb'):
        return []
    m = DP_RE.match(s)
    if m:
        dst = m.group(2)
        # `str`-like and `stp`-like forms have the destination in the
        # second slot; everything matched here is a real destination.
        if m.group(1).startswith(('str', 'stp')):
            return []
        return [norm(dst)]
    return []


def scan_once(path, vendor, root_off, label_state):
    """One linear pass. label_state maps a label to the sock-register set
    that is live on entry to it; it is both read (at label definitions) and
    updated (at branches), and the caller iterates to a fixpoint so that
    forward branches such as `cbnz x0, .L189` are followed correctly."""
    fn = None
    sock_regs = {}
    findings = []
    for i, line in enumerate(open(path, errors='replace'), 1):
        m = FUNC_RE.match(line)
        if m:
            fn = m.group(1)
            sock_regs = {}
            continue

        lab = LABEL_RE.match(line)
        if lab:
            # Merge whatever arrived here via a branch.
            for r, origin in label_state.get(lab.group(1), {}).items():
                sock_regs.setdefault(r, origin)
            continue

        s = line.strip()
        if not s or s.startswith(('.', '#')):
            continue

        m = LD_RE.match(s)
        if m:
            _op, dst, base, off = m.groups()
            off = int(off) if off else 0
            if off == root_off and base not in ('x29', 'sp'):
                sock_regs[norm(dst)] = (fn, i, s)
                continue
            if norm(base) in sock_regs and off in vendor and off != root_off:
                findings.append(('LOAD', fn, i, base, off, vendor[off], s))
                continue
            sock_regs.pop(norm(dst), None)
            continue

        m = ST_RE.match(s)
        if m:
            _op, _src, base, off = m.groups()
            off = int(off) if off else 0
            if norm(base) in sock_regs and off in vendor and off != root_off:
                findings.append(('STORE', fn, i, base, off, vendor[off], s))
            continue

        # `cbnz xN, .Lfoo` -- on the taken path xN still holds the sock.
        m = CBR_RE.match(s)
        if m:
            _op, reg, target = m.groups()
            r = norm(reg)
            if r in sock_regs and _op == 'cbnz':
                d = label_state.setdefault(target, {})
                d.setdefault(r, sock_regs[r])
            continue

        # `b .Lfoo` -- the whole current state flows to the target.
        m = B_RE.match(s)
        if m:
            d = label_state.setdefault(m.group(1), {})
            for r, origin in sock_regs.items():
                d.setdefault(r, origin)
            continue

        # Invalidate exactly the registers this instruction overwrites.
        # (Blanket "any mention" invalidation loses real sites: the base
        # register is usually also a source operand of the same insn.)
        for r in writes_of(s):
            sock_regs.pop(r, None)
    return findings


def scan(path, vendor, root_off, shift):
    """Iterate scan_once to a fixpoint so branch-carried state converges."""
    label_state = {}
    seen = set()
    for _ in range(8):
        findings = scan_once(path, vendor, root_off, label_state)
        key = tuple(sorted((k, tuple(sorted(v))) for k, v in label_state.items()))
        if key == seen:
            break
        seen = key
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='*', help='.S files (default: hw_netfilter)')
    ap.add_argument('--shift', type=int, default=SHIFT,
                    help='layout delta to apply (default %d)' % SHIFT)
    args = ap.parse_args()

    if args.files:
        targets = args.files
    else:
        d = os.path.join(HERE, 'drivers/huawei_platform/net/hw_netfilter')
        if not os.path.isdir(d):
            sys.exit('no .S files given and %s not found' % d)
        targets = [os.path.join(d, f) for f in sorted(os.listdir(d))
                   if f.endswith('.S')]

    total = 0
    for path in targets:
        fnd = scan(path, VENDOR_SOCK_OFFS, SKB_SK_OFF, args.shift)
        print('=== %s : %d struct-sock access(es)'
              % (os.path.relpath(path, HERE), len(fnd)))
        for kind, fn, ln, base, off, field, ins in fnd:
            print('   %-5s L%-6d [%s] off=%-5d %-18s %s'
                  % (kind, ln, fn, off, field, ins))
            print('         -> must become %d' % (off + args.shift))
        total += len(fnd)

    print()
    print('TOTAL struct-sock accesses needing +%d: %d'
          % (args.shift, total))
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
