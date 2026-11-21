# UASP gadget 交接文档

> 状态快照：**2026-11-21 18:12**。设备 H4P0218923000886 当前运行内核 **`#43`**。
> 详细技术论证见 [UASP_GADGET_GUIDE.md](UASP_GADGET_GUIDE.md)；本文只讲「现在是什么状态、你接着改要注意什么」。

---

## 1. 一句话现状

**手机侧 UASP 已全部做对并刷入真机，但 PC 端拿不到数据 —— 卡在 DWC_usb31 芯片的 stream 行为上。**
**BOT（现有方案）实测读 264 MB/s，且主机侧 `queue_depth` 只读改不动，提速不可行。**

---

## 2. 当前设备状态（可直接复用）

| 项 | 值 |
|---|---|
| 设备 | H4P0218923000886（走 IP adb `192.168.64.86:5555`，极不稳，每条命令前 `adb disconnect; adb connect; sleep`） |
| 内核 | `#43 SMP PREEMPT Sat Nov 21 17:31:05 CST 2026` |
| 镜像 | `kernel-uasp-gadget23.img`，sha256 `0e77f5d324f53779a162cd751215817273239610a7b79b4b5c2bb65094a04a17`（15,155,200 字节） |
| 位置 | `/mnt/g/projects/huawei-phone-ssd-project/kernel-uasp-gadget23.img` 与仓库内同名文件 |
| root | KernelSU 为 built-in（`CONFIG_KSU=y`、`CONFIG_KSU_MANUAL_HOOK=y`），**换 kernel 分区不影响 root** |
| 刷入方式 | `dd if=<img> of=/dev/block/by-name/kernel bs=4096`（该分区 25,165,824 字节，**无 `boot`/`ramdisk` 分区**，`/proc/cmdline` 含 `skip_initramfs`，纯内核镜像正确） |
| 分区 | `by-name/kernel` → `/dev/block/sdd38` |

**重启后 configfs 配置不持久**，需要重跑 `uasp-setup.sh`（在 `/data/local/tmp/uasp-setup.sh`，需 `su -c 'sh ...'`）。

---

## 3. 代码改动清单（都已提交）

分支 `ds-v4`，仓库 `/mnt/g/projects/huawei-phone-ssd-project/NEO_EMUI9.1.0_RKSU`。

| 提交 | 内容 |
|---|---|
| `1c1b2358c` | defconfig：`CONFIG_TARGET_CORE=y` / `CONFIG_TCM_FILEIO=y` / `CONFIG_USB_CONFIGFS_F_TCM=y`，回退误加的 `CONFIG_USB_UAS=y` |
| `9c58aeb41` | `UASP_GADGET_GUIDE.md` 初版 |
| `d7e86e716` | 回移 `config_ep_by_speed_and_alt`（修复端点 companion 取错 alt setting） |
| `be48631f1` | 回移 v5.10 bulk stream 支持（LST/CSP/`is_last`/stream 事件/stream id） |
| `5d27ec95b` | 移除 `UASPDBG` 调试探针（干净版） |
| `babcc49a5` | 文档补全 §5.3–§5.5、§8 |

**功能改动落点（改内核配置前请先读这些）**：

- `drivers/usb/gadget/function/f_tcm.c` —— 新增 `tcm_get_alt()`；`bot_set_alt`/`uasp_set_alt` 改用 `config_ep_by_speed_and_alt(..., alt)`；三处 `is_last = 1`
- `drivers/usb/gadget/composite.c` —— `next_desc()`/`for_each_desc()` + `config_ep_by_speed_and_alt()`（`config_ep_by_speed()` 退化为 alt=0 包装）
- `include/linux/usb/composite.h` —— `config_ep_by_speed_and_alt` 声明
- `include/linux/usb/gadget.h` —— `struct usb_request` 加 `unsigned is_last:1;`
- `drivers/usb/dwc3/gadget.c` —— START_TRANSFER 的 stream 参数、三参数 `dwc3_stop_active_transfer()`、`dwc3_gadget_endpoint_stream_event()`、TRB 的 LST/CSP 逻辑
- `drivers/usb/dwc3/core.h` —— `DWC3_EP_FORCE_RESTART_STREAM`/`IGNORE_NEXT_NOSTREAM`/`FIRST_STREAM_PRIMED`/`WAIT_TRANSFER_COMPLETE`/`DELAY_START`、`DEPEVT_STREAM_PRIME`/`NOSTREAM`、`DWC3_DGCMD_SET_ENDPOINT_PRIME`
- `drivers/target/target_core_transport.c` —— 防 UAF panic（`int ret = 0;` + 三处 `if (ret) return;`）

**ABI**：`bash tools/abi-verify.sh` → `ABI CHECK PASSED`（netfilter 的既有修复未被破坏）。

---

## 4. 构建 / 打包 / 刷入（命令模板）

```bash
cd /mnt/g/projects/huawei-phone-ssd-project/NEO_EMUI9.1.0_RKSU
./rebuild.sh 43                                     # 自增版本号
SELINUX_MODE=enforcing ./pack.sh out/arch/arm64/boot/Image.gz kernel-uasp-gadgetN.img
sha256sum kernel-uasp-gadgetN.img

adb disconnect; adb connect 192.168.64.86:5555; sleep 4
adb -s 192.168.64.86:5555 push kernel-uasp-gadgetN.img /data/local/tmp/kN.img
adb -s 192.168.64.86:5555 shell "su -c 'dd if=/data/local/tmp/kN.img of=/dev/block/by-name/kernel bs=4096 && sync'"
adb -s 192.168.64.86:5555 reboot                      # 若无效：disconnect/connect 再 reboot
# 起来后务必核对：
adb -s 192.168.64.86:5555 shell "uname -v; su -c 'head -c 15155200 /dev/block/by-name/kernel | sha256sum'"
```

**注意**：`svc power reboot` 有时不生效；`pack.sh` 的输出必须是**仓库内相对路径**（脚本内部会 `cd tools`）。

---

## 5. ⚠️ 改别的内核配置前必须知道的坑

1. **`defconfig` 改动会触发大面积重编**（`autoconf.h` 变），一次 `rebuild.sh` 要十几分钟。
2. **apples-to-apples 验证法**（避免引入意外配置漂移）：
   ```bash
   cp out/.config .scratch/config-before
   cp arch/arm64/configs/merge_kirin970_defconfig arch/arm64/configs/tmp_defconfig
   make O=.scratch/cfgpreview ARCH=arm64 tmp_defconfig
   diff .scratch/config-before .scratch/cfgpreview/.config
   ```
   UASP 那次实测仅 16 行差异，全部是 `TARGET_CORE` 的 select 连带。
3. **`# CONFIG_BLK_DEV_INTEGRITY is not set` 必须保持关闭** —— 与 netfilter ABI 修复强相关（`m00414` 的硬约束：**不许改编译选项去修 netfilter ABI 问题**）。
4. **不要动 `drivers/target/`、`drivers/usb/dwc3/` 之外的东西**，除非你清楚后果。
5. **每次刷完必须 `uname -v` 核对** —— `#40` 曾出现 push 路径写错、实际没刷上的事故。
6. **`ln -sf` 在 configfs 上 EPERM**，必须用不带 `-f` 的 `ln -s`。
7. **configfs 上 `rm` 属性全部 `Operation not permitted`**；`uasp-setup.sh` 不是完全幂等（残留 symlink 时 `lun rc=1`）。
8. **临时文件放 `/tmp` 会丢**，脚本一律放 `.scratch/` 再 push。
9. **手机 `dmesg` 环形缓冲会绕回**，取证用常驻捕获：
   ```bash
   su -c 'nohup sh /data/local/tmp/kmsgcap.sh >/dev/null 2>&1 &'
   # kmsgcap.sh: cat /dev/kmsg | grep --line-buffered -aE 'dwc3|configfs-gadget|Using the|uasp|UASP|tcm|target|USB CONNDONE|otg' > /data/local/tmp/kmsgf.log
   ```
   噪音源：`logd.auditd` 每秒刷 `avc: denied { connect } ... dockerd/droidspacesd`，约 1 MB/s。
10. **tracefs 可用**（`/sys/kernel/debug/tracing`）：`CONFIG_FTRACE=y`，但 `# CONFIG_FUNCTION_TRACER is not set`、`# CONFIG_DYNAMIC_DEBUG is not set`。可用 tracepoint：`dwc3_prepare_trb`、`dwc3_gadget_giveback`、`dwc3_complete_trb`、`dwc3_ep_queue`、`dwc3_ctrl_req`、`dwc3_gadget`、`dwc3_event`、`target_sequencer_start`、`target_cmd_complete`。
11. **tracefs 是每设备独立的**，重启后要重新 arm。

---

## 6. 已确认的关键事实（省得重查）

**硬件/分区**
- 芯片 **DWC_usb31**：`rev=0xb136302a`，`dwc3_is_usb31()=1`（`core.h:1232`）→ 不在 v5.10 的 `DWC3_VER_IS_WITHIN(DWC32,100A,ANY)` 范围。
- 设备分区 `by-name/kernel` = `/dev/block/sdd38`，25,165,824 字节；**无 `boot`、无 `ramdisk`**；有 `erecovery_kernel`(sdd35)、`recovery_ramdisk`(sdd40)、`misc`(sdd19)、`fastboot`(sdd28)。
- `/proc/cmdline`：含 `skip_initramfs`、`bootlock=unlocked`、`userlock=unlocked`、`androidboot.verifiedbootstate=orange`、`androidboot.veritymode=enforcing`。
- UDC：`/config/usb_gadget/g1/UDC` = `ff100000.dwc3`。

**性能**
- 手机后端读 **1.0 GB/s**（`dd` 536870912 B / 0.532 s）。
- BOT 现状 **264 MB/s**（KDiskMark SEQ1M Q8T1 读 263.88 / 写 193.41）。
- 主机侧：`max_sectors_kb=1024`、`nr_requests`（改到 128 无效）、`device/queue_depth` = **`-r--r--r--` 0444 只读**（root 报 EACCES）。
- ⇒ BOT 吞吐 = 1 MB / 往返延迟(≈3.8 ms) ≈ 264 MB/s，与实测吻合。

**configfs 正确顺序（UASP，顺序错了必失败）**
1. `setprop sys.usb.config uasp`（用**未知值**，`/init.usb.configfs.rc` 无 trigger 命中，避免系统自动挂载干扰）
2. target 后端：`mkdir -p /config/target/core/fileio_0/disk0` → `control` 写 `fd_dev_name=...,fd_dev_size=...` → `echo 1 > enable`
3. **`mkdir /config/usb_gadget/g1/functions/tcm.usb0`**（必须在第 3 步，tpg 依赖它的 `set_inst_name`）
4. tpg + nexus：`mkdir -p /config/target/usb_gadget/naa.<wwn>/tpgt_1` → 写 `nexus`
5. LUN symlink → `echo 1 > tpgt_1/enable`（必须在绑定前）
6. `echo "" > UDC` → `ln -s .../functions/tcm.usb0 configs/b.1/f1`（**`ln -s` 必须在解绑之后**，华为 `gadget_unlink_functions()` 会清空）→ `echo ff100000.dwc3 > UDC`

**失败对照表**

| 症状 | 根因 |
|---|---|
| `Config b/1 of g1 needs at least one function.` / `-22` | `ln -s` 写在解绑之前 |
| `failed to start g1: -19` | 未先 `echo 1 > tpgt_1/enable` |
| `ep0 setup error, ret -95` + `01 0b 0001 0000 0000` | `f_tcm.c` 缺 `get_alt()`（已修，§5.1） |
| 枚举成功但 INQUIRY 超时、`length 0/36 ==> -108` | `config_ep_by_speed` 取错 alt（已修，§5.2） |
| `WARNING gadget.c:296` + `there is no transfer resource available on the endpoint.` | `dwc3_gadget_start_config()` 对 `dep->number != 0` 直接 early-return，非 0 号端点没有 transfer resource |
| `UASPDBG STREAMEVT` 0 条 | `dwc3_endpoint_interrupt()` 的 ENABLED guard 在 switch 之前，事件被丢弃 |

---

## 7. 如果下次想接着修 UASP，下一步

1. 把 `dwc3_gadget_endpoint_stream_event()` 的调用**移到 `dwc3_endpoint_interrupt()` 的 ENABLED guard 之前**（或放宽 guard）。
2. 在 `DEPEVT_STREAM_NOSTREAM` 时走**非 DWC32 分支**：`dep->flags |= DWC3_EP_DELAY_START; dwc3_stop_active_transfer(dep, true, true); return;`
3. 真机抓 trace，确认 `ep1in` 出现 `dwc3_complete_trb`。

---

## 8. 环境与脚本清单

| 文件 | 说明 |
|---|---|
| `.scratch/uasp-setup.sh` | 幂等 6 步 UASP configfs 配置（第 6 步前 arm tracepoints），已 push 到 `/data/local/tmp/` |
| `.scratch/kmsgcap.sh` | 常驻过滤式 kmsg 捕获 → `/data/local/tmp/kmsgf.log` |
| `.scratch/trace24.txt` | `#24` 的关键 trace（352 行，含 `ctrl 00004c19` / `length 0/36 ==> -108`） |
| `.scratch/dwc3-gadget-v510.c` / `dwc3-core-v510.h` / `f_tcm-v510.c` / `uas-host-v510.c` / `usbcore-hcd.c` / `drivers/usb_storage_uas-detect.h` | 上游对照源码（v5.10） |
| `.scratch/panic-20261121/console-ramoops-0.txt` | `#23` 的 panic 现场（524,276 字节） |
| `tools/abi-verify.sh` / `tools/abi-guard.py` | ABI 校验（基线 48 structs / 9 STALE） |

**已知环境坑**：IP adb 极不稳；`sudo` 需密码且沙箱 `no new privileges`；`/sys` 只读；`/dev/kmsg` 不存在；debugfs 只读；PC 与手机同机（`XJBOSS-HZ-PC`）；手机已迁移到 **USB hub**（直连供电不足）。

---

## 9. 硬约束（沿用）

- 不改内核编译选项来修 netfilter ABI 问题（`m00414`）。
- 只看 9.1.0 代码，不对比 9.0（`m00244`）。
- 「之前内核用着十分正常，毫无问题」→ 改动须最小且无回归（`m01501`）。
- 刷机已获用户显式授权（`m02067`），但每次刷完必须核对 `uname -v`。
