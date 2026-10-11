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

### 3.1 准备后端存储

用一个文件当磁盘（最简单）：

```sh
su
dd if=/dev/zero of=/data/media/0/uasp.img bs=1M count=8192
# 或者直接导出一整个块设备（危险，会覆盖该分区）：
# BACKEND=/dev/block/by-name/userdata
```

### 3.2 创建 target 后端

```sh
mkdir -p /sys/kernel/config/target/core/fileio_0/disk0
cd /sys/kernel/config/target/core/fileio_0/disk0
echo "fd_dev_name=/data/media/0/uasp.img" > control
echo "fd_dev_size=8589934592"             > control
echo 1 > enable
```

> 目录名 `fileio_0` 由 `target_core_file.c` 的 HBA 自动创建
> （`fileio_ops.name = "fileio"`），`disk0` 可任意命名。

### 3.3 创建 USB fabric（UAS 的 tpg）

```sh
mkdir -p /sys/kernel/config/target/usb_gadget/naa.6001405000000001/tpgt_1
cd /sys/kernel/config/target/usb_gadget/naa.6001405000000001/tpgt_1
echo "naa.6001405000000001" > nexus      # 必须带 naa. 前缀
```

> fabric 名固定为 `usb_gadget`（`f_tcm.c:1721 .name = "usb_gadget"`）。
> `nexus` 写入的 NAA 地址必须与 WWN 目录名一致，且**必须**含 `naa.` 前缀，
> 否则报 `Missing 'naa.' prefix`（见 `f_tcm.c:1675`）。

### 3.4 把后端 LUN 挂到 tpg

```sh
mkdir -p /sys/kernel/config/target/usb_gadget/naa.6001405000000001/tpgt_1/lun/lun_0
ln -s /sys/kernel/config/target/core/fileio_0/disk0 \
      /sys/kernel/config/target/usb_gadget/naa.6001405000000001/tpgt_1/lun/lun_0/disk0
```

### 3.5 绑定到 USB gadget

**注意：华为的 USB gadget 由 Android init 脚本管理**，`/config/usb_gadget/g1`
上已挂载了 `mtp` / `mass_storage` / `ffs.adb` / `ffs.hdb` 四个功能。
先把它们摘掉（或另建一个 gadget 目录），再挂 `tcm.usb0`：

```sh
cd /config/usb_gadget/g1
echo "" > UDC                      # 先解绑，否则功能无法改动
rm configs/b.1/f1 configs/b.1/f2 configs/b.1/f3 configs/b.1/f4
mkdir functions/tcm.usb0
ln -s functions/tcm.usb0 configs/b.1/f1
echo ff100000.dwc3 > UDC           # 重新绑定，PC 端此时出现 UASP 硬盘
```

### 3.6 启用 tpg（UAS 真正上线）

```sh
echo 1 > /sys/kernel/config/target/usb_gadget/naa.6001405000000001/tpgt_1/enable
```

`enable=1` 会调用 `usbg_attach()`；只有 `tcm_register_callback()` 已把
`can_attach` 置位（即 `tcm.usb0` 已被 gadget 绑定）后才允许，顺序不能颠倒。

### 3.7 收尾 / 卸载

```sh
echo 0 > .../tpgt_1/enable
echo "" > /config/usb_gadget/g1/UDC
rm /config/usb_gadget/g1/configs/b.1/f1
rmdir /config/usb_gadget/g1/functions/tcm.usb0
```

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
| 内核版本 | `4.9.148-NEO_EMUI9.1.0_RKSU_xixiaobei@Github+ #21 SMP PREEMPT` |

镜像为**标准 Android bootimg**（`ANDROID!` magic、page_size 2048、
header_version 1、`androidboot.selinux=enforcing`），
payload 与 `out/arch/arm64/boot/Image.gz` 的 sha256 **逐字节一致**。

> **本项目约定：绝不代替用户刷机。** 镜像由用户自行刷入。

---

## 7. 换机型 Checklist

- [ ] 确认需求方向：gadget 侧（`USB_CONFIGFS_F_TCM`）而非宿主侧（`USB_UAS`）
- [ ] `CONFIG_TARGET_CORE=y` + `CONFIG_TCM_FILEIO=y`（**绝不要 `TCM_IBLOCK`**）
- [ ] `CONFIG_USB_CONFIGFS_F_TCM=y`
- [ ] 确认 `# CONFIG_BLK_DEV_INTEGRITY is not set` 保持关闭
- [ ] 确认 `CONFIG_USB_GADGET` / `USB_LIBCOMPOSITE` / `USB_CONFIGFS` / `USB_DWC3` 已开
- [ ] 确认 DTS 的 dwc3 `maximum-speed = "super-speed"`
- [ ] 确认 `dwc3/gadget.c` 有 `sg_supported = true`
- [ ] 用 `pahole` 复核 §5 表格中所有结构体（或跑 `tools/abi-guard.py`）
- [ ] 编译后确认 `target_core_mod.o` / `target_core_file.o` / `usb_f_tcm.o` 产出
- [ ] `nm out/vmlinux | grep -E "tcm_alloc|uasp_|fd_alloc_device"` 有符号
- [ ] 跑 `tools/abi-verify.sh` 确认既有 ABI 修复未被破坏
- [ ] 打包后核对 payload sha256 与 `Image.gz` 一致
