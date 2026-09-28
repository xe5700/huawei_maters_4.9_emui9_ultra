#!/usr/bin/env python3
"""Repair the Huawei hw_netfilter frozen-assembly ABI mismatch.

WHY THIS IS NEEDED
------------------
drivers/huawei_platform/net/hw_netfilter/*.S are *pre-generated assembly*
shipped by Huawei. The vendor CI compiled them with CONFIG_NET_NS=n, so in
their build `struct sock_common.skc_net` (type `possible_net_t`) occupied
0 bytes. Our rebuild enables CONFIG_NET_NS=y (Droidspaces), which makes
`possible_net_t` contain a `struct net *` and therefore 8 bytes. That grows
sock_common from 136 to 144 bytes and shifts *every later member of
struct sock by +8* (struct sock: 936 -> 944).

Because .S holds hard-coded numeric immediates, the assembler cannot
recompute them; the vendor code silently dereferences the wrong fields.
Concretely, `ldr x0,[x0,#744]` -- meant to load sk->sk_socket -- actually
loads our sk_stamp low word, then dereferences it, producing the observed
panic:

    Unable to handle kernel paging request at virtual address 00030018
    PC is at net_hw_hook_localout+0x170/0x22c

WHAT THIS SCRIPT DOES
---------------------
Rewrites only the affected immediates in nf_hw_hook.S so the vendor
assembly matches the kernel's actual struct sock layout. This keeps
CONFIG_NET_NS=y (containers keep working) and keeps the Huawei packet
filter enabled.

The other three modules (nf_ad_filter, nf_app_dl_monitor, nf_hw_common)
contain no struct sock accesses at all, so they need no change -- verified
both by their C logic and by scanning every memory operand in the .S.

Run with --check to verify without writing.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
while not os.path.exists(os.path.join(HERE, 'drivers', 'huawei_platform')) and HERE != '/':
    HERE = os.path.dirname(HERE)

TARGET = os.path.join(
    HERE, 'drivers/huawei_platform/net/hw_netfilter/nf_hw_hook.S')

# (vendor immediate, corrected immediate, what the access really is)
FIXES = [
    (744, 752, 'find_skb_uid(): sk->sk_socket  (skbuff->sk -> sock)'),
    (616, 624, 'send_reject_error(): sk->sk_err = ECONNRESET'),
    (840, 848, 'send_reject_error(): sk->sk_error_report(sk)'),
]

# Offsets that are legitimately shared with other (unchanged) structs and
# must NOT be rewritten. skb->sk is 24 in both layouts; skc_state is 18.
GUARD_OFFSETS = {18, 24, 28, 152, 156, 216, 218, 220, 224, 228, 232, 240}

# Match the whole instruction so we only touch the intended operand.
INSN = re.compile(r'^(\s*)(ldr|str|ldrb|strb|ldrh|strh|ldrsw)(\s+)(\S+)(\s*,\s*)'
                  r'\[\s*(\S+)\s*,\s*(\d+)\s*\]\s*$')


def main():
    check_only = '--check' in sys.argv
    if not os.path.exists(TARGET):
        sys.exit('ERROR: %s not found' % TARGET)

    with open(TARGET, 'r', encoding='utf-8', errors='surrogateescape') as f:
        lines = f.read().split('\n')

    plan = []          # (lineno, old_offset, new_offset, text)
    for i, line in enumerate(lines):
        m = INSN.match(line.rstrip('\n'))
        if not m:
            continue
        off = int(m.group(7))
        base = m.group(6)
        if base in ('x29', 'sp'):
            continue
        for old, new, _why in FIXES:
            if off == old:
                # Safety: never touch an offset we did not prove is struct sock.
                if off in GUARD_OFFSETS:
                    sys.exit('ERROR: refusing to patch guarded offset %d at line %d'
                             % (off, i + 1))
                plan.append((i + 1, old, new, line.strip()))
                break

    if not plan:
        sys.exit('ERROR: no patch sites found -- already patched, or the file changed')

    print('Patch plan for %s' % os.path.relpath(TARGET, HERE))
    print('-' * 72)
    for ln, old, new, text in plan:
        print('  L%-6d  %-9d -> %-9d  %s' % (ln, old, new, text))
    print('-' * 72)
    print('  %d instruction(s)' % len(plan))

    # Each expected fix must appear exactly once (no silent mass rewrite).
    counts = {}
    for _ln, old, _new, _t in plan:
        counts[old] = counts.get(old, 0) + 1
    expect = {744: 1, 616: 2, 840: 1}
    for off, want in expect.items():
        got = counts.get(off, 0)
        if got != want:
            sys.exit('ERROR: offset %d found %d time(s), expected %d'
                     % (off, got, want))

    if check_only:
        print('\n--check: no changes written.')
        return

    for ln, old, new, _text in plan:
        line = lines[ln - 1]
        lines[ln - 1] = re.sub(r'(\[\s*\S+\s*,\s*)%d(\s*\])' % old,
                               r'\g<1>%d\g<2>' % new, line)

    tmp = TARGET + '.tmp'
    with open(tmp, 'w', encoding='utf-8', errors='surrogateescape') as f:
        f.write('\n'.join(lines))
    os.replace(tmp, TARGET)
    print('\nWrote %s' % os.path.relpath(TARGET, HERE))
    print('Now rebuild and confirm with: ./.scratch/verify_abi.sh')


if __name__ == '__main__':
    main()