#!/usr/bin/env bash
# 054 内核编译流水线（GitHub Actions 与 WSL/Linux 通用）
#
# 目标：产出与官方 6.1.157-android14-11-o-g7335883bfebb 同 vermagic 的 Image
# 用法：
#   KSU=none   ./scripts/build.sh          # 任务 3：最小构建（无补丁）
#   KSU=sukisu ./scripts/build.sh          # 任务 4：内建 SukiSU
#   KSU=sukisu SUSFS=1 ./scripts/build.sh  # 任务 5：叠加 SUSFS
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${WORK:-$ROOT/work}"
SRC="$WORK/common"
OUT="$SRC/out"
DIST="$ROOT/dist"
JOBS="${JOBS:-$(nproc)}"

KSU="${KSU:-none}"                       # none | sukisu
SUSFS="${SUSFS:-0}"                      # 0 | 1
PERF="${PERF:-0}"                        # 0 | 1 性能向（关调试开销 + BBR + -O3）
KSU_REPO="${KSU_REPO:-SukiSU-Ultra/SukiSU-Ultra}"
KSU_REF="${KSU_REF:-builtin}"
SUSFS_REPO="${SUSFS_REPO:-https://gitlab.com/simonpunk/susfs4ksu}"
SUSFS_REF="${SUSFS_REF:-gki-android14-6.1}"
KERNEL_REPO="${KERNEL_REPO:-OnePlusOSS/android_kernel_oneplus_mt6989}"
KERNEL_COMMIT="${KERNEL_COMMIT:-822beed40827f1e9a103bc06ab4714a670080b72}"
CONFIG_IN="${CONFIG_IN:-$ROOT/config/base_6.1.157.config}"

# 与 vendor_dlkm 模块的 vermagic 逐字一致，改这里等于让 270+ 个模块全部加载失败
EXPECTED_RELEASE="${EXPECTED_RELEASE:-6.1.157-android14-11-o-g7335883bfebb}"

log() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[FAIL] %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 1. 源码
fetch_source() {
  log "拉取内核源码 $KERNEL_REPO@${KERNEL_COMMIT:0:12}"
  if [[ -f "$SRC/Makefile" ]]; then
    echo "已存在，跳过"
    return
  fi
  mkdir -p "$WORK"
  local zip="$WORK/kernel-${KERNEL_COMMIT:0:12}.zip"
  if [[ ! -s "$zip" ]]; then
    curl -fL -sS --retry 5 --retry-delay 5 -o "$zip" \
      "https://codeload.github.com/${KERNEL_REPO}/zip/${KERNEL_COMMIT}" \
      || die "源码下载失败"
  fi
  echo "源码包：$(du -h "$zip" | cut -f1)"
  unzip -q "$zip" -d "$WORK/.src"
  local d
  d="$(find "$WORK/.src" -maxdepth 1 -mindepth 1 -type d | head -n1)"
  mv "$d" "$SRC"
  rm -rf "$WORK/.src"
  echo "源码版本：$(sed -n 's/^VERSION = //p;s/^PATCHLEVEL = //p;s/^SUBLEVEL = //p' "$SRC/Makefile" | paste -sd.)"
}

# ---------------------------------------------------------------- 2. 配置
apply_config() {
  log "预处理源码树（补悬空 Kconfig/Makefile 引用）"
  python3 "$ROOT/scripts/prepare_tree.py" "$SRC"

  log "应用配置基线（$(basename "$CONFIG_IN")，$(wc -l < "$CONFIG_IN") 行）"
  cp "$CONFIG_IN" "$SRC/arch/arm64/configs/neo7_defconfig"
  make -C "$SRC" O="$OUT" ARCH=arm64 LLVM=1 neo7_defconfig >/dev/null

  # 钉死 UTS_RELEASE。
  # 原厂 CONFIG_LOCALVERSION 为空，后缀由 OPLUS 改造过的 scripts/setlocalversion
  # 拼出来（-android14-11 + -g<hash>）；换源后哈希必然不同，而且这个脚本在
  # Actions 里会因为外层 git 仓库误判而多出 "-" / "+"。这里直接把它替换成
  # 固定输出，保证与 vendor_dlkm 模块的 vermagic 逐字一致。
  "$SRC/scripts/config" --file "$OUT/.config" --set-str LOCALVERSION ""
  "$SRC/scripts/config" --file "$OUT/.config" --disable LOCALVERSION_AUTO
  cat > "$SRC/scripts/setlocalversion" <<'EOS'
#!/bin/sh
# [054] 固定版本串：必须与 vendor_dlkm 模块 vermagic 完全一致。
# 注意：OPLUS 的 Makefile 会在版本号后自己补一个 "-"，这里不能再带前导连字符，
# 否则会得到 "6.1.157--android14-11-..."。
echo "${LOCALVERSION_FORCE#-}"
EOS
  chmod +x "$SRC/scripts/setlocalversion"
  export LOCALVERSION_FORCE="-${EXPECTED_RELEASE#6.1.157}"

  # 原厂 config 指向 certs/mtk_signing_key.pem（MTK 私有签名密钥，未随源码发布），
  # 改回内核自带的自动生成密钥；MODULE_SIG_ALL 未开，不会真的签任何模块。
  "$SRC/scripts/config" --file "$OUT/.config" \
    --set-str MODULE_SIG_KEY "certs/signing_key.pem"

  make -C "$SRC" O="$OUT" ARCH=arm64 LLVM=1 olddefconfig >/dev/null

  # 记录「这颗内核比原厂少了哪些配置项」——换源后能不能开机的核心判据
  mkdir -p "$DIST"
  python3 "$ROOT/scripts/config_diff.py" "$CONFIG_IN" "$OUT/.config" "$DIST/config.diff.txt"

  # vermagic 依赖这几项，缺一不可
  for k in CONFIG_PREEMPT=y CONFIG_MODULE_UNLOAD=y CONFIG_MODVERSIONS=y CONFIG_ARM64=y; do
    grep -qx "$k" "$OUT/.config" || die "config 缺少 $k，vermagic 会与官方不一致"
  done
  echo "kernel.release = $(cat "$OUT/include/config/kernel.release" 2>/dev/null || true)"
}

# ---------------------------------------------------------------- 3. root 与隐藏
apply_sukisu() {
  [[ "$KSU" == "sukisu" ]] || return 0
  log "集成 SukiSU（$KSU_REPO@$KSU_REF）"
  local zip="$WORK/ksu-${KSU_REF}.zip"
  [[ -s "$zip" ]] || curl -fL --retry 5 -o "$zip" \
    "https://codeload.github.com/${KSU_REPO}/zip/${KSU_REF}"
  rm -rf "$WORK/.ksu"
  unzip -q "$zip" -d "$WORK/.ksu"
  rm -rf "$SRC/KernelSU"
  mv "$(find "$WORK/.ksu" -maxdepth 1 -mindepth 1 -type d | head -n1)" "$SRC/KernelSU"
  rm -rf "$WORK/.ksu"

  ln -sfn ../KernelSU/kernel "$SRC/drivers/kernelsu"   # 相对 drivers/ -> $SRC/KernelSU
  grep -q "obj-\$(CONFIG_KSU) += kernelsu/" "$SRC/drivers/Makefile" \
    || echo 'obj-$(CONFIG_KSU) += kernelsu/' >> "$SRC/drivers/Makefile"
  grep -q 'drivers/kernelsu/Kconfig' "$SRC/drivers/Kconfig" \
    || sed -i '$i source "drivers/kernelsu/Kconfig"' "$SRC/drivers/Kconfig"
  echo "KernelSU 提交：$(cd "$SRC/KernelSU" && git rev-parse HEAD 2>/dev/null || echo "$KSU_REF")"
}

apply_susfs() {
  [[ "$SUSFS" == "1" ]] || return 0
  log "叠加 SUSFS（$SUSFS_REPO $SUSFS_REF）"
  if [[ ! -d "$WORK/susfs4ksu" ]]; then
    git clone -q --depth=1 -b "$SUSFS_REF" "$SUSFS_REPO" "$WORK/susfs4ksu" || die "susfs 克隆失败"
  fi
  local p="$WORK/susfs4ksu/kernel_patches"
  local patch="$p/50_add_susfs_in_${SUSFS_REF}.patch"
  [[ -f "$patch" ]] || die "找不到 SUSFS 内核补丁：$patch"

  cp "$p"/fs/* "$SRC/fs/"
  cp "$p"/include/linux/* "$SRC/include/linux/"

  # SukiSU-Nova 的 Kconfig 已不含 CONFIG_KSU_SUSFS，先补一个最小开关，
  # 否则 fs/Makefile 里的 obj-$(CONFIG_KSU_SUSFS) 永远不生效。
  if ! grep -q "config KSU_SUSFS$" "$SRC/KernelSU/kernel/Kconfig" 2>/dev/null; then
    cat "$ROOT/config/susfs_kconfig.fragment" >> "$SRC/KernelSU/kernel/Kconfig"
    echo "已注入 CONFIG_KSU_SUSFS 开关"
  fi

  # 主补丁：OPLUS 树上有且仅有一个 hunk（namespace.c 的 include 块）必然失败，
  # 因为它的后置上下文里有本树不存在的 <trace/hooks/blk.h>，用 -F3 也不能消除。
  # 这里允许它失败，但必须严格断言「只失败这一个」，其他任何 reject 都算硬错误。
  log "应用 SUSFS 主补丁（-F3，允许 namespace.c 的 include hunk 失败）"
  set +e
  ( cd "$SRC" && patch -p1 -F3 --forward --no-backup-if-mismatch < "$patch" ) \
    | tee "$WORK/susfs-patch.log"
  local prc=${PIPESTATUS[0]}
  set -e
  local rej
  rej=$(find "$SRC" -name '*.rej' | sed "s|^$SRC/||" | sort | tr '\n' ' ')
  if [[ "$rej" != "fs/namespace.c.rej " ]]; then
    die "SUSFS 补丁失败范围超出预期（rejected: ${rej:-无}），检查 $WORK/susfs-patch.log"
  fi
  echo "预期内失败：fs/namespace.c（include 块），改用 fixup 重放"
  find "$SRC" -name '*.rej' -delete
  find "$SRC" -name '*.orig' -delete

  ( cd "$SRC" && patch -p1 -F3 --forward --no-backup-if-mismatch \
      < "$ROOT/patches/susfs_namespace_fixup.patch" ) \
    || die "namespace.c fixup 应用失败"
  grep -q "CL_COPY_MNT_NS" "$SRC/fs/namespace.c" || die "fixup 未生效"
  find "$SRC" -name '*.rej' -delete
  echo "[OK] namespace.c include 块已用 fixup 补齐（patch 退出码 $prc）"

  # 注意：builtin 分支的 kernel/selinux/selinux.c 已提供 susfs_is_current_ksu_domain()，
  # kernel/{feature/sucompat.c,runtime/ksud.c,preinit/preinit.c,supercall/*} 提供
  # ksu_handle_* 全套钩子，因此这里不能再放兼容层，否则符号重复定义。
  echo "SUSFS 提交：$(cd "$WORK/susfs4ksu" && git rev-parse --short HEAD)"
}

# ------------------------------------------------------- 3.5 root/隐藏配置
apply_root_config() {
  [[ "$KSU" != "none" || "$SUSFS" == "1" ]] || return 0
  log "写入 KSU/SUSFS 配置并重新归一化"
  [[ "$KSU" != "none" ]] && cat "$ROOT/config/sukisu.fragment" >> "$OUT/.config"
  [[ "$SUSFS" == "1" ]] && cat "$ROOT/config/susfs.fragment" >> "$OUT/.config"
  make -C "$SRC" O="$OUT" ARCH=arm64 LLVM=1 olddefconfig >/dev/null

  for k in CONFIG_PREEMPT=y CONFIG_MODULE_UNLOAD=y CONFIG_MODVERSIONS=y CONFIG_ARM64=y; do
    grep -qx "$k" "$OUT/.config" || die "config 缺少 $k，vermagic 会与官方不一致"
  done
  [[ "$KSU" == "none" ]] || grep -qx "CONFIG_KSU=y" "$OUT/.config" \
    || die "CONFIG_KSU 未生效，Kconfig 注入或 drivers/kernelsu 软链有问题"
  if [[ "$SUSFS" == "1" ]]; then
    grep -qx "CONFIG_KSU_SUSFS=y" "$OUT/.config" || die "CONFIG_KSU_SUSFS 未生效"
  fi
  echo "[OK] KSU=$(grep -c '^CONFIG_KSU=y' "$OUT/.config") SUSFS=$(grep -c '^CONFIG_KSU_SUSFS=y' "$OUT/.config")"
}

# ------------------------------------------------------- 3.6 性能向配置
apply_perf() {
  [[ "$PERF" == "1" ]] || return 0
  log "追加性能向配置（config/perf.fragment）"
  cat "$ROOT/config/perf.fragment" >> "$OUT/.config"
  make -C "$SRC" O="$OUT" ARCH=arm64 LLVM=1 olddefconfig >/dev/null

  grep -qx "CONFIG_KASAN=y" "$OUT/.config" && die "KASAN 未关掉"
  grep -qx "CONFIG_SLUB_DEBUG=y" "$OUT/.config" && die "SLUB_DEBUG 未关掉"
  grep -qx "CONFIG_INIT_ON_ALLOC_DEFAULT_ON=y" "$OUT/.config" && die "INIT_ON_ALLOC 未关掉"
  grep -qx 'CONFIG_DEFAULT_TCP_CONG="bbr"' "$OUT/.config" || die "BBR 未生效"
  cp "$OUT/.config" "$DIST/config.used"
  echo "[OK] perf: KASAN/SLUB_DEBUG/DEBUG_LIST/SCHEDSTATS 关闭，BBR 默认"
}

# ---------------------------------------------------------------- 4. 编译
build_kernel() {
  log "编译 Image（-j$JOBS）"
  local t0; t0=$(date +%s)
  local opt=""
  [[ "$PERF" == "1" ]] && opt=" -O3"
  make -C "$SRC" O="$OUT" ARCH=arm64 LLVM=1 -j"$JOBS" \
    KCFLAGS="-Wno-error${opt}" Image
  echo "编译耗时：$(( $(date +%s) - t0 )) 秒"
}

# ---------------------------------------------------------------- 5. 验收
verify() {
  log "验收"
  local rel; rel="$(cat "$OUT/include/config/kernel.release")"
  [[ "$rel" == "$EXPECTED_RELEASE" ]] \
    || die "UTS_RELEASE 不符：期望 $EXPECTED_RELEASE，实际 $rel"
  echo "[OK] kernel.release = $rel"

  grep -aq "Linux version $EXPECTED_RELEASE" "$OUT/vmlinux" \
    || die "vmlinux 内未找到期望的版本串"
  echo "[OK] vmlinux 内含 'Linux version $EXPECTED_RELEASE'"

  if [[ "$KSU" != "none" ]]; then
    if strings -a "$OUT/vmlinux" | grep -q "kernelsu"; then
      echo "[OK] vmlinux 已编入 kernelsu 符号（内建，非模块）"
    else
      die "未能在 vmlinux 中找到 kernelsu 符号，KSU 可能没编进去"
    fi
  fi

  if [[ "$SUSFS" == "1" ]]; then
    strings -a "$OUT/vmlinux" | grep -q "susfs" \
      || die "vmlinux 中找不到 susfs 符号"
    echo "[OK] vmlinux 内已含 susfs"
  fi

  mkdir -p "$DIST"
  cp "$OUT/arch/arm64/boot/Image" "$DIST/Image"
  cp "$OUT/.config" "$DIST/config.used"
  echo "[OK] Image 大小：$(du -h "$DIST/Image" | cut -f1)"
}

fetch_source
apply_config
apply_sukisu
apply_susfs
apply_root_config
apply_perf
build_kernel
verify
log "完成：$DIST"
