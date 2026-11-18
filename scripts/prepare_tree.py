#!/usr/bin/env python3
"""预处理 OPLUS 公开源码树：补齐「悬空引用」。

OPLUS 把部分私有目录（如 drivers/soc/oplus/oplus_resctrl）在公开仓库里做成
symlink，指向未发布的路径。GitHub 的 zip 归档把它落成普通文件、目标不存在，
于是 kconfig 一上来就 `can't open file`。

两类引用：
  1. Kconfig 的 `source "x/Kconfig"` —— 路径相对**源码根**（srctree），不是当前文件所在目录
  2. Makefile 的 `obj-* += x/` —— 路径相对**当前 Makefile 所在目录**

目标不存在时补最小桩，并打印清单，方便判断到底少了哪些 OEM 私有组件。
"""
import os
import re
import sys

src = os.path.abspath(sys.argv[1])
stubs = []
skipped = []


def looks_like_symlink_residue(path):
    """zip 把 symlink 落成普通文件，内容就是一串路径。"""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > 512:
            return False
        text = open(path, "rb").read().decode("utf-8", "replace").strip()
        return bool(text) and "\n" not in text and " " not in text
    except OSError:
        return False


def ensure_parent_dir(target):
    """逐级建目录；遇到 symlink 残骸（普通文件）先删掉再建。"""
    parent = os.path.dirname(target)
    parts = []
    p = parent
    while p and p != src and not os.path.exists(p):
        parts.append(p)
        p = os.path.dirname(p)
    if p and p != src and not os.path.isdir(p):
        if looks_like_symlink_residue(p):
            os.remove(p)
        else:
            raise OSError(f"parent exists and is not a dir: {p}")
    for d in reversed(parts):
        if os.path.exists(d) and not os.path.isdir(d):
            if looks_like_symlink_residue(d):
                os.remove(d)
            else:
                raise OSError(f"blocked by non-dir: {d}")
        os.makedirs(d, exist_ok=True)


def stub(target, content):
    try:
        ensure_parent_dir(target)
        if os.path.isdir(target):
            return False
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return True
    except OSError as exc:
        skipped.append((target, exc))
        return False


# 1. Kconfig 的 source（相对 srctree）
for root, _dirs, files in os.walk(src):
    if os.sep + ".git" in root:
        continue
    for f in files:
        if not (f == "Kconfig" or f.startswith("Kconfig.") or f == "Kconfig.ext"):
            continue
        try:
            text = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in re.finditer(r'^\s*source\s+"([^"$]+)"', text, re.M):
            rel = m.group(1)
            if rel.startswith("/"):
                target = os.path.normpath(rel)
            else:
                target = os.path.normpath(os.path.join(src, rel))
            sibling = os.path.normpath(os.path.join(root, rel))
            if not target.startswith(src):
                continue
            # 内核里 source 基本都相对 srctree；少数写法相对自身目录，两者存在即视为正常
            if os.path.exists(target) or os.path.exists(sibling):
                continue
            if stub(target, f"# stub for unpublished OPLUS source: {rel}\n"):
                stubs.append(("Kconfig", os.path.relpath(target, src)))

# 2. Makefile 的 obj-* += dir/（相对当前目录）
for root, _dirs, files in os.walk(src):
    if os.sep + ".git" in root:
        continue
    if "Makefile" not in files:
        continue
    try:
        text = open(os.path.join(root, "Makefile"), encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    for m in re.finditer(r'^\s*obj-[^\s]*\s*\+=\s*([\w./-]+)/\s*$', text, re.M):
        d = os.path.normpath(os.path.join(root, m.group(1)))
        if os.path.exists(d):
            continue
        if stub(os.path.join(d, "Makefile"),
                f"# stub for unpublished OPLUS dir: {m.group(1)}\n"):
            stubs.append(("Makefile", os.path.relpath(d, src)))

print(f"[prepare] 补齐 {len(stubs)} 处悬空引用")
for kind, p in stubs[:40]:
    print(f"  - [{kind}] {p}")
if len(stubs) > 40:
    print(f"  ... 其余 {len(stubs) - 40} 处略")

if skipped:
    print(f"[prepare] 跳过 {len(skipped)} 处（不致命）")
    for target, exc in skipped[:10]:
        print(f"  - {os.path.relpath(target, src)}: {exc}")
