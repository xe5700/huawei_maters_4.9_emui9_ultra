# NEO_EMUI9.1.0_RKSU

> ✅ **真机验证通过**：`NEO_EMUI9.1.0_RKSU.img`（标准无头 bootimg + enforcing）已在 MateRS EMUI 9.1.0 启动成功（2026-09-22）。Hisilicon 头非必需；permissive 才会要求解密/格式化 DATA。

华为 MateRS (NEO) · EMUI 9.1.0 · Linux 4.9.148 · **RKSU** (rsuntk/KernelSU v3.0.0-30-legacy)

基于华为官方 EMUI 9.1.0 开源内核的 RKSU 修改版内核适配仓库。
移植自已验证的 EMUI 9.0 RKSU 适配（`NEO_EMUI9.0_RKSU`），并集成 RKSU v3.0.0-30-legacy 驱动源码（已 vendor 入库）。

## ✅ 构建状态：编译通过

- `out/arch/arm64/boot/Image.gz` — 15,022,321 B（解压后 40.8 MB Image）
- `kernel_mkbootimg.img` — mkbootimg 打包（Android bootimg，**仅验证用，无 Hisilicon 头**）
- System.map 含 **17 个 KSU 符号**（`ksu_handle_execveat` / `ksu_handle_vfs_read` / `is_ksu_transition` 等）—— KSU 已实证编译进内核
- 配置：`CONFIG_KSU=y`、`CONFIG_KSU_MANUAL_HOOK=y`；24 项华为防 root/安全项已关闭；`DM_VERITY`/`DM_VERITY_AVB` 已关

## 📦 仓库内容

| 路径 | 说明 |
|---|---|
| `KernelSU/kernel/` | RKSU v3.0.0-30-legacy 驱动源码（vendor 入库，无需子模块） |
| `drivers/kernelsu` | → `../KernelSU/kernel` 符号链接 |
| `arch/arm64/configs/merge_kirin970_defconfig` | defconfig（防 root 关闭 + KSU 开启），见 `DEFCONFIG_NOTES.md` |
| `build.sh` | 编译脚本（JOBS≤16，`HOSTCFLAGS=-fcommon`） |
| `pack.sh` / `tools/repack_maters_boot.sh` | 打包脚本（保留 Hisilicon 头） |
| `.github/workflows/build-kernel.yml` | GitHub Actions 编译 |
| `ADAPT_INVENTORY.md`（工作区根目录） | 完整适配盘点 |
| `VERIFY_REPORT.md` / `REVIEW_T7.md` / `REVIEW.md` | t6 静态校验 + t7 疑难复核报告 |

## 🔧 编译

```bash
./build.sh 8        # 线程数 ≤ 16
# 产物: out/arch/arm64/boot/Image.gz
```

## 📱 刷入（正式版需原厂镜像）

1. 解锁 Bootloader（EMUI 9 需要解锁码）
2. **正式刷入镜像**：从真机提取原厂 `KERNEL.img`（含 Hisilicon 头）后执行：
   ```bash
   SELINUX_MODE=enforcing ./pack.sh out/arch/arm64/boot/Image.gz NEO_EMUI9.1.0_RKSU.img   # 推荐：无头 enforcing，真机验证可启动
   fastboot flash kernel kernel.img
   fastboot reboot
   ```
3. 若确要刷 PM（permissive）内核（SELINUX_MODE=permissive），必须先将 DATA 解密并格式化，否则 bootloop
4. 安装管理器：`KernelSU_v3.0.0-30-legacy`（[rsuntk/KernelSU Releases](https://github.com/rsuntk/KernelSU/releases)）

## ⚠️ 注意

- 必须匹配 EMUI 9.1.0（内核 4.9.148）底包，否则无法开机
- `kernel_mkbootimg.img` 缺 Hisilicon 头，**不要直接刷入**
- KernelSU 官方 1.0+ 已放弃 non-GKI，请保持 RKSU v3.0.0-30-legacy 管理器版本，勿升级
