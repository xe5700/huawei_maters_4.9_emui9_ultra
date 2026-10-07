#!/bin/bash
# abi-verify: assert that the patched hw_netfilter assembly matches the
# kernel's real struct sock ABI and no stale struct-sock immediate remains.
#
# Run this AFTER rebuilding. It inspects the compiled .o, so it catches the
# case where you edited the .S but the build did not pick it up (or you
# packaged an old Image.gz).
#
# Adapting to another struct/machine: change OFFSETS_STALE / OFFSETS_NEW and
# the function name below.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
TC=${CROSS_COMPILE:-/mnt/g/projects/huawei-phone-ssd-project/aarch64-linux-android-4.9-refs_heads_pie-release/bin/aarch64-linux-android-}
OBJ=$ROOT/out/drivers/huawei_platform/net/hw_netfilter/nf_hw_hook.o
VML=$ROOT/out/vmlinux
FUNC=net_hw_hook_localout
STALE="616 744 840"
NEW="624 752 848"

[ -f "$OBJ" ] || { echo "ERROR: $OBJ missing; build first"; exit 2; }
[ -f "$VML" ] || { echo "ERROR: $VML missing; build first"; exit 2; }

echo "=== 1. kernel's authoritative struct sock offsets ==="
pahole -C sock "$VML" 2>/dev/null \
  | grep -E '\bsk_err;|\bsk_socket;|\bsk_error_report\)'

echo
echo "=== 2. offsets used in $FUNC (rebuilt object) ==="
BODY=$("${TC}objdump" -d --no-show-raw-insn "$OBJ" 2>/dev/null \
      | sed -n "/<$FUNC>:/,/^\$/p")
echo "$BODY" | grep -E '\[x[0-9]+, ?#?[0-9]+\]' \
     | grep -E '#(616|624|744|752|840|848)\]' | sed 's/^/   /'

echo
echo "=== 3. assertions ==="
fail=0
for o in $STALE; do
  if echo "$BODY" | grep -qE "\[x[0-9]+, *#?$o\]"; then
    echo "   FAIL: stale vendor offset $o still present"; fail=1
  else echo "   ok: stale offset $o gone"; fi
done
for o in $NEW; do
  if echo "$BODY" | grep -qE "\[x[0-9]+, *#?$o\]"; then
    echo "   ok: corrected offset $o present"
  else echo "   FAIL: corrected offset $o missing"; fail=1; fi
done
echo
[ $fail -eq 0 ] && echo "ABI CHECK PASSED" || echo "ABI CHECK FAILED"
exit $fail
