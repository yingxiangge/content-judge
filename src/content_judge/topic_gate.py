# -*- coding: utf-8 -*-
"""选题结构校验 —— `testable` 四要素齐不齐。**零 LLM，纯确定性判断。**

## 为什么这一步不交给模型

判「这条选题可不可验证」如果问模型，它会说「可以，用历史数据回测一下」——
这是废话，而模型自己不觉得是废话。**让模型自评可验证性，等于没有闸**。

而「四要素写没写全」是结构问题，代码一眼能查：

    数据对象 asset      申万航运港口指数 / 沪深300 / 中证智能汽车
    事件条件 condition  油轮遇袭当天 / 单日跌幅超5%后 / 政策发布日
    观察窗口 horizon    5/10/20 个交易日
    统计指标 metric     收益中位数 / 正收益概率 / 胜率 / 最大回撤

⇒ **结构检查放代码，语义判断放模型**。放模型只会引入抖动，还要多花一次调用。
（同 `evidence.assemble` 的分工：`same_as` 那种语义判定才交给模型。）

## 四个要素的强度不一样，这是有意的

`asset` / `horizon` / `metric` 是硬判据 —— 它们要求句子里出现**具体的标的、
具体的期数、具体的统计量**，「用历史数据回测看看效果」这种废话三条全过不了。

`condition` 的词面宽松（「后」「当日」「时」都算），单独看拦不住什么。
留它是因为**缺了它说明连事件都没提**，而四条要求全齐才放行 —— 宽松的那条
不降低整体拦截力，却能挡住「沪深300过去5年的收益中位数」这种没有事件界定的题。

⚠️ 按 `always.md` 判据一（闸只留 100% 确定的），这里**不做语义猜测**：
不判「这个指数存不存在」「这个条件合不合理」—— 那是回测层的事，判错了就是误杀。
"""
from __future__ import annotations

import re

# 🔴 四要素的判据。**只查「有没有写出这一类信息」，不查内容对不对。**
PATTERNS = {
    # ⚠️ 必须认得纯指数名（沪深300 / 上证50 / 中证500）：它们是最常用的标的写法，
    #    却不含「指数」二字 —— 漏了这一类，`topic_cluster` spec 自己给的示范
    #    「沪深300历史数据中，单日跌幅超过5%后…」都会被本闸误杀（写测试时抓到）。
    "asset":     re.compile(r"指数|板块|概念|个股|股票|[A-Za-z]?股|基金|ETF|转债|期权|期货"
                            r"|沪深\s*\d+|上证\s*\d+|中证\s*\d+|深证\s*\d+|创业板|科创|恒生|国债"),
    "condition": re.compile(r"后|当日|次日|首个交易日|发布日|公布日|出台|事件|超过|跌|涨"),
    "horizon":   re.compile(r"\d+\s*[/、]?\s*\d*\s*个?交易日|\d+\s*日|\d+\s*个月|\d+\s*周"),
    "metric":    re.compile(r"收益|概率|胜率|回撤|超额|中位数|均值|平均|天数|涨跌幅"),
}


def check_testable(testable: str) -> dict[str, bool]:
    """逐要素返回是否命中。四个全 True 才算合格。"""
    t = testable or ""
    return {k: bool(p.search(t)) for k, p in PATTERNS.items()}


def missing_parts(testable: str) -> list[str]:
    """缺哪几个要素。空列表 ＝ 合格。"""
    return [k for k, ok in check_testable(testable).items() if not ok]


def filter_topics(topics: list[dict]) -> tuple[list[dict], list[tuple[str, list[str]]]]:
    """过闸。返回 `(合格的, [(选题名, 缺的要素), ...])`。

    🔴 **拒收要留痕**：一批全被拦下可能是热点质量差（正常），也可能是
    Clusterer 的 prompt 坏了（事故）—— 不记下来两者分不开
    （同 `fact_builder.build` 那条「拒收理由要留痕」）。
    """
    keep: list[dict] = []
    rejected: list[tuple[str, list[str]]] = []
    for t in topics:
        miss = missing_parts(t.get("testable", ""))
        if miss:
            rejected.append((t.get("name", "?"), miss))
        else:
            keep.append(t)
    return keep, rejected
