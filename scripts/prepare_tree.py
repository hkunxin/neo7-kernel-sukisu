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


# ---------------------------------------------------------------- 悬空 include
# OPLUS 把若干头文件做成 symlink 指向 vendor/oplus/...（未公开），zip 归档里
# 有时连残骸都不留，而内核却无条件 include 它们。按显式清单补空桩，可审计、不误伤：
# 这些头只提供 OPLUS 私有锁/调度实现，关掉对应 CONFIG 后内核不引用其中任何符号。
STUB_HEADERS = {
    # kernel/sched/core.c 在 __schedule() 里无条件调用它；原实现只是 OPLUS 的
    # 锁竞争统计，置空不影响调度语义。
    "kernel/locking/locking_main.h": """/* [prepare] stub: 原文件是 symlink 指向 vendor/oplus/kernel/synchronize/oplus_locking.h */
#ifndef _OPLUS_LOCKING_MAIN_STUB_H
#define _OPLUS_LOCKING_MAIN_STUB_H
struct task_struct;
static inline void locking_record_switch_in_cs(struct task_struct *p) { (void)p; }
#endif
""",
    "kernel/locking/sa_common_struct.h": """/* [prepare] stub: 原文件是 symlink 指向未公开的 OPLUS 锁实现 */
#ifndef _OPLUS_SA_COMMON_STRUCT_STUB_H
#define _OPLUS_SA_COMMON_STRUCT_STUB_H
#endif
""",
    "mm/mm-trace.h": """/* [prepare] stub: 原文件是 symlink 指向 vendor/oplus/kernel/mm/mm_osvelte/mm-trace.h
 * OPLUS 的 mm 事件埋点，只做统计上报；这里全部置空，不改变回收/分配语义。
 */
#ifndef _OPLUS_MM_TRACE_STUB_H
#define _OPLUS_MM_TRACE_STUB_H
#define mm_trace_int64(...)     do { } while (0)
#define mm_trace_fmt_begin(...) do { } while (0)
#define mm_trace_fmt_end(...)   do { } while (0)
#endif
""",
}

for rel, content in STUB_HEADERS.items():
    target = os.path.join(src, rel)
    try:
        # 树里可能是「悬空软链接」——isfile/exists 都是 False，但 open 会跟着
        # 链接写到不存在的 vendor 路径上并报 ENOENT，必须先摘掉链接。
        if os.path.islink(target):
            os.remove(target)
        elif os.path.isfile(target) and os.path.getsize(target) > 0:
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        changes.append(("stub-header", rel, "explicit"))
    except OSError as exc:
        changes.append(("stub-failed", rel, str(exc)))

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
# 一行可能挂多个目标（obj-y += a.o b.o c/ d.o），逐个判断，缺的从行里摘掉并
# 追加到注释里，保留原样便于审计。
OBJ_LINE_RE = re.compile(r'^(\s*)(obj-[^\s]*\s*\+=\s*)(\S.*?)\s*$', re.M)

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

    def repl_line(m):
        indent, prefix, body = m.group(1), m.group(2), m.group(3)
        # 多行续行（行尾反斜杠）整段跳过：单独改第一行会把后续续行变成孤儿
        if body.rstrip().endswith("\\") or "\\" in body:
            return m.group(0)
        if "$(" in body:  # 变量展开的列表不动
            return m.group(0)
        keep, dropped = [], []
        for tok in body.split():
            if tok.endswith("/"):
                d = os.path.normpath(os.path.join(root, tok.rstrip("/")))
                ok = os.path.isdir(d)
            elif tok.endswith(".o"):
                base = os.path.normpath(os.path.join(root, tok[:-2]))
                name = tok[:-2]
                ok = any(os.path.isfile(base + ext) for ext in (".c", ".S", ".s"))
                if not ok:
                    # 复合对象（kvm.o 由 kvm-y := ... 拼出来）没有同名 .c，不能删
                    ok = bool(re.search(rf'^{re.escape(name)}(-|\s*[:+]?=)', text, re.M))
            else:
                ok = True
            (keep if ok else dropped).append(tok)
        if not dropped:
            return m.group(0)
        for tok in dropped:
            changes.append(("Makefile", os.path.relpath(path, src), tok))
        if not keep:
            return f"{indent}# {prefix}{' '.join(dropped)}   # [prepare] missing upstream"
        return (f"{indent}{prefix}{' '.join(keep)}"
                f"   # [prepare] dropped: {' '.join(dropped)}")

    new = OBJ_LINE_RE.sub(repl_line, text)
    if new != text:
        write(path, new)

print(f"[prepare] 处理 {len(changes)} 处未公开依赖")
for kind, where, what in changes[:40]:
    print(f"  - [{kind}] {where}: {what}")
if len(changes) > 40:
    print(f"  ... 其余 {len(changes) - 40} 处略")
