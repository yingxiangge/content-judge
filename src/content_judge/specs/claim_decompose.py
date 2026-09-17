# -*- coding: utf-8 -*-
"""Claim Decomposer —— 热点事件 → 4 组客观事实检索词。

目标：扩大高相关事实召回，不预设观点、结论或视频叙事。
2026-09-11 老板定：废除旧 4 层议论文八股拆解（核心现象/认知反差/背后机制/风险边界），
重构为 4 个客观事实检索切片（政策通报/规模供需/核心企业/价格市场）。
"""
from __future__ import annotations

# claim 类型 → 这个 claim 需要哪几类证据。
EVIDENCE_BY_TYPE: dict[str, tuple[str, ...]] = {
    "controversial": ("support", "counter"),
    "factual": ("direct",),
    "causal": ("mechanism",),
}

DIMENSION_NAMES: tuple[str, ...] = ("核心事件", "关键底牌", "市场反应", "横向影响")
LAYER_NAMES: tuple[str, ...] = DIMENSION_NAMES
LAYER_TYPES: tuple[str, ...] = ("factual", "factual", "factual", "factual")

ROLE = """针对以下证券短视频选题及其异常矛盾，提炼事实检索切片。

目标：动态生成 2~4 个事实检索切片。固定取证目的，不固定取证对象；不适用的切片不得强行生成。"""

RULES = """【检索切片与取证目的】
1. 核心事件【必选】：确认核心变动的确切事实，优先搜索公告、官方文件、公司回应及交易细节。
2. 关键底牌【通常必选】：搜索能够证明事实与底层逻辑的核心数据（如业务依赖度、营收/利润占比、毛利率、估值、份额、供需等）。若涉及反差对撞与暗门排雷，重点搜索反向制约事实与隐性账本代价（如增资摊薄、除息税负、原材料吞噬利润、毛利下滑、大资金逢高兑现等）。
3. 市场反应【按需】：搜索相关资产的涨跌、成交、估值及市场分化。若选题涉及主体博弈，搜索龙虎榜、大宗交易、重要股东增减持等主体行为证据。
4. 横向影响【按需】：搜索同业、上下游、竞争对手或相关产业链的对照事实，寻找制约边界或外部阻力。无明确关联时省略。

【检索词规则】
- 每个切片输出 1 个可直接用于搜索引擎的事实检索词（2 至 5 个关键词）。
- 检索词必须包含具体主体名、产品名、机构名或指标名，严禁观点词。
- 只生成事实检索词，不预设主观结论。
- 某切片不适用或无明确对象时直接返回空字符串。"""

OUTPUT_JSON = """【输出格式】
必须严格输出合法 JSON，包裹在 ```json 与 ``` 之间：
{
  "核心事件": "检索词",
  "关键底牌": "检索词",
  "市场反应": "检索词",
  "横向影响": "检索词"
}

不要输出任何解释、前言或 Markdown 正文。"""


def render_topic(topic: str, gate: str = "", why: str = "") -> str:
    """热点事件。"""
    lines = [f"【热点事件】{topic}"]
    if why and why != topic:
        lines.append(f"【背景来源】{why}")
    if gate and gate not in (topic, why):
        lines.append(f"【补充信息】{gate}")
    return "\n".join(lines)


SYSTEM_BLOCKS = (ROLE, RULES, OUTPUT_JSON)
