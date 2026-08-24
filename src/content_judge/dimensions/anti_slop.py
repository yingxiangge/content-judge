"""
Anti-Slop Dimension Bridge for content-judge
桥接底层独立的 anti-slop 规则底座包，转换为 content-judge 标准 Issue
"""
from __future__ import annotations

from typing import List
from anti_slop import scan, assert_clean, is_clean, ALL_RULES
from ..types import Issue, Severity

def scan_slop_violations(text: str):
    return scan(text)

def assert_no_slop(text: str, context: str = "") -> None:
    assert_clean(text, context=context)

def check_anti_slop(text: str) -> List[Issue]:
    """
    将 anti_slop 扫描结果适配为 content-judge 标准 Issue
    """
    issues: List[Issue] = []
    paras = (text or "").split("\n\n")
    for i, p in enumerate(paras):
        hits = scan(p)
        for h in hits:
            issues.append(Issue(
                dimension="自然度",
                name=h.rule_id,
                severity=Severity.HIGH,
                description=f"出现典型 AI 套话/营销号词汇: \"{h.matched_text}\" ({h.description})",
                location=i,
                evidence=p[max(0, h.position - 20):min(len(p), h.position + len(h.matched_text) + 20)]
            ))
    return issues

__all__ = [
    "scan_slop_violations",
    "assert_no_slop",
    "check_anti_slop",
    "scan",
    "assert_clean",
    "is_clean",
    "ALL_RULES"
]
