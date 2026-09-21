#!/bin/bash
#===============================================================================
# repack_maters_boot.sh
# 为华为 Mate RS (NEO) 生成可刷入内核镜像
# 保留原厂 Hisilicon 头部，只替换内核数据+cmdline
#===============================================================================
set -e

NEW_KERNEL="$1"
OUTPUT="${2:-KERNEL_new.img}"
ORIGINAL_IMG="${3:-original_KERNEL.img}"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
fail() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

[ $# -ge 1 ] || { echo "用法: $0 <Image.gz> [输出] [原厂镜像]"; exit 1; }
[ -f "$NEW_KERNEL" ] || fail "找不到: ${NEW_KERNEL}"
[ -f "$ORIGINAL_IMG" ] || fail "找不到原厂镜像: ${ORIGINAL_IMG}"

NEW_KSIZE=$(stat -c%s "${NEW_KERNEL}")
info "新内核: $(basename ${NEW_KERNEL}) ($((NEW_KSIZE / 1024)) KB)"

python3 << PYEOF
import struct

new_kernel_path = "${NEW_KERNEL}"
output_path = "${OUTPUT}"
original_img = "${ORIGINAL_IMG}"
new_ksize = ${NEW_KSIZE}

with open(original_img, 'rb') as f:
    orig = f.read()

assert orig[4096:4104] == b'ANDROID!', '原厂镜像格式错误'
ksize = struct.unpack_from('<I', orig, 4096+8)[0]
page_size = struct.unpack_from('<I', orig, 4096+36)[0]
hisi_sz = 4096
andr_sz = page_size
koff = hisi_sz + andr_sz

print(f'原厂内核: {ksize} ({ksize/1024:.0f} KB)')
print(f'新内核:   {new_ksize} ({new_ksize/1024:.0f} KB)')

with open(new_kernel_path, 'rb') as f:
    new_kernel = f.read()

kpadded = ((new_ksize + page_size - 1) // page_size) * page_size

# 构建: Hisilicon头 + Android头(更新内核大小+permissive cmdline) + 新内核
img = bytearray()
img.extend(orig[:hisi_sz])  # Hisilicon 头部不变

hdr = bytearray(orig[hisi_sz:koff])
struct.pack_into('<I', hdr, 8, new_ksize)  # 更新 kernel_size

# 改 cmdline 为 permissive (offset 0x40)
old_cmd = hdr[64:].split(b'\x00')[0].decode('ascii')
new_cmd = old_cmd.replace('androidboot.selinux=enforcing', 'androidboot.selinux=permissive')
print(f'原 cmdline: {old_cmd}')
print(f'新 cmdline: {new_cmd}')
cbytes = new_cmd.encode('ascii')[:511]
# 清空整个 cmdline 缓冲区再写入
hdr[64:576] = b'\x00' * 512
hdr[64:64+len(cbytes)] = cbytes

img.extend(hdr)
img.extend(new_kernel)
pad = kpadded - new_ksize
if pad > 0:
    img.extend(b'\x00' * pad)

with open(output_path, 'wb') as f:
    f.write(img)

sz = len(img)
print(f'\n生成成功! Hisilicon头={hisi_sz} Android头={andr_sz} 内核={new_ksize} 总计={sz} ({sz/1024:.0f} KB)')

# 验证
with open(output_path, 'rb') as f:
    assert f.read(8) == orig[:8]
    f.seek(4096)
    assert f.read(8) == b'ANDROID!'
print('验证通过!')
PYEOF

ok "生成成功: ${OUTPUT}"
ls -lh "${OUTPUT}"
echo ""
echo "刷入: fastboot flash kernel ${OUTPUT} && fastboot reboot"
