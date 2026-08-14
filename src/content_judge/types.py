"""评分结果的统一形态。

三条设计原则全部来自小说侧 V4 评分器（跑了几个月、有验证记录的那套）：

  ① **客观项走正则，零随机**。字数、代码块数、技术符号命中数这些能数出来的，
     不问 LLM。V4 的原话：「客观项走正则（字数合规），零随机」。
  ② **主观项必须带原文证据**。分数会飘，证据不会。有证据才能人工复核，
     也才能定位到具体段落去改。
  ③ **输出分档，不输出精确分**。V4 的原话：「精确分是伪精确，分档才是决策单位」。
     实测反例：同一篇文章里同一个假编号，LLM 裁判第一次给 100 分放行、第二次判 0 分；
     另一次评语明明是「符合低浓度特征」，分数却给 32 把整篇毙掉 —— 这种数字不该当闸。

`Issue.location` 是**定向修订的前提**。没有它就只能整篇重写，而整篇重写会
把上游辛苦守住的事实边界重新搅乱。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    HIGH = "high"        # 必须改，否则不该发
    MEDIUM = "medium"    # 该改
    LOW = "low"          # 可改可不改


@dataclass
class Issue:
    """一个具体问题。**必须能定位**，否则修不了。"""
    dimension: str
    kind: str
    severity: Severity
    detail: str
    # 定位：段落序号（从 0 起）或原文片段，二者至少有一个
    location: int | None = None
    evidence: str = ""

    def format(self) -> str:
        where = f"段落{self.location}" if self.location is not None else "全文"
        ev = f"\n        证据：{self.evidence[:80]}" if self.evidence else ""
        return f"  [{self.severity.value:6s}] {where} · {self.dimension}/{self.kind}\n        {self.detail}{ev}"


@dataclass
class DimensionScore:
    name: str
    score: float
    full: float
    objective: bool          # True=正则算出来的，可复现；False=LLM 判的
    evidence: str = ""

    @property
    def ratio(self) -> float:
        return self.score / self.full if self.full else 0.0


@dataclass
class Verdict:
    tier: str = "C"
    total: float = 0.0
    full: float = 100.0
    dimensions: list[DimensionScore] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.tier in ("S", "A")

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.HIGH]

    def format(self) -> str:
        lines = [f"[content-judge] {self.tier} 档 · {self.total:.0f}/{self.full:.0f}"]
        for d in self.dimensions:
            mark = "尺" if d.objective else "眼"
            lines.append(f"  {mark} {d.name:14s} {d.score:>5.1f}/{d.full:<5.0f}"
                         + (f"  {d.evidence[:50]}" if d.evidence else ""))
        if self.issues:
            lines.append(f"  ── 问题 {len(self.issues)} 处 "
                         f"（阻断 {len(self.blocking)}）──")
            lines += [i.format() for i in self.issues]
        return "\n".join(lines)


def tier_of(total: float, full: float = 100.0) -> str:
    """S≥85 / A≥70 / B≥50 / C<50，与 V4 同口径。"""
    pct = 100.0 * total / full if full else 0.0
    if pct >= 85:
        return "S"
    if pct >= 70:
        return "A"
    if pct >= 50:
        return "B"
    return "C"
