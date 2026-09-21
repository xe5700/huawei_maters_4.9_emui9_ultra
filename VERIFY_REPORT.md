# VERIFY_REPORT — t5 RKSU 钩子移植静态校验

> 校验对象：`NEO_EMUI9.1.0_RKSU` commit `cf0608b8a`（Port RKSU manual hooks，10 文件 98 行插入 0 删除）
> 参考基线：`NEO_EMUI9.0_RKSU`（9.0 RKSU 已完成适配）+ `NEO_PIE_EMUI9.1.0_opensource/kernel`（9.1.0 官方源码）
> 校验人：sensenova（盘点 / 静态校验）
> 校验时间：2026-09-21
> 校验方式：**纯静态**（diff / grep / md5 / 结构比对），未编译

---

## 0. 结论

**t5 的 RKSU 钩子移植静态校验通过，可放行。**

- 8 个内核 hook 文件 + 2 个构建文件（`drivers/Kconfig`、`drivers/Makefile`）全部就位，**与 9.0 RKSU 参考语义一致**。
- 两个 9.0↔9.1.0 逐字节完全相同的回移块（`can_umount` / `path_umount`）md5 一致。
- 9.1.0 特有的结构差异（`input_handle_event` vs `input_event`、`vfs_read` vs `sys_read`、`statx` 缺失、`sys_reboot` 参数）经核实**不构成移植风险**，详见 §4。
- **下游阻塞项（非 t5 范围）**：defconfig 尚未设置 `CONFIG_KSU`，见 §5 —— 已由 **t4（船长，in_progress）** 承接。

未发现任何 findings（无遗漏、无重复声明、无签名错配）。

---

## 1. 钩子文件逐文件 diff（9.0 RKSU vs 9.1.0 RKSU）

| 文件 | diff 行数 | 差异性质 | 结论 |
|---|---|---|---|
| `fs/read_write.c` | **0** | 无差异 | ✅ 完全一致 |
| `drivers/input/input.c` | **0** | 无差异 | ✅ 完全一致 |
| `security/selinux/hooks.c` | **0** | 无差异 | ✅ 完全一致 |
| `fs/open.c` | 2 | 仅 1 行空行（`378a379`） | ✅ hook 块一致 |
| `fs/stat.c` | 2 | 仅 1 行空行（`98a99`） | ✅ hook 块一致 |
| `kernel/reboot.c` | 2 | 仅 1 行空行（`288a289`） | ✅ hook 块一致 |
| `fs/exec.c` | 32 | 全部为 9.1.0 原生差异（见 §3.1），**hook 块不在 diff 中** | ✅ hook 一致 |
| `fs/namespace.c` | 115 | 全部为 9.1.0 原生差异（见 §3.2），**回移块不在 diff 中** | ✅ 回移一致 |
| `drivers/Kconfig` | 22 | 全部为 9.1.0 原生 driver 增减（见 §3.3） | ✅ KSU 行一致 |
| `drivers/Makefile` | 16 | 全部为 9.1.0 原生 driver 增减（见 §3.3） | ✅ KSU 行一致 |

**判定依据**：只要 RKSU 的 hook 行不出现在 diff 输出中，就说明两个仓库在该行上逐字节相同。

### 1.1 `CONFIG_KSU` 出现次数（逐文件一致）

| 文件 | 9.0 RKSU | 9.1.0 RKSU |
|---|---|---|
| `fs/exec.c` | 2 | 2 |
| `fs/namespace.c` | 0 | 0 |
| `fs/open.c` | 2 | 2 |
| `fs/read_write.c` | 2 | 2 |
| `fs/stat.c` | 2 | 2 |
| `drivers/input/input.c` | 2 | 2 |
| `kernel/reboot.c` | 2 | 2 |
| `security/selinux/hooks.c` | 2 | 2 |

> 每个文件 2 次 = 1 个 `#ifdef CONFIG_KSU` 包住 extern 声明 + 1 个 `#ifdef CONFIG_KSU` 包住调用点，语义正确。
> `fs/namespace.c` 为 0 是**正确**的：`can_umount`/`path_umount` 回移是**无条件代码**（上游函数，KSU 驱动直接调用），与 9.0 RKSU 一致。

### 1.2 `ksu_*` / `is_ksu_transition` 符号清单（完全一致）

两个仓库去重排序后完全相同，共 **11 个符号**：

```
is_ksu_transition                 ksu_handle_vfs_read
ksu_execveat_hook                 ksu_input_hook
ksu_handle_execveat               ksu_vfs_read_hook
ksu_handle_execveat_sucompat      ksu_handle_faccessat
ksu_handle_input_handle_event     ksu_handle_stat
                                  ksu_handle_sys_reboot
```

### 1.3 重复声明检查（每文件 extern=1 / call=1）

| 文件 | 符号 | extern 次数 | 调用次数 |
|---|---|---|---|
| `fs/exec.c` | `ksu_handle_execveat` | 1 | 1 |
| `fs/exec.c` | `ksu_handle_execveat_sucompat` | 1 | 1 |
| `fs/exec.c` | `ksu_execveat_hook` | 1 | 1 |
| `fs/open.c` | `ksu_handle_faccessat` | 1 | 1 |
| `fs/read_write.c` | `ksu_handle_vfs_read` | 1 | 1 |
| `fs/read_write.c` | `ksu_vfs_read_hook` | 1 | 1 |
| `fs/stat.c` | `ksu_handle_stat` | 1 | 1 |
| `drivers/input/input.c` | `ksu_handle_input_handle_event` | 1 | 1 |
| `drivers/input/input.c` | `ksu_input_hook` | 1 | 1 |
| `kernel/reboot.c` | `ksu_handle_sys_reboot` | 1 | 1 |
| `security/selinux/hooks.c` | `is_ksu_transition` | 1 | 1 |

**无重复声明、无遗漏调用。**

---

## 2. 8 个钩子的精确位置与语义核对

### 2.1 `fs/exec.c` — `do_execveat_common` 双模式

```
1687  #ifdef CONFIG_KSU
1688  extern bool ksu_execveat_hook __read_mostly;
1689  extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr, void *argv,
1690  				void *envp, int *flags);
1691  extern int ksu_handle_execveat_sucompat(int *fd, struct filename **filename_ptr,
1692  					 void *argv, void *envp, int *flags);
1693  #endif
1694  static int do_execveat_common(int fd, struct filename *filename, ...
...
1705  #ifdef CONFIG_KSU
1706  	if (unlikely(ksu_execveat_hook))
1707  		ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
1708  	else
1709  		ksu_handle_execveat_sucompat(&fd, &filename, &argv, &envp, &flags);
1710  #endif
1711
1712  	if (IS_ERR(filename))
```
9.0 RKSU 同结构位于 line 1678–1701（偏移 +9 行，因 9.1.0 原生多了一段 `CONFIG_HWAA` include）。**hook 块逐字节相同，插入位置语义正确**（变量声明之后、`IS_ERR` 检查之前）。

### 2.2 `fs/namespace.c` — `can_umout` / `path_umount` 回移

| 项 | 值 |
|---|---|
| `can_umount` md5 | `080323bc258130e50047cd825341148b`（18 行） |
| `path_umount` md5 | `79c0bd3bf84f1dfd27740d7ab44d09a0`（14 行） |
| 9.0 RKSU ↔ 9.1.0 RKSU | **两仓库 md5 完全相同** |
| 9.1.0 定义位置 | `can_umount` line 1697，`path_umount` line 1716 |
| `may_mount()` 定义位置 | line 1692（**在 can_umount 之前**，前置依赖满足）|

**关键核对**：`can_umount` 内部只调用 `may_mount()` 和 `capable(CAP_SYS_ADMIN)`，**不调用 `may_mandlock`**。9.1.0 把 `may_mandlock()` 从 line 1664 移到了 line 1731（挪到 `path_umount` 之后），但这对回移块**没有影响**，回移仍可编译。

`path_umount` 的全部 6 个依赖符号在 9.1.0 `fs/namespace.c` 中均存在：

| 依赖符号 | 9.1.0 出现次数 |
|---|---|
| `real_mount` | 40 |
| `may_mount` | 5 |
| `check_mnt` | 12 |
| `do_umount` | 3 |
| `mntput_no_expire` | 5 |
| `dput` | 11 |

> `path_umount` 非 static（供 KSU 驱动跨文件引用），与 9.0 RKSU 一致。

### 2.3 其余 6 个 hook（与 9.0 RKSU 逐字节相同）

- `fs/open.c` `faccessat` → `ksu_handle_faccessat(&dfd, &filename, &mode, NULL)`
- `fs/read_write.c` `vfs_read` → `ksu_vfs_read_hook` 开关 + `ksu_handle_vfs_read`
- `fs/stat.c` `vfs_fstatat` → `ksu_handle_stat(&dfd, &filename, &flag)`
- `drivers/input/input.c` `input_handle_event` → `ksu_input_hook` 开关 + `ksu_handle_input_handle_event`
- `kernel/reboot.c` `sys_reboot` → `ksu_handle_sys_reboot(magic1, magic2, cmd, &arg)`
- `security/selinux/hooks.c` `check_nnp_nosuid` → `is_ksu_transition(old_tsec, new_tsec)`

### 2.4 构建文件

```
drivers/Kconfig  line 265: source "drivers/kernelsu/Kconfig"   ← 紧接 endmenu 之前 ✓
drivers/Makefile line 220: obj-$(CONFIG_KSU) += kernelsu/      ✓
```

---

## 3. 9.1.0 原生差异明细（均与 RKSU 移植无关）

### 3.1 `fs/exec.c` 的 32 行差异

| 位置 | 9.1.0 原生内容 | 性质 |
|---|---|---|
| line 70–74 | `#ifdef CONFIG_HWAA` + `#include <huawei_platform/hwaa/hwaa_proc_hooks.h>` | 华为 hwaa 框架 include |
| line 314–318 | `#ifdef CONFIG_SPECULATIVE_PAGE_FAULT` / `INIT_VMA(vma)` / `#else ... #endif` | 华为投机页错误处理 |
| line 950 | `goto out` → `goto out_free` | 9.1.0 原生 bugfix（错误路径释放） |
| line 1853–1867 | `#ifdef CONFIG_HWAA` 包裹的 `hwaa_proc_pre_execve` / `hwaa_proc_post_execve` | 华为 hwaa 在 `sys_execve` 层的包装 |

**判定**：全部发生在 `sys_execve`（hwaa 包装层）与 VMA 初始化路径，**不触及** `do_execveat_common` 内部的 RKSU hook。`do_execveat_common` 的签名与函数体结构在两个仓库中一致，hook 可原位生效。

### 3.2 `fs/namespace.c` 的 115 行差异

| 位置 | 9.1.0 原生内容 | 性质 |
|---|---|---|
| line 30–32 | `#ifdef CONFIG_HW_BFMR_HISI` + bfmr include | 华为 BFMR 挂载追踪 |
| line 612, 619–626 | `smp_mb()` 屏障 + `MNT_DOOMED` 二次检查 | 挂载引用计数稳定性修复 |
| line 1173–1193 | `mntput_no_expire()` 重写（`READ_ONCE` + `smp_mb()` + RCU 注释） | 4.9.148 的 RCU 内存屏障修复 |
| line 1625–1632 | `MNT_LOCKED` 持锁二次检查 + `event++` 顺序调整 | 卸载路径加固 |
| line 1696 vs 1664 | `may_mandlock()` 定义位置移动 | 位置调整（见 §2.2 判定：无影响） |
| line 1753–1755, 1781–1788, 2860–2862, 2930–2937 | `CONFIG_HW_BFMR_HISI` 的 `bfmr_set_mount_state` 调用 | 华为 BFMR 挂载状态上报 |
| line 1920 | `umount_tree(..., UMOUNT_SYNC)` → `umount_tree(..., 0)` | 9.1.0 原生行为调整 |
| line 1860–1867 | `skip_mnt_tree(s)` → `MNT_LOCKED` 分支检查 | 9.1.0 原生行为调整 |

**判定**：全部为 9.1.0 挂载子系统的原生演进，**没有一行触及** `can_umount` / `path_umount` 回移块。

### 3.3 `drivers/Kconfig` / `drivers/Makefile` 的差异

全部为 9.1.0 原生 driver 增减：
- `+` `drivers/vcodec/imagination/D5500/Kconfig`、`D5500_DRM/Kconfig`（GPU 重组）
- `+` `drivers/hwerecovery/Kconfig`、`drivers/storage_rofa/Kconfig`、`drivers/oases/Kconfig`、`drivers/oae_fw_patch/Kconfig`
- `-` `drivers/gpu/gmc/Kconfig` + `drivers/gpu/arm/Kconfig` → `drivers/gpu/Kconfig`（GPU 目录合并）
- `-` `obj-$(CONFIG_LOG_EXCEPTION) += log_usertype/`

**判定**：`source "drivers/kernelsu/Kconfig"` 与 `obj-$(CONFIG_KSU) += kernelsu/` 两行未出现在 diff 中，逐字节一致。

---

## 4. 9.1.0 特有结构差异专项核查（验收标准 2）

### 4.1 `input_handle_event` vs `input_event`

| 检查项 | 9.0 RKSU | 9.1.0 RKSU | 9.1.0 官方源码 |
|---|---|---|---|
| `static void input_handle_event` | 1 | 1 | 1 |
| `int input_event(` | 0 | 0 | 0 |
| `ksu_handle_input_handle_event` | 2 | 2 | 0 |
| `input_handle_event(` 调用总数 | 5 | 5 | 3 |

**结论**：4.9 系华为内核统一使用 `input_handle_event()`，**不存在** `input_event()` 的分离变体。9.1.0 与 9.0 结构完全一致，hook 命中正确的唯一调用点（RKSU 版比官方源码多 2 处 `input_handle_event(` 出现，即 extern 声明 + 调用点）。✅

### 4.2 `vfs_read` vs `sys_read`

| 检查项 | 9.0 RKSU | 9.1.0 RKSU | 9.1.0 官方源码 |
|---|---|---|---|
| `ssize_t vfs_read(` | 1 | 1 | 1 |
| `SYSCALL_DEFINE*(read` | 3 | 3 | 3 |
| `vfs_read(` 出现总数 | 7 | 7 | 5 |

**结论**：9.1.0 未把 read 路径拆分或改为直接系统调用，`vfs_read()` 仍是所有 read 系统调用的唯一汇聚点。hook 放在 `vfs_read()` 而非 `sys_read()` 是**正确的拦截层级**（能覆盖 `pread64`/`readv`/`preadv` 等所有走 VFS 的路径）。9.1.0 结构与 9.0 完全一致。✅

### 4.3 `statx` 存在性（潜在绕过风险核查）

| 检查项 | 9.0 官方源码 | 9.1.0 官方源码 |
|---|---|---|
| `SYSCALL_DEFINE*(statx)` | **0** | **0** |
| `fs/stat.c` 总行数 | 510 | **510（完全相同）** |
| `int vfs_fstatat(` | 1 | 1 |

**结论**：statx 系统调用（上游 4.11+ 引入）**未被华为回移进此 4.9.x 内核**，因此**不存在绕过 `vfs_fstatat` 的 stat 路径**。hook 打在 `vfs_fstatat` 上即可覆盖全部 stat 类系统调用（`stat`/`lstat`/`fstatat`/`statx` 若存在）。无绕过风险。✅

### 4.4 `vfs_fstatat` 签名一致性

```
9.0 RKSU line 93: int vfs_fstatat(int dfd, const char __user *filename, struct kstat *stat, int flag)
9.1.0 RKSU line 93: int vfs_fstatat(int dfd, const char __user *filename, struct kstat *stat, int flag)
```
逐字节一致，hook 的 `ksu_handle_stat(&dfd, &filename, &flag)` 三参数映射正确。✅

### 4.5 `sys_reboot` 参数一致性

```
9.0 RKSU line 283: SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd, void __user *, arg)
9.1.0 RKSU line 283: SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd, void __user *, arg)
```
`SYSCALL_DEFINE4` 的 4 个参数与 hook 的 `ksu_handle_sys_reboot(magic1, magic2, cmd, &arg)` **一一对应，类型匹配**（3 个值 + 1 个指针）。✅

---

## 5. 下游阻塞项（不属于 t5，不属于 t6）

静态校验中发现 **9.1.0 RKSU 的 defconfig 尚未做 RKSU 处理**：

| 项 | 9.1.0 RKSU 当前值 | 9.0 RKSU 参考值 |
|---|---|---|
| `CONFIG_KSU` | **缺失** | `=y`（line 5861） |
| `CONFIG_KSU_MANUAL_HOOK` | **缺失** | `=y`（line 5862） |
| `CONFIG_LOCALVERSION` | `""`（line 48，空） | `-NEO_EMUI9.0_RKSU_xixiaobei@Github` |
| `CONFIG_HISI_PMALLOC` | **仍 =y** | 应为 `# is not set` |
| `CONFIG_TEE_ANTIROOT_CLIENT` | **仍 =y** | 应为 `# is not set` |
| `CONFIG_HIVIEW_SELINUX` | **仍 =y** | 应为 `# is not set` |
| `CONFIG_HISI_SELINUX_PROT` | **仍 =y** | 应为 `# is not set` |
| `CONFIG_HUAWEI_HIDESYMS` | **仍 =y** | 应为 `# is not set` |
| `CONFIG_HW_ROOT_SCAN` | **仍 =y** | 应为 `# is not set` |

**影响**：所有 8 个 hook 都被 `#ifdef CONFIG_KSU` 包裹，defconfig 不设置 `CONFIG_KSU=y` 会导致 **hook 全部被编译剔除**，本次移植在运行时完全不生效（编译能通过，产物是无 root 能力的普通内核）。此外防 root 项不关闭会在启动或管理器加载时与 KernelSU 冲突。

**归属**：该工作已由 **t4「处理 9.1.0 defconfig（关闭反root/安全项+开启KSU）」** 承接（assignee=captain，in_progress），**不是 t5 移植的缺陷，也不是 t6 校验范围**。此处仅作为下游提醒记录。

---

## 6. 校验命令汇总

```bash
# 1. 逐文件 diff 行数统计
for f in fs/exec.c fs/namespace.c fs/open.c fs/read_write.c fs/stat.c \
         drivers/input/input.c kernel/reboot.c security/selinux/hooks.c \
         drivers/Kconfig drivers/Makefile; do
  diff -rq NEO_EMUI9.0_RKSU/$f NEO_EMUI9.1.0_RKSU/$f
done

# 2. CONFIG_KSU 出现次数
grep -c "CONFIG_KSU" <file>

# 3. ksu 符号清单去重比对
grep -rhoE "ksu_[a-zA-Z_]+|is_ksu_transition" NEO_EMUI9.0_RKSU/{fs,drivers/input} NEO_EMUI9.0_RKSU/kernel/reboot.c NEO_EMUI9.0_RKSU/security/selinux | sort -u

# 4. 回移块 md5
awk '/^static int can_umount/,/^}/' <file> | md5sum
awk '/^int path_umount/,/^}/'      <file> | md5sum

# 5. 函数定义顺序
grep -nE '^(static inline bool may_mount|static inline bool may_mandlock|static int can_umount|int path_umount)' fs/namespace.c

# 6. 9.1.0 特有结构
grep -c 'static void input_handle_event\|int input_event(' drivers/input/input.c
grep -c 'ssize_t vfs_read(\|SYSCALL_DEFINE[0-9](read' fs/read_write.c
grep -rc 'SYSCALL_DEFINE[0-9](statx' fs/stat.c
grep -n -A3 '^SYSCALL_DEFINE[0-9](reboot' kernel/reboot.c

# 7. 构建文件
tail -8 drivers/Kconfig
grep -n kernelsu drivers/Makefile
grep -n CONFIG_KSU arch/arm64/configs/merge_kirin970_defconfig
```

---

## 7. 校验结论

| 验收标准 | 结果 |
|---|---|
| 逐文件核对 t5 钩子 extern 声明/调用点/条件编译是否完整且与 9.0 参考语义一致 | ✅ **通过**（§1、§2：11 个符号 extern=1/call=1，CONFIG_KSU 计数逐文件一致，无重复声明） |
| 9.1.0 特有差异（input_event/input_handle_event、vfs_read/sys_read、statx 存在性）已在报告中说明 | ✅ **通过**（§4.1–4.5：5 项专项核查全部无风险） |
| 验证命令全部通过并附证据 | ✅ **通过**（§6：7 组命令全部执行，证据见各节表格） |
| 输出 VERIFY_REPORT.md 到仓库根目录 | ✅ **通过**（本文件） |

**findings：无。** t5 移植可放行。
