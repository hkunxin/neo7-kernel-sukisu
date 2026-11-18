#!/usr/bin/env python3
"""预处理 OPLUS 公开源码树：补齐「悬空引用」。

OPLUS 把部分私有目录（如 drivers/soc/oplus/oplus_resctrl）在公开仓库里做成
symlink，指向未发布的路径。GitHub 的 zip 归档把它落成普通文件、目标不存在，
于是 kconfig 一上来就 `can't open file`。

做法：扫描所有 Kconfig 的 source 指令与 Makefile 的 obj += dir/ 引用，
目标不存在的按最小可编译桩补齐，并打印清单（便于审计到底缺了什么）。
"""
import os
import re
import sys

src = sys.argv[1]
stubs = []
skipped = []


def safe_mkdir_and_write(target, content):
    """父路径可能是「symlink 被 zip 落成普通文件」的残骸，失败就跳过而不是崩。"""
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isdir(target):
            return False
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return True
    except OSError as exc:
        skipped.append((target, exc))
        return False


# 1. Kconfig: source "xxx/Kconfig"
for root, _dirs, files in os.walk(src):
    if "/.git" in root.replace(os.sep, "/"):
        continue
    for f in files:
        if not (f == "Kconfig" or f.startswith("Kconfig.") or f == "Kconfig.ext"):
            continue
        path = os.path.join(root, f)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in re.finditer(r'^\s*source\s+"([^"$]+)"', text, re.M):
            rel = m.group(1)
            target = os.path.normpath(os.path.join(root, rel))
            if os.path.exists(target):
                continue
            if safe_mkdir_and_write(target, f"# stub for unpublished OPLUS source: {rel}\n"):
                stubs.append(("Kconfig", os.path.relpath(target, src)))

# 2. Makefile: obj-y += some/dir/ 且该目录不存在
for root, _dirs, files in os.walk(src):
    if "/.git" in root.replace(os.sep, "/"):
        continue
    if "Makefile" not in files:
        continue
    path = os.path.join(root, "Makefile")
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
        for m in re.finditer(r'^\s*obj-[^\s]*\s*\+=\s*([\w./-]+)/\s*$', text, re.M):
            d = os.path.normpath(os.path.join(root, m.group(1)))
            if os.path.exists(d):
                continue
            if safe_mkdir_and_write(
                    os.path.join(d, "Makefile"),
                    f"# stub for unpublished OPLUS dir: {m.group(1)}\n"):
                stubs.append(("Makefile", os.path.relpath(d, src)))

if stubs:
    print(f"[prepare] 补齐 {len(stubs)} 处悬空引用：")
    for kind, p in stubs:
        print(f"  - [{kind}] {p}")
else:
    print("[prepare] 无需补齐，树是完整的")

if skipped:
    print(f"[prepare] 跳过 {len(skipped)} 处（父路径被 symlink 残骸占用，非致命）：")
    for target, exc in skipped[:20]:
        print(f"  - {target}: {exc}")
