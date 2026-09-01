# -*- coding: utf-8 -*-
"""Claim Decomposer —— 选题 → required claims（带类型与检索键）。

**为什么要拆**：一个选题不能只用一句话回答。「抄底到底好不好」至少包含
「是否赚钱 / 胜率多少 / 风险多大 / 与不择时比 / 极端情况」几层，
而**证据要按层配齐**才叫回答完整。不拆的话，8 条资料全在讲同一层，
成品看着有数据、其实只答了五分之一。

🔴 **两个不能省的输出**：

1. **`type` 决定这个 claim 需要什么证据结构** —— 见 `EVIDENCE_BY_TYPE`。
   ⚠️ **不许一刀切要求所有 claim 都有反向证据**：
   「沪深300 创立至今收益多少」是事实型，强行找反方就是为形式完整添垃圾
   （同 `always.md`「闸误杀的代价是回落」）。

2. **检索键 `asset` / `condition` / `action`** —— 拆完直接就能喂给
   `factstore.recall()`。少了它们，下游还要再解析一次自然语言，
   而那一步会引入第二套判据、迟早与这里分叉。
"""
from __future__ import annotations

# claim 类型 → 这个 claim 需要哪几类证据。
# 🔴 **这是唯一真相**，prompt 里的说明从它生成，禁止手抄（`always.md` 2026-08-24）。
EVIDENCE_BY_TYPE: dict[str, tuple[str, ...]] = {
    # 有争议的判断题 —— 只给支持面必然偏，正反都要
    "controversial": ("support", "counter"),
    # 无争议的事实查询 —— 一条高质量直接证据就够，**不需要反方**
    "factual": ("direct",),
    # 因果断言 —— 光有相关性不够，要能说清机制
    "causal": ("correlation", "mechanism"),
    # 实验/回测结论 —— 结果之外还要方法与对照，否则无法判断可信度
    "experimental": ("result", "method", "control"),
}

TYPE_DESC = {
    "controversial": "有争议的判断题（大家吵得起来，正反都有人信）",
    "factual": "无争议的事实查询（查一下就有确定答案）",
    "causal": "因果断言（A 导致了 B）",
    "experimental": "实验或回测结论（在某个方法下跑出来的结果）",
}

EVIDENCE_DESC = {
    "support": "支持该判断的证据",
    "counter": "反例或边界条件（什么情况下不成立）",
    "direct": "直接回答的高质量证据",
    "correlation": "相关性证据（数据上确实同向）",
    "mechanism": "机制解释（为什么会这样）",
    "result": "实验/回测结果",
    "method": "方法与口径（怎么算的）",
    "control": "对照组（跟什么比）",
}

ROLE = """你负责把一个视频选题拆成**几个必须分别回答的子问题**。

面向 A 股散户的 20~30 秒短视频。观众问一个问题时，脑子里其实有好几层疑问；
只答其中一层，观众会觉得"说了但没说清"。

🔴 你**不是**在写提纲，也**不是**在扩展话题。你在列**为了让这条内容站得住，
必须分别拿出证据的那几个点**。"""

RULES = """## 拆解规则

1. **3~5 个 claim**。少于 3 个说明拆得不够，多于 5 个 20 秒讲不完。
2. **彼此互斥**：两个 claim 不能是同一件事的不同说法。
   🚫 「抄底赚不赚钱」+「抄底收益如何」——同一个问题
   ✅ 「抄底后的收益」+「抄底的胜率」+「最差情况亏多少」——三个不同维度
3. **合起来能回答原选题**：拆完检查一遍，这几个都答了，原问题是不是就答完了。
4. **按重要性排序**，`C1` 是最核心的那个 —— 20 秒讲不完时从后往前砍。
5. **每个 claim 都要给检索键**（`asset`/`condition`/`action`），
   它们直接用于从事实库召回，写不出就留空字符串，**不要编**。

## `action` 字段（🔴 最容易填错，填反就召回到相反结论的数据）

只能是 `buy`（买入/补仓/抄底类）· `sell`（卖出/止损/减仓类）·
`hold`（持有不动）· `none`（不涉及操作方向的纯统计或纯状态）。

「大跌后抄底收益如何」是 `buy`；「大跌后止损损失多少」是 `sell`。
这两句语义极近、结论相反。**拿不准就填 `none`。**"""


def render_types() -> str:
    """类型与证据要求说明 —— **从 `EVIDENCE_BY_TYPE` 生成，不手抄**。"""
    lines = ["## claim 类型（决定这个 claim 需要哪几类证据）", ""]
    for t, evs in EVIDENCE_BY_TYPE.items():
        need = " + ".join(EVIDENCE_DESC.get(e, e) for e in evs)
        lines.append(f"- **`{t}`** {TYPE_DESC.get(t, '')}\n  ⇒ 需要：{need}")
    lines += [
        "",
        "⚠️ **类型判错的代价**：把事实型判成争议型，系统就会去找根本不存在的"
        "反方证据，找不到就判这条内容不完整 —— 那是纯误杀。",
        "「沪深300 创立至今累计收益多少」是 `factual`，**不需要反方**。",
    ]
    return "\n".join(lines)


OUTPUT_JSON = """## 输出格式

只输出合法 JSON，包裹在 ```json 与 ``` 之间：

{
  "claims": [
    {
      "id": "C1",
      "question": "这一层要回答的具体问题",
      "type": "controversial",
      "asset": "沪深300",
      "condition": "单日跌幅>=5%",
      "action": "buy",
      "why": "为什么这一层必须回答（一句话）"
    }
  ]
}

`type` 只能是 controversial / factual / causal / experimental。
不要输出任何解释、前言或 Markdown 正文。"""


def render_topic(topic: str, gate: str = "", why: str = "") -> str:
    lines = [f"【选题】{topic}"]
    if gate:
        # 选题层已判出的转发理由（A警告/B打脸/C反常识）——拆 claim 时要围绕它，
        # 否则拆出来的几层跟这条内容的角度是脱节的。
        lines.append(f"【这条内容的角度】{gate}")
    if why:
        lines.append(f"【为什么值得做】{why}")
    return "\n".join(lines)


SYSTEM_BLOCKS = (ROLE, RULES, render_types(), OUTPUT_JSON)
