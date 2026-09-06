# -*- coding: utf-8 -*-
"""TopicFit —— 这条事实**对今天这道题**有多合适。

🔴 与 FactQuality 的分工是整个事实层的地基：

    FactQuality  这个事实值不值得信   入库判一次，**持久化**
    TopicFit     它适不适合今天这题   每次 run 重算，**绝不进 facts 表**

「沪深300 历史最大回撤 53%」这条事实，对「抄底有没有用」很贴题，
对「为什么长期持有也会很痛苦」同样贴题，对「新股怎么打」毫不相干 ——
把 TopicFit 写进事实的永久字段，等于把某一天的上下文固化成事实的属性。

## `direction` 是 Evidence Pack 能不能组装的前提

一条事实是**支持**还是**反对**这个 claim，决定它能填哪个证据槽。
争议型 claim 需要 support + counter 两类，全是 support 的一组证据
在结构上就是不完整的 —— 内容会一边倒，而观众看得出来。
"""
from __future__ import annotations

DIRECTIONS = ("support", "counter", "neutral")

ROLE = """你判断一批**已经核验过的事实**，对今天这道选题分别有多大用处。

面向 A 股散户的 20~30 秒短视频。

🔴 你**不判事实真假** —— 那在入库时已经判过了。你只判**贴不贴今天这道题**。
一条非常权威、非常正确的事实，完全可能对今天这条内容毫无用处。"""

SCORE_SPEC = """## topic_fit（0-100）

- **90-100**：**直接回答**了某一层问题，且带具体数字。
  例：题问「大跌后抄底赚不赚」，事实是「大跌 10% 后 20 日中位收益 +2.83%」
- **60-89**：回答了某一层的一部分，或需要一步换算才能用上
- **30-59**：相关，但答的不是这几层里的任何一层
  例：题问「抄底赚不赚」，事实是「沪深300 于 2005 年发布」
- **0-29**：跟这道题没关系

⚠️ 判 30 分以下不用犹豫 —— **宁可少用一条，不可硬凑**。
硬凑进来的事实会占掉 20 秒里的宝贵时间，讲一件观众不关心的事。

## covers：这条事实能回答哪几层

填 claim 的 id 列表。一条都答不上就填 `[]` ——
那意味着它这次用不上，**这是正常结果**。

## same_as：这条和前面哪一条讲的是**同一件事**

填**更靠前**那条的编号；不是重复就填 `null`。

判据是「**换成对方那句，这一层的证据强度会不会变**」：
- 不变 → 同一件事。典型是同一份统计被抄了两遍，只是前缀/措辞不同：
    3.「下修期间套利：当转债涨5%平仓，平均持仓54天，共198次…」
    5.「当转债涨5%平仓，平均持仓54天，共198次…」          → 5 的 same_as 填 3
- 会变 → **不是**重复，哪怕字面几乎一样：
    1.「…平均持仓 54 天…虚值期权收益 1033.13%，年化 83.26%」
    2.「…平均持仓 63 天…虚值期权收益  397.16%，年化 32.01%」
  这两条字面重合 60%，但讲的是**下修期间**与**回售期间**两个不同场景，
  数字全不同 ⇒ 各自独立，都填 `null`。

🔴 **拿不准就填 `null`**。判成重复的代价是丢掉一条真数据；判不出来的代价只是
这次多用一条相似的，下游还有一道拒绝闸兜着 —— **两边不对等，往松了判**。

- `support` 支持该层的判断
- `counter` 反例、边界条件、相反的证据
- `neutral` 纯背景或口径说明，不站边

🔴 **`counter` 极其重要，不要因为「看起来不利」就不给**：
争议型的问题**必须有反面证据**才站得住。一组全是 support 的证据，
观众一眼看出是在单方面说服他。"""

OUTPUT_JSON = """## 输出格式

只输出合法 JSON，包裹在 ```json 与 ``` 之间。**逐条对应输入编号，一条不许漏**：

{
  "items": [
    {"id": 1, "topic_fit": 92, "covers": ["C1"], "direction": "support",
     "same_as": null, "why": "一句话：它回答了哪一层、是什么立场"},
    {"id": 2, "topic_fit": 35, "covers": [], "direction": "neutral",
     "same_as": null, "why": "只是背景信息，不答这几层里的任何一层"},
    {"id": 3, "topic_fit": 88, "covers": ["C1"], "direction": "support",
     "same_as": 1, "why": "与第1条是同一份统计，只是措辞不同"}
  ]
}

`direction` 只能是 support / counter / neutral。
不要输出任何解释、前言或 Markdown 正文。"""


def render(topic: str, claims: list, facts: list) -> str:
    """选题 + 要回答的几层 + 候选事实。"""
    lines = [f"【今天的选题】{topic}", "", "【要分别回答的几层】"]
    for c in claims:
        lines.append(f"  {c.id}. {c.question}（{c.type}）")
    lines += ["", "【候选事实（都已核验过真实性，只判贴不贴题）】"]
    for n, f in enumerate(facts, 1):
        # ⚠️ 用 getattr 而不是直接取属性：元信息缺一个字段只该少显示一行，
        #    不该让整条产线崩。调用方传进来的未必都是 `factstore.Fact`。
        meta = " · ".join(x for x in (getattr(f, "asset", ""),
                                      getattr(f, "condition", ""),
                                      getattr(f, "horizon", "")) if x)
        lines.append(f"{n}. {getattr(f, 'claim', '')}")
        if meta:
            lines.append(f"   （{meta}）")
    return "\n".join(lines)


SYSTEM_BLOCKS = (ROLE, SCORE_SPEC, OUTPUT_JSON)
