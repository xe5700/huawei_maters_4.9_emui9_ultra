# t7 疑难复核结论（最终质量门）

**Verdict: PASS（round 1，零 findings）** — 复核人 longcat，详版报告见 REVIEW_T7.md。

## 四项抽查结果

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| a | defconfig 24 项防 root 全部 not set | ✅ | commit 3124fc400 移除；当前精确词边界检查 `=y` 计数 0；`# CONFIG_DM_VERITY is not set`（1673 行）下 FEC/HW_RETRY/HASH_PREFETCH 为惰性子选项不生效（与 9.0 参考一致的原厂行为） |
| b | hooks.c is_ksu_transition extern+调用与 9.0 一致 | ✅ | `grep -c is_ksu_transition` = 2；两行与 9.0 参考逐字节一致（diff 空）；定义在 KernelSU/kernel/selinux/selinux.c:36（≤4.19 守卫命中 4.9.148），签名匹配 |
| c | namespace.c path_umount 回移存在 | ✅ | `grep -c path_umount` = 1（1716 行，非 static）；函数体 34 行与 9.0 参考逐字节一致；被 KernelSU kernel_umount.c 经 KSU_HAS_PATH_UMOUNT 自动探测消费 |
| d | KernelSU Kconfig 支持 CONFIG_KSU_MANUAL_HOOK | ✅ | KernelSU/kernel/Kconfig:32 `config KSU_MANUAL_HOOK`（choice 内，depends on KSU && KSU != m）；defconfig:6007 已设 y；KPROBES off → SYSCALL_HOOK 不可能 → MANUAL_HOOK 强制解析，无未定义引用场景 |

## 结论

t5 移植（commit cf0608b8a）通过疑难级复核：无华为安全残留拦截、SELinux 域转换钩子正确、CONFIG_KSU 与 4.9.148 编译兼容、path_umount 回移正确。**t9 全量编译放行。**
