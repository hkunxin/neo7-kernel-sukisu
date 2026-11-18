#!/usr/bin/env python3
"""对比「本机原厂 config」与「实际用于编译的 config」，输出差异清单。

用途：换了源码基线后，olddefconfig 会静默丢弃本树不存在的符号。
被丢掉的项直接等于「这颗内核比原厂少了什么」，是判断能不能开机的主要依据，
必须落成文件进 artifact，而不是埋在日志里。
"""
import sys

def parse(p):
    d = {}
    for line in open(p, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            if line.startswith("# ") and line.endswith(" is not set"):
                d[line[2:].split(" is not set")[0]] = "n"
            continue
        k, _, v = line.partition("=")
        d[k] = v
    return d

stock, used, out = sys.argv[1], sys.argv[2], sys.argv[3]
A, B = parse(stock), parse(used)

missing = sorted(k for k in A if k not in B)
valued = sorted(k for k in A if k in B and A[k] != B[k])

lines = []
lines.append(f"# 原厂 config：{stock}（{len(A)} 项）")
lines.append(f"# 实际 config：{used}（{len(B)} 项）")
lines.append(f"# 本树不存在被丢弃：{len(missing)} 项")
lines.append(f"# 取值发生变化：{len(valued)} 项")
lines.append("")
if missing:
    lines.append("## 被丢弃（本树无此符号）")
    lines += [f"- {k}={A[k]}" for k in missing]
    lines.append("")
if valued:
    lines.append("## 取值变化")
    lines += [f"- {k}: {A[k]} -> {B[k]}" for k in valued]
    lines.append("")

open(out, "w", encoding="utf-8").write("\n".join(lines))
print(f"[config-diff] 丢弃 {len(missing)} 项，变化 {len(valued)} 项 -> {out}")
for k in missing[:15]:
    print(f"  - dropped {k}")
