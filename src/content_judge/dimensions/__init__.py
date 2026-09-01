"""评分维度。

⚠️ `anti_slop` 桥接**不在这里 import** —— 它依赖外部的 anti-slop 包，
而 content-judge 本体零依赖。写成顶层 import 会让整个包在没装 anti-slop
的环境里 `import content_judge` 就崩（2026-09-01 开放前修）。
需要自然度维度的调用方自己显式：

    from content_judge.dimensions.anti_slop import check_anti_slop
"""
from . import objective

__all__ = ["objective"]
