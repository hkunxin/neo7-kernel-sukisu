#!/usr/bin/env bash
# 把 dist/Image 打包成可直接 fastboot 刷入的 boot.img，外加一份 AnyKernel3 zip
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
WORK="$ROOT/work"
RELEASE="${EXPECTED_RELEASE:-6.1.157-android14-11-o-g7335883bfebb}"
MAGISKBOOT_URL="${MAGISKBOOT_URL:-https://github.com/WildKernels/magiskboot/releases/download/nightly/magiskboot-x86_64}"
AK3_URL="${AK3_URL:-https://codeload.github.com/Osm0sis/AnyKernel3/zip/refs/heads/master}"
BOOT_MAX=67108864

log() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[FAIL] %s\033[0m\n' "$*" >&2; exit 1; }

[[ -f "$DIST/Image" ]] || die "dist/Image 不存在，先跑 build.sh"

log "准备原厂 boot.img"
STOCK="$WORK/boot_stock.img"
mkdir -p "$WORK"
if [[ ! -f "$STOCK" ]]; then
  gunzip -c "$ROOT/assets/boot_stock.img.gz" > "$STOCK"
fi
echo "原厂 boot.img sha256: $(sha256sum "$STOCK" | cut -d' ' -f1)"

log "取 magiskboot"
MB="$WORK/magiskboot"
if [[ ! -x "$MB" ]]; then
  curl -fL --retry 5 -o "$MB" "$MAGISKBOOT_URL"
  chmod +x "$MB"
fi
"$MB" | head -n1 || true

log "替换内核并重打包 boot.img"
RB="$WORK/bootrepack"
rm -rf "$RB"; mkdir -p "$RB"
cp "$STOCK" "$RB/boot.img"
(
  cd "$RB"
  "$MB" unpack boot.img >/dev/null
  # magiskboot 会按原镜像的压缩格式（此处 lz4 legacy）重新压缩我们塞进去的 Image
  cp "$DIST/Image" kernel
  "$MB" repack boot.img
)
[[ -f "$RB/new-boot.img" ]] || die "repack 未产出 new-boot.img"

# [054] 往 boot 头里塞 cmdline：把早期 initcall 与 printk 全部说出来，
# 失败时 panic 写进 ramoops 的 dmesg 才能看到死在哪一步。
python3 - "$RB/new-boot.img" <<'EOPY'
import sys
p = sys.argv[1]
cmd = b"loglevel=8 ignore_loglevel initcall_debug printk.devkmsg=on"
d = bytearray(open(p, "rb").read())
assert d[:8] == b"ANDROID!", "not a boot image"
assert len(cmd) < 1536
d[44:44 + 1536] = cmd.ljust(1536, b"\x00")
open(p, "wb").write(d)
print("[package] cmdline 注入:", cmd.decode())
EOPY
cp "$RB/new-boot.img" "$DIST/boot-${RELEASE}.img"

sz=$(stat -c %s "$DIST/boot-${RELEASE}.img")
echo "新 boot.img 大小：$sz"
(( sz <= BOOT_MAX )) || die "boot.img 超过 ${BOOT_MAX} 字节，AK3/分区放不下"

log "打包 AnyKernel3"
AK="$WORK/ak3"
if [[ ! -d "$AK" ]]; then
  curl -fL --retry 5 -o "$WORK/ak3.zip" "$AK3_URL"
  rm -rf "$WORK/.ak3"; unzip -q "$WORK/ak3.zip" -d "$WORK/.ak3"
  mv "$(find "$WORK/.ak3" -maxdepth 1 -mindepth 1 -type d | head -n1)" "$AK"
  rm -rf "$WORK/.ak3"
fi
cp "$DIST/Image" "$AK/Image"
rm -f "$AK/zImage" "$AK/Image.gz" "$AK/Image.lz4" 2>/dev/null || true
# 本机没有第三方 recovery，AK3 只作为「有 root 时可从管理器直接刷」的备用形态
sed -i 's/^kernel.string=.*/kernel.string=SukiSU builtin + SUSFS ('"$RELEASE"')/' "$AK/anykernel.sh" || true
sed -i 's/^do.devicecheck=1/do.devicecheck=0/' "$AK/anykernel.sh" || true
sed -i 's/^BLOCK=.*/BLOCK=boot/' "$AK/anykernel.sh" || true
( cd "$AK" && rm -f "$DIST/AnyKernel3-${RELEASE}.zip" \
  && zip -q -r9 "$DIST/AnyKernel3-${RELEASE}.zip" . -x '*.git*' )

log "校验与摘要"
( cd "$DIST" && sha256sum Image boot-*.img AnyKernel3-*.zip > SHA256SUMS.txt && cat SHA256SUMS.txt )
