// SPDX-License-Identifier: GPL-2.0
/*
 * SUSFS ↔ SukiSU 兼容层
 *
 * susfs4ksu 的 6.1 补丁是按「官方 KernelSU + 10_enable_susfs_for_ksu.patch」写的，
 * 该补丁在 SukiSU v3.0.0（Nova）上完全无法应用。但补丁本身在 fs/open.c、
 * fs/read_write.c、kernel/reboot.c 里引用了几个 KernelSU 侧符号，Nova 已重命名或
 * 移除，于是链接期报 undefined。这里统一补齐：
 *
 *   - susfs_is_current_ksu_domain()：桥到 Nova 的 is_ksu_domain()
 *   - ksu_is_init_rc_hook_enabled / ksu_handle_sys_read / ksu_handle_faccessat /
 *     ksu_handle_sys_reboot：KernelSU 用来在 syscall 层拦截 su / init.rc 的钩子。
 *     SukiSU 有自己的 sucompat 实现，这几个置空不影响 root 与隐藏，
 *     只是少了一层「KSU 自己拦截自己的 su 路径」的优化。
 */
#include <linux/types.h>
#include <linux/fs.h>
#include <linux/jump_label.h>

extern bool is_ksu_domain(void);

bool susfs_is_current_ksu_domain(void)
{
	return is_ksu_domain();
}

/* 静态键置 false：static_branch_unlikely() 恒不成立，相关分支不会被编译进快路径 */
struct static_key_true ksu_is_init_rc_hook_enabled = STATIC_KEY_INIT_FALSE;

void ksu_handle_sys_read(unsigned int fd)
{
	(void)fd;
}

int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode,
			 int *__unused_flags)
{
	(void)dfd;
	(void)filename;
	(void)mode;
	(void)__unused_flags;
	return 0;
}

int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg)
{
	(void)magic1;
	(void)magic2;
	(void)cmd;
	(void)arg;
	return 0;	/* 0 = 未接管，走正常 reboot 流程 */
}
