"""客观维度：能数出来的一律不问 LLM。

零随机、可复现、零成本。V4 把「字数合规」放在这里，实测证明是对的 ——
LLM 判字数既贵又不准。

本模块的每一项都只做一件事：数出来，跟阈值比。
"""
from __future__ import annotations

import re

from ..types import DimensionScore, Issue, Severity

_CJK = re.compile(r"[一-鿿]")
_CODE_FENCE = re.compile(r"^```", re.M)
_MD_TABLE = re.compile(r"^\|.*\|$", re.M)
_HR = re.compile(r"^\s*([-*_])\s*\1\s*\1[\s\-*_]*$", re.M)


def cjk_count(text: str) -> int:
    return len(_CJK.findall(text or ""))


def score_length(text: str, floor: int, target: int, full: float = 10.0) -> DimensionScore:
    """字数。达到 floor 得满分的 70%，达到 target 得满分。

    ⚠️ 阈值该由 spec 传进来，不写死在这里 —— 报错文和小说章节的合理长度差一个量级，
       而「继承一个不适用的字数下限」正是让模型注水或编造的常见起因。
    """
    n = cjk_count(text)
    if n >= target:
        s = full
    elif n >= floor:
        s = full * (0.7 + 0.3 * (n - floor) / max(target - floor, 1))
    else:
        s = full * 0.7 * n / max(floor, 1)
    return DimensionScore("字数", round(s, 1), full, objective=True,
                          evidence=f"{n} 字（下限 {floor} / 目标 {target}）")


def score_code_blocks(text: str, need: int, full: float = 10.0) -> DimensionScore:
    n = len(_CODE_FENCE.findall(text or "")) // 2
    s = full if n >= need else full * n / max(need, 1)
    return DimensionScore("代码块", round(s, 1), full, objective=True,
                          evidence=f"{n} 处（需 ≥{need}）")


def score_symbols(text: str, symbols: list[str], full: float = 10.0) -> DimensionScore:
    """技术符号是否原样保留 —— 报错文能否被搜到，全看这个。"""
    if not symbols:
        return DimensionScore("技术符号", full, full, objective=True, evidence="无待查符号")
    hit = [s for s in symbols if s.lower() in (text or "").lower()]
    s = full * len(hit) / len(symbols)
    return DimensionScore("技术符号", round(s, 1), full, objective=True,
                          evidence=f"{len(hit)}/{len(symbols)} 命中：{hit[:3]}")


def check_format(text: str) -> list[Issue]:
    """格式硬伤。都是能一眼数出来的，不必问 LLM。"""
    out: list[Issue] = []
    paras = (text or "").split("\n\n")
    for i, p in enumerate(paras):
        if _MD_TABLE.search(p):
            out.append(Issue("格式", "markdown_table", Severity.MEDIUM,
                             "出现 Markdown 表格", location=i, evidence=p[:60]))
        if _HR.search(p):
            out.append(Issue("格式", "horizontal_rule", Severity.LOW,
                             "单独成行的横线会渲染成整宽 <hr>", location=i, evidence=p[:40]))
    return out


def check_fabrication(text: str, allowed_source: str) -> list[Issue]:
    """编造检测：正文里的编号/版本号/容量/commit，必须在给定来源里出现过。

    🔴 为什么这一项必须是客观项：实测同一篇文章里同一个假编号 `Issue #15352`，
       LLM 裁判第一次给 100 分放行、第二次判 0 分 —— **是掷骰子不是闸**。
       而这类东西能精确比对，不该交给 LLM。
    """
    checks = [
        ("编号", re.compile(r"(?:#|(?:issue|pr|bug)\s*#?\s*)(\d{2,})", re.I)),
        ("版本号", re.compile(r"\bv?(\d+\.\d+(?:\.\d+)+)\b")),
        ("容量", re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:GB|MB|TB|KB)\b", re.I)),
        ("commit", re.compile(r"\b([0-9a-f]{7,40})\b")),
    ]
    hay = (allowed_source or "").lower()
    paras = (text or "").split("\n\n")
    out: list[Issue] = []
    for i, p in enumerate(paras):
        for kind, pat in checks:
            for m in pat.finditer(p):
                if m.group(1).lower() in hay:
                    continue
                out.append(Issue("事实", f"fabricated_{kind}", Severity.HIGH,
                                 f"{kind} `{m.group(1)}` 在素材里找不到出处",
                                 location=i,
                                 evidence=p[max(0, m.start() - 30):m.end() + 30]))
    return out
