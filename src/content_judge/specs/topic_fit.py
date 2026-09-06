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

ROLE = """你负责评估输入的一组事实，对给定选题及其待验证子问题（Claims）的论证契合度。
仅评估事实对各子问题的论证有效性，不校验事实真伪。"""

SCORE_SPEC = """## 打分标准（topic_fit，0-100）

- **90-100（强支撑）**：直接支撑或确证某一子问题，包含明确的结论、定量数据或典型个案实据。
- **60-89（部分支撑）**：支撑某子问题的一部分，或需一步直接逻辑推导即可作为论据。
- **30-59（弱相关）**：与选题大方向相关，但未能有效回答已列出的任何一个具体子问题。
- **0-29（无关）**：与选题核心问题及各子问题均无关。

## 事实适用性（covers）

标注该事实能够直接回答或有力支撑的子问题 ID 列表，以数组表示。
若该事实未能有效回答任何子问题，填入空数组 `[]`。

## 重复判定（same_as）

识别多条事实是否指向同一事实源：
- 若当前事实与此前某条事实的核心主体、条件变量与结论完全一致（仅表述措辞差异），填入更靠前事实的整数编号。
- 若核心变量、观察主体、前提条件或结论数据存在差异，填入 null。无法确定时填入 null。

## 立场标注（direction）

- support：支撑该子问题所表述的现象、机制或论断。
- counter：提供反例、失效场景、边界条件或相反结果。
- neutral：纯背景介绍或中立描述，无明确论证立场。"""

OUTPUT_JSON = """## 输出格式

必须严格输出合法 JSON，包裹在 ```json 与 ``` 之间：

{
  "items": [
    {
      "id": 1,
      "topic_fit": 92,
      "covers": ["C1"],
      "direction": "support",
      "same_as": null,
      "why": "简要说明契合维度与支撑理由"
    }
  ]
}

`direction` 只能是 support / counter / neutral。
逐条对应输入编号，不得遗漏、合并或输出额外解释。"""


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
