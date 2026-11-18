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


def symlink_target(path):
    """zip 把 symlink 落成普通文件，内容就是目标路径；不是残骸则返回 None。"""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > 512:
            return None
        text = read(path).strip()
        if not text or "\n" in text or " " in text or "/" not in text:
            return None
        return text
    except OSError:
        return None


# ---------------------------------------------------------------- 悬空软链
# 例：kernel/locking/locking_main.h -> ../../../vendor/oplus/kernel/synchronize/oplus_locking.h
# 目标不在公开树里。头文件补空桩（很多文件只是 include 一下，并未真正使用），
# 源文件交给下面的 Makefile 规则处理。
for root, _dirs, files in os.walk(src):
    if os.sep + ".git" in root:
        continue
    for f in files:
        path = os.path.join(root, f)
        target = symlink_target(path)
        if target is None:
            continue
        resolved = os.path.normpath(os.path.join(root, target))
        if os.path.exists(resolved):
            continue
        if f.endswith(".h"):
            write(path, f"/* [prepare] stub: upstream symlink to {target} is unpublished */\n")
            changes.append(("stub-header", os.path.relpath(path, src), target))
        else:
            changes.append(("dangling", os.path.relpath(path, src), target))


# ---------------------------------------------------------------- Kconfig
SRC_RE = re.compile(r'^(\s*)source\s+"([^"]+)"\s*$', re.M)

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
            indent, raw = m.group(1), m.group(2)
            # OPLUS 用 $(KCONFIG_EXT_PREFIX) 做前缀，本树里它为空
            rel = raw.replace("$(KCONFIG_EXT_PREFIX)", "").replace("${KCONFIG_EXT_PREFIX}", "")
            if "$" in rel:
                return m.group(0)  # 其它变量路径不动
            if rel.startswith("/"):
                target = os.path.normpath(rel)
            else:
                target = os.path.normpath(os.path.join(src, rel))
            sibling = os.path.normpath(os.path.join(root, rel))
            # source 必须指向真实文件；symlink 残骸（普通文件/空目录）不算
            if os.path.isfile(target) or os.path.isfile(sibling):
                return m.group(0)
            changes.append(("Kconfig", os.path.relpath(path, src), raw))
            return f'{indent}# source "{raw}"   # [prepare] missing upstream'

        new = SRC_RE.sub(repl, text)
        if new != text:
            write(path, new)

# ---------------------------------------------------------------- Makefile
OBJ_DIR_RE = re.compile(r'^(\s*)(obj-[^\s]*\s*\+=\s*)([\w./-]+)/\s*$', re.M)
OBJ_OBJ_RE = re.compile(r'^(\s*)(obj-[^\s]*\s*\+=\s*)([\w./-]+)\.o\s*$', re.M)

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

    def repl3(m):
        indent, prefix, name = m.group(1), m.group(2), m.group(3)
        base = os.path.normpath(os.path.join(root, name))
        # .o 需要同名 .c/.S 存在，否则就是指向未公开源文件的悬空引用
        if any(os.path.isfile(base + ext) for ext in (".c", ".S", ".s")):
            return m.group(0)
        changes.append(("Makefile", os.path.relpath(path, src), name + ".o"))
        return f"{indent}# {prefix}{name}.o   # [prepare] missing upstream"

    new = OBJ_OBJ_RE.sub(repl3, OBJ_DIR_RE.sub(repl2, text))
    if new != text:
        write(path, new)

print(f"[prepare] 注释掉 {len(changes)} 处指向未公开目录的引用")
for kind, where, what in changes[:40]:
    print(f"  - [{kind}] {where}: {what}")
if len(changes) > 40:
    print(f"  ... 其余 {len(changes) - 40} 处略")
