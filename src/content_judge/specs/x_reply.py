"""X (Twitter) 回帖质检标准。

核心防御：
1. **量化指标与数字编造拦截**：出现「指标名 + 数字」（如 win rate 40%, ARR $5M, 胜率 80%），
   而该数字在原推（source）中不存在 → 判定为编造，严重度 HIGH（直接阻断）。
2. **通用编造检测**：Issue编号/版本号/commit SHA 必须在原推中有出处。
3. **零 LLM、纯客观项**：毫秒级响应，杜绝 LLM 裁判的打分波动。
"""
from __future__ import annotations

import re

from ..judge import Spec
from ..types import DimensionScore, Issue, Severity

_METRIC_NUM_RE = re.compile(
    r'(?:'
    r'win\s*rate|accuracy|sharpe|sortino|pnl|roi|drawdown|calmar|alpha|beta'
    r'|ARR|MRR|churn|retention|conversion|CAC|LTV|DAU|MAU|NPS|margin|runway'
    r'|胜率|准确率|收益率|回撤|夏普|年化|月活|留存|转化'
    r')'
    r'[^\d\n]{0,25}'
    r'(\d+(?:\.\d+)?%?)',
    re.I,
)


def check_metric_fabrication(text: str, ctx: dict) -> list:
    """回帖里出现「量化指标 + 数字」而该数字在原推中不存在 → 判定为编造。"""
    source = str(ctx.get("source") or "")
    src_nums = set(re.findall(r'\d+(?:\.\d+)?', source))
    out = []
    penalty = 0.0

    for m in _METRIC_NUM_RE.finditer(text or ""):
        num_part = re.sub(r'[^\d.]', '', m.group(1))
        if num_part and num_part not in src_nums:
            penalty += 100.0
            out.append(Issue(
                dimension="事实",
                kind="fabricated_metric",
                severity=Severity.HIGH,
                detail=f"回帖含编造指标「{m.group(0)}」（原推无此数字）",
                evidence=m.group(0),
            ))

    score = max(0.0, 100.0 - penalty)
    out.append(DimensionScore(
        name="事实无编造",
        score=score,
        full=100.0,
        objective=True,
        evidence="无编造指标" if penalty == 0 else f"发现编造指标扣 {penalty:.0f} 分",
    ))
    return out


X_REPLY = Spec(
    name="x_reply",
    length_full=0.0,
    code_blocks_full=0.0,
    symbols_full=0.0,
    check_format=False,
    check_fabrication=True,
    extra_objective=[check_metric_fabrication],
)
