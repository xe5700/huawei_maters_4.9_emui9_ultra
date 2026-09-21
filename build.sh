#!/bin/bash
#===============================================================================
# build.sh — 编译华为 MateRS (NEO) EMUI 9.1.0 RKSU 内核
# 用法: ./build.sh [JOBS]     默认 JOBS=23（24 核机器，用户已放开限制）
# 前置: aarch64-linux-android-4.9 工具链已就位（见 README_BUILD.md）
#===============================================================================
set -euo pipefail

JOBS="${1:-23}"
MAX_JOBS="$(nproc)"
if [ "$JOBS" -gt "$MAX_JOBS" ]; then
    echo "JOBS($JOBS) 超过核数($MAX_JOBS)，已限制为 $MAX_JOBS"
    JOBS="$MAX_JOBS"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export ARCH=arm64
export SUBARCH=arm64
export CROSS_COMPILE="${CROSS_COMPILE:-/mnt/g/projects/huawei-phone-ssd-project/aarch64-linux-android-4.9-refs_heads_pie-release/bin/aarch64-linux-android-}"
export PATH="$(dirname "$CROSS_COMPILE"):$PATH"
# gcc10+ 宿主编译老内核需要 -fcommon（解决 yylloc 等多重定义）
export HOSTCFLAGS="${HOSTCFLAGS:--fcommon}"

echo "==> 生成 defconfig (merge_kirin970_defconfig)"
make O=out merge_kirin970_defconfig

echo "==> 全量编译 (-j${JOBS})"
make O=out -j"${JOBS}"

echo "==> 产物"
ls -lh out/arch/arm64/boot/Image.gz
echo "完成。下一步: ./pack.sh 打包（需要原厂镜像时用 tools/repack_maters_boot.sh）"
