#!/bin/bash
#===============================================================================
# pack.sh — 打包内核镜像
# 用法 A（推荐，保留 Hisilicon 头）:
#   ./pack.sh <Image.gz> <输出.img> <原厂KERNEL.img>
# 用法 B（无原厂镜像时的临时方案，缺 Hisilicon 头，刷入大概率无法开机）:
#   ./pack.sh <Image.gz> <输出.img>
#===============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NEW_KERNEL="${1:-out/arch/arm64/boot/Image.gz}"
OUTPUT="${2:-kernel.img}"
ORIGINAL="${3:-}"

if [ -n "$ORIGINAL" ]; then
    echo "==> repack_maters_boot.sh 方案（保留 Hisilicon 头 + cmdline 改 permissive）"
    tools/repack_maters_boot.sh "$NEW_KERNEL" "$OUTPUT" "$ORIGINAL"
else
    echo "==> 未提供原厂镜像，退回 mkbootimg 方案（仅验证产物，不建议刷入）"
    # 修正 --kernel Image.gz 与 os_patch_level（对应 EMUI 9.1.0 2019-11-29）
    sed -i 's/--kernel kernel /--kernel Image.gz /' tools/pack_kernerimage_cmd.sh
    sed -i 's/--os_patch_level [0-9-]*/--os_patch_level 2019-11-29/' tools/pack_kernerimage_cmd.sh
    # 构造临时 cmdline 版本：Image.gz 从 out/arch/arm64/boot 复制到 tools
    cp "$NEW_KERNEL" tools/Image.gz
    (cd tools && ./mkbootimg --kernel Image.gz --base 0x0 \
        --cmdline "loglevel=4 initcall_debug=n page_tracker=on unmovable_isolate1=2:192M,3:224M,4:256M printktimer=0xfff0a000,0x534,0x538 androidboot.selinux=permissive buildvariant=user" \
        --tags_offset 0x07A00000 --kernel_offset 0x00080000 --ramdisk_offset 0x07C00000 \
        --header_version 1 --os_version 9 --os_patch_level 2019-11-29 \
        --output "../$OUTPUT")
    echo "==> 已生成 $OUTPUT（警告：无 Hisilicon 头，仅供验证；正式刷入请提供原厂镜像重跑 repack 方案）"
fi

ls -lh "$OUTPUT"
