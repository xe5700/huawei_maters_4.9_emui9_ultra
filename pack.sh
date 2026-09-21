#!/bin/bash
#===============================================================================
# pack.sh — 打包内核镜像（MateRS NEO EMUI 9.1.0 RKSU）
#
# 用法 A（推荐，已真机验证）：标准无头 Android bootimg（与 9.0 社区发布同款）
#   SELINUX_MODE=enforcing|permissive ./pack.sh <Image.gz> <输出.img>
#     默认 enforcing —— RKSU 走 per-domain permissive，enforcing 下可开机可 root；
#     permissive 需先解密/格式化 DATA 分区，否则 bootloop（实测结论）
#   实测：kernel_headerless_enforcing.img 在 MateRS EMUI 9.1.0 真机启动成功
#         => Hisilicon 头并非必需（9.0 社区同样无头直刷）
#
# 用法 B（备选）：保留 Hisilicon 头的 repack 方式
#   SELINUX_MODE=enforcing|permissive ./pack.sh <Image.gz> <输出.img> <原厂KERNEL.img>
#     仅当未来固件要求 Hisilicon 头时使用；本测试证明 9.1.0 不需要
#===============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NEW_KERNEL="${1:-out/arch/arm64/boot/Image.gz}"
OUTPUT="${2:-kernel.img}"
ORIGINAL="${3:-}"
export SELINUX_MODE="${SELINUX_MODE:-enforcing}"
SEL_ARG="androidboot.selinux=$SELINUX_MODE"

if [ -n "$ORIGINAL" ]; then
    echo "==> repack 方案（保留 Hisilicon 头，SELINUX_MODE=$SELINUX_MODE）"
    tools/repack_maters_boot.sh "$NEW_KERNEL" "$OUTPUT" "$ORIGINAL"
else
    echo "==> 标准 Android bootimg（无 Hisilicon 头，9.0 社区同款，真机已验证可启动）SELINUX_MODE=$SELINUX_MODE"
    cp "$NEW_KERNEL" tools/Image.gz
    (cd tools && ./mkbootimg --kernel Image.gz --base 0x0 \
        --cmdline "loglevel=4 initcall_debug=n page_tracker=on unmovable_isolate1=2:192M,3:224M,4:256M printktimer=0xfff0a000,0x534,0x538 $SEL_ARG buildvariant=user" \
        --tags_offset 0x07A00000 --kernel_offset 0x00080000 --ramdisk_offset 0x07C00000 \
        --header_version 1 --os_version 9 --os_patch_level 2019-11-29 \
        --output "../$OUTPUT")
    echo "==> 已生成 $OUTPUT（标准 bootimg，$SELINUX_MODE；若为 permissive 请先处理 DATA 分区）"
fi

ls -lh "$OUTPUT"
