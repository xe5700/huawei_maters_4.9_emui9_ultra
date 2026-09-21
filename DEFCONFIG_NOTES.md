# merge_kirin970_defconfig 变更说明（EMUI 9.1.0 / RKSU）

基于官方 NEO EMUI9.1.0 基线，参照 NEO_EMUI9.0_RKSU（EMUI 9.0 已验证适配版）与
KernelSU_on_Huawei 教程 how-to-intergrate-kernelsu.md 修改。

## 1. 关闭华为防 root / 安全加固项（24 项，用户确认：9.0 RKSU 全量清单 + 教程补充项）
HISI_PMALLOC, HISI_SUBPMU, TEE_ANTIROOT_CLIENT, HISI_HHEE, HISI_HHEE_TOKEN,
HISI_DIEID, HIVIEW_SELINUX, HISI_SELINUX_EBITMAP_RO, HISI_SELINUX_PROT,
HISI_RO_LSM_HOOKS, INTEGRITY, INTEGRITY_AUDIT, HUAWEI_CRYPTO_TEST_MDPP,
HUAWEI_SELINUX_DSM, HUAWEI_HIDESYMS, HW_SLUB_SANITIZE, HUAWEI_PROC_CHECK_ROOT,
HW_ROOT_SCAN, HUAWEI_EIMA, HUAWEI_EIMA_ACCESS_CONTROL, HW_DOUBLE_FREE_DYNAMIC_CHECK,
HKIP_ATKINFO, HW_KERNEL_STP, HWAA
全部由 `=y` 改为 `# CONFIG_XXX is not set`（仅当原值确实为 =y；不存在的项不动）。

## 2. 关闭 AVB 验证
CONFIG_DM_VERITY=y        -> # CONFIG_DM_VERITY is not set
CONFIG_DM_VERITY_AVB=y    -> # CONFIG_DM_VERITY_AVB is not set

## 3. 开启 RKSU（KernelSU v3.0.0-30-legacy）
文件末尾追加：
CONFIG_KSU=y
CONFIG_KSU_MANUAL_HOOK=y
（不开启 CONFIG_KSU_DEBUG）

## 4. 版本标识
CONFIG_LOCALVERSION="-NEO_EMUI9.1.0_RKSU_xixiaobei@Github"

## 5. 保持原值（用户决策：先不动，后续用其它麒麟970 9.1.0 机型作参考）
9.1.0 新增加固项：CONFIG_HISI_EARLY_RODATA_PROTECTION、CONFIG_SPECULATIVE_PAGE_FAULT、
CONFIG_ARM64_SW_TTBR0_PAN、CONFIG_HW_SLUB_DF 等，维持官方原值。

## 6. 验证结果
- 24 项防 root 清单 grep "^CONFIG_X=y$" 全部为空（全部已关闭）
- CONFIG_KSU=y / CONFIG_KSU_MANUAL_HOOK=y 各仅 1 处
- git diff：30 insertions / 27 deletions，仅 defconfig 一个文件

## 7. erofs 对齐（用户真机排查补充）
官方发布 KERNEL.img 内嵌真实配置（IKCONFIG 提取）显示 `# CONFIG_EROFS_FS is not set`
（文件系统为 ext4+f2fs，无 erofs）。官方开源源码 defconfig 与发布二进制不一致（源码里 =y）。
为与真机一致，已将整个 CONFIG_EROFS_FS* 块改为 not set。
