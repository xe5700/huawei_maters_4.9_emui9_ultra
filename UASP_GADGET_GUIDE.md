# 让华为手机本身作为 UASP 外接硬盘（gadget 侧）使用

> 适用：`NEO_EMUI9.1.0_RKSU`（Kirin 970 / Mate RS 等），内核 `#21` 及以后。
> 目标：手机通过 USB 线插到 PC 上，PC 把手机识别为一块**支持 UASP 的外接硬盘**，
> 而不是手机去连接外接硬盘。

---

## 0. 一句话结论

内核侧改动只有 4 行 defconfig：

```
CONFIG_TARGET_CORE=y
CONFIG_TCM_FILEIO=y
CONFIG_USB_CONFIGFS_F_TCM=y
# CONFIG_USB_UAS is not set      <- 宿主侧开关，与本需求无关
```

用户态不需要任何二进制，**全部通过 configfs 手工搭建**，见 §3。

---

## 1. 为什么是 TCM 而不是 UAS

| 方向 | 需要的配置 | 说明 |
|---|---|---|
| 手机**连接** UASP 硬盘盒 | `CONFIG_USB_UAS`（宿主侧 `drivers/usb/storage/uas.c`） | 不是本需求 |
| 手机**充当** UASP 硬盘 | `CONFIG_USB_CONFIGFS_F_TCM`（gadget 侧 `drivers/usb/gadget/function/f_tcm.c`） | **本需求** |

`f_tcm.c` = **USB Gadget Target Fabric**，它把内核 target（SCSI target core）
通过 USB gadget 暴露出去，同时提供两种协议：

- **BOT / BBB**（Bulk-Only Transport）→ alternate setting **0**（主接口）
- **UAS**（USB Attached SCSI）→ alternate setting **1**，走 USB 3.0 **streams**

两者在 USB2.0 / USB3.0 下都能工作；UAS 在 USB2.0 下退化为 BOT 行为，插到
USB3.0 口才真正启用 streams。

### 前置条件（本树已满足，换机型需自查）

- `CONFIG_USB_GADGET=y`、`CONFIG_USB_LIBCOMPOSITE=y`、`CONFIG_USB_CONFIGFS=y`
- `CONFIG_USB_DWC3=y` + `CONFIG_USB_DWC3_DUAL_ROLE=y` + `CONFIG_USB_DWC3_HISI=y`
- DTS 中 dwc3 节点 `maximum-speed = "super-speed"`
  （本树：`arch/arm64/boot/dts/auto-generate/config/kirin970/kirin970_usb.dtsi:43`）
- `drivers/usb/dwc3/gadget.c` 中 `dwc->gadget.sg_supported = true`
  （UAS 需要 scatter-gather）

---

## 2. ⚠️ 后端必须选 FILEIO，不能选 IBLOCK

这是本次改动**唯一的高危点**，换机型时务必照抄这个选择。

`drivers/target/Kconfig`：

| 后端 | 是否 `select BLK_DEV_INTEGRITY` | 能否用 |
|---|---|---|
| `TCM_IBLOCK` | **是** | ❌ 禁用 |
| `TCM_FILEIO` | 否 | ✅ 用这个 |
| `TCM_PSCSI` | 否 | 可，但需物理 SCSI HBA |
| `TCM_USER2` | 否 | 需 UIO，用户态实现 |

### 为什么 IBLOCK 会炸

`CONFIG_BLK_DEV_INTEGRITY=y` 会改变 `struct bio`
（`include/linux/blk_types.h:158`）：

```c
union {
#if defined(CONFIG_BLK_DEV_INTEGRITY)
        struct bio_integrity_payload *bi_integrity;   /* 0 -> 8 字节 */
#endif
};
```

空 union 是 0 字节，开了就变 8 字节指针，**其后所有成员整体 +8**，
`struct bio` 从 **392 → 400**。连带还会改 `struct gendisk`
（`include/linux/genhd.h:213`）、`struct bio_set`（`include/linux/bio.h:681`）、
`struct request`（`include/linux/blkdev.h:252`）、
`struct request_queue`（`include/linux/blkdev.h:713`）。

而本树有 **10 个华为预编译 `block/*.S`** 用**冻结立即数**访问这些结构体：

```
block/hisi-bkops-core.S          block/hisi-blk-core.S
block/hisi-bkops-sysfs.S         block/hisi-blk-dump.S
block/hisi-blk-busy-idle-notify.S  block/hisi-blk-flush.S
block/hisi-blk-ft.S              block/hisi-blk-iosched-ufs-mq.S
block/hisi-blk-latency.S         block/hisi_freq_ctl.S
```

其中 `block/hisi-blk-core.S:736` 的 `ldr x1, [x19,376]` 读的就是
`bio.bi_io_vec`，紧接着 `ldr x0, [x1, x0]` 解引用 —— 一旦 +8 错位，
**立刻 panic**。这与本项目此前 `struct sock` 的 netfilter 事故是同一类错误。

### FILEIO 同样能导出块设备

`drivers/target/target_core_file.c:147` 有 `if (S_ISBLK(inode->i_mode))` 分支，
可以直接把整块块设备（如 `/dev/block/sda`）作为后端，参数：

```
fd_dev_name=/dev/block/sda      # 块设备或普通文件均可
fd_dev_size=...                 # 可省略，块设备自动取
fd_buffered_io=0|1              # 是否走页缓存，默认 0（O_DIRECT）
```

FILEIO 对 `bio_integrity*` / `bioset_integrity*` 的引用数为 **0**，
纯软缓冲 IO，不碰 integrity 路径。

---

## 3. 用户态配置（configfs）

**不需要重新编译任何用户态程序**，全在 shell 里完成。

> **顺序是硬约束，颠倒必失败。** 三个坑（均为真机实测）：
>
> 1. **必须先 `mkdir functions/tcm.usb0`，再建 wwn/tpg。**
>    `usbg_make_tpg()`（`drivers/usb/gadget/function/f_tcm.c:1345`）要求 `opts->ready`，
>    而该标志只在 `tcm_set_name()`（`f_tcm.c:2234`）里置位 —— 也就是**创建 function
>    instance 时**。先建 tpg 会得到 `Invalid argument`（EINVAL）。
> 2. **必须先写 tpg 的 `enable=1`，再绑 UDC。**
>    `tcm_bind()`（`f_tcm.c:2002-2018`）在 `!opts->can_attach` 时返回 `-ENODEV`；
>    而 `can_attach` 只在 `usbg_attach()`（`f_tcm.c:2211`）→
>    `tcm_register_callback()`（`:2192`）里置真，后者只被
>    `tcm_usbg_tpg_enable_store()`（`:1520`）调用。先绑后 enable 会得到
>    `configfs-gadget ff100000.dwc3: failed to start g1: -19`。
> 3. **不要新建 config 目录，直接用现成的 `configs/b.1`。**
>    `usb_add_config_only()`（`drivers/usb/gadget/composite.c:849-861`）在
>    `bConfigurationValue` 重复时返回 `-EBUSY`（`b.1` 已占用 1）。空 config 更会让
>    `configfs_composite_bind()`（`drivers/usb/gadget/configfs.c:1333-1350`）报
>    `Config b/1 of g1 needs at least one function.` 并返回 `-EINVAL`。

本机型 configfs 挂在 `/config`（等价于 `/sys/kernel/config`，用 `/config` 更短）。

### 3.0 先让系统自动挂载脚本闭嘴

`/init.usb.configfs.rc` 按 `sys.usb.config=<已知组合>` 精确触发（已知值共 38 个）。
设成一个它不认识的值，就不会有人来动你的配置：

```sh
setprop sys.usb.config uasp          # 未知值 → 无 trigger 命中
getprop sys.usb.config               # 应为 uasp
```

### 3.1 准备后端存储

```sh
truncate -s 512M /data/local/tmp/uasp-test.img     # 稀疏文件，秒建
# 或真磁盘镜像：
# dd if=/dev/zero of=/data/media/0/uasp.img bs=1M count=8192
# 或直接导出一整个块设备（危险，会覆盖该分区）：
# BACKEND=/dev/block/by-name/userdata
```

### 3.2 创建 target 后端

```sh
mkdir -p /config/target/core/fileio_0/disk0
echo "fd_dev_name=/data/local/tmp/uasp-test.img,fd_dev_size=536870912" \
     > /config/target/core/fileio_0/disk0/control
cat /config/target/core/fileio_0/disk0/info   # 应显示 Size: 536870912 Mode: O_DSYNC
echo 1 > /config/target/core/fileio_0/disk0/enable
```

`control` 语法来自 `drivers/target/target_core_file.c` 的 `fd_set_configfs_dev_params()`：
**逗号分隔**的 `key=value`；`fd_buffered_io` 只接受 `1`（要 `O_DSYNC` 就别写它）。
`fileio_0` 的 `0` 是 HBA id（`fileio_ops.name = "fileio"`），`disk0` 可任意命名。

### 3.3 创建 function instance（**必须在这一步**）

```sh
mkdir /config/usb_gadget/g1/functions/tcm.usb0
```

`f_tcm.c:2327` `DECLARE_USB_FUNCTION(tcm, tcm_alloc_inst, tcm_alloc)` →
configfs 里的名字就是 `tcm`，所以目录是 `tcm.usb0`。
`TPG_INSTANCES = 1`（`f_tcm.c:28`）→ 全系统只能有一个实例，重复 `mkdir` 会 `-EBUSY`。

### 3.4 创建 USB fabric（UAS 的 tpg）

```sh
mkdir -p /config/target/usb_gadget/naa.6001405000000001/tpgt_1
echo "naa.6001405000000001" > /config/target/usb_gadget/naa.6001405000000001/tpgt_1/nexus
```

fabric 名固定为 `usb_gadget`（`f_tcm.c:1721` `.name = "usb_gadget"`），
所以目录在 `/config/target/usb_gadget/`。
`nexus` 的 NAA 地址必须与 WWN 目录名一致且**必须**含 `naa.` 前缀，
否则 `Missing 'naa.' prefix`（`f_tcm.c:1675`）。`nexus` 只能设一次。

### 3.5 把后端 LUN 挂到 tpg

```sh
mkdir -p /config/target/usb_gadget/naa.6001405000000001/tpgt_1/lun/lun_0
ln -s /config/target/core/fileio_0/disk0 \
      /config/target/usb_gadget/naa.6001405000000001/tpgt_1/lun/lun_0/disk0
```

LUN 目录的 CIT 是 `tpg_port`（`drivers/target/target_core_fabric_configfs.c:769`），
其 `.allow_link = target_fabric_port_link`（同文件 `:709`）；
`fs/configfs/symlink.c:164-172` 里 **allow_link 返回 0 才真正建符号链接**，
即 `core_dev_add_lun()` 成功。

### 3.6 启用 tpg（**必须在绑定之前**）

```sh
echo 1 > /config/target/usb_gadget/naa.6001405000000001/tpgt_1/enable
```

`tcm_usbg_tpg_enable_store()` 要求 `!tpg->gadget_connect` 才允许 enable，
成功后 `gadget_connect=1` 且 `can_attach=1`。

### 3.7 把 tcm 挂进 b.1 并绑定

华为的 gadget 由 init 脚本管着，`b.1` 上原本挂着
`f1→mtp.gs0` / `f2→mass_storage.gs6` / `f3→ffs.adb` / `f4→ffs.hdb`。

```sh
echo "" > /config/usb_gadget/g1/UDC            # 解绑（必须，否则改不动功能链接）
echo 0 > /config/usb_gadget/g1/os_desc/use     # 顺手关掉 OS 描述符
ln -s /config/usb_gadget/g1/functions/tcm.usb0 \
      /config/usb_gadget/g1/configs/b.1/f1
echo ff100000.dwc3 > /config/usb_gadget/g1/UDC  # 重新绑定
cat /sys/class/android_usb/android0/state      # 期望 CONFIGURED
```

> **解绑会清空 `b.1` 的 function 链接**：华为补丁 `CONFIG_HISI_USB_CONFIGFS` 的
> `gadget_unlink_functions()`（`drivers/usb/gadget/configfs_unlink_funs.c:48-61`）
> 在解绑路径上遍历所有 config 摘掉 function。所以 `ln -s` 必须写在**解绑之后**。
> 绑定成功后 `UDC` 文件会消失（configfs 行为），这是正常的。
>
> `idVendor` / `idProduct` 是 **gadget 根**属性
> （`drivers/usb/gadget/configfs.c:237-238` / `:363-364`），不在 config 目录下；
> config 下只有 `MaxPower` / `bmAttributes`（`:576-577`）。往 `configs/xxx/` 写
> `idVendor` 会得到 `Permission denied`。

### 3.8 收尾 / 卸载

```sh
echo 0 > /config/target/usb_gadget/naa.6001405000000001/tpgt_1/enable
echo "" > /config/usb_gadget/g1/UDC
rm /config/usb_gadget/g1/configs/b.1/f1
rmdir /config/usb_gadget/g1/functions/tcm.usb0
```

恢复原状：把 `sys.usb.config` 设回原值，init 脚本会重建 `b.1` 的四个 symlink
并重新绑定（它只做 `symlink`，所以 **`b.1` 目录必须还在，别 `rmdir b.1`**）：

```sh
setprop sys.usb.config hisuite,mtp,mass_storage,adb,hdb
```

或者直接重启。

### 关键约束

- `TPG_INSTANCES = 1`（`f_tcm.c:28`）→ **全系统只能有一个 `tcm.usb0` 实例**，
  重复 `mkdir functions/tcm.usb0` 会 `-EBUSY`。
- `nexus` 只能设置一次；改地址要先 `echo NULL > nexus` 掉线再重设。
- configfs 的 `target` 子系统只有在 `target_core_mod` 加载后才出现
  （本配置为 built-in，开机即有）。

---

## 4. 如何验证 UAS 真的生效

1. PC 端（Linux）：`dmesg | grep -i uas` 应出现
   `uas_eh_device_reset_handler` 所在驱动的 probe 记录，
   `lsusb -t` 能看到接口的 alternate setting 1。
2. PC 端（Windows）：设备管理器出现 `USB Attached SCSI (UAS) Mass Storage Device`，
   而不是 `USB Mass Storage Device`。
3. 手机端：`cat /sys/kernel/config/target/usb_gadget/*/tpgt_*/enable` 返回 1。
4. 手机端 `dmesg | grep -i "Using the"` → 应打印
   `Using the UAS protocol`（`f_tcm.c:876`）；若显示
   `Using the BOT protocol`（`f_tcm.c:409`）说明只协商到了 BOT，
   检查是否插在 USB3.0 口、以及 DTS 的 `maximum-speed`。

---

## 5. 变更清单与验证结果（本次改动）

改动文件：`arch/arm64/configs/merge_kirin970_defconfig`

```diff
-# CONFIG_TARGET_CORE is not set
+CONFIG_TARGET_CORE=y
+# CONFIG_TCM_IBLOCK is not set
+CONFIG_TCM_FILEIO=y
+# CONFIG_TCM_PSCSI is not set

 CONFIG_USB_CONFIGFS_F_ACC=y
+CONFIG_USB_CONFIGFS_F_TCM=y
```

生成配置与改动前逐行 diff **仅 16 行**，全部为上述启用项及其连带
（`CRC_T10DIF` / `CRYPTO_CRCT10DIF` 由 `TARGET_CORE` 自动 select）。

### 5.1 ⚠️ 必须打的内核补丁：`f_tcm.c` 缺 `get_alt`

**只开配置不够。** 华为的 `drivers/usb/gadget/function/f_tcm.c` **没有实现
`get_alt()`**，而 `drivers/usb/gadget/composite.c:1731` 有这条规则：

```c
int value = -EOPNOTSUPP;                       /* composite.c:1567 */
...
case USB_REQ_SET_INTERFACE:
        ...
        if (w_value && !f->get_alt)
                break;                         /* value 仍是 -EOPNOTSUPP */
```

于是主机发 `SET_INTERFACE(alt=1)`（选 UAS）时被直接跳过，`composite_setup()`
返回 `-EOPNOTSUPP`，dwc3 打印：

```
configfs-gadget gadget: super-speed config #1
dwc3 ff100000.dwc3: ep0 setup error, ret -95!
dwc3 ff100000.dwc3: ctrl: 01 0b 0001 0000 0000
```

`01 0b ...` 就是 `SET_INTERFACE(alt=1, iface=0)`。主机随即放弃枚举 ——
**PC 端看不到任何 UAS 设备**（真机实测）。

修复（`drivers/usb/gadget/function/f_tcm.c`）：

```c
static int tcm_get_alt(struct usb_function *f, unsigned intf)
{
	struct f_uas *fu = to_f_uas(f);

	if (fu->flags & USBG_IS_UAS)
		return USB_G_ALT_INT_UAS;
	return USB_G_ALT_INT_BBB;
}
```

并在 `tcm_alloc()` 里补一行：

```c
	fu->function.set_alt = tcm_set_alt;
	fu->function.get_alt = tcm_get_alt;     /* ← 新增 */
```

依据：`fu->flags` 就是当前 alt —— `bot_set_alt()`（`:387`）置 `USBG_IS_BOT`(=0)，
`uasp_set_alt()`（`:841`）置 `USBG_IS_UAS`(=1)，常量在 `tcm.h:23-24`。
本树其他多 alt 函数（`f_ecm.c:612`、`f_ncm.c:901`、`f_obex.c:245`、
`f_sourcesink.c:749`、`f_uvc.c:272`、`f_uac2.c:1230`）**全都**实现了 `get_alt`，
`f_tcm` 是唯一的漏网。

这是**普通 C 文件**，不涉及预编译汇编，无 ABI 风险。

修好后 dmesg 变成：

```
Using the BOT protocol        ← 主机先选 alt 0
Using the UAS protocol        ← 再选 alt 1，成功
```

### 5.2 ⚠️ 必须打的第二个补丁：端点 companion 描述符取错 alt setting

**症状**：`get_alt` 修好后 PC 能枚举（`usb 6-2.4: new SuperSpeed USB device`、
`scsi host12: uas`、`idVendor=12d1 idProduct=107e`），但 **INQUIRY 无响应**：

```
scsi 12:0:0:0: tag#8 uas_eh_abort_handler 0 uas-tag 1 inflight: CMD IN
scsi 12:0:0:0: tag#8 CDB: Inquiry 12 00 00 00 24 00
scsi host12: uas_eh_host_reset_handler start
usb 6-2.4: reset SuperSpeed USB device number 19 using xhci_hcd
scsi 12:0:0:0: Device offlined - not ready after error recovery
```

设备侧 trace 只有一条，说明 target 已经正确应答、是 USB 传输没出去：

```
dwc3_gadget_giveback: ep1in: req ffffffe7428a50c0 length 0/36 zsI ==> -108
```

`length 0/36` = 请求 36 字节（正是 INQUIRY 响应长度）、实收 0；`-108` = `-ETIMEDOUT`。

**根因**：`config_ep_by_speed()`（`drivers/usb/gadget/composite.c`）在
`f->ss_descriptors` 里按 `bEndpointAddress` 取**第一个**匹配的端点描述符，
并把它**紧邻的下一个**描述符当作 SS endpoint companion：

```c
	for_each_ep_desc(speed_desc, d_spd) {
		chosen_desc = (struct usb_endpoint_descriptor *)*d_spd;
		if (chosen_desc->bEndpointAddress == _ep->address)
			goto ep_found;
	}
	...
ep_found:
	_ep->comp_desc = NULL;
	...
	comp_desc = (struct usb_ss_ep_comp_descriptor *)*(++d_spd);
```

而 `f_tcm.c` 的 `uasp_ss_function_desc[]` 里 **BOT 与 UAS 两个 alt setting 复用同一组
端点地址**（`tcm_bind()` 注释 "Assume endpoint addresses are the same for both speeds"），
且 `usb_ep_autoconfig_ss()`（`drivers/usb/gadget/epautoconfig.c:101-112`）会把
`desc->bEndpointAddress` 改写成真实端点号（`ep1in` → `0x81`），两段指向**同一个结构体对象**。
于是数据 IN/OUT 端点的第一个匹配落在 **BOT 段**，companion = `bot_bi_ep_comp_desc`
（`f_tcm.c:1814`，**只有 `bLength`/`bDescriptorType`/`bMaxBurst=0`，`bmAttributes` 为 0**）：

| companion | `bmAttributes` | `usb_ss_max_streams()` |
|---|---|---|
| `bot_bi_ep_comp_desc` / `bot_bo_ep_comp_desc` | 0（未设） | 0 |
| `uasp_bi_ep_comp_desc` / `uasp_bo_ep_comp_desc` | `UASP_SS_EP_COMP_LOG_STREAMS`(=4) | 16 |

→ `dwc3_gadget_set_ep_config()`（`drivers/usb/dwc3/gadget.c:594`）
`usb_ss_max_streams(comp_desc)` = 0 → 不设 `DWC3_DEPCFG_STREAM_CAPABLE` →
`dep->stream_capable = false` → `dwc3_prepare_trb()`（`gadget.c:989`）
**不会**给 TRB 置 `DWC3_TRB_CTRL_SID_SOFN`。

而 `f_tcm` 自己**是**用 stream 的：`uasp_set_alt()` 在 SuperSpeed 置
`fu->flags |= USBG_USE_STREAMS`（`f_tcm.c:849-850`），`uasp_prepare_reqs()` 分配
`UASP_SS_EP_COMP_NUM_STREAMS` 条 stream，请求带 `request.stream_id`。
设备发的是**不带 stream ID 的普通 bulk 传输**，主机却按 stream 传输等它 → 永远等不到。

**上游早已修复**：v5.10 起 `f_tcm.c` 改调
`config_ep_by_speed_and_alt(gadget, f, ep, USB_G_ALT_INT_UAS)`，
`composite.c` 新增 `config_ep_by_speed_and_alt()` + `next_desc()`/`for_each_desc()`，
把端点搜索**限定在指定 alt setting 的接口段内**：

```c
	/* find correct alternate setting descriptor */
	for_each_desc(speed_desc, d_spd, USB_DT_INTERFACE) {
		int_desc = (struct usb_interface_descriptor *)*d_spd;
		if (int_desc->bAlternateSetting == alt) {
			speed_desc = d_spd;
			goto intf_found;
		}
	}
	return -EIO;
intf_found:
	/* find descriptors */
	for_each_desc(speed_desc, d_spd, USB_DT_ENDPOINT) { ... }
```

`config_ep_by_speed()` 退化为 `config_ep_by_speed_and_alt(g, f, _ep, 0)`。

**本次落地**（`#23`）：

- `drivers/usb/gadget/composite.c`：`next_ep_desc`/`for_each_ep_desc` →
  `next_desc(desc_type)`/`for_each_desc`；新增 `config_ep_by_speed_and_alt()`；
  `config_ep_by_speed()` 变 wrapper（`alt = 0`，行为对单 alt 函数完全不变）。
- `include/linux/usb/composite.h`：声明 `config_ep_by_speed_and_alt()`。
- `drivers/usb/gadget/function/f_tcm.c`：`bot_set_alt()` 用 `USB_G_ALT_INT_BBB`，
  `uasp_set_alt()` 四个端点全部用 `USB_G_ALT_INT_UAS`。

**回归风险**：`config_ep_by_speed()` 现在要求描述符里存在
`bAlternateSetting == 0` 的接口（`uasp_fs_function_desc` / `uasp_ss_function_desc`
都含 `bot_intf_desc`，alt 0 是第一个接口，✓）。其余调用者（`hw_f_acm.c`、
`f_uvc.c`、`f_ecm.c` 等）的 FS/HS/SS 描述符第一个接口都是 alt 0，行为不变。

### ABI 安全复核（`pahole`，厂商 `.o` vs 新 `vmlinux`）

| 结构体 | 厂商 | 新内核 | 结论 |
|---|---|---|---|
| `struct bio` | 392 | 392 | 未漂移 |
| `struct request_queue` | 15024 | 15024 | 未漂移 |
| `struct request` | 688 | 688 | 未漂移 |
| `struct gendisk` | 1120 | 1120 | 未漂移 |
| `struct bio_set` | 112 | 112 | 未漂移 |
| `struct blk_mq_tag_set` | 1480 | 1480 | 未漂移 |
| `struct scsi_device` | 2152 | 2152 | 未漂移 |
| `struct scsi_cmnd` | 344 | 344 | 未漂移 |
| `Scsi_Host` | 3648 | 3648 | 未漂移 |

- `# CONFIG_BLK_DEV_INTEGRITY is not set` 保持关闭（这是上表成立的原因）。
- 新启用符号在 `include/` 下命中 **0** 个头文件，无布局风险。
- `tools/abi-verify.sh` → `ABI CHECK PASSED`（netfilter 修复未被破坏）。
- 全树 `tools/abi-guard.py` 漂移基线仍为 **48 structs / 9 STALE**，
  与改动前完全一致。

---

## 6. 产物

| 文件 | 说明 |
|---|---|
| `kernel-uasp-gadget.img` | 15,153,152 字节，sha256 `5e3742e45095bb3e483d178e6837ed6f6331acd5f3ad9ebc74c8847e7ef324de` |
| `kernel-uasp-gadget2.img` | 15,155,200 字节，sha256 `6f7c75429e3e964ef1ec77070471d2981c6652c0862ba5aabe4acab113498010`（含 §5.1 `get_alt`） |
| `kernel-uasp-gadget3.img` | 15,155,200 字节，sha256 `7a170df11ae0343f88a5a02f8a43be46172c7e5f87bb0dd918ae084b72c6af20`（含 §5.1 + §5.2） |
| 内核版本 | `4.9.148-NEO_EMUI9.1.0_RKSU_xixiaobei@Github+ #23 SMP PREEMPT Sat Nov 21 01:10:16 CST 2026` |

镜像为**标准 Android bootimg**（`ANDROID!` magic、page_size 2048、
header_version 1、`androidboot.selinux=enforcing`），
payload 与 `out/arch/arm64/boot/Image.gz` 的 sha256 **逐字节一致**。

> **刷机约定**：本项目默认**不代替用户刷机**；本次经用户显式授权后刷入。
> 镜像也可由用户自行 `dd if=<img> of=/dev/block/by-name/kernel`。

---

## 7. 换机型 Checklist

- [ ] 确认需求方向：gadget 侧（`USB_CONFIGFS_F_TCM`）而非宿主侧（`USB_UAS`）
- [ ] `CONFIG_TARGET_CORE=y` + `CONFIG_TCM_FILEIO=y`（**绝不要 `TCM_IBLOCK`**）
- [ ] `CONFIG_USB_CONFIGFS_F_TCM=y`
- [ ] 确认 `# CONFIG_BLK_DEV_INTEGRITY is not set` 保持关闭
- [ ] **确认 `f_tcm.c` 实现了 `get_alt()`**（`grep get_alt drivers/usb/gadget/function/f_tcm.c`）；没有就按 §5.1 补，否则 PC 端看不到设备
- [ ] **确认 `config_ep_by_speed_and_alt()` 存在**（`grep config_ep_by_speed_and_alt drivers/usb/gadget/composite.c`）；没有就按 §5.2 回移，并把 `f_tcm.c` 两个 `set_alt` 改成按 alt setting 取描述符，否则 PC 能枚举但 INQUIRY 超时
- [ ] 确认 `CONFIG_USB_GADGET` / `USB_LIBCOMPOSITE` / `USB_CONFIGFS` / `USB_DWC3` 已开
- [ ] 确认 DTS 的 dwc3 `maximum-speed = "super-speed"`
- [ ] 确认 `dwc3/gadget.c` 有 `sg_supported = true`
- [ ] 用 `pahole` 复核 §5 表格中所有结构体（或跑 `tools/abi-guard.py`）
- [ ] 编译后确认 `target_core_mod.o` / `target_core_file.o` / `usb_f_tcm.o` 产出
- [ ] `nm out/vmlinux | grep -E "tcm_alloc|uasp_|fd_alloc_device"` 有符号
- [ ] 跑 `tools/abi-verify.sh` 确认既有 ABI 修复未被破坏
- [ ] 打包后核对 payload sha256 与 `Image.gz` 一致
