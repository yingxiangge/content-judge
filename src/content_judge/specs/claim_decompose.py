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

DIMENSION_NAMES: tuple[str, ...] = ("政策通报", "规模供需", "核心企业", "价格市场")
LAYER_NAMES: tuple[str, ...] = DIMENSION_NAMES
LAYER_TYPES: tuple[str, ...] = ("factual", "factual", "factual", "factual")

ROLE = """针对以下热点事件，生成 4 组客观事实检索词。

目标：扩大高相关事实召回，不预设观点、结论或视频叙事。"""

RULES = """【检索维度】
1. 政策通报：发文机构、文件名称、政策条款、准入门槛
2. 规模供需：投资总额、产能、产量、需求量、同比/环比变化
3. 核心企业：头部与尾部企业动态、出货、开工率、业绩
4. 价格市场：产品成交价、中标价、报价、价格变化、市场表现

【检索词规则】
- 只生成事实检索词，不生成观点、结论或决策问题。
- 检索词应尽可能包含具体主体名、产品名、机构名、时间或量化单位。
- 优先使用可检索的实体、指标和数据，而非“影响、原因、前景、机会、风险”等观点词。
- 不得预设利好、利空、上涨、下跌、见底、过剩等结论。
- 某维度没有明确相关对象时返回空字符串。
- 每个维度输出一个可直接用于搜索的检索词。"""

OUTPUT_JSON = """【输出格式】
必须严格输出合法 JSON，包裹在 ```json 与 ``` 之间：
{
  "政策通报": "检索词",
  "规模供需": "检索词",
  "核心企业": "检索词",
  "价格市场": "检索词"
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
