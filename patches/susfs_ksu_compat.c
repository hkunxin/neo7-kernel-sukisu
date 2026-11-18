// SPDX-License-Identifier: GPL-2.0
/*
 * SUSFS ↔ SukiSU 兼容层
 *
 * susfs4ksu 的 susfs.c 依赖 KernelSU 侧提供的 susfs_is_current_ksu_domain()，
 * 官方 KernelSU 由 10_enable_susfs_for_ksu.patch 注入。SukiSU v3.0.0（Nova）
 * 重写后无法套用该补丁，但已经把等价的判定函数导出为 is_ksu_domain()，
 * 这里做一层一行的桥接，避免为了一个布尔判定去改 KSU 源码。
 */
#include <linux/types.h>

extern bool is_ksu_domain(void);

bool susfs_is_current_ksu_domain(void)
{
	return is_ksu_domain();
}
