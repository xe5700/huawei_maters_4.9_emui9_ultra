# 构建与打包说明（NEO EMUI 9.1.0 RKSU）

## 依赖

- 宿主机建议 Ubuntu 18.04–22.04（老内核在新宿主编译需 `HOSTCFLAGS=-fcommon`，build.sh 已内置）
- 工具链：`aarch64-linux-android-4.9-refs_heads_pie-release`（AArch64 GCC 4.9.x）
- 依赖包：`make bc bison flex libssl-dev device-tree-compiler cpio lz4 python2`
  - Arch：`pacman -S make bc bison flex cpio python2`（openssl 头默认随 openssl 包提供）
  - Debian/Ubuntu：按教程 `sudo apt-get install ...`

## 编译

```bash
./build.sh 23          # 23 线程（24 核机器，可自行调）
```

产物：`out/arch/arm64/boot/Image.gz`

## 打包（两条路径）

### 方案 A：保留原厂 Hisilicon 头（正式刷入，推荐）

需要 MateRS 原厂 `KERNEL.img`（从真机 fastboot 提取或解包固件）：

```bash
./pack.sh out/arch/arm64/boot/Image.gz kernel.img /path/to/original_KERNEL.img
```

内部调用 `tools/repack_maters_boot.sh`：保留 Hisilicon 头 + 更新 Android 头内核大小 + cmdline 改 `androidboot.selinux=permissive`。

```bash
fastboot flash kernel kernel.img
fastboot reboot
```

### 方案 B：无原厂镜像（仅验证产物）

```bash
./pack.sh out/arch/arm64/boot/Image.gz kernel_mkbootimg.img
```

⚠️ 缺少 Hisilicon 头，MateRS 刷入大概率无法开机，仅用于验证内核本身。

## GitHub Actions

`.github/workflows/build-kernel.yml`：Ubuntu 20.04 + gcc-9，编译后上传
`Image.gz` 与 `out/.config` 工件。前提：把 `aarch64-linux-android-4.9` 工具链
放入仓库根目录（或改为在 workflow 中下载）。

## 刷入注意事项

1. 解锁 Bootloader（EMUI 9 需要解锁码）
2. 若刷 PM（permissive）内核，需先解密/格式化 DATA 分区
3. 安装 RKSU 管理器：`KernelSU_v3.0.0-30-legacy`（rsuntk/KernelSU release）
4. 对应底包必须为 EMUI 9.1.0（内核 4.9.148）
