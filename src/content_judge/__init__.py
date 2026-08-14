"""content-judge —— 内容质量评分与问题定位。

judge(text, spec) -> Verdict(tier, dimensions, issues)
issues 带 location，供定向修订使用。
"""
from .judge import Spec, judge
from .types import DimensionScore, Issue, Severity, Verdict, tier_of

__all__ = ["judge", "Spec", "Verdict", "Issue", "Severity", "DimensionScore", "tier_of"]
__version__ = "0.1.0"
