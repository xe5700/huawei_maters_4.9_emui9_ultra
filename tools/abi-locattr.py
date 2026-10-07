#!/usr/bin/env python3
"""abi-locattr: attribute struct offsets in a prebuilt .S to their real struct.

THE PROBLEM THIS SOLVES
-----------------------
`abi-guard.py` finds numeric offsets that appear in a .S and match a drifted
struct field -- but a numeric offset is shared by many unrelated structs, so
that match is a candidate, not a verdict. This tool supplies the missing
evidence.

Huawei's prebuilt .S files embed full DWARF: `.file N "path"` declares the
source files the original C was compiled from, and `.loc N LINE` records
which of them each instruction came from. Since the vendor .S lists the
*system* headers it included (sock.h, skbuff.h, ...), the header a given
instruction maps to tells you which struct it actually touches.

Output: for every non-stack offset, the set of header basenames that the
instructions using it were attributed to. Read it as:

    off 216    skbuff.h x3, file.h x1

i.e. offset 216 is used from code attributed to skbuff.h and file.h --
NOT from net.h, so the `struct net.proc_net` candidate from abi-guard.py
is a false positive.

Note `.loc` gives the header, not the exact struct: a header can define
several structs. Use it to INCLUDE/EXCLUDE candidate headers, then confirm
with data-flow tracing (abi-sockflow.py) or by reading the vendor C source
where available (HarmonyOS trees ship nf_hw_hook.c).

Usage:
    python3 tools/abi-locattr.py                       # all prebuilt .S
    python3 tools/abi-locattr.py FILE.S [FILE.S ...]   # specific files
    python3 tools/abi-locattr.py --offset 216 FILE.S   # one offset, with sites
"""

import argparse
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
while not os.path.exists(os.path.join(HERE, 'drivers')) and HERE != '/':
    HERE = os.path.dirname(HERE)

FILE_RE = re.compile(r'^\s*\.file\s+(\d+)\s+"([^"]+)"')
LOC_RE = re.compile(r'^\s*\.loc\s+(\d+)\s+(\d+)')
OFF_RE = re.compile(
    r'\b(ldrb|strb|ldrh|strh|ldrsw|ldrsb|ldrsh|ldr|str)\s+'
    r'(x\d+|w\d+)\s*,\s*\[\s*(x\d+|w\d+|sp)\s*,\s*#?(\d+)\s*\]')


def parse(path):
    """Return (files, rows) where rows = [(header, line, off, ins)]."""
    files = {}
    cur = None
    rows = []
    for line in open(path, errors='replace'):
        m = FILE_RE.match(line)
        if m:
            files[m.group(1)] = os.path.basename(m.group(2))
            continue
        m = LOC_RE.match(line)
        if m:
            cur = (files.get(m.group(1), 'F' + m.group(1)), int(m.group(2)))
            continue
        s = line.strip()
        if not s or s.startswith(('.', '#')):
            continue
        for mm in OFF_RE.finditer(line):
            dst, base, off = mm.group(2), mm.group(3), int(mm.group(4))
            if base in ('x29', 'sp') or off < 8:
                continue
            rows.append((cur, dst, base, off, s))
    return files, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='*', help='.S files (default: all prebuilt)')
    ap.add_argument('--offset', type=int,
                    help='show individual sites for this offset')
    args = ap.parse_args()

    if args.files:
        targets = args.files
    else:
        targets = []
        for root, dirs, fs in os.walk(HERE):
            rel = os.path.relpath(root, HERE)
            if rel.startswith(('out', '.git', '.scratch')):
                dirs[:] = []
                continue
            for f in fs:
                if f.endswith('.S'):
                    targets.append(os.path.join(root, f))
        targets.sort()

    if not targets:
        sys.exit('no .S files found')

    for path in targets:
        files, rows = parse(path)
        if not rows:
            continue
        print('=' * 74)
        print('%s   (%d source files referenced by .loc)'
              % (os.path.relpath(path, HERE), len(files)))
        print('=' * 74)
        if not files:
            print('  no .file/.loc directives -- cannot attribute; this file')
            print('  is hand-written assembly with no vendor C origin.')
            print()
            continue
        agg = collections.defaultdict(collections.Counter)
        for loc, _dst, _base, off, _ins in rows:
            agg[off][loc[0] if loc else '<no-loc>'] += 1
        for off in sorted(agg):
            hdrs = agg[off]
            print('  off %-6d  %s' % (off, ', '.join(
                '%s x%d' % (h, n) for h, n in hdrs.most_common())))
            if args.offset is not None and off == args.offset:
                for loc, dst, base, o, ins in rows:
                    if o == off:
                        print('        %s:%s  [%s,%d]  %s'
                              % (loc[0] if loc else '?',
                                 loc[1] if loc else '?', base, off, ins))
        print()


if __name__ == '__main__':
    main()
