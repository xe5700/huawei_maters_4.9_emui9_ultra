# t7 疑难复核报告：RKSU 钩子移植与华为安全机制兼容性

- 复核对象：t5 移植成果（commit cf0608b8a，10 文件 98 行纯新增）
- 复核人：longcat（疑难复核，round 1）
- 结论：**PASS，零 findings**

## 1. 华为安全机制残留检查 — 通过

defconfig（merge_kirin970_defconfig）中防 root/安全项全部关闭：

| 配置项 | 状态 | 行号 |
|---|---|---|
| CONFIG_TEE_ANTIROOT_CLIENT / _ENG_DEGUG | not set | 4515/4518 |
| CONFIG_HUAWEI_ROOT_SCAN_DUMMY_API | not set | 4516 |
| CONFIG_HISI_HHEE / HISI_HHEE_TOKEN | not set | 4752/4753 |
| CONFIG_HUAWEI_PROC_CHECK_ROOT | not set | 5750 |
| CONFIG_HW_ROOT_SCAN / _ENG_DEBUG | not set | 5755/5756 |
| CONFIG_HUAWEI_EIMA / ENG_EIMA / EIMA_ACCESS_CONTROL | not set | 5757-5759 |
| CONFIG_HKIP_ATKINFO / _DEBUGFS | not set | 5761/5762 |
| CONFIG_HW_KERNEL_STP / _ENG_DEBUG | not set | 5767/5768 |
| CONFIG_DM_VERITY / DM_VERITY_AVB | not set | 1673/1680 |

- DM_VERITY_FEC=y / DM_VERITY_HW_RETRY=y 为惰性子选项（依赖 DM_VERITY），不生效。
- drivers/Makefile、fs/Makefile 中无 ROOT_SCAN/ANTIROOT/CHECK_ROOT 构建入口，相关代码不编译。
- `CONFIG_OAE_DM_ROOT=y`（5228 行）为 Qihoo 启动设备挂载补丁（drivers/oae_fw_patch/do_mounts_oae，"Use oae dm as boot device"），非安全拦截机制，保持原厂值即可。
- SELinux 配置（DEVELOP/DISABLE/BOOTPARAM 均 not set）与 9.0 RKSU 参考逐项一致，非移植回归；KSU v3 走 per-domain permissive 策略注入（selinux/rules.c `ksu_permissive(db, KERNEL_SU_DOMAIN)`），不依赖全局 setenforce。

## 2. is_ksu_transition 移植一致性 — 通过

- security/selinux/hooks.c：extern 声明（2290-2293）+ check_nnp_nosuid 内调用点（2308-2311）与 9.0 参考逐字节一致。
- 定义位于 KernelSU/kernel/selinux/selinux.c:36，守卫 `#if LINUX_VERSION_CODE <= KERNEL_VERSION(4, 19, 0)` → 4.9.148 命中编译。
- 签名匹配：`bool(const struct task_security_struct *, const struct task_security_struct *)`。
- 兼容层正确：4.9 无 selinux_state/selinux_cred 字段（Kbuild 自动探测 KSU_COMPAT_HAS_* 均不命中），selinux.h 将 KSU_COMPAT_HAS_SELINUX_STATE 映射为 KSU_COMPAT_USE_SELINUX_STATE，selinux_defs.h 对 <5.1 无 KSU_OPTIONAL_SELINUX_CRED 时 `selinux_cred(cred)` 回退为 `cred->security` 强转——4.9 正确路径。

## 3. extern 声明与 CONFIG_KSU 条件编译兼容性（4.9.148）— 通过

内核侧 11 个 extern 符号在 KernelSU/kernel 中全部有定义且被构建（obj-$(CONFIG_KSU) += kernelsu.o，Kbuild 覆盖 ksud.o/sucompat.o/supercalls.o/selinux/selinux.o）：

| 符号 | 定义位置 | 守卫 |
|---|---|---|
| ksu_execveat_hook / ksu_vfs_read_hook / ksu_input_hook | ksud.c:76-78 | #ifdef CONFIG_KSU_MANUAL_HOOK（defconfig 已设 y，Kbuild 另加 -DCONFIG_KSU_MANUAL_HOOK 双保险） |
| ksu_handle_execveat | sucompat.c:199（组合 ksud+sucompat） | 无 |
| ksu_handle_execveat_sucompat | sucompat.c:174 | 无 |
| ksu_handle_faccessat | sucompat.c:147 | 无 |
| ksu_handle_stat | sucompat.c:156 | 无 |
| ksu_handle_sys_reboot | supercalls.c:760 | 无 |
| ksu_handle_vfs_read | ksud.c:378 | 无 |
| ksu_handle_input_handle_event | ksud.c:496 | 无 |
| is_ksu_transition | selinux/selinux.c:36 | ≤4.19 版本守卫 |

- **无未定义引用风险**：CONFIG_KPROBES not set → KSU_SYSCALL_HOOK 依赖不满足 → choice 强制解析为 KSU_MANUAL_HOOK，三个 bool 开关必然编译。
- **无重复定义**：全树各符号仅一处定义；KSU 头文件仅有声明（kp_hook.h 的声明无害，kp_hook.c 仅 SYSCALL_HOOK 模式构建）。
- 签名逐一比对内核侧 extern 与 KSU 侧定义：参数类型完全一致。
- 4.9 API 存在性：security_secctx_to_secid/security_secid_to_secctx/security_release_secctx（security.h:367-369）、security_add_hooks 2 参形式（<4.11 分支，lsm_hook.c:120）、__read_mostly/unlikely/struct filename 等均可用。

## 4. namespace.c path_umount 回移正确性 — 通过

- 9.1.0 的 `SYSCALL_DEFINE2(umount, ...)`（1747 行）为旧式内联实现（含华为 BFMR 扩展），**不调用** path_umount——与 9.0 参考及 4.9 pre-refactor 上游行为一致，非缺陷。
- 回移的 path_umount（1716 行，非 static）服务对象是 **KernelSU/kernel/kernel_umount.c**：Kbuild 自动探测 `grep "int\s\+path_umount" fs/namespace.c` 命中 → 定义 KSU_HAS_PATH_UMOUNT → kernel_umount.c:50 `extern int path_umount(...)` 并调用（模块卸载特性）。
- 回移函数体与 9.0 参考逐字节一致（34 行）；can_umount 为 static 文件局部；全树无重复定义（path_umount 仅 1 处、can_umount 仅定义+内部调用）。
- 依赖符号（may_mount/check_mnt/do_umount/mntput_no_expire/MNT_*）在同文件相邻 umount 系统调用中同样使用，必然可用。

## 结论

t5 移植（commit cf0608b8a）通过疑难级复核：无华为安全残留拦截、SELinux 域转换钩子正确、CONFIG_KSU/CONFIG_KSU_MANUAL_HOOK 与 4.9.148 编译兼容（无未定义引用/重复定义）、path_umount 回移正确且被 KSU 消费。t9 全量编译可放行。
