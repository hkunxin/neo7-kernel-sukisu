# realme Neo7 内核构建（SukiSU 内建 + SUSFS）

给 **RMX5060 / realme Neo7 / MT6989** 编一颗自带 root、且在 `/proc/modules` 里看不到 `kernelsu` 的内核。

对应 spec：`E:\znzl\specs\054-内核编译-SukiSU与SUSFS`。

## 结论先放这里（为什么这么选）

| 问题 | 结论 | 证据 |
|---|---|---|
| 用哪套源码 | `OnePlusOSS/android_kernel_oneplus_mt6989` @ `822beed`（6.1.157，KMI `android14-6.1-11`） | realme 官方 AndroidB 树仍是 6.1.134，与设备 6.1.157 差 23 个小版本；同平台社区已有 RMX5060 实测开机记录 |
| 版本串怎么对齐 | 用 `CONFIG_LOCALVERSION` 把 `UTS_RELEASE` **逐字钉死** | `vendor_dlkm.img` 内 282 处 vermagic 全为 `6.1.157-android14-11-o-g7335883bfebb SMP preempt mod_unload modversions aarch64`，哈希不同则 270+ 个 vendor 模块全部加载失败 |
| defconfig 用哪套 | 本机 105 固件 `boot.img` 里 IKCONFIG 提取的完整 config（9140 行） | 见 `config/rmx5060_105_stock.config` |
| root 方案 | SukiSU Ultra v3.0.0（Nova）内建 | 手机现有内核模块版本串为 `v4.3.0-r1-0a4c3132@release`，同源 |

## 流水线

```
GitHub Actions (ubuntu-24.04)
  ├─ 1. codeload 拉内核源码 zip（固定 commit）
  ├─ 2. Clang 20 r547379 + build-tools
  ├─ 3. 套用本机原厂 config → 钉 localversion → 追加 KSU/SUSFS 开关
  ├─ 4. 链接 KernelSU 到 drivers/kernelsu（CONFIG_KSU=y）
  ├─ 5. 打 SUSFS 内核补丁 + 一行 KSU 桥接
  ├─ 6. make Image
  └─ 7. 验收版本串 / 符号 → 用原厂 boot.img 重打包 → artifact
```

`scripts/build.sh` 与 `scripts/package.sh` 在本地 WSL 也能直接跑。

## 用法

Actions → build-kernel → Run workflow：

| 参数 | 说明 |
|---|---|
| `ksu` | `none` 只验证工具链与配置；`sukisu` 内建 root |
| `susfs` | `1` 叠加 SUSFS；`0` 只编 root |
| `kernel_commit` | 默认 `822beed...`，改源码基线时才动 |
| `ksu_ref` / `susfs_ref` | 升级依赖时固定到具体 tag/commit |

产物 `kernel-<ksu>-susfs<0|1>`：

- `boot-6.1.157-...img` —— **主刷入件**，原厂 boot 换内核重打包，`fastboot flash boot`
- `Image` —— 裸内核，给 AK3 / 其他工具用
- `AnyKernel3-*.zip` —— 有 root 时从管理器刷的备用形态
- `SHA256SUMS.txt` / `config.used` / 日志

## 刷入与回滚

刷入（成对，缺一不可）：

```
fastboot flash boot     dist\boot-6.1.157-android14-11-o-g7335883bfebb.img
fastboot flash init_boot _analysis\img\init_boot.img     # 必须回原厂，否则两套 KSU 抢同一入口
```

回滚：`rollback\回滚内核.bat`（先校验备份 sha256，再刷回 boot + init_boot）。

备份基准（`E:\neo7\_analysis\img`）：

```
boot.img      281aaa520d9008a1f82da7ee0a3fb0d546f27b05c39e285796015d98f2665b48
init_boot.img a0a95ce9f2f26b2bc63f1aea81a112c4a62259c3d0aaa7a2504a1c8c9c59d188
```

## 已知风险

1. **源码基线比固件旧一个月**：822beed 对应一加 PLF110 16.0.9.402，本机是 realme 17.0.0.105。同平台同 KMI，但 vendor 模块的符号 CRC 是否完全一致只能靠真机验证。
2. **SukiSU Nova 去掉了 CONFIG_KSU_SUSFS**：官方 KernelSU 的 `10_enable_susfs_for_ksu.patch` 无法应用，本仓库用 `config/susfs_kconfig.fragment` + `patches/susfs_ksu_compat.c` 做最小补齐；SUSFS 的「KSU 自隐藏」部分能力会弱于 KernelSU-Next 方案。
3. **AVB 失效**：换内核后 boot 的 vbmeta 签名必然失效，依赖 bootloader 已解锁（橙灯状态）。
4. 首次成功前不要刷；每次产物都有 sha256，可与上一次对比。

## 变更记录

- 2026-11-18 建库：锁定 6.1.157 基线、钉死 UTS_RELEASE、原厂 config 入库、最小构建流水线。
