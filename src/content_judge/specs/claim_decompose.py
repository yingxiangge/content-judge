# -*- coding: utf-8 -*-
"""Claim Decomposer —— 选题 → required claims（带类型与检索键）。

**为什么要拆**：一个选题不能只用一句话回答。观众问一个问题时脑子里有好几层疑问，
只答其中一层，他会觉得「说了但没说清」。而**证据要按层配齐**才叫回答完整 ——
不拆的话，8 条资料全在讲同一层，成品看着有内容、其实只答了一小半。

🔴 **按受众的疑问拆，不按素材的形态拆**（2026-09-06 老板定，第三次重申）：
原来的类型表里有个 `experimental`（实验/回测结论），要求 result + method + control
—— **除了回测，没有任何素材能填满它**。于是拆层 LLM 照着这个类型，把
「连板澄清后怎么走」拆成「N 日走势」「胜率多大」，新闻类事实一层都答不上，
`covers` 恒空 ⇒ 一条可用素材都没有 ⇒ 当天三条选题全灭、缺片。

同日上午刚把「必须有回测统计」从写稿层的 REJECT 条件里删掉，
而它**从拆层就写死了** —— 位置换了，卡人的效果一模一样。
⇒ 回测只是**素材之一**：它能填 `factual` 的直接证据、能填 `causal` 的机制说明，
但**没有任何一层是非它不可的**。

🔴 **模型每层只输出 `question` + `search`**（2026-09-11 老板定）：
- `type` 不再让模型判：四层固定、按序输出，类型由层位置决定（`LAYER_TYPES`）。
  实测同一选题跑三次，第 4 层被标成 controversial 一次、causal 两次 —— 让模型判只会引入抖动。
- `asset` / `condition` 删掉：它们原本给 SQL 召回用（09-10 已退役），之后只剩拼向量查询串一处，
  由 `search` 顶替（`video_evidence._claim_queries`）。
- `search` 是补搜的检索词：09-11 实测拿选题问句搜新闻，8 条大半跑题；按层用检索词搜，前三层几乎全贴题。
"""
from __future__ import annotations

# claim 类型 → 这个 claim 需要哪几类证据。
# 🔴 **这是唯一真相**，prompt 里的说明从它生成，禁止手抄（`always.md` 2026-08-24）。
# 🔴 **每一类的证据要求都必须是「多种素材都填得上」的**：新闻、公告、财报、
#    回测、研报都算数。要求只有某一类素材能满足，等于把那类素材变成必要条件。
EVIDENCE_BY_TYPE: dict[str, tuple[str, ...]] = {
    # 有争议的判断题 —— 只给支持面必然偏，正反都要
    "controversial": ("support", "counter"),
    # 无争议的事实查询 —— 一条高质量直接证据就够，**不需要反方**
    "factual": ("direct",),
    # 因果断言 —— 要能说清为什么会这样
    "causal": ("mechanism",),
}

# 四层固定顺序 → 每层的 claim 类型。**唯一真相**，`claims.decompose` 按输出顺序套用。
LAYER_TYPES: tuple[str, ...] = ("factual", "controversial", "causal", "causal")
# 四层名称，与下方「拆解维度」逐条对应；写稿层按它给每条事实标层（`video_evidence.to_facts_dict`）
LAYER_NAMES: tuple[str, ...] = ("发生了什么", "认知反差", "背后机制", "风险边界")

ROLE = """你负责将短视频选题拆解为 4 个面向短视频受众的子问题。"""

RULES = """## 拆解维度

按以下 4 层顺序，每层拆 1 个子问题，按顺序输出：
1. 核心现象：发生了什么具体异动或事件，发生时间与核心主体具体表现。
2. 认知反差：受众普遍持有的预期，与实际表现的反差事实。
3. 背后机制：导致该反差的深层原因、底层驱动机制或运作机理。
4. 风险边界：该逻辑在什么情况下失效、存在哪些例外或潜在代价。

## 规则

1. 每一个子问题都必须是确定的事实能够回答的。
2. 子问题彼此互斥，合起来完整回答原选题。
3. 检索词 search：输出 2 至 5 个关键词，必须包含本次事件的核心主体。"""

OUTPUT_JSON = """## 输出格式

必须严格输出合法 JSON，包裹在 ```json 与 ``` 之间：
{
  "claims": [
    {"question": "子问题", "search": "关键词 关键词 关键词"}
  ]
}

不要输出任何解释、前言或 Markdown 正文。"""


def render_topic(topic: str, gate: str = "", why: str = "") -> str:
    """选题 + 来源标题。`gate` 与 `why` 相同时只给一次（选题线 v3 起二者都是来源标题）。"""
    lines = [f"【选题】{topic}"]
    if why:
        lines.append(f"【来源标题】{why}")
    if gate and why not in gate:
        lines.append(f"【这条内容的角度】{gate}")
    return "\n".join(lines)


SYSTEM_BLOCKS = (ROLE, RULES, OUTPUT_JSON)
