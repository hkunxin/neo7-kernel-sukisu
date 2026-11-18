#!/usr/bin/env python3
"""预处理 OPLUS 公开源码树：注释掉指向「未公开私有目录」的引用。

OPLUS 把部分私有目录（drivers/soc/oplus/oplus_resctrl、kernel/oplus_cpu 等）
在公开仓库里做成 symlink，指向未发布的路径。GitHub 的 zip 归档把它们落成
普通文件，于是：
  - kconfig 直接失败：can't open file ".../oplus_resctrl/Kconfig"
  - make 找不到 obj-y 引用的目录

处理方式：把引用行改成注释（保留原文，便于审计到底缺了什么），不创建假目录。
  - Kconfig:  source "x/Kconfig"  →  # source "x/Kconfig"  # [prepare] missing upstream
  - Makefile:  obj-* += x/        →  # obj-* += x/  # [prepare] missing upstream
"""
import os
import re
import sys

src = os.path.abspath(sys.argv[1])
changes = []


def read(path):
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as fh:
        fh.write(text)


# ---------------------------------------------------------------- Kconfig
SRC_RE = re.compile(r'^(\s*)source\s+"([^"$]+)"\s*$', re.M)

for root, _dirs, files in os.walk(src):
    if os.sep + ".git" in root:
        continue
    for f in files:
        if not (f == "Kconfig" or f.startswith("Kconfig.") or f == "Kconfig.ext"):
            continue
        path = os.path.join(root, f)
        try:
            text = read(path)
        except OSError:
            continue
        if 'source "' not in text:
            continue

        def repl(m):
            indent, rel = m.group(1), m.group(2)
            if rel.startswith("/"):
                target = os.path.normpath(rel)
            else:
                target = os.path.normpath(os.path.join(src, rel))
            sibling = os.path.normpath(os.path.join(root, rel))
            # 内核里 source 基本相对 srctree，少数相对自身目录，两者存在即正常
            if os.path.exists(target) or os.path.exists(sibling):
                return m.group(0)
            changes.append(("Kconfig", os.path.relpath(path, src), rel))
            return f'{indent}# source "{rel}"   # [prepare] missing upstream'

        new = SRC_RE.sub(repl, text)
        if new != text:
            write(path, new)

# ---------------------------------------------------------------- Makefile
OBJ_RE = re.compile(r'^(\s*)(obj-[^\s]*\s*\+=\s*)([\w./-]+)/\s*$', re.M)

for root, _dirs, files in os.walk(src):
    if os.sep + ".git" in root:
        continue
    if "Makefile" not in files:
        continue
    path = os.path.join(root, "Makefile")
    try:
        text = read(path)
    except OSError:
        continue

    def repl2(m):
        indent, prefix, d = m.group(1), m.group(2), m.group(3)
        full = os.path.normpath(os.path.join(root, d))
        if os.path.isdir(full):
            return m.group(0)
        changes.append(("Makefile", os.path.relpath(path, src), d + "/"))
        return f"{indent}# {prefix}{d}/   # [prepare] missing upstream"

    new = OBJ_RE.sub(repl2, text)
    if new != text:
        write(path, new)

print(f"[prepare] 注释掉 {len(changes)} 处指向未公开目录的引用")
for kind, where, what in changes[:40]:
    print(f"  - [{kind}] {where}: {what}")
if len(changes) > 40:
    print(f"  ... 其余 {len(changes) - 40} 处略")
