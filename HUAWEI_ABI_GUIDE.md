# 华为机型内核适配：预编译汇编 ABI 错位排查手册

> 适用：华为 / 荣耀（HiSilicon Kirin）开源内核适配，尤其涉及自编译内核
> 首次成文：2026-09-28（MateRS NEO / Kirin 970 / EMUI 9.1 / Linux 4.9.148）
> 触发案例：`net_hw_hook_localout+0x170` 内核 panic（§8，配置漂移）
> 补充案例：`struct inode` 因 CVE-2020-14381 回移漂移（§8.6，补丁漂移，**无需修复**）

---

## 0. 一句话结论

**华为内核源码里的部分驱动是"预编译汇编"（`.S`），其结构体偏移是写死的数字字面量。
只要结构体布局相对华为 CI 当年编译时发生变化，这些 `.S` 就会读错字段——
而编译器、链接器、静态检查都不会报错，只在运行时崩溃。**

布局变化的**两个来源**，必须同时防：

| 来源 | 机制 | 实例 |
|---|---|---|
| **① 配置漂移** | 改了影响结构体布局的开关 | `CONFIG_NET_NS=y` → `possible_net_t` 0→8 → `struct sock` +8（§2、§8） |
| **② 补丁漂移** | 回移的 CVE 补丁改了被 `.S` 引用的结构体定义 | CVE-2020-14381 在 `struct inode` 插入 `atomic64_t i_sequence` → 其后成员 +8（§8.6） |

> ⚠️ 反直觉之处：**补丁通常改 `.c`（会重编译，安全），
> 但 CVE 回移经常顺带改 `.h` 里的结构体定义**——那一刻所有预编译 `.S` 全部作废。

本手册给出：如何**提前发现**（§3）、如何**定位**（§4–§5）、如何**修复**（§6）、
**哪些配置项是高危开关**（§2）、以及**如何区分候选与真实故障**（§3、§8.6）。

---

## 1. 为什么华为内核有这种坑

| 事实 | 后果 |
|---|---|
| 华为把部分驱动以 `.S`（预生成汇编）发布，**没有 `.c` 源码** | 无法重新编译，只能改汇编或对齐配置 |
| `.S` 里保留完整 DWARF（`.file` / `.loc` / `.debug_info`） | **好消息**：可反查出厂商编译时的结构体布局 |
| 汇编立即数是数字字面量，汇编器**不会**按当前 `.config` 重算 | 配置一变，偏移就错，且无任何编译期警告 |
| 华为 CI 用**出厂配置 + 出厂源码**编译这些 `.S` | 你的配置或源码偏离越多，风险越大 |

**关键推论**：这不是"华为的 bug"，而是"我们改了东西"的必然结果。
只要动了**影响结构体布局的配置开关**，或回移了**改动结构体定义头文件的补丁**，
就必须重新审计所有预编译 `.S`。

> 📌 **两个来源都要查**：只盯 `defconfig` 是不够的。
> `git log -p -- include/linux/fs.h include/net/sock.h ...` 里任何
> "在结构体中间插入字段"的改动，都会让相关 `.S` 作废（§8.6 实例）。

### 1.1 已确认的预编译汇编清单（MateRS EMUI 9.1.0 树，共 25 个）

含结构体访问（**需要审计**）：

```
block/hisi-bkops-core.S              block/hisi-bkops-sysfs.S
block/hisi-blk-busy-idle-notify.S    block/hisi-blk-core.S
block/hisi-blk-dump.S                block/hisi-blk-flush.S
block/hisi-blk-ft.S                  block/hisi-blk-iosched-ufs-mq.S
block/hisi-blk-latency.S             block/hisi_freq_ctl.S
drivers/huawei_platform/net/hw_netfilter/nf_ad_filter.S
drivers/huawei_platform/net/hw_netfilter/nf_app_dl_monitor.S
drivers/huawei_platform/net/hw_netfilter/nf_hw_common.S
drivers/huawei_platform/net/hw_netfilter/nf_hw_hook.S
drivers/scsi/ufs/hisi_ufs_bkops.S    drivers/scsi/ufs/ufs_vendor_mode.S
mm/pagecache_manage.S
```

纯寄存器代码（**无需审计**）：`arch/arm64/{crypto,kernel,lib,mm}/*.S`、
`drivers/oases/*.S`、`fs/erofs/lz4armv8/lz4armv8.S`、`usr/initramfs_data.S`。

> 判定方法：`pahole --sizes <obj> | wc -l` 为 0 即无 DWARF 结构体信息，无需审计。

---

## 2. 高危配置开关（改这些必须重新审计 §1.1）

### 2.1 已验证：`CONFIG_NET_NS`

```c
/* include/net/net_namespace.h:262 */
typedef struct {
#ifdef CONFIG_NET_NS
	struct net *net;      /* 0 → 8 字节 */
#endif
} possible_net_t;
```

- 关闭时 `possible_net_t` = **0 字节**；开启时 = **8 字节**
- 每个内嵌它的结构体，**其后所有成员整体 +8**

内嵌 `possible_net_t` 的结构体（`grep -rn possible_net_t include/`）：

| 头文件 | 结构体 |
|---|---|
| `include/net/sock.h:188` | `sock_common`（→ 整个 `struct sock` 及所有子类） |
| `include/linux/netdevice.h:1867` | `net_device` |
| `include/net/neighbour.h:72,173` | `neigh_parms`、`pneigh_entry` |
| `include/net/netfilter/nf_conntrack.h:100` | `nf_conn` |
| `include/net/xfrm.h:125,524` | `xfrm_state`、`xfrm_policy` |
| `include/net/inet_hashtables.h:78` | `inet_bind_bucket` |
| `include/net/genetlink.h:99` | `genl_family` |
| `include/net/cfg80211.h:3569` | `wiphy` |

**连带效应**：`struct sock` 变大 → 所有继承它的结构体全部偏移：
`tcp_sock`、`request_sock`、`inet_timewait_sock`、`unix_sock`、`netlink_sock` 等。

> ⚠️ `CONFIG_NET_NS` 在 `init/Kconfig:1363` 中 **`default y`**，且 `depends on NET`。
> 所以只要父开关 `CONFIG_NAMESPACES=y`，**不改 defconfig 也会默认打开**。
> 华为出厂 defconfig 通常是 `# CONFIG_NAMESPACES is not set`（整个命名空间族关闭）。

### 2.2 其他高危类别（同类风险，需按 §3 扫描确认）

| 类别 | 代表开关 | 影响 |
|---|---|---|
| 命名空间族 | `CONFIG_NAMESPACES` / `USER_NS` / `PID_NS` / `IPC_NS` / `UTS_NS` | 结构体内嵌 `struct nsproxy`、`possible_net_t` 等 |
| 安全框架 | `CONFIG_SECURITY` / `SELINUX` / `HISI_*_LSM_HOOKS` | `struct sock.sk_security`、`inode.i_security` 等字段有无 |
| 审计 / 统计 | `CONFIG_HW_NETWORK_MEASUREMENT` / `HW_DPIMARK_MODULE` / `HUAWEI_XENGINE` | `struct sock` 尾部华为私有字段 |
| 锁调试 | `CONFIG_DEBUG_SPINLOCK` / `LOCKDEP` / `DEBUG_LOCK_ALLOC` | `spinlock_t` / `rwlock_t` / `mutex` 尺寸变化（**全局**影响） |
| 内存 cgroup | `CONFIG_MEMCG` | `struct page` / `sk_memcg` 等 |
| 追踪 / 性能 | `CONFIG_FTRACE` / `BPF` / `PERF_EVENTS` | `task_struct`、`sk_buff` 等热结构 |

**实战教训**：`CONFIG_HW_DPIMARK_MODULE` 与 `CONFIG_NET_RX_BUSY_POLL` 曾被我误判为元凶，
实际二者在厂商 `.o` 的 DWARF 中**同样存在**（即厂商也是开的），故与偏移无关。
**必须用 DWARF 对比来判定，不能靠猜。**

### 2.3 补丁导致的布局漂移（与配置无关，同样高危）

回移 CVE 补丁时，**改了结构体定义的头文件**就会引入漂移。
这类改动在 `defconfig` 里完全看不出来，必须查 git 历史。

**本次实例（详见 §8.6）**：CVE-2020-14381 回移在 `include/linux/fs.h:687`
**无条件**插入了 `atomic64_t i_sequence;`，位于 `i_version` 与 `i_count` 之间，
导致 `struct inode` 从 704 → 712 字节，`i_count` 376 → 384、`i_private` 688 → 696。

**排查命令**（改完补丁、烧录前）：

```bash
# 找出所有"改过结构体定义头文件"的提交
git log --oneline -- '*.h' | head -30

# 精确看某个头文件里是否插入了字段
git log -S "i_sequence" -- include/linux/fs.h     # 命中即说明有插入
git log -p -- include/linux/fs.h | grep -E '^\+.*;' | head -20

# 与 pristine 树逐字节对比（最可靠）
diff -u <pristine>/kernel/include/linux/fs.h include/linux/fs.h | head -40
```

**高危头文件清单**（内嵌它们、或本身被预编译 `.S` 大量引用的）：

| 头文件 | 结构体 | 被谁引用 |
|---|---|---|
| `include/net/sock.h` | `sock_common` / `sock` | `hw_netfilter/*.S` |
| `include/linux/fs.h` | `inode` / `file` | `hisi-blk-*.S`、`hisi_ufs_bkops.S` |
| `include/linux/blkdev.h` | `request_queue` | `block/hisi-blk-*.S` |
| `include/scsi/scsi_host.h` | `Scsi_Host` | `hisi_ufs_bkops.S`、`ufs_vendor_mode.S` |
| `include/linux/mm_types.h` | `mm_struct` / `vm_area_struct` | `mm/pagecache_manage.S` |
| `include/linux/sched.h` | `task_struct` | 多个 |
| `include/linux/fs.h`（`file`） | `file` | `hw_netfilter/*.S` |

> 判定法：`git log -p -- <头文件>` 中出现 `+<type> <field>;` 且**不在结构体末尾**，
> 即中间插入 → 该结构体此后所有成员偏移变化 → 立即重跑 `tools/abi-guard.py`。

---

## 3. 预防：改配置后自动扫描

仓库内置 `tools/abi-guard.py`（本手册配套工具）：

```bash
# 全量扫描所有预编译汇编（改配置后、烧录前必跑）
python3 tools/abi-guard.py

# 只看概要（每个漂移结构体一行）
python3 tools/abi-guard.py --summary

# 列出可疑指令点（含函数名与行号）
python3 tools/abi-guard.py --obj out/drivers/huawei_platform/net/hw_netfilter/nf_hw_hook.o --candidates
```

**原理**：把厂商 `.o` 自身 DWARF 里的结构体布局，与你 `out/vmlinux` 的布局逐字段对比，
找出所有发生漂移的结构体；再把 `.S` 里用到的、数值等于厂商旧偏移的立即数列为**候选点**。

> ⚠️ **务必理解 `candidate` 的含义**：它只是"这里值得看"，**不是结论**。
> 一个数字偏移会被几十个不相干的结构体同时命中，所以
> "`.S` 里出现了 216，而 `struct net` 有字段在 216" **完全不能证明**那条指令访问的是 `struct net`。
> 本次案例中 `ldr x0,[x0,216]` 的真实归属是 `struct file.f_cred`（**未漂移**），
> 却被 `net.proc_net` / `request_sock.saved_syn` 双双命中。
> 工具的输出必须再用 §4 的 `.loc` 归属法或 §5 的数据流法确认。

**`STALE` 与 `AMBIG` 的区别（修完之后工具才不会一直报警）**：

工具把候选再分成两类，因为**修好之后旧的候选点会"看起来还在"**：

| 标记 | 含义 | 说明 |
|---|---|---|
| `[STALE]` | `.S` 用的是**厂商偏移**，而该数值在你内核布局里**不是**同宽度字段的合法偏移 | **可能真的错**，重点看这些 |
| `[AMBIG]` | 该数值在**两套布局里都合法**（同宽度） | 数值匹配无法判定，必须靠 `.loc`/数据流 |

实例（本仓库实测）：修好之后 `nf_hw_hook.S` 用 `752`（内核 `sk_socket`），
但厂商布局里 `752` 是 `sk_user_data`（也是 8 字节）——纯数值匹配会**永远报警**。
而修复**前**用 `744`，厂商 `sk_socket`=744，内核布局里 744 只有 `sk_tsflags`（**2 字节**），
宽度不匹配 → 正确判为 `[STALE]`。

**这就是为什么必须做宽度匹配**：`744` 在内核里确实存在，但它是 2 字节字段，
而指令读 8 字节 → 不是同一个字段。

**自校验（本仓库实测，可作为工具正确性的回归测试）**：

对 `nf_hw_hook.o` 单个对象：

| `.S` 状态 | `[STALE]` 数 | 说明 |
|---|---|---|
| 厂商**原始**（未修） | **7** | 含 `sk_err` 616、`sk_socket` 744 |
| 本仓库**已修复** | **5** | 上述两项变为 `[AMBIG]`/消失 |

差值 2 即本次真正修掉的 `struct sock` 字段。**全树**（17 个对象）对应为
原始 **11** → 已修复 **9**。

若你的树跑出来两者相同，说明修复没生效或工具退化。

> ⚠️ **绝不要只看 `RESULT: N struct(s) show layout drift` 就动手**。
> 漂移是**必然**的（你改了配置/补丁），关键看 `[STALE]` 里有几处、
> 再用 §8.7 顺序确认归属。本仓库最终结论是**只有 4 处真实故障**。

**两个实现坑（都会让工具悄悄漏报，务必知道）**：

1. **函数指针字段**。`pahole` 把 `void (*sk_error_report)(struct sock *);`
   排成 `void (*sk_error_report)(struct sock *); /* 848 8 */`，
   若用 `name;` 正则解析字段名，**所有函数指针字段都会被丢掉**——
   本次 `sk_error_report` 的 `840→848` 漂移就是这样一度漏掉的。
   工具已改用「先取 `/* off size */` 注释前的文本，再分别匹配 `(*name)` 与 `name;`」。
2. **同名结构体多布局**。`out/vmlinux` 的 DWARF 合并了所有 `.o`（含厂商 blob），
   所以 `struct sock` 会同时出现 936 字节（厂商 blob，2 条）与 944 字节（内核真实，935 条）。
   工具取「块数最多的那个」作为内核布局，并在多布局时打印 `NOTE`；
   否则会拿厂商自己的旧布局当基线，漂移全部消失。

**建议接入流程**：
1. 每次改 defconfig → 立即跑 `abi-guard.py --summary`
2. 出现 `candidate` → 用 §4/§5 逐条确认归属（**不要直接照改**）
3. 确认后 → 按 §6 选修复路线
4. 仅"布局漂移但 `.S` 未使用"→ 记录备案，可不改（但换机型要重扫）

> 性能：工具对每个二进制只跑**一次** `pahole` 全量 dump（`out/vmlinux` 约 12s），
> 解析出所有结构体；早期版本对每个结构体单独跑 `pahole -C`，
> 486 个结构体 × 3 次调用会慢到几分钟不出结果。

---

## 4. 定位：三步确认法

### 第 1 步 — 从 panic 反查崩溃指令

```bash
# 找到崩溃函数与偏移
grep -nE "PC is at|LR is at|Unable to handle" console-ramoops-0.txt

# 反汇编（.o 与 vmlinux 都要看）
TC=<工具链>/bin/aarch64-linux-android-
$TC objdump -d out/drivers/.../xxx.o | awk '/<崩溃函数>:/,/^$/'
```

**要点**：`PC is at func+0x170` 中的 `0x170` 是**函数内偏移**，
不是结构体偏移。要反汇编到 `func+0x170` 看那条指令访问了哪个偏移。

### 第 2 步 — 用 DWARF 解出"厂商以为的结构体"

```bash
# 厂商布局（从预编译 .o 的 DWARF）
pahole -C sock out/drivers/.../xxx.o | grep -E "sk_socket|sk_err|size:"

# 你的内核布局
pahole -C sock out/vmlinux | grep -E "sk_socket|sk_err|size:"
```

**判定**：若厂商 `sk_socket=744` 而你的是 `752`，则整体 +8 → 命中 §2 某开关。

### 第 3 步 — 确认该偏移确实被指令使用

```bash
grep -nE "\[x[0-9]+, ?744\]" drivers/.../xxx.S
```

### 4.1 用 `.loc` 精确定位归属（避免误伤）

`.S` 里的 `.loc <file_idx> <line>` 记录了每行汇编来自哪个头文件，
**这是区分"这个偏移属于哪个结构体"的权威依据**：

```bash
# 看 .S 里 sock.h 的 file 索引
grep -n '\.file.*sock\.h' nf_hw_hook.S

# 列出所有非栈偏移及其来源头文件
python3 tools/abi-locattr.py    # 见 §9 脚本清单
```

> ⚠️ **重要教训**：不要用"偏移数值匹配任意结构体"来判断归属。
> 例如偏移 `80` 在厂商 DWARF 里同时匹配 `file.f_flags`、`vm_area_struct.vm_flags`、
> `sock_common.skc_cookie` 等几十个字段，纯数值匹配会产生大量假阳性。
> **必须结合数据流**（该寄存器是否来自 `skb->sk`）或 `.loc` 头文件归属。

---

## 5. 数据流法：确认"结构体真的被访问了"

对网络类驱动，`struct sock` **只能**通过 `skb->sk`（`sk_buff` 偏移 24）到达。
可用数据流追踪排除假阳性：

```python
# 见 tools/abi-sockflow.py：追踪 ldr xN,[xM,#24] 后的解引用
```

**实战结果**：`nf_hw_hook.S` 中真正访问 `struct sock` 的只有 **4 条指令**
（均在 `net_hw_hook_localout` 内），即本次需要修的全部：

| 行号 | 指令 | 偏移 | 字段 |
|---|---|---|---|
| 1699 | `ldr x0, [x0,744]` | 744 → 752 | `sock.sk_socket`（`find_skb_uid`） |
| 1786 | `str w1, [x0,616]` | 616 → 624 | `sock.sk_err`（`send_reject_error`） |
| 1790 | `ldr x1, [x1,840]` | 840 → 848 | `sock.sk_error_report` |
| 1799 | `ldr w2, [x4,616]` | 616 → 624 | `sock.sk_err`（printk 读回） |

其余三个模块（`nf_ad_filter` / `nf_app_dl_monitor` / `nf_hw_common`）
**完全不含 `struct sock` 访问**——尽管偏移扫描器会报出若干"疑似"。

> ⚠️ 实现要点：条件分支会携带状态。`cbnz x0, .L189` 把 `x0=skb->sk`
> 带到目标标签，若只做线性扫描会**漏掉 `str w1,[x0,616]`**（只剩 3 处）。
> 工具用不动点迭代合并各标签的活跃寄存器集合，才能得到完整的 4 处。

---

## 6. 修复：三条路线

| 路线 | 做法 | 适用 | 风险 |
|---|---|---|---|
| **A. 改汇编立即数**（推荐） | 把 `.S` 里过时偏移改成正确值 | 偏移固定、改动点少（本次仅 4 处） | 低。需逐条核对，勿全局替换 |
| **B. 关掉触发开关** | 如 `CONFIG_HW_NETFILTER_MODULE=n` | 该功能可放弃时 | 低，但**丢功能**（失去华为包过滤等） |
| **C. 对齐配置** | 关 `CONFIG_NET_NS` 等 | 想完全复现出厂 ABI | **高**：容器等功能一并失效；且 `default y` 需改父开关 |

### 6.1 路线 A 的正确姿势

```bash
# 1) 先备份原文件（或直接依赖 git）
git show HEAD:drivers/.../nf_hw_hook.S > /tmp/orig.S   # 修改前先留底

# 2) 用脚本按"精确偏移+精确指令"改写，拒绝全局 sed
python3 fix-netfilter-abi.py --check    # 预演
python3 fix-netfilter-abi.py            # 应用

# 3) 重新编译（只改了 .S，属增量编译）
./rebuild.sh 23

# 4) 断言校验
bash tools/abi-verify.sh
```

**脚本必须做的安全约束**（`fix-netfilter-abi.py` 已实现）：
- 只改**已证明**属于该结构体的偏移，其余偏移列入 `GUARD_OFFSETS` 拒绝改写
- 校验每个偏移的**出现次数**与预期一致（防漏改/多改）
- 提供 `--check` 预演模式

### 6.2 验证必须覆盖"最终烧录产物"

不要只验证 `.o`。要验证**真正被烧录的二进制**：

```bash
# 从 Image.gz 解出裸内核，按指令签名搜索
zcat out/arch/arm64/boot/Image.gz > /tmp/Image
python3 - <<'PY'
import struct
d=open('/tmp/Image','rb').read()
def w(x): return struct.pack('<I',x)
def ldr(rt,base,off): return w(0xF9400000|((off//8)<<10)|(base<<5)|rt)
# 用崩溃点前后若干条指令构成唯一签名
sig = lambda off: (w(0x39404801)+w(0x12800015)+w(0x53001C21)+w(0x7100183F)+w(0x540000E0)+ldr(0,off))
print('fixed #752:', d.count(sig(752)), ' stale #744:', d.count(sig(744)))
PY
```

**本次实测**：`fixed=1, stale=0` → 确认修复进入产物。

---

## 7. 换机型 Checklist（可直接照做）

```
□ 1. 确认机型/内核版本/出厂 defconfig
     - 找出所有 *_defconfig，注意华为常把关键开关集中在 merge_*_defconfig

□ 2. 盘点预编译汇编
     find . -name '*.S' | 排除 arch/ usr/ oases/
     对每个：pahole --sizes <obj> | wc -l   # 非 0 才需审计

□ 3. 建立"基线 ABI 快照"（编译一次原始配置）
     pahole -C <关键结构体> out/vmlinux > baseline.txt

□ 4. 记录你要改的每个配置项，逐一问：
     这个开关会不会改变某个结构体的布局？
     （对照 §2 高危清单 + 在头文件里 grep 该 CONFIG_）

□ 4b. 同样检查你回移的补丁（配置漂移之外的第二来源）
      git log --oneline -- '*.h'                # 哪些提交改了头文件
      git log -p -- include/linux/fs.h | grep -E '^\+.*;'
      diff -u <pristine>/kernel/include/linux/fs.h include/linux/fs.h
      → 任何"在结构体中间插入字段"的改动都会作废相关 .S（§2.3、§8.6）

□ 5. 改完配置/补丁后立即扫描
     python3 tools/abi-guard.py
     有 candidate → 进入 §4/§5 定位（先确认归属，再动手）
     归属判定按 §8.7 顺序：指令形态 → 基址结构体全字段 diff → .loc → 数据流
     若全字段 diff = NONE → 该候选是假阳性，记录备案即可，**不要改**

□ 6. 修复并验证
     - 备份原 .S
     - 精确改写（拒绝全局 sed）
     - 重新编译
     - 对 Image.gz 做指令签名断言

□ 7. 保留证据
     - 修复提交写清"哪个配置 → 哪个结构体 → 哪个字段 → 偏移差"
     - 保存原始 .S 备份
```

---

## 8. 案例复盘：`net_hw_hook_localout+0x170` panic

### 8.1 现象

```
[127.779418s][pid:0,cpu4,swapper/4]Unable to handle kernel paging request at virtual address 00030018
[127.779510s][pid:0,cpu4,swapper/4]PC is at net_hw_hook_localout+0x170/0x22c
[127.779510s][pid:0,cpu4,swapper/4]LR is at net_hw_hook_localout+0x148/0x22c
[127.784271s][pid:0,cpu4,swapper/4]Kernel panic - not syncing: Fatal exception in interrupt
```

- 中断上下文（`swapper/4`, pid 0）→ 必然 panic
- `Oops: 96000005` = level-1 translation fault（访问未映射地址）
- 触发条件：访问 HTTP 接口（`POST /admin/api/login`）

### 8.2 定位过程

| 步骤 | 动作 | 结果 |
|---|---|---|
| 1 | 反汇编 `func+0x170` | `ldr x0,[x0,#24]` |
| 2 | 往前找 `x0` 来源 | `ldr x0,[x0,#744]`，且此时 `x0=0x30000` |
| 3 | 验算 | `0x30000+0x18=0x30018` ✅ 与日志完全一致 |
| 4 | `.loc` 归属 | `nf_hw_hook.c:55` → `find_skb_uid()` 的 `sk->sk_socket` |
| 5 | `pahole` 对比 | 厂商 `sk_socket=744`，内核 `=752`，**差 +8** |
| 6 | 求根因 | 厂商 `sock_common=136`，内核 `=144`；`possible_net_t` 0→8 字节 |
| 7 | 查配置 | 我方 `CONFIG_NET_NS=y`；厂商出厂 `# CONFIG_NAMESPACES is not set` |

**为什么 `0x30000` 不是 NULL？** 因为 `744` 在你的布局里是 `sk_tsflags`(u16)，
读 8 字节得到 `sk_tsflags|sk_shutdown<<16|...` = `0x00030000`
（`sk_shutdown=3`，即 `SHUTDOWN_MASK`）。**非零垃圾值绕过了所有 NULL 检查**——
这正是此类 bug 隐蔽的原因。

### 8.3 真机 A/B 对照（决定性证据）

| | 正常内核 #2 | 崩溃内核 #18 |
|---|---|---|
| 构建时间 | 09-23 20:13 | 09-24 20:32 |
| `CONFIG_NAMESPACES` | **not set** | `=y` |
| `CONFIG_NET_NS` | 随之关闭 | `=y` |
| 结果 | 稳定运行 | panic |

配置全量 diff 仅 **14 行**，全部是命名空间族开关。

### 8.4 修复

仅改 `nf_hw_hook.S` 中 4 处：

| 函数 | 字段 | 原值 | 修正 |
|---|---|---|---|
| `find_skb_uid()` | `sk_socket` | 744 | **752** |
| `send_reject_error()` | `sk_err` | 616 | **624** |
| `send_reject_error()` | `sk_error_report` | 840 | **848** |

保留 `CONFIG_NET_NS=y`（容器功能不受影响），华为包过滤模块继续可用。

### 8.5 归因（重要）

**本次崩溃是自致的，与 CVE / RKSU 补丁无关**：

- `include/net/sock.h` 与华为 pristine 树**逐字节一致**（`cmp` 验证）
- CVE 补丁从未改动它
- 真正原因：Droidspaces 适配开启 `CONFIG_NAMESPACES=y` → `NET_NS` 默认 `y`

> 教训：**"改了配置"比"打了补丁"更容易引入这类 ABI 错位**，
> 因为补丁通常改 `.c`（会重新编译），而配置改的是**所有代码共同的假设**。

### 8.6 第二个案例：`struct inode` 因 CVE 回移而漂移（但**无人使用**）

这是与 §8 相反的**对照案例**，价值在于说明「工具报候选 ≠ 有 bug」。

**漂移事实（真实存在）**：

| | 厂商 blob | 本树内核 |
|---|---|---|
| `struct inode` size | 704 | **712** |
| `i_version` | 368 | 368 |
| `i_sequence` | **不存在** | **376**（`atomic64_t`，8B） |
| `i_count` | 376 | **384** |
| `i_private` | 688 | **696** |

**根因**：commit `cd83b94ca`「CVE-2020-14381: futex: Fix inode life-time issue」
（回移上游 4.9.218 `fb099f3bb477a0ee2d0669a753f7ffcdf8884c2d` /
upstream `8019ad13ef7f64be44d4f892af9c840179009254`，
改 `fs/inode.c` / `include/linux/fs.h` / `include/linux/futex.h` / `kernel/futex.c`）
在 `include/linux/fs.h:687` **无条件**插入：

```c
	u64			i_version;              /* :686  — 本来就有 */
+	atomic64_t		i_sequence;		/* :687 see futex  ← 新增，无 #ifdef */
	atomic_t		i_count;                /* :688  — 本来就有 */
```

pristine 树（`NEO_PIE_EMUI9.1.0_opensource/kernel/include/linux/fs.h:686-687`）
确认是 `u64 i_version;` 紧跟 `atomic_t i_count;`，**无 `i_sequence`**。

**这是与 §8.5 相反方向的结论**：对 `struct sock` 而言 CVE 补丁无辜
（`include/net/sock.h` 与 pristine 逐字节一致）；但 `struct inode` 的漂移
**恰恰是 CVE 回移造成的**。所以「补丁有罪 / 无罪」必须**按结构体分别判定**，
不能一概而论。

**候选点与证伪结果**：`abi-guard.py` 对全树报出 11 处候选，其中 9 处指向 `inode`
（`hisi-blk-core.o` 的 `i_private` 8 处、`hisi-blk-iosched-ufs-mq.o` 的 `i_flctx` 1 处、
`hisi_ufs_bkops.o` 的 `i_count` 1 处）。**经逐一数据流/结构体对照，9 处全部证伪**：

| 对象 | 报出的 inode 字段 | 真实归属 | 证伪依据 |
|---|---|---|---|
| `hisi-blk-core.o`（8 处） | `i_private` 688→696 | `request_queue.queue_tags@688` | 指令是 `ldr xN,[xM,688]` → `add xN,xN,136`（`lld_func` 内 `blk_idle`），`request_queue` 全字段 diff = **NONE** |
| `hisi_ufs_bkops.o`（1 处） | `i_count` 376→384 | `ufs_hba.ufshcd_state@376` | `x19 = hba`（首参），`ufs_hba` 全字段 diff = **NONE** |
| `hisi-blk-iosched-ufs-mq.o`（1 处） | `i_flctx` 400→408 | `kmalloc` 出的模块本地定时器对象 | 上下文为 `init_timer_key` 后写回调，`x19` 来自 `kmalloc`（`.loc 17 499` = slab.h） |

**全字段 diff 是决定性的排除手段**：

```bash
# 对"基址指针指向的结构体"做逐字段 diff，drifted=NONE 即可排除
python3 - <<'EOF'
import subprocess, re
def one(path, name):
    out = subprocess.run(['pahole','-C',name,path],capture_output=True,text=True).stdout
    f = {}
    for line in out.splitlines():
        m = re.search(r'/\*\s*(\d+)\s+(\d+)\s*\*/', line)
        if not m or 'size:' in line: continue
        body = line[:m.start()]
        if ';' not in body: continue
        fm = re.search(r'\(\s*\*\s*([A-Za-z_]\w*)\s*\)', body) or \
             re.search(r'([A-Za-z_]\w*)\s*(?:\[\d+\])?\s*;\s*$', body)
        if fm: f[fm.group(1)] = (int(m.group(1)), int(m.group(2)))
    return f
v = one('out/block/hisi-blk-core.o', 'request_queue')
k = one('out/vmlinux',              'request_queue')
drift = {n: (v[n], k.get(n)) for n in v if n in k and v[n] != k[n]}
print('drifted fields:', drift or 'NONE')     # NONE → 该结构体没漂移，候选是假阳性
EOF
```

**结论（重要诚实点）**：`struct inode` 的漂移**真实存在**，
但**当前 9.1.0_RKSU 树内没有任何厂商预编译 `.S` 真的以过时立即数访问它**。
全树 11 处候选经逐一核对后**全部是假阳性**。
→ **不需要为 `struct inode` 做任何修复**；但要**记录备案**，换机型/改配置后重扫。

### 8.7 候选归属的判定顺序（照这个顺序做，别跳步）

```
① 看指令形态与寄存器来源 —— 谁是这个基址寄存器的来源？
      ldr xN,[xM,OFF]  →  xM 是参数？是 kmalloc 返回值？是另一个结构体成员？
② 对"基址结构体"做全字段 diff —— drifted=NONE 立即排除（最快、最硬）
③ 再看 .loc 归属头文件 —— 确认这条指令来自哪个 .c/.h
④ 最后才做数据流追踪 —— 用于 ①②③ 都无法排除时
```

> ⚠️ **绝不要只用"偏移数值 + 访问宽度相等"下结论**。
> 一个数值会被几十个结构体同时命中，本次 11 处候选**全部**是这种假阳性。
> `abi-guard.py` 的输出必须视为「**去哪看**」，而不是「**是什么**」。

---

## 9. 配套脚本清单

| 脚本 | 用途 |
|---|---|
| `tools/abi-guard.py` | **入口**：扫描预编译汇编的结构体布局漂移，列出候选指令点 |
| `tools/abi-locattr.py` | **归属**：用 `.loc` 把偏移归到具体头文件，排除假阳性 |
| `tools/abi-sockflow.py` | **定论**：数据流追踪，确认哪些指令真的访问了 `struct sock` |
| `fix-netfilter-abi.py` | 修复 `nf_hw_hook.S` 的 4 处偏移（含 `--check`） |
| `tools/abi-verify.sh` | **回归**：断言重建后 `.o` 旧偏移消失、新偏移出现 |

> 厂商原始 `.S` 无需额外备份：它就是修复提交的父版本，随时可取回
> `git show <修复commit>^:drivers/huawei_platform/net/hw_netfilter/nf_hw_hook.S`
> （本仓库实测与手工备份 md5 逐字节一致 `23be2731f372`）。

**三个工具的定位（按顺序用）**：

```
abi-guard.py    →  有哪些结构体漂移了？哪些偏移值得看？      （候选，必跑）
abi-locattr.py  →  这个偏移来自哪个头文件？                  （排除，快速）
abi-sockflow.py →  到底哪几条指令访问了目标结构体？          （定论，精确）
```

**自校验（本仓库实测）**：`abi-sockflow.py`（数据流定论工具）对厂商**原始**
`nf_hw_hook.S` 独立得出 **4** 个故障点，与人工数据流分析、与实际补丁**完全一致**；
对**已修复**的 `.S` 得出 **0** 个：

| 行号 | 指令 | 偏移 | 字段 |
|---|---|---|---|
| 1699 | `ldr x0, [x0,744]` | 744 → 752 | `sock.sk_socket` |
| 1786 | `str w1, [x0,616]` | 616 → 624 | `sock.sk_err` |
| 1790 | `ldr x1, [x1,840]` | 840 → 848 | `sock.sk_error_report` |
| 1799 | `ldr w2, [x4,616]` | 616 → 624 | `sock.sk_err`（printk 读回） |

> ⚠️ 注意区分：**`abi-sockflow.py` 能给出 0/4 的干净结论**（它追踪真实数据流）；
> 而 `abi-guard.py` 即使在**已修复**的树上仍会报 `[STALE]`（本仓库 5 处）——
> 因为它是**候选扫描器**，会命中无关结构体。判断"修没修好"要用
> `abi-sockflow.py` 或 `tools/abi-verify.sh`，**不要用 `abi-guard.py` 的 STALE 计数**。

> `abi-sockflow.py` 需要处理**条件分支携带状态**（`cbnz x0, .L189` 把
> `x0=skb->sk` 带到目标标签），否则会漏掉 `str w1,[x0,616]` 这类站点。
> 工具已用不动点迭代处理；换机型时若结果与预期不符，先查这里。

**全树扫描基线（本仓库实测，可作换机型时的对照）**：

| 指标 | 值 |
|---|---|
| 需审计的预编译对象 | **17** 个 |
| 漂移结构体条目（对象×结构体） | **48** 条（10 个不同结构体名） |
| `abi-guard.py` 报出的候选字段 | **20** 处（11 个结构体条目含候选） |
| 其中 `[STALE]` | **9** 处 |
| 其中 `[AMBIG]` | **11** 处 |
| 经 §8.7 判定为**真实故障**的 | **4** 处（全在 `nf_hw_hook.S`） |
| 判定为**假阳性**的 | 其余全部 |

> 这个 20 → 9 → 4 的收敛过程就是本手册的核心方法论：
> **工具负责缩小范围，人负责用结构体 diff / 数据流定性**。
> 一个"漂移了但没人用"的结构体（如 `struct inode`）**不需要任何修复**。
>
> 9 处 `[STALE]` 的归属（全部证伪，记录备案即可）：
> `nf_hw_hook.o` 5 处（`neigh_setup`/`reachable_time`/`proc_net`/`secid`/`peer_secid`
> —— 实为模块本地 `dl_info` 与 `file.f_cred`）、
> `nf_app_dl_monitor.o` 3 处（`abi-sockflow.py` 实测该模块访问 `struct sock` = **0**）、
> `hisi_ufs_bkops.o` 1 处（`i_count` 实为 `ufs_hba.ufshcd_state`，`ufs_hba` 全字段 diff = NONE）。

---

## 10. 反面教训（避免重走弯路）

1. **不要靠猜配置项**。我最初误判为 `HW_DPIMARK_MODULE` / `NET_RX_BUSY_POLL`，
   实际二者在厂商 DWARF 里同样存在。**必须用 DWARF 对比**。
2. **不要用偏移数值匹配结构体**。一个数值可匹配几十个字段，假阳性极高。
   要用 `.loc` 归属或数据流分析。
3. **不要只验证 `.o`**。要验证最终 `Image.gz`，否则可能打包了旧产物。
4. **不要全局 `sed` 替换偏移**。同一数值在不同结构体里含义不同，会改坏无关代码。
5. **不要忽略"看起来无关"的开关**。`CONFIG_NAMESPACES` 名字里没有 "net"，
   但它通过 `NET_NS` 的 `default y` 间接改变了整个网络栈的 ABI。
6. **不要在没有 A/B 对照时下结论**。真机上"旧内核正常 / 新内核崩溃"的
   `config` 对比，比任何推理都可靠。
7. **不要只防配置、不防补丁**。CVE 回移常顺手改结构体定义头文件，
   `defconfig` 里看不出来。改完补丁也要重跑 `abi-guard.py`（§2.3、§8.6）。
8. **不要把候选当结论**。本次全树 20 处候选 → 9 处 `[STALE]` → **真实故障只有 4 处**；
   `struct inode` 漂移真实存在却**无人使用**。
   报候选就动手改，会改坏正常代码（§8.6、§8.7）。
9. **不要用"数值是否出现过"判断修复是否生效**。修好之后新偏移
    （如 `752`）在厂商布局里恰好是另一个字段（`sk_user_data`），
    纯数值匹配会永远报警。必须做**宽度匹配**才能区分
    （`744` 在内核里只是 2 字节的 `sk_tsflags`，指令读 8 字节 → 真错）。
    工具已用 `[STALE]`/`[AMBIG]` 区分，见 §3。
10. **不要跳过「基址结构体全字段 diff」这一步**。它是排除假阳性最快最硬的手段：
   `request_queue` / `ufs_hba` / `blk_mq_tag_set` 三者 diff 均为 NONE，
   一次性否掉了 10 处候选（§8.6）。

---

## 附：快速自查命令

```bash
# 1. 我的内核有哪些结构体比厂商的大/小？
python3 tools/abi-guard.py --summary

# 2. 某个结构体在两边分别长什么样？
pahole -C sock out/drivers/huawei_platform/net/hw_netfilter/nf_hw_hook.o | head -30
pahole -C sock out/vmlinux | head -30

# 3. 这个配置项影响哪些结构体？
grep -rn "CONFIG_NET_NS" include/ | head

# 4. 厂商这个 .S 里用了哪些偏移？
grep -oE '\[x[0-9]+, ?[0-9]+\]' drivers/.../xxx.S | sort -u

# 5. 某偏移属于哪个结构体？（结合 .loc）
python3 tools/abi-locattr.py

# 6. 排除假阳性：对候选的"基址结构体"做全字段 diff（drifted=NONE 即排除）
#    见 §8.6 的 request_queue 例子；这是最快最硬的排除手段

# 7. 补丁是否改了结构体定义？（配置之外的第二来源）
git log -p -- include/linux/fs.h include/net/sock.h include/linux/blkdev.h \
  | grep -E '^\+.*[a-z_]+ [a-z_]+;' | head -20
```

> **全树扫描耗时提示**：`abi-guard.py` 对单个对象约 15s（`out/vmlinux` 的全量
> `pahole` dump 约 12s 是固定成本）。全树有 17 个需审计对象，
> 建议**后台运行或分批**，不要在前台等（早期串行跑 8 个 block 对象超过 600s）。
