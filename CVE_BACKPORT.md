# CVE 安全修复回移报告 —— 华为 MateRS (NEO) EMUI 9.1.0 内核

> 目标内核：Linux **4.9.148**（`NEO_EMUI9.1.0_RKSU`，RKSU 适配版）  
> 分支：`cve-backport`　基线提交：`bd7e6f9de`  
> 报告时间：2026-09-23

---

## 0. 一句话结论

- **已回移并提交 131 个 CVE 修复**，其中 **2 个（CVE-2021-47121 / CVE-2021-47122）经审阅后已回退**（上游补丁不自洽），**当前净生效 129 个**；补丁原文全部保存在 `cve-patches/`。
- 分支共 **142 个提交** = 131 个 CVE 修复提交 + 1 个 `.gitignore` 加固 + 2 个构建问题修复（§9.1）+ 2 个审阅问题修复（§11.4）+ 1 个回退提交 + 4 个文档提交 + 1 个归档提交。
- **2026-11-21 高危补齐批次（工作树改动，构建 #47，详见 §4.2）**：按指定清单回移 **5 项**（CVE-2022-1012 / CVE-2019-9506 / CVE-2019-11487 / CVE-2022-2964 / CVE-2018-20856，共 17 个上游 stable 提交等价修复），另 2 项经实证因 `CONFIG_VHOST_NET`、`CONFIG_BLK_DEV_IO_TRACE` 未启用而不可达、不做改动；#47 已在 H4P0218923000886 验证启动。补丁归档 `cve-patches/CVE-batch-2026-11-21-v47.patch`。
- **内核版本号保持 4.9.148 不变**：未改动 `Makefile` 的 VERSION/PATCHLEVEL/SUBLEVEL/EXTRAVERSION（已逐提交校验）。
- **每个 CVE 一个独立 git 提交**，提交信息含 CVE 编号、stable 提交哈希、upstream 提交哈希。
- **CVE-2026-31431 (Copy Fail) 经实证判定对本机不适用**，无需修复（见 §5）。
- **CVE-2026-43503 (DirtyClone/Fragnesia, CVSS 8.8) 已手工适配回移**（4.9 的标记名与主线不同，见 §4）。
- **CVE-2026-98432（IPv4 TCP UAF，CVSS 9.8）于 2026-11-21 追加回移**：两处 `kfree()` → `kfree_rcu()`，并**必须**补本树缺失的 NULL 保护（否则 `inet_opt`/`ireq_opt` 为 NULL 时写地址 0，`panic_on_oops=1` 直接起不来，构建 #45 已实测复现）；#46 已在 H4P0218923000886 验证启动。本树已实证具备 `079096f103fa` 前提，详见 §4.1。
- **`./build.sh 12` 构建成功（exit 0）**；过程中发现并修复 2 个「补丁依赖 4.9.148 不存在的 API」问题（见 §9.1）。
- 另有约 30 个高危 CVE 因华为重度改写相关文件而**未能自动应用，已跳过（未作任何修改）**，清单见 §7。

---

## 1. 硬约束遵守情况

| 约束 | 状态 | 证据 |
|---|---|---|
| 不更改内核版本号 | ✅ 遵守 | `head -4 Makefile` → `SUBLEVEL = 148`；流水线含 Makefile 版本 hunk 剥离逻辑 |
| 只打 CVE 补丁，不做版本升级 | ✅ 遵守 | 逐 CVE 独立提交，非增量版本补丁（不含 4.9.149→337 的非安全改动） |
| 增加 git 提交记录 | ✅ 遵守 | 131 个 CVE 提交 + 补丁归档提交 |
| 保留补丁文件 | ✅ 遵守 | `cve-patches/` 共 **131 个生效补丁**（129 个上游原文 + 2 个 4.9 适配）+ `_reverted/` 下 2 个已回退补丁存档 |
| 剔除低危漏洞 | ✅ 遵守 | 剔除 CVSS<7.0 共 165 项 |
| 剔除主线驱动/KVM | ✅ 遵守 | 剔除无关驱动 80 项、非 arm64 架构 6 项 |

---

## 2. 判定方法

```
① 上游 4.9 stable 提交列表  → 4.9_security.txt (CVE → 修复版本 → 提交哈希)
② 筛选影响 4.9.148 的 CVE   → 修复版本 > 148，共 547 个
③ 拉取单个提交补丁          → github.com/gregkh/linux/commit/<sha>.patch
④ 三级应用策略：
     正向干净应用  → 直接提交
     反向干净应用  → 判定「华为已自行修复」，不重复修
     两者皆失败    → 三方合并 (ours=华为文件, base=上游父提交, theirs=上游修复后)
                     合并成功 → 提交；仍冲突 → 标记待人工、**不落任何修改**
⑤ 严重性分级 + 硬件相关性筛选（本报告 §6）
```

**关键设计**：三方合并为原子操作——全部文件合并成功才写盘，避免部分写入污染后续提交（该缺陷在早期版本中曾出现 1 次，已修正并回归验证，见 §8）。

---

## 3. 已应用 CVE 清单（提交 131 个，扣除回退后净生效 129 个）

> 下表为提交时的 131 个 CVE 清单。其中 **CVE-2021-47121 / CVE-2021-47122 已于审阅后回退**（见 §11.4），
> 故当前实际生效 129 个。

| # | CVE | CVSS | 修复版本 | stable 提交 | 说明 | 涉及文件 |
|---|---|---|---|---|---|---|
| 1 | CVE-2017-18509 | 7.8 | 4.9.187 | `1e531ad4316c` | ipv6: check sk sk_type and protocol early in ip_mroute_set/g | `net/ipv6/ip6mr.c` |
| 2 | CVE-2018-16884 | 8.0 | 4.9.151 | `37c791a031ec` | sunrpc: use-after-free in svc_process_common() | `include/linux/sunrpc/svc.h, net/sunrpc/svc.c, net/sunrpc/svc_xprt.c …` |
| 3 | CVE-2018-20976 | 7.8 | 4.9.197 | `e6e3f36b1ac9` | xfs: clear sb->s_fs_info on mount failure | `fs/xfs/xfs_super.c` |
| 4 | CVE-2019-0136 | 7.4 | 4.9.185 | `9f0f5ff93ed0` | mac80211: drop robust management frames from unknown TA | `net/mac80211/rx.c` |
| 5 | CVE-2019-10124 | 7.5 | 4.9.165 | `78f42f1156fd` | mm: hwpoison: fix thp split handing in soft_offline_in_use_p | `mm/memory-failure.c` |
| 6 | CVE-2019-10126 | 9.8 | 4.9.186 | `f70d411e2ecd` | mwifiex: Fix heap overflow in mwifiex_uap_parse_tail_ies() | `drivers/net/wireless/marvell/mwifiex/ie.c` |
| 7 | CVE-2019-10142 | 7.8 | 4.9.177 | `71e29a15b4ba` | drivers/virt/fsl_hypervisor.c: prevent integer overflow in i | `drivers/virt/fsl_hypervisor.c` |
| 8 | CVE-2019-10639 | 7.5 | 4.9.169 | `6996763856e1` | netns: provide pure entropy for net_hash_mix() | `include/net/net_namespace.h, include/net/netns/hash.h, net/core/net_namespace.c` |
| 9 | CVE-2019-11478 | 7.5 | 4.9.182 | `e358f4af19db` | tcp: tcp_fragment() should apply sane memory limits | `include/uapi/linux/snmp.h, net/ipv4/proc.c, net/ipv4/tcp_output.c` |
| 10 | CVE-2019-11486 | 7.0 | 4.9.169 | `942ddc0de8ef` | tty: mark Siemens R3964 line discipline as BROKEN | `drivers/char/Kconfig` |
| 11 | CVE-2019-11815 | 8.1 | 4.9.169 | `a1aa69beac4d` | net: rds: force to destroy connection if t_sock is NULL in r | `net/rds/tcp.c` |
| 12 | CVE-2019-12818 | 7.5 | 4.9.163 | `05d3d2d0b857` | net: nfc: Fix NULL dereference on nfc_llcp_build_tlv fails | `net/nfc/llcp_commands.c, net/nfc/llcp_core.c` |
| 13 | CVE-2019-13272 | 7.8 | 4.9.185 | `d8b99303da93` | ptrace: Fix ->ptracer_cred handling for PTRACE_TRACEME | `kernel/ptrace.c` |
| 14 | CVE-2019-14814 | 7.8 | 4.9.194 | `21dfacaf201e` | mwifiex: Fix three heap overflow at parsing element in cfg80 | `drivers/net/wireless/marvell/mwifiex/ie.c, drivers/net/wireless/marvell/mwifiex/uap_cmd.c` |
| 15 | CVE-2019-14895 | 9.8 | 4.9.210 | `efa99b6f3844` | mwifiex: fix possible heap overflow in mwifiex_process_count | `drivers/net/wireless/marvell/mwifiex/sta_ioctl.c` |
| 16 | CVE-2019-14896 | 9.8 | 4.9.212 | `b5e6f199de3b` | libertas: Fix two buffer overflows at parsing bss descriptor | `drivers/net/wireless/marvell/libertas/cfg.c` |
| 17 | CVE-2019-14901 | 9.8 | 4.9.217 | `cb87b895f146` | mwifiex: Fix heap overflow in mmwifiex_process_tdls_action_f | `drivers/net/wireless/marvell/mwifiex/tdls.c` |
| 18 | CVE-2019-15117 | 7.8 | 4.9.191 | `53856af73d85` | ALSA: usb-audio: Fix an OOB bug in parse_audio_mixer_unit | `sound/usb/mixer.c` |
| 19 | CVE-2019-15538 | 7.5 | 4.9.191 | `4862942c5906` | xfs: fix missing ILOCK unlock when xfs_setattr_nonsize fails | `fs/xfs/xfs_iops.c` |
| 20 | CVE-2019-15916 | 7.5 | 4.9.163 | `d81778b84253` | net-sysfs: Fix mem leak in netdev_register_kobject | `net/core/net-sysfs.c` |
| 21 | CVE-2019-15917 | 7.0 | 4.9.202 | `3858f013de0a` | Bluetooth: hci_ldisc: Postpone HCI_UART_PROTO_READY bit set  | `drivers/bluetooth/hci_ldisc.c` |
| 22 | CVE-2019-15926 | 9.1 | 4.9.187 | `8e8b0ba1dc67` | ath6kl: add some bounds checking | `drivers/net/wireless/ath/ath6kl/wmi.c` |
| 23 | CVE-2019-15927 | 7.8 | 4.9.150 | `beab6f305f4f` | ALSA: usb-audio: Avoid access before bLength check in build_ | `sound/usb/mixer.c` |
| 24 | CVE-2019-16413 | 7.5 | 4.9.165 | `0a97dbd82f40` | 9p: use inode->i_lock to protect i_size_write() under 32-bit | `fs/9p/v9fs_vfs.h, fs/9p/vfs_file.c, fs/9p/vfs_inode.c …` |
| 25 | CVE-2019-16746 | 9.8 | 4.9.197 | `a873afd7d888` | nl80211: validate beacon head | `net/wireless/nl80211.c` |
| 26 | CVE-2019-16995 | 7.5 | 4.9.164 | `a582b20fd743` | net: hsr: fix memory leak in hsr_dev_finalize() | `net/hsr/hsr_device.c, net/hsr/hsr_framereg.c, net/hsr/hsr_framereg.h` |
| 27 | CVE-2019-17133 | 9.8 | 4.9.198 | `49d84740f8a7` | cfg80211: wext: avoid copying malformed SSIDs | `net/wireless/wext-sme.c` |
| 28 | CVE-2019-17666 | 8.8 | 4.9.199 | `4a2fbab9e82f` | rtlwifi: Fix potential overflow on P2P code | `drivers/net/wireless/realtek/rtlwifi/ps.c` |
| 29 | CVE-2019-19049 | 7.5 | 4.9.200 | `0228cd262dda` | of: unittest: fix memory leak in unittest_data_add | `drivers/of/unittest.c` |
| 30 | CVE-2019-19052 | 7.5 | 4.9.201 | `b46a2067f36d` | can: gs_usb: gs_can_open(): prevent memory leak | `drivers/net/can/usb/gs_usb.c` |
| 31 | CVE-2019-19060 | 7.5 | 4.9.262 | `9c8c498ae28e` | iio: imu: adis16400: release allocated memory on failure | `drivers/iio/imu/adis_buffer.c` |
| 32 | CVE-2019-19061 | 7.5 | 4.9.262 | `10f675ec4eda` | iio: imu: adis16400: fix memory leak | `drivers/iio/imu/adis16400_buffer.c` |
| 33 | CVE-2019-19074 | 7.5 | 4.9.233 | `f0b65fee921f` | ath9k: release allocated buffer if timed out | `drivers/net/wireless/ath/ath9k/wmi.c` |
| 34 | CVE-2019-19447 | 7.8 | 4.9.208 | `e1513b36319d` | ext4: work around deleting a file with i_nlink == 0 safely | `fs/ext4/namei.c` |
| 35 | CVE-2019-25160 | - | 4.9.163 | `1c973f9c7cc2` | netlabel: fix out-of-bounds memory accesses | `net/ipv4/cipso_ipv4.c, net/netlabel/netlabel_kapi.c` |
| 36 | CVE-2019-3846 | 8.8 | 4.9.186 | `58ec3690a908` | mwifiex: Fix possible buffer overflows at parsing bss descri | `drivers/net/wireless/marvell/mwifiex/scan.c` |
| 37 | CVE-2019-9466 | 9.8 | 4.9.181 | `433b957a9e2d` | brcmfmac: add subtype check for event handling in data path | `drivers/net/wireless/broadcom/brcm80211/brcmfmac/core.c, drivers/net/wireless/broadcom/brcm80211/brcmfmac/fweh.h, drivers/net/wireless/broadcom/brcm80211/brcmfmac/msgbuf.c` |
| 38 | CVE-2019-9500 | 8.3 | 4.9.181 | `76e7e98e229a` | brcmfmac: assure SSID length from firmware is limited | `drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c` |
| 39 | CVE-2020-0255 | - | 4.9.222 | `6affa87d168d` | selinux: properly handle multiple messages in selinux_netlin | `security/selinux/hooks.c` |
| 40 | CVE-2020-0432 | 7.8 | 4.9.213 | `8b6487d85ca9` | staging: most: net: fix buffer overflow | `drivers/staging/most/aim-network/networking.c` |
| 41 | CVE-2020-0433 | 7.8 | 4.9.219 | `f530afb974c2` | blk-mq: sync the update nr_hw_queues with blk_mq_queue_tag_b | `block/blk-mq-tag.c, block/blk-mq.c` |
| 42 | CVE-2020-0444 | 7.8 | 4.9.216 | `145bd64d3582` | audit: fix error handling in audit_data_to_entry() | `kernel/auditfilter.c` |
| 43 | CVE-2020-12351 | 8.8 | 4.9.240 | `720369661674` | Bluetooth: L2CAP: Fix calling sk_filter on non-socket based  | `include/net/bluetooth/l2cap.h, net/bluetooth/l2cap_core.c, net/bluetooth/l2cap_sock.c` |
| 44 | CVE-2020-12653 | 7.8 | 4.9.214 | `7a4d6a45f2fa` | mwifiex: Fix possible buffer overflows in mwifiex_cmd_append | `drivers/net/wireless/marvell/mwifiex/scan.c` |
| 45 | CVE-2020-12654 | 7.1 | 4.9.214 | `0a996849d804` | mwifiex: Fix possible buffer overflows in mwifiex_ret_wmm_ge | `drivers/net/wireless/marvell/mwifiex/wmm.c` |
| 46 | CVE-2020-13974 | 7.8 | 4.9.227 | `adf823fa2a53` | vt: keyboard: avoid signed integer overflow in k_ascii | `drivers/tty/vt/keyboard.c` |
| 47 | CVE-2020-14351 | 7.8 | 4.9.244 | `5a097d643717` | perf/core: Fix race in the perf_mmap_close() function | `kernel/events/core.c` |
| 48 | CVE-2020-14381 | 7.8 | 4.9.218 | `fb099f3bb477` | futex: Fix inode life-time issue | `fs/inode.c, include/linux/fs.h, include/linux/futex.h …` |
| 49 | CVE-2020-14386 | 7.8 | 4.9.239 | `9a675ac9fe97` | net/packet: fix overflow in tpacket_rcv | `net/packet/af_packet.c` |
| 50 | CVE-2020-25212 | 7.0 | 4.9.233 | `8973046648c4` | nfs: Fix getxattr kernel panic and memory overflow | `fs/nfs/nfs4proc.c, fs/nfs/nfs4xdr.c` |
| 51 | CVE-2020-25643 | 7.2 | 4.9.238 | `585e29541c29` | hdlc_ppp: add range checks in ppp_cp_parse_cr() | `drivers/net/wan/hdlc_ppp.c` |
| 52 | CVE-2020-25645 | 7.5 | 4.9.244 | `1200ebbd06c2` | geneve: add transport ports in route lookup for geneve | `drivers/net/geneve.c` |
| 53 | CVE-2020-25668 | 7.0 | 4.9.242 | `ea5dd52c3568` | tty: make FONTX ioctl use the tty pointer they were actually | `drivers/tty/vt/vt_ioctl.c` |
| 54 | CVE-2020-25669 | 7.8 | 4.9.245 | `452e66f60880` | Input: sunkbd - avoid use-after-free in teardown paths | `drivers/input/keyboard/sunkbd.c` |
| 55 | CVE-2020-25671 | 7.8 | 4.9.267 | `013b8099064f` | nfc: fix refcount leak in llcp_sock_connect() | `net/nfc/llcp_sock.c` |
| 56 | CVE-2020-27068 | 9.8 | 4.9.216 | `4d284a7a2ce3` | cfg80211: add missing policy for NL80211_ATTR_STATUS_CODE | `net/wireless/nl80211.c` |
| 57 | CVE-2020-27815 | 7.8 | 4.9.249 | `2c7c903caef1` | jfs: Fix array index bounds check in dbAdjTree | `fs/jfs/jfs_dmap.h` |
| 58 | CVE-2020-29368 | 7.0 | 4.9.228 | `d93d7bd61072` | mm: thp: make the THP mapcount atomic against __split_huge_p | `mm/huge_memory.c` |
| 59 | CVE-2020-29370 | 7.0 | 4.9.217 | `ff58bb340c43` | mm: slub: add missing TID bump in kmem_cache_alloc_bulk() | `mm/slub.c` |
| 60 | CVE-2020-29661 | 7.8 | 4.9.248 | `742f3062298a` | tty: Fix ->pgrp locking in tiocspgrp() | `drivers/tty/tty_io.c` |
| 61 | CVE-2020-36386 | 7.1 | 4.9.233 | `aea77913022b` | Bluetooth: Fix slab-out-of-bounds read in hci_extended_inqui | `net/bluetooth/hci_event.c` |
| 62 | CVE-2020-8648 | 7.1 | 4.9.216 | `290a9381ccc1` | vt: selection, close sel_buffer race | `drivers/tty/vt/selection.c` |
| 63 | CVE-2021-0937 | - | 4.9.267 | `0c58c9f9c5c5` | netfilter: x_tables: fix compat match/target pad out-of-boun | `net/ipv4/netfilter/arp_tables.c, net/ipv4/netfilter/ip_tables.c, net/ipv6/netfilter/ip6_tables.c …` |
| 64 | CVE-2021-28660 | 8.8 | 4.9.262 | `b318d268318b` | staging: rtl8188eu: prevent ->ssid overflow in rtw_wx_set_sc | `drivers/staging/rtl8188eu/os_dep/ioctl_linux.c` |
| 65 | CVE-2021-32399 | 7.0 | 4.9.269 | `34f1f8aecf16` | bluetooth: eliminate the potential race condition when remov | `net/bluetooth/hci_request.c` |
| 66 | CVE-2021-33033 | 7.8 | 4.9.298 | `f49f0e65a956` | cipso,calipso: resolve a number of problems with the DOI ref | `net/ipv4/cipso_ipv4.c, net/ipv6/calipso.c, net/netlabel/netlabel_cipso_v4.c` |
| 67 | CVE-2021-33034 | 7.8 | 4.9.269 | `31f20a6e7366` | Bluetooth: verify AMP hci_chan before amp_destroy | `include/net/bluetooth/hci_core.h, net/bluetooth/hci_event.c` |
| 68 | CVE-2021-33909 | 7.8 | 4.9.276 | `c5157b3e775d` | seq_file: disallow extremely large seq buffer allocations | `fs/seq_file.c` |
| 69 | CVE-2021-3483 | 7.8 | 4.9.265 | `cf4ab748a0ef` | firewire: nosy: Fix a use-after-free bug in nosy_ioctl() | `drivers/firewire/nosy.c` |
| 70 | CVE-2021-34981 | - | 4.9.271 | `77c559407276` | Bluetooth: cmtp: fix file refcount when cmtp_attach_device f | `net/bluetooth/cmtp/core.c` |
| 71 | CVE-2021-3609 | 7.0 | 4.9.276 | `545914a9f926` | can: bcm: delay release of struct bcm_op after synchronize_r | `net/can/bcm.c` |
| 72 | CVE-2021-3612 | 7.8 | 4.9.259 | `e0154ded9330` | Input: joydev - prevent potential read overflow in ioctl | `drivers/input/joydev.c` |
| 73 | CVE-2021-3640 | 7.0 | 4.9.291 | `9bbe312ebea4` | Bluetooth: sco: Fix lock_sock() blockage by memcpy_from_msg( | `net/bluetooth/sco.c` |
| 74 | CVE-2021-3715 | 7.8 | 4.9.218 | `97a8e7afaee8` | net_sched: cls_route: remove the right filter from hashtable | `net/sched/cls_route.c` |
| 75 | CVE-2021-3752 | 7.1 | 4.9.291 | `d19ea7da0eeb` | Bluetooth: fix use-after-free error in lock_sock_nested() | `net/bluetooth/l2cap_sock.c` |
| 76 | CVE-2021-3760 | 7.8 | 4.9.288 | `8a44904ce83e` | nfc: nci: fix the UAF of rf_conn_info object | `net/nfc/nci/rsp.c` |
| 77 | CVE-2021-39634 | 7.8 | 4.9.239 | `a16d314ccda2` | epoll: do not insert into poll queues until all sanity check | `fs/eventpoll.c` |
| 78 | CVE-2021-39685 | 7.8 | 4.9.293 | `d2ca6859ea96` | USB: gadget: detect too-big endpoint 0 requests | `drivers/usb/gadget/composite.c, drivers/usb/gadget/legacy/dbgp.c, drivers/usb/gadget/legacy/inode.c` |
| 79 | CVE-2021-39698 | 7.8 | 4.9.293 | `0e92a7e47a04` | wait: add wake_up_pollfree() | `include/linux/wait.h, kernel/sched/wait.c` |
| 80 | CVE-2021-40490 | 7.0 | 4.9.283 | `7067b09fe587` | ext4: fix race writing to an inline_data file while its xatt | `fs/ext4/inline.c` |
| 81 | CVE-2021-4157 | 8.0 | 4.9.269 | `c621f3654bba` | pNFS/flexfiles: fix incorrect size check in decode_nfs_fh() | `fs/nfs/flexfilelayout/flexfilelayout.c` |
| 82 | CVE-2021-41864 | 7.8 | 4.9.287 | `4fd6663eb01b` | bpf: Fix integer overflow in prealloc_elems_and_freelist() | `kernel/bpf/stackmap.c` |
| 83 | CVE-2021-42008 | 7.8 | 4.9.281 | `de9171c1d9a5` | net: 6pack: fix slab-out-of-bounds in decode_data | `drivers/net/hamradio/6pack.c` |
| 84 | CVE-2021-4202 | 7.0 | 4.9.291 | `4a59a3681158` | NFC: reorganize the functions in nci_request | `net/nfc/nci/core.c` |
| 85 | CVE-2021-46932 | - | 4.9.296 | `d1962f263a17` | Input: appletouch - initialize work before device registrati | `drivers/input/mouse/appletouch.c` |
| 86 | CVE-2021-46933 | - | 4.9.296 | `cc8c8028c21b` | usb: gadget: f_fs: Clear ffs_eventfd in ffs_data_clear. | `drivers/usb/gadget/function/f_fs.c` |
| 87 | CVE-2021-46938 | - | 4.9.269 | `8ae0185255ea` | dm rq: fix double free of blk_mq_tag_set in dev remove after | `drivers/md/dm-rq.c` |
| 88 | CVE-2021-46939 | - | 4.9.269 | `859b47a43f5a` | tracing: Restructure trace_clock_global() to never block | `kernel/trace/trace_clock.c` |
| 89 | CVE-2021-47054 | - | 4.9.269 | `a6191e91c10e` | bus: qcom: Put child node before return | `drivers/bus/qcom-ebi2.c` |
| 90 | CVE-2021-47056 | - | 4.9.269 | `f4c4e0714068` | crypto: qat - ADF_STATUS_PF_RUNNING should be set after adf_ | `drivers/crypto/qat/qat_c3xxxvf/adf_drv.c, drivers/crypto/qat/qat_c62xvf/adf_drv.c, drivers/crypto/qat/qat_dh895xccvf/adf_drv.c` |
| 91 | CVE-2021-47086 | - | 4.9.295 | `b10c7d745615` | phonet/pep: refuse to enable an unbound pipe | `net/phonet/pep.c` |
| 92 | CVE-2021-47114 | - | 4.9.272 | `33e03adafb29` | ocfs2: fix data corruption by fallocate | `fs/ocfs2/file.c` |
| 93 | CVE-2021-47117 | - | 4.9.272 | `5b3a9a2be594` | ext4: fix bug on in ext4_es_cache_extent as ext4_split_exten | `fs/ext4/extents.c` |
| 94 | CVE-2021-47118 | - | 4.9.272 | `f86c80515a8a` | pid: take a reference when initializing `cad_pid` | `init/main.c` |
| 95 | CVE-2021-47121 | - | 4.9.272 | `81afc61cb6e2` | net: caif: fix memory leak in cfusbl_device_notify | `net/caif/caif_usb.c` |
| 96 | CVE-2021-47122 | - | 4.9.272 | `9348c1f10932` | net: caif: fix memory leak in caif_device_notify | `net/caif/caif_dev.c` |
| 97 | CVE-2021-47145 | - | 4.9.271 | `e934c4ee17b3` | btrfs: do not BUG_ON in link_to_fixup_dir | `fs/btrfs/tree-log.c` |
| 98 | CVE-2021-47146 | - | 4.9.271 | `17728616a4c8` | mld: fix panic in mld_newpack() | `net/ipv6/mcast.c` |
| 99 | CVE-2021-47153 | - | 4.9.271 | `09c9e79f4c10` | i2c: i801: Don't generate an interrupt on bus reset | `drivers/i2c/busses/i2c-i801.c` |
| 100 | CVE-2021-47166 | - | 4.9.271 | `b291baae24f8` | NFS: Don't corrupt the value of pg_bytes_written in nfs_do_r | `fs/nfs/pagelist.c` |
| 101 | CVE-2021-47168 | - | 4.9.271 | `b287521e9e94` | NFS: fix an incorrect limit in filelayout_decode_layout() | `fs/nfs/filelayout/filelayout.c` |
| 102 | CVE-2021-47169 | - | 4.9.271 | `c697244ce940` | serial: rp2: use 'request_firmware' instead of 'request_firm | `drivers/tty/serial/rp2.c` |
| 103 | CVE-2021-47171 | - | 4.9.271 | `22c840596af0` | net: usb: fix memory leak in smsc75xx_bind | `drivers/net/usb/smsc75xx.c` |
| 104 | CVE-2021-47173 | - | 4.9.271 | `7889c70e6173` | misc/uss720: fix memory leak in uss720_probe | `drivers/usb/misc/uss720.c` |
| 105 | CVE-2021-47180 | - | 4.9.271 | `4a621621c7af` | NFC: nci: fix memory leak in nci_allocate_device | `include/net/nfc/nci_core.h, net/nfc/nci/core.c, net/nfc/nci/hci.c` |
| 106 | CVE-2022-0435 | 8.8 | 4.9.301 | `175db196e45d` | tipc: improve size validations for received domain records | `net/tipc/link.c, net/tipc/monitor.c` |
| 107 | CVE-2022-0492 | 7.8 | 4.9.301 | `7e33a0ad792f` | cgroup-v1: Require capabilities to set release_agent | `kernel/cgroup.c` |
| 108 | CVE-2022-0644 | - | 4.9.288 | `52ed5a196b11` | vfs: check fd has read access in kernel_read_file_from_fd() | `fs/exec.c` |
| 109 | CVE-2022-0850 | 7.1 | 4.9.276 | `25dcc64fa0c9` | ext4: fix kernel infoleak via ext4_extent_header | `fs/ext4/extents.c` |
| 110 | CVE-2022-1011 | 7.8 | 4.9.320 | `b79d4d0da659` | fuse: fix pipe buffer lifetime for direct_io | `fs/fuse/dev.c, fs/fuse/file.c, fs/fuse/fuse_i.h` |
| 111 | CVE-2022-1353 | 7.1 | 4.9.311 | `7b0e01a9b7f2` | af_key: add __GFP_ZERO flag for compose_sadb_supported in fu | `net/key/af_key.c` |
| 112 | CVE-2022-1729 | 7.0 | 4.9.316 | `a1466528d8ae` | perf: Fix sys_perf_event_open() race against self | `kernel/events/core.c` |
| 113 | CVE-2022-1966 | 7.8 | 4.9.318 | `94e9b7591961` | netfilter: nf_tables: disallow non-stateful expression in se | `net/netfilter/nf_tables_api.c, net/netfilter/nft_dynset.c` |
| 114 | CVE-2022-20141 | 7.0 | 4.9.283 | `e9924c4204ed` | igmp: Add ip_mc_list lock in ip_check_mc_rcu | `net/ipv4/igmp.c` |
| 115 | CVE-2022-20566 | 7.8 | 4.9.326 | `d255c861e268` | Bluetooth: L2CAP: Fix use-after-free caused by l2cap_chan_pu | `include/net/bluetooth/l2cap.h, net/bluetooth/l2cap_core.c` |
| 116 | CVE-2022-24958 | 7.8 | 4.9.305 | `be1bb345f180` | usb: gadget: don't release an existing dev->buf | `drivers/usb/gadget/legacy/inode.c` |
| 117 | CVE-2022-2588 | 7.8 | 4.9.326 | `34a475425612` | net_sched: cls_route: remove from list when handle is 0 | `net/sched/cls_route.c` |
| 118 | CVE-2022-27223 | 8.8 | 4.9.304 | `958b6ab4d70b` | USB: gadget: validate endpoint index for xilinx udc | `drivers/usb/gadget/udc/udc-xilinx.c` |
| 119 | CVE-2022-28390 | 7.8 | 4.9.311 | `e9c4ee674586` | can: ems_usb: ems_usb_start_xmit(): fix double dev_kfree_skb | `drivers/net/can/usb/ems_usb.c` |
| 120 | CVE-2022-2978 | 7.8 | 4.9.331 | `d1ff475d7c83` | fs: fix UAF/GPF bug in nilfs_mdt_destroy | `fs/inode.c` |
| 121 | CVE-2022-30594 | 7.8 | 4.9.311 | `4f96b94a8342` | ptrace: Check PTRACE_O_SUSPEND_SECCOMP permission on PTRACE_ | `kernel/ptrace.c` |
| 122 | CVE-2022-3424 | 7.8 | 4.9.337 | `f99d5f1bd8cd` | misc: sgi-gru: fix use-after-free error in gru_set_context_o | `drivers/misc/sgi-gru/grufault.c, drivers/misc/sgi-gru/grumain.c, drivers/misc/sgi-gru/grutables.h` |
| 123 | CVE-2022-3564 | 7.1 | 4.9.333 | `dc30e05bb188` | Bluetooth: L2CAP: Fix use-after-free caused by l2cap_reassem | `net/bluetooth/l2cap_core.c` |
| 124 | CVE-2022-3635 | 7.0 | 4.9.326 | `acf173d9e278` | atm: idt77252: fix use-after-free bugs caused by tst_timer | `drivers/atm/idt77252.c` |
| 125 | CVE-2022-3649 | 7.0 | 4.9.331 | `a9043a24c6e3` | nilfs2: fix use-after-free bug of struct nilfs_root | `fs/nilfs2/inode.c` |
| 126 | CVE-2022-36946 | 7.5 | 4.9.326 | `3b3e2de46232` | netfilter: nf_queue: do not allow packet truncation below tr | `net/netfilter/nfnetlink_queue.c` |
| 127 | CVE-2022-41858 | 7.1 | 4.9.311 | `113284fe4877` | drivers: net: slip: fix NPD bug in sl_tx_timeout() | `drivers/net/slip/slip.c` |
| 128 | CVE-2022-42896 | 8.8 | 4.9.335 | `c834df40af8e` | Bluetooth: L2CAP: Fix accepting connection request for inval | `net/bluetooth/l2cap_core.c` |
| 129 | CVE-2022-45934 | 7.8 | 4.9.337 | `49d5867819ab` | Bluetooth: L2CAP: Fix u8 overflow | `net/bluetooth/l2cap_core.c` |
| 130 | CVE-2023-1390 | 7.5 | 4.9.253 | `310014f572a5` | tipc: fix NULL deref in tipc_link_xmit() | `net/tipc/link.c` |
| 131 | CVE-2026-43503 | - | 上游主线 | `48f6a5356a33` | net: skbuff: 传播 shared-frag 标记修复 ESP 就地写入 (DirtyClone/Fragne | `` |
| 132 | CVE-2026-98432 | 9.8 | 上游主线（2026-10-01 v2） | `edumazet@kernel.org` v2 | ipv4: free inet_opt and ireq_opt after an RCU grace period | `net/ipv4/af_inet.c, net/ipv4/tcp_ipv4.c` |

---

## 4. CVE-2026-43503 (DirtyClone / Fragnesia) 手工回移说明

**CVSS 3.1 = 8.8（高危，本地提权）**。根因：frag-transfer 辅助函数移动 frag 描述符时未传播 shared-frag 标记，
目标 skb 仍引用外部/页缓存页却报告 `skb_has_shared_frag()` 为 false；ESP 输入据此跳过 `skb_cow_data()`，
使非特权用户可经 authencesn-ESN stray write 写入 root 只读文件的页缓存。

**4.9 适配要点**：主线使用 `skb_shinfo()->flags` 的 `SKBFL_SHARED_FRAG`；
**4.9 没有该标记，对应物是 `skb_shinfo()->tx_flags` 的 `SKBTX_SHARED_FRAG`**，故按 4.9 语义改写。

| 修复位置 | 4.9 状态 | 处理 |
|---|---|---|
| `__pskb_copy_fclone()` | 缺失传播 | ✅ 已补 |
| `skb_shift()` | 缺失传播 | ✅ 已补 |
| `skb_segment()` | 仅传播 head_skb | ✅ 已补 frag_skb 折叠（2 处） |
| `skb_gro_receive()` | 缺失传播 | ✅ 已补（p 与 lp） |
| `skb_try_coalesce()` | 缺失传播 | ✅ 已补 |
| `skb_split()` | **4.9 已有**（历史修复） | — 无需改动 |
| `tcp_clone_payload()` | 4.9 无此函数 | — 跳过 |
| `skb_gro_receive_list()` | 4.9 无此函数 | — 跳过 |

上游提交：`48f6a5356a33dd78e7144ae1faef95ffc990aae0`、`f84eca5817390257cef78013d0112481c503b4a3`

---

## 4.1 CVE-2026-98432 (IPv4 TCP use-after-free) —— 2026-11-21 追加回移

**CVSS 3.1 = 9.8（严重，未认证远程 DoS / root RCE）**。根因：`tcp_v4_syn_recv_sock()` 把
`ireq->ireq_opt`（`struct ip_options_rcu`）的所有权无拷贝地转移给子 socket（`newinet->inet_opt`）；
另一 CPU 同时处理同一 request socket 的重传 SYN，经 `tcp_check_req()` → `inet_rtx_syn_ack()` →
`tcp_v4_send_synack()` / `inet_csk_route_req()` 只以 `rcu_read_lock()` 读取该 options，
而子 socket 已被释放且 `inet_sock_destruct()` 用**裸 `kfree()`** 回收 `inet_opt` → UAF。

**本树适用性（实证，非套话）**：

```
net/ipv4/inet_connection_sock.c:650   inet_ehash_insert(req_to_sk(req), NULL)
   ← reqsk_queue_hash_req() ← inet_csk_reqsk_queue_hash_add()
```

即 4.12 的 `079096f103fa`「syn_recv requests install into ehash table」行为已由 MPTCP/net
backport 带入本树——request socket 在无 listener 锁的情况下进入 ehash，正是本 CVE 的前提。
请求 socket 迁移路径（第二个 Fixes，`net.ipv4.tcp_migrate_req`）本树不存在，故仅第一条竞态成立。

**4.9 适配（关键：必须补 NULL 检查，不能逐字照搬上游）**：

| 文件 | 函数 | 改动 |
|---|---|---|
| `net/ipv4/af_inet.c` | `inet_sock_destruct()` | 新增局部 `struct ip_options_rcu *opt;`；`opt = rcu_dereference_protected(inet->inet_opt, 1);` 然后 `if (opt) kfree_rcu(opt, rcu);` |
| `net/ipv4/tcp_ipv4.c` | `tcp_v4_reqsk_destructor()` | 同样写法，作用于 `inet_rsk(req)->ireq_opt` |

**为什么必须加 NULL 判断**：主线 `kfree_rcu()` 宏自带 NULL 保护（先判 `if (__ptr)` 再取
rcu_head 地址），而本树 4.9 的宏（`include/linux/rcupdate.h:1114`）没有：

```
#define kfree_rcu(ptr, rcu_head) \
    __kfree_rcu(&((ptr)->rcu_head), offsetof(typeof(*(ptr)), rcu_head))
```

`inet_opt` / `ireq_opt` 对绝大多数 socket 就是 **NULL**（`tcp_ipv4.c` 多条路径显式
`newinet->inet_opt = NULL`）。传 NULL 时展开为 `head == NULL`，
`__call_rcu()`（`kernel/rcu/tree.c:3133`）执行 `head->func = func;` 即写地址 0 → data abort；
本机 `panic_on_oops=1`，于是立即 panic → 反复重启进华为 eRecovery。

**已实测复现**：构建 **#45** 逐字照搬上游那一行，H4P0218923000886 刷入后无法启动并进入 eRecovery；
刷回 #44 后一切正常。树内其它 `ip_options_rcu` 使用者本来就都带判断
（`net/ipv4/ip_sockglue.c:673-674 if (old)`、`net/ipv4/cipso_ipv4.c:1872-1873` 与 `:1939-1940 if (opt)`），
所以树内 283 处 `kfree_rcu()` 调用不受影响——问题只出在这两个新落点。

`net/dccp/ipv4.c:554` 有同款裸 kfree，但 `CONFIG_DCCP` 未启用，不参与编译，未改。
改动为指令级 + 一个局部变量，无结构体布局/符号变化，ABI 不变（`tools/abi-verify.sh` 通过）。

补丁归档：`cve-patches/CVE-2026-98432.patch`。
验证设备：H4P0218923000886 —— **#46 已刷入并正常启动**（`uname -v` =
`#46 SMP PREEMPT Sat Nov 21 20:01:35 CST 2026`，分区回读 sha256
`c20a94f5fdf6e5ccaf792b7d61e6aeb14eeca20181f5c325321eb08fffe6c452`，
`CONFIG_POSIX_MQUEUE/CGROUP_DEVICE/BPF_JIT` 仍为 y，`sys.boot_completed=1`，
内核日志无 oops/panic）。

---

## 4.2 高危补齐批次（2026-11-21，工作树未提交改动，构建 #47）

按用户指定清单补齐 7 项；其中 **5 项已回移并验证**，**2 项经实证在本机不可达、不做改动**。
全部取自 `linux-4.9.y` 稳定分支的上游 backport，除标注「手工适配」者外均按原文应用。
另：**刻意跳过** `39e2c51405fb`（`tcp: configurable source port perturb table size`，
2022-12-08，引入 `CONFIG_INET_TABLE_PERTURB_ORDER`）——属额外加固而非 CVE 修复本身，避免扩大改动面。

| CVE | CVSS | 组件 / 落点 | 采用的上游 stable 提交 |
|---|---|---|---|
| CVE-2022-1012 | 8.2 | TCP 源端口随机性不足 | `136b4799419a`、`05a12e5c4063`、`576696ed0dee`、`2ed413f140bb`、`aa7722529f6d`、`dd82067bd6ca`(手工)、`3c78eea640f6`(手工)、`a81a6b204a30`(手工) |
| CVE-2019-9506 | 8.1 | Bluetooth KNOB（BR/EDR 最小密钥长度） | `6290d9d3192e`、`68d1e285e934`、`f470557724f2` |
| CVE-2019-11487 | 7.8 | page refcount 溢出（pipe/splice/fuse/gup/hugetlb） | `604d7b594c6d`、`96019c691458`、`9557090582a3`(fuse 部分手工)、`2ed768cfd895`(gup 部分手工) |
| CVE-2022-2964 | 7.8 | ASIX AX88179_178A RX fixup OOB 读写 | `711b6bf3fb05`（函数整体按上游 post-image 重写） |
| CVE-2018-20856 | 7.8 | `block/blk-core.c` `__blk_drain_queue()` UAF | `54648cf1ec2d`（一行：`blk_free_flush_queue(q->fq)` 后补 `q->fq = NULL`） |

**判定为不可达（未修改，无需修复）**：

- **CVE-2019-3900**（vhost_net `handle_rx()` 死循环 DoS）：`CONFIG_VHOST_NET` 为 `not set`，
  `drivers/vhost/net.c` 不参与编译，代码路径不存在。
- **CVE-2019-19768**（`kernel/trace/blktrace.c` `__blk_add_trace()` UAF(read)）：
  `CONFIG_BLK_DEV_IO_TRACE` 为 `not set`，`blktrace` 不编译，路径不存在。

**构建与真机验证**：

- `./rebuild.sh 16` exit 0；`out/.version` = **47**，`UTS_VERSION "#47 SMP PREEMPT Sat Nov 21 21:15:55 CST 2026"`；
- `bash tools/abi-verify.sh` → `ABI CHECK PASSED`；`Image.gz` 15168027 B；
- 打包 `SELINUX_MODE=enforcing ./pack.sh ... kernel-cve-batch-v47.img`，15171584 B，
  sha256 `0df0e9b51f81311964633f6dfb51040d7caa14e0fbf93c4970fe61832f46275a`；
- H4P0218923000886：push 后设备侧 sha 一致 → `dd` 写入 `/dev/block/by-name/kernel` →
  分区回读 sha 一致 → `adb reboot` 约 30s 起来，`uname -v` = `#47`，
  `sys.boot_completed=1`，`CONFIG_POSIX_MQUEUE/CGROUP_DEVICE/BPF_JIT` 仍 y、
  `CONFIG_BLK_DEV_INTEGRITY` 仍 not set；dmesg 中仅有华为 `aware_net_exit`/`remove_proc_entry`
  的既存 WARN（netns 清理），无 oops/panic。

**注意**：`table_perturb` 改为动态分配（2^16 × u32 = 256kB），在 `inet_hashinfo_init()`
中为 `tcp_hashinfo` 申请，失败即 `panic("TCP: failed to alloc table_perturb")`（上游行为）；
本机启动正常说明分配成功。

---

## 5. CVE-2026-31431 (Copy Fail) —— 判定为「不受影响」，无需修复

**CVSS 3.1 = 7.8（高危，本地提权 / 容器逃逸）**，受影响组件为 `algif_aead`（AF_ALG 用户态 AEAD 接口）。

**本机判定依据（实证）**：

```
crypto/Makefile:134:  obj-$(CONFIG_CRYPTO_USER_API_AEAD) += algif_aead.o
本内核 out/.config:   # CONFIG_CRYPTO_USER_API_AEAD is not set
```
该模块**根本未被编译进内核**，攻击面不存在。故 MateRS 不受 CVE-2026-31431 影响。
（旁证：Ubuntu 亦说明 3.13 / 4.4 内核不受影响，本机 4.9 且该选项关闭，双重不适用。）

---

## 6. 已剔除的低危 / 无关项（251 个）

| 剔除理由 | 数量 |
|---|---|
| 低/中危 (<7.0) | 165 |
| 无关驱动/硬件 | 80 |
| 非 arm64 架构 | 6 |

剔除标准：① CVSS < 7.0（低/中危，按「只关注高危」要求）；② 无关主线驱动/硬件（安卓使用厂商驱动，主线网卡/GPU/RDMA/Xen/vhost 等不适用）；③ 非 arm64 架构（x86/mips/ppc/s390 等）。

> 这些补丁**未应用**，但补丁原文仍保存在 `.cve-scratch/patches/`，且全量分支 `full-backport-512`（383 个提交）已存档，可随时取用。

---

## 7. ⚠️ 待人工处理的高危项（**未应用**，需你决策）

以下 CVE 因**华为对相关文件有重度改写**（如 `drivers/android/binder.c` 为华为定制版），
自动三方合并后仍存在冲突。**流水线未对工作树做任何修改**，因此不存在「错误应用」的风险，但也意味着这些漏洞当前仍未修复。

待人工总数 **102** 个，其中 CVSS ≥ 7.0 的 **39** 个；经语义存在性检测，确认**确实缺失修复**的高危项约 **30** 个：

| CVE | CVSS | 修复内容在树中缺失率 |
|---|---|---|
| CVE-2022-1012 | 8.2 | ~~缺失 100%~~ → **已回移（§4.2，构建 #47）** |
| CVE-2020-28374 | 8.1 | 缺失 94% |
| CVE-2019-9506 | 8.1 | ~~缺失 100%~~ → **已回移（§4.2，构建 #47）** |
| CVE-2022-26490 | 7.8 | 缺失 67% |
| CVE-2021-26930 | 7.8 | 缺失 75% |
| CVE-2019-11487 | 7.8 | ~~缺失 80%~~ → **已回移（§4.2，构建 #47）** |
| CVE-2020-27786 | 7.8 | 缺失 82% |
| CVE-2020-14356 | 7.8 | 缺失 82% |
| CVE-2022-2964 | 7.8 | ~~缺失 85%~~ → **已回移（§4.2，构建 #47）** |
| CVE-2022-20368 | 7.8 | 缺失 88% |
| CVE-2018-20856 | 7.8 | ~~缺失 100%~~ → **已回移（§4.2，构建 #47）** |
| CVE-2019-2182 | 7.8 | 缺失 100% |
| CVE-2020-35519 | 7.8 | 缺失 100% |
| CVE-2022-4095 | 7.8 | 缺失 100% |
| CVE-2019-3900 | 7.7 | 不可达：`CONFIG_VHOST_NET` not set（§4.2），不修改 |
| CVE-2019-19768 | 7.5 | 不可达：`CONFIG_BLK_DEV_IO_TRACE` not set（§4.2），不修改 |
| CVE-2021-45485 | 7.5 | 缺失 100% |
| CVE-2020-25705 | 7.4 | 缺失 100% |
| CVE-2022-33742 | 7.1 | 缺失 96% |
| CVE-2022-33741 | 7.1 | 缺失 97% |
| CVE-2022-3202 | 7.1 | 缺失 100% |
| CVE-2022-26365 | 7.1 | 缺失 100% |
| CVE-2023-26607 | 7.1 | 缺失 100% |
| CVE-2022-23036 | 7.0 | 缺失 86% |
| CVE-2022-23038 | 7.0 | 缺失 86% |

其中**最值得优先处理**的是安卓核心 IPC 相关项：
`CVE-2019-2215`（binder UAF，CVSS 7.8，Android 史上最著名的在野利用提权漏洞之一）、
`CVE-2020-0030`、`CVE-2021-39686`、`CVE-2019-11599`、`CVE-2018-20510`。

### 7.1 补充核查：华为是否已自行加固这些项？

针对「华为可能自己加固过」这一判断，对 binder 相关项逐条做了**功能性验证**（不只看新增行字符串，而是查关键机制是否在位）：

| CVE | CVSS | 华为是否已修 | 判定依据 |
|---|---|---|---|
| **CVE-2019-2215** | 7.8 | ✅ **已修** | `BINDER_LOOPER_STATE_POLL` 机制齐全：枚举定义（`binder.c:630`）、`binder_poll` 置位（`5035`）、线程释放时 `wake_up_poll(&thread->wait, POLLHUP \| POLLFREE)`（`5000-5002`）；上游补丁的整段注释与代码均在位 |
| **CVE-2020-0030** | 7.0 | ✅ **已修** | 补丁 6/6 新增行均存在 |
| **CVE-2018-20510** | 5.5 | ✅ **已修** | 4 处 `%p`→`%pK`（`binder.c:2564/4253/5800/5825`）全部在位，与华为 4.14 一致。（早先"75%"为字符串启发式误报，已更正） |
| **CVE-2021-39686** | 7.0 | ❌ **原未修 → 已由本轮修复** | 原 `binder.c:3383` 为 `t->sender_euid = task_euid(proc->tsk);`；**已验证华为 4.14.116 含 `const struct cred *cred` 字段并普遍使用 `proc->cred`**，说明华为认定需修。→ 已按上游补丁 + 华为 4.14 实现回移（提交 `db5618bc4`） |
| **CVE-2019-11599 / CVE-2019-3892** | 7.0 | ❌ **原未修 → 已由本轮修复** | 全树原无 `mmget_still_valid`；**已验证华为 4.14.116 含该函数并在 mm/ fs/ 多处使用**。→ 已回移（提交 `0c8566175`，5 文件） |

**结论（对「华为可能自己加固过」的校准）**：

- ✅ **对 binder 大体成立**：华为**确实独立加固过** binder —— `CVE-2019-2215`、`CVE-2020-0030`、`CVE-2018-20510` 都已修复，
  且 `BINDER_LOOPER_STATE_POLL` 取值华为用 `0x20` 而上游用 `0x40`，说明是**华为自己的实现**，不是机械回移。
- ❌ **但不完全**：`CVE-2021-39686` 与 coredump 竞争条件（`CVE-2019-11599`/`CVE-2019-3892`）在 4.9.148 这支上**确实缺失**
  —— 华为是在后续的 4.14 分支里补上的，未回移到 4.9.148。**这两项已由本轮修复**。
- ⚠️ **不宜推广为「华为都修过」**：本次回移在 CAIF/TIPC 两个未启用子系统中发现的上游补丁缺陷说明，
  未被编译器覆盖的代码路径长期缺乏检验，不能假定其已被加固。

> **判定方法说明**：以华为 NEO 鸿蒙 3.0 源码（`NEO-AN00_HarmonyOS3.0.0_opensource`，Linux **4.14.116**）为参照，
> 逐项检查「华为是否修过、怎么修」。因 4.14 与 4.9 大版本不同，仅用作**修复与否的判据与实现参考**，
> 落点按本树结构适配（例如 binder 分配逻辑本树已拆分至 `binder_alloc.c`）。

因此建议：binder 组可按「风险可接受」不修，但**应知悉 `CVE-2021-39686` 与 coredump 竞争条件确实未修**，由你决定是否补。

---

## 8. 完整性与构建验证

- **提交污染审计**：逐个提交比对「实际改动文件」与「该 CVE 补丁涉及文件」，**0 个提交含额外文件**。
- **`.img` 误纳防护**：`.gitignore` 已改为根级 `/*.img`（驱动固件 `drivers/**/*.img` 不受影响）。
- **版本号断言**：每个提交后 `SUBLEVEL = 148` 保持不变。
- **构建验证**：见 §9。

---

## 9. 构建验证

**结论：`./build.sh 12` 构建成功（exit 0）**，产物 `out/arch/arm64/boot/Image.gz` = 14,992,568 B（解压 40,282,120 B）。

| 验证项 | 结果 |
|---|---|
| 编译/链接 | ✅ 无 error（仅厂商驱动既有 warning） |
| 内核内嵌版本串 | ✅ `Linux version 4.9.148-NEO_EMUI9.1.0_RKSU_xixiaobei@Github+` —— **版本号 4.9.148 在二进制层面得到验证** |
| RKSU 集成完好 | ✅ `out/System.map` 含 14 处 `ksu_handle*` / `is_ksu_transition` 符号 |

### 9.1 构建过程中发现并修复的 2 个问题（重要）

首次构建**失败**，暴露出一类系统性风险：**较晚的 4.9.y stable 补丁依赖了 4.9.148 之后才加入的宏/API**。两处均已修复并复验：

| # | 报错 | 根因 | 修复 | 提交 |
|---|---|---|---|---|
| 1 | `net/bluetooth/l2cap_core.c:504 error: implicit declaration of function 'kref_read'` | `kref_read()` 在 v4.11 才引入，4.9.148 没有（上游 4.9.y 是较晚才补入的） | 改用 4.9 等价写法 `atomic_read(&c->kref.refcount)`，与本文件 `l2cap_chan_hold()` 既有写法一致 | `9d4feef92` |
| 2 | `net/wireless/nl80211.c:235 error: implicit declaration of function 'for_each_element'` | CVE-2019-16746 的修复用到 `for_each_element` 宏族，4.9.148 中尚未定义 | 按上游 **4.9.337 原文**原样补入 `struct element` 与 element iteration helpers 宏族（含 `for_each_element_completed`），插入位置与上游一致 | `8c2724ddf` |

为一次性排查同类残留，另做了一次**全量符号扫描**：提取 130 个补丁全部新增行（1488 行）中被调用的 224 个标识符，与全树 2,826,514 个符号建立索引比对，
结果**仅 `kref_read` 一个缺失**（`for_each_element` 为宏，已随修复补入）。故同类风险已清空。

> ⚠️ 诚实说明：本节的"构建成功"只证明**可编译可链接**，不等于逐补丁语义正确。语义层面的复核由 §11 的独立审阅完成。

---

## 10. 后续可选工作

1. 处理 §7 的 30 个高危待人工项（建议从 binder 开始）。
2. 如需覆盖全部安全修复（含中危），可切换回 `full-backport-512` 分支（383 个提交已存档）。
3. 真机刷入验证：`SELINUX_MODE=enforcing ./pack.sh out/arch/arm64/boot/Image.gz NEO_EMUI9.1.0_RKSU_CVE.img`

---

## 11. 独立审阅（AgentTeams）

已组建独立审阅小组 `cve-backport-review`（4 名审阅者，使用免费模型），按文件分组只读审阅，**审阅者不得改动任何文件**，问题由船长复核后亲自修复：

| 任务 | 审阅者 | 模型 | 范围 |
|---|---|---|---|
| t1-manual | m1-manual | sensenova-6.8-flash-lite | 3 个手工改动文件（`net/core/skbuff.c` / `include/linux/ieee80211.h` / `net/bluetooth/l2cap_core.c`） |
| t2-core | m2-core | LongCat-2.0 | `kernel/ mm/ fs/ ipc/ security/ block/ init/ include/`（51 文件） |
| t3-netdrv | m3-netdrv | workbuddy/hy3 | `net/` 与 `drivers/`（104 文件） |
| t4-integrity | m4-integrity | workbuddy-ai/hy4-preview-f | 硬约束与交付完整性校验 |

> 注：`m3-netdrv` 与 `m4-integrity` 的模型由用户在 Web 审阅界面将计划改为 `workbuddy/hy3` 与 `workbuddy-ai/hy4-preview-f` 后执行（这两条路由未出现在 `list_subagent_models` 的注册清单中，属于用户侧提供的可用免费模型）。

### 11.1 t4-integrity 审阅结果：6/6 通过

| # | 检查项 | 结论 |
|---|---|---|
| 1 | 内核版本号未被修改 | ✅ `git diff bd7e6f9de HEAD -- Makefile` 为空；`SUBLEVEL = 148` |
| 2 | 每个 CVE 一个独立提交 | ✅ 区间 134 提交，唯一 CVE 号 131 个，非 CVE 主题仅补丁归档提交 1 条 |
| 3 | 未混入 `.img` | ✅ 全区间 `--name-only` 无 `.img` 命中 |
| 4 | 补丁文件已保留 | ✅ 双向 `comm` 比对无缺失、无多出 |
| 5 | 提交信息质量 | ✅ 129/131 主 CVE 提交含上游哈希 |
| 6 | `.gitignore` 正确性 | ✅ 根级 `/*.img` 命中；25 个驱动固件 `.img` 未被忽略（`check-ignore` 退出码 1） |

**审阅者指出并已由船长处理的 1 条真实缺口**（原提示 #2）：
归档提交 `d3e0051e7` 只保存了当时的 131 个上游补丁，其后两次**编译适配提交**（`9d4feef92` 的 `kref_read` 改写、`8c2724ddf` 的 `for_each_element` 宏族回移）没有对应补丁文件，归档不自洽。

→ 已修复：补入 `cve-patches/CVE-2022-20566-4.9-adapt.patch` 与 `cve-patches/CVE-2019-16746-4.9-adapt.patch`，
并新增 `cve-patches/README.md` 说明「上游原文补丁」与「4.9 适配补丁」两类文件的区别。现共 **133** 个补丁文件。

**未采纳的 1 条提示**（原提示 #1）：CVE-2019-16746 与 CVE-2022-20566 各有 2 个提交（主修复 + 编译适配）。
**有意保留拆分**——两个适配提交是「上游补丁不适用于 4.9.148」的独立证据，squash 会掩盖这一事实，不利于后续审计。

**待 t1-manual 回答的 1 条**（原提示 #3）：CVE-2026-43503 的正确性确认，已由 t1-manual 专门审阅（见 §11 表格）。

### 11.2 t2-core 审阅结果：51 文件全部通过

审阅范围：`kernel/ mm/ fs/ ipc/ security/ block/ init/ include/` 共 51 个文件。

| 审阅要点 | 结论 |
|---|---|
| 新增符号是否在 4.9.148 中存在 | ✅ 40+ 个符号逐一核对通过（`percpu_ref_is_zero` / `get_pid` / `POLLFREE` / `atomic64_cmpxchg_relaxed` / `MAX_RW_COUNT` / `kref_get_unless_zero` / `i_sequence` 等） |
| 三方合并残留标记 | ✅ 全文无 `<<<<<<<` / `=======` / `>>>>>>>` |
| `Kconfig` / `Makefile` 改动 | ✅ 仅 `drivers/char/Kconfig`（CVE-2019-11486 预期改动） |
| 逐子系统逻辑 | ✅ block(RCU) / futex(`futex_key` union inode→i_sequence) / perf(`detach_rest`) / ptrace / auditfilter / cgroup / THP / memory-failure / eventpoll 错误路径 / inode `i_sequence` / 9p / ext4(`eh_generation`) / NFS / XFS / ocfs2 / nilfs2 / SELinux(`nlmsg_perm`) 均判定正确 |

**船长独立复核（不直接采信审阅结论）**：

| 复核项 | 方法 | 结果 |
|---|---|---|
| 三方合并残留 | 自行对全部新增行做冲突标记正则扫描 | ✅ 无命中（与审阅结论一致） |
| `kref_read` 是否彻底清除 | 全树 `grep -rn kref_read` | ✅ 无任何引用 |
| 抽检 6 个符号的定义位置 | 全树定位 | ✅ 全部存在；其中 `detach_rest` 为 `kernel/events/core.c:5191` 局部变量、`eh_generation` 为 `fs/ext4/extents.h:102` 结构体字段（初次只在 `include/` 内检索造成误报，已澄清） |
| 最终裁决 | — | **审阅结论成立，未发现需修正项** |

### 11.3 t1-manual 审阅结果：3 个手工改动文件，发现并修复 1 个 medium 问题

| 文件 | 审阅结论 |
|---|---|
| `net/core/skbuff.c`（`97f7b6bca`，CVE-2026-43503） | ✅ **未发现问题**。6 处修复（`__pskb_copy_fclone` / `skb_shift` / `skb_segment`×2 / `skb_gro_receive` / `skb_try_coalesce`）标记传播方向均为 src→dst；4.9 适配（`tx_flags`/`SKBTX_SHARED_FRAG`）正确；`frag_skb` 无空指针风险；`tcp_clone_payload` 与 `skb_gro_receive_list` 正确未移植（4.9 不存在） |
| `net/bluetooth/l2cap_core.c`（`9d4feef92`） | ✅ **未发现问题**。`atomic_read(&c->kref.refcount)` 与 `kref_read` 等价，与文件既有模式一致，include 完整 |
| `include/linux/ieee80211.h`（`8c2724ddf`） | ⚠️ 1 medium + 1 low，见下 |

**发现的问题与处置**：

| 级别 | 问题 | 船长复核 | 处置 |
|---|---|---|---|
| **medium** | `for_each_element_extid` 宏（第 2666 行）引用 `WLAN_EID_EXTENSION`，但 `enum ieee80211_eid` 中无此成员；宏当前未被使用故编译通过，将来一旦使用即编译失败 | **核实成立，且比报告更严重**：上游 **4.9.337 自身也有同样遗漏**（其 ieee80211.h 的同一宏同样引用未定义的 `WLAN_EID_EXTENSION`）。本树此前的植入与上游逐字节一致，故该缺陷源自上游 4.9.y 的回移疏漏 | ✅ **已修**（`e4278eda4`）：按主线取值补入 `WLAN_EID_EXTENSION = 255`（v5.4 内核确认）。枚举中无其它成员取值 255，无冲突；宏此前未被使用，对现有二进制零行为影响。定向重编 `net/wireless/nl80211.o` 通过 |
| **low** | 宏定义与上游 `ad180ca` 非逐字符一致（5 处差异：`__packed`、参数名、const 强转、`(int)sizeof` 等） | **不成立**：已逐字节比对，本树植入块与**上游 4.9.337 原文完全一致**（`diff` 无差异）。审阅者对比的是另一参考版本（引入该宏的原始提交或主线版本），对 4.9 回移而言 4.9.337 才是正确基准 | 无需改动 |

> 结论：t1 的 medium 发现有效且已修复，并额外暴露出一个**上游 4.9.y 自身的缺陷**；low 项为基准选错，已澄清。

### 11.4 t3-netdrv 审阅结果：104 文件，发现 2 个真实缺陷（均已修）

审阅范围：`net/` 与 `drivers/` 共 104 个文件。审阅者自评 `needs_revision`。

| 编号 | 审阅者定级 | 问题 | 船长独立复核 | 处置 |
|---|---|---|---|---|
| **F1** | blocker | `net/caif/caif_dev.c` 使用未定义的 `cfserl_release()`，并把返回 void 的 `caif_enroll_dev()` 当 int 用 | **缺陷成立，但定级有误**：`CONFIG_CAIF is not set` → `net/caif` 根本不参与编译，故**不阻断构建**（构建实测 exit 0、error 计数 0）。确为潜在编译隐患 | ✅ **已回退**（`cd4812fe4`）：CVE-2021-47121 / CVE-2021-47122 均不自洽（都向 void 函数赋值；47121 自带 `cfusbl_release` 但同样赋值错误），缺前置提交，且 CAIF 在本机零使用场景 |
| **F2** | high | `net/tipc/link.c`：`imp = msg_importance(hdr)` 位于 `hdr = buf_msg(skb_peek(list))` 之前，读取未初始化指针 | **成立**。并查明根因：**上游 4.9.y 补丁 `310014f572a5` 自身写错了顺序**，本仓库 clean 方式原样应用，忠实复现上游缺陷，非流水线引入。同样因 `CONFIG_TIPC is not set` 而未影响当前构建产物 | ✅ **已修**（`45d025711`）：恢复「赋值先于使用」。因 TIPC 未启用无法编译验证，改用代码审查验证——`hdr` 在第 21 行赋值、第 22 行及后续所有使用点均在其后 |

**本轮暴露出一个更重要的方法论问题**：先前用于排查"缺失符号"的全树索引**把补丁自己新增的代码也算进了索引**，导致自引用掩盖了真正的缺失符号（`cfserl_release` 就是这样漏掉的）。

→ 已改用**基线树 `bd7e6f9de`** 作为比对基准重扫 269 个候选符号。重扫结果：真正「基线无、补丁也未定义」的符号仅 **`cfserl_release`** 1 个（`kref_read` 已修；`skb_gro_receive_list` / `tcp_clone_payload` 经查仅出现在本文档与补丁归档的**说明文字**中，属误报）。

**遗留的验证盲区（如实声明）**：编译器只能验证**已启用**的子系统。本次两个真实缺陷都恰好落在**未编译**的子系统（CAIF、TIPC）里，因此"构建成功"对它们没有任何证明力。这类缺陷只有靠人工/独立审阅发现，或靠**启用对应子系统后的编译**发现。
