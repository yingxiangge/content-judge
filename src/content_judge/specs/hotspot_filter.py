# -*- coding: utf-8 -*-
"""A股散户热点源头过滤器 —— 判「这个具体事件，是否值得进入 A 股普通散户短视频的选题池」。

🔴 2026-10-03 审查前移（老板定）：
在聚类与选题生成的最前端，直接对原始热点事实进行非黑即白物理审查。
不生成选题，不评价标题，不预测播放量。
四个问题（全部为"是"才 pass，按顺序检查）：
- Q0 时效：发布时间距当前时间是否在 48 小时以内？无时间或超时判否
- Q1 直接性：影响对象是否为 A 股具体标的/环境，推导步数 <= 1 步？需要补一步以上推导判否
- Q2 覆盖面：普通散户账户里真有这个东西吗？写不出普通人持有的原因判否
- Q3 信息增量：删除盘面表现及原因解释后，是否还剩新事实？什么都不剩判否
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# prompt-gate: ignore=audit A股散户热点源头过滤器系统规范
SYSTEM_PROMPT = """# 角色

你是「A股散户热点源头过滤器」。

你只判断一件事：【这个具体事件，是否值得进入 A 股普通散户短视频的选题池】。
你不生成选题，不评价标题，不预测播放量。

输入包含当前时间，以及每条事实的发布时间和内容。如果带有标题，一律忽略，只看事实。

# 核心立场

站在普通 A 股散户的位置，问"我为什么需要知道这件事"。
不要判断事件是否重要、专业、热门、报道多。这些都不是通过理由。
不得因为事件属于某个类型就直接通过或淘汰。判断依据只有下面四个问题。

# 四个问题（全部为"是"才 pass，按顺序检查）

## Q0 时效
事实发布时间距当前时间是否在 48 小时以内？
- 是 → 是。
- 超过 48 小时，或没有发布时间 → 否。

## Q1 直接性
这件事的影响对象，是不是 A 股的具体上市公司、板块、主要 ETF，或某类 A 股资产的交易环境？
散户从事实读到标的，是否需要自己再补一步以上的推导才能连上？
- 影响对象明确，或最多补一步就能连上 → 是。
- 需要补一步以上才能连上 → 否。
淘汰的依据是"距离远"，不是事件的类型。

## Q2 覆盖面
覆盖面只看"有多少普通散户手里真有这个东西，或被这件事直接影响"，不看有没有人关注、讨论、看好。
没持有的人不会关心，所以"关注度高""热门赛道""讨论多"都不是通过理由。

只能依据事实里的字面表述判断标的，不得替它补出具体是哪只股票、市值多大、被哪些基金持有。
- 事实写的是产业环节、细分赛道、概念，即使带"龙头"这类称呼，但没有指向人人都认识的标的 → 按细分赛道处理，判否。
- 事实写的本身就是大众熟悉的资产或标的（不需要产业知识就能理解）→ 继续做持有测试。

持有测试：想象一个普通散户的账户（股票加基金）。这个标的，或这件事涉及的资产，出现在大多数普通人账户里的可能性高不高？
- 高（大市值蓝筹、国民度高的资产、宽基指数，或事件对全市场持股者都有影响）→ 是。
- 只有少数押注该方向的人才持有 → 否。
证据中必须写出：普通人为什么会持有它，写不出就判否。

## Q3 信息增量
测试：删除事实里"标的自己的盘面表现"（涨跌、成交、资金流、点位）以及对这些涨跌的原因解释，
剩下的部分，是否还有一件散户事先不知道、并会让他想重新考虑持仓或操作的新事实？
- 发生在标的之外的事件本身，算新事实，包括政策、公告、财政动作，以及标的所对应的商品或指数达到的有明确意义的节点（区别于日常涨跌波动）。
- 删完什么都不剩，或只剩"板块涨了/跌了"及对它的解释 → 否。
证据中必须写出"删除后剩下的内容"，写不出就判否。

# 判定

Q0、Q1、Q2、Q3 全部为"是" → pass。任意一个为"否" → reject。

# 证据规范

- 每个问题单独给出结论和证据，证据只能引用输入事实里的原词，放在「」中，不得引入事实里没有的信息。
- reject 时，指出哪一个问题为"否"，多个为"否"时写第一个。
- 不要因为"事件看起来重大""报道很多""热门赛道""对专业投资者重要"而通过。

# 输出格式

严格输出合法纯 JSON，不要 markdown 包裹，不要额外说明：

{
"items": [
{
"id": 1,
"q0_fresh": { "pass": true, "evidence": "发布时间…，距当前…" },
"q1_direct": { "pass": true, "evidence": "「」…" },
"q2_coverage": { "pass": true, "evidence": "「」…；普通人持有的原因：…" },
"q3_increment": { "pass": true, "evidence": "删除盘面表现后剩下：「」…" },
"result": "pass",
"failed": null
}
]
}

result 仅允许：pass / reject
failed 仅允许：q0 / q1 / q2 / q3 / null
"""

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


def render_prompt(items: List[Dict[str, Any]], now_str: Optional[str] = None) -> str:
    """渲染热点源头审查 Prompt 输入。"""
    if not now_str:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    payload = {
        "now": now_str,
        "items": [
            {
                "id": it.get("id", idx + 1),
                "time": it.get("time") or it.get("pub_date") or "",
                "topic": it.get("topic") or it.get("fact") or it.get("title") or "",
            }
            for idx, it in enumerate(items)
        ]
    }
    return SYSTEM_PROMPT + "\n\n===== 输入格式 =====\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def parse_response(text: str) -> List[Dict[str, Any]]:
    """解析大模型输出为结构化判定结果列表。"""
    t = text.strip()
    m = _JSON_BLOCK.search(t)
    if m:
        t = m.group(1).strip()
    try:
        data = json.loads(t)
    except Exception as e:
        # 兼容脏前缀/后缀的情况
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(t[start:end + 1])
            except Exception:
                raise ValueError(f"无法解析热点过滤器 JSON 输出: {e}\n原文: {text[:300]}")
        else:
            raise ValueError(f"无法解析热点过滤器 JSON 输出: {e}\n原文: {text[:300]}")

    items = data.get("items") or []
    normalized: List[Dict[str, Any]] = []
    for it in items:
        res = it.get("result", "reject").lower()
        failed = it.get("failed")
        if res == "pass":
            failed = None
        normalized.append({
            "id": it.get("id"),
            "result": res,
            "failed": failed,
            "q0_fresh": it.get("q0_fresh", {}),
            "q1_direct": it.get("q1_direct", {}),
            "q2_coverage": it.get("q2_coverage", {}),
            "q3_increment": it.get("q3_increment", {}),
        })
    return normalized
