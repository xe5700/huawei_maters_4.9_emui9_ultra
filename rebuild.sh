#!/bin/bash
#===============================================================================
# rebuild.sh — 增量构建脚本（相比 build.sh 省去不必要的重编）
#
# 背景：build.sh 每次都执行 `make O=out merge_kirin970_defconfig`。
#   仅改源码时这属于多余动作；而配置改动本身会触发 autoconf.h 更新，
#   进而让大量文件重编 —— 那是**必要代价**，不是浪费
#   （内核几乎所有源文件都包含配置头，故配置一变就要大面积重编）。
#
# 本脚本策略：按 defconfig 指纹决定是否需要重新生成配置
#   - 指纹一致 → 只跑 `make O=out -jN`（纯增量，通常几秒）
#   - 指纹变化 → 先 merge_kirin970_defconfig 再编译（配置变更必须重编）
#
# 关于 ccache：**不接入**。实测本树加 ccache 会导致内核编译器能力探测误判
#   （prepare-compiler-check 报 "-fstack-protector-strong not supported"），
#   且配置变更会令缓存大面积失效，收益有限。
#
# 用法: ./rebuild.sh [JOBS]        默认 JOBS=12
#       ./rebuild.sh 12 --force    强制重新生成 defconfig
#===============================================================================
set -euo pipefail

JOBS="${1:-12}"
FORCE="${2:-}"
MAX_JOBS="$(nproc)"
[ "$JOBS" -gt "$MAX_JOBS" ] && JOBS="$MAX_JOBS"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export ARCH=arm64
export SUBARCH=arm64
export CROSS_COMPILE="${CROSS_COMPILE:-/mnt/g/projects/huawei-phone-ssd-project/aarch64-linux-android-4.9-refs_heads_pie-release/bin/aarch64-linux-android-}"
export PATH="$(dirname "$CROSS_COMPILE"):$PATH"
export HOSTCFLAGS="${HOSTCFLAGS:--fcommon}"

DEFCONFIG="arch/arm64/configs/merge_kirin970_defconfig"
STAMP="out/.defconfig.sha256"
CUR_SHA="$(sha256sum "$DEFCONFIG" | awk '{print $1}')"
OLD_SHA="$(cat "$STAMP" 2>/dev/null || echo none)"

if [ "$FORCE" = "--force" ] || [ "$CUR_SHA" != "$OLD_SHA" ] || [ ! -f out/.config ]; then
    echo "==> defconfig 已变更（或首次构建），重新生成配置"
    make O=out merge_kirin970_defconfig
    echo "$CUR_SHA" > "$STAMP"
    MODE="配置变更"
else
    echo "==> defconfig 未变更，跳过配置生成（纯增量编译）"
    MODE="纯增量"
fi

echo "==> 编译 (-j${JOBS}, ${MODE})"
make O=out -j"${JOBS}"

echo "==> 产物"
ls -lh out/arch/arm64/boot/Image.gz
echo "完成。"
