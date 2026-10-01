# -*- coding: utf-8 -*-
"""两道硬门 + 三维张力爆款门禁单元测试。

验证内容：
1. 两道硬门逐门证伪（任一为 False 直接 eliminated）；
2. 评分解耦：代码计算死公式 G1×6 + G2×8 + G3×6 == 100；
3. 三档裁决：publish（顶级爆款才发）/ hold（平庸扣下）/ eliminated（淘汰）；
4. 真实生产案例双向证伪与金丝雀回归。
"""
from content_judge.potential import Score
from content_judge.specs.content_potential import GATE_KEYS, WEIGHTS

ALL_PASS = {"direct_impact": True, "actionable_choice": True}


def test_hard_gates_and_publish_pass():
    """顶级爆款：两道硬门全过且三维均达标(>=3)且总分>=70 -> publish。"""
    s = Score(
        title="宇邦新材控制权变更复牌，追涨胜率多大？",
        gate=dict(ALL_PASS),
        decision_urgency=4,
        event_tension=4,
        cost_of_error=4,
    )
    assert s.passed is True
    assert s.verdict == "publish"
    assert s.total == 80.0  # 4*6 + 4*8 + 4*6 = 24 + 32 + 24 = 80.0


def test_each_gate_alone_can_block():
    """🔴 逐门证伪：任一硬门为 False 直接 eliminated 淘汰。"""
    for k in GATE_KEYS:
        g = dict(ALL_PASS)
        g[k] = False
        s = Score(
            title="测试题",
            gate=g,
            decision_urgency=5,
            event_tension=5,
            cost_of_error=5,
        )
        assert s.passed is False, f"{k}=False 竟然放行了"
        assert s.verdict == "eliminated"
        assert k in s.line(), f"line() 没说明缺的是 {k}"


def test_hold_verdict_when_score_subpar():
    """平庸及格品扣下留存：硬门虽过但反差不足或总分不足 -> hold（不予放行出片）。"""
    # 模拟微盘股反弹诱多：G2=2(日常波动猜多空)
    s = Score(
        title="微盘股反弹超30%，资金回流还是诱多出逃？",
        gate=dict(ALL_PASS),
        decision_urgency=3,
        event_tension=2,
        cost_of_error=3,
    )
    assert s.passed is False
    assert s.verdict == "hold"
    assert s.total == 52.0  # 3*6 + 2*8 + 3*6 = 18 + 16 + 18 = 52.0


def test_high_score_cannot_buy_a_pass():
    """满分也救不了硬门 —— 淘汰只由硬门决定，不由分数决定。"""
    s = Score(
        title="测试题",
        gate=None,
        decision_urgency=5,
        event_tension=5,
        cost_of_error=5,
    )
    assert s.total == 100.0
    assert s.passed is False
    assert s.verdict == "eliminated"


def test_compliance_block_overrides_gates():
    """合规黑名单词命中直接一票否决。"""
    s = Score(
        title="荐股测试题",
        gate=dict(ALL_PASS),
        blocked=["荐股"],
        decision_urgency=5,
        event_tension=5,
        cost_of_error=5,
    )
    assert s.passed is False
    assert s.verdict == "eliminated"


def test_weights_match_comment():
    """注释公式 == 代码公式：G1×6 + G2×8 + G3×6 = 100，逐字对齐。"""
    assert WEIGHTS == {"decision_urgency": 6, "event_tension": 8, "cost_of_error": 6}
    assert sum(WEIGHTS.values()) * 5 == 100  # 满分各5分时为 30+40+30=100
    s1 = Score(title="x", decision_urgency=5, event_tension=0, cost_of_error=0)
    assert s1.total == 30.0
    s2 = Score(title="x", decision_urgency=0, event_tension=5, cost_of_error=0)
    assert s2.total == 40.0
    s3 = Score(title="x", decision_urgency=0, event_tension=0, cost_of_error=5)
    assert s3.total == 30.0


def test_render_batch_strictly_strips_facts():
    """验证 render_batch 无论输入什么字典或字符串，送给模型的 user JSON 数组绝对只含净标题，物理阻断事实。"""
    import json
    from content_judge.specs.content_potential import render_batch

    items = [
        # 情况 1：字典里带单独的 event/fact/body 字段
        {
            "name": "银行股还能拿吗？",
            "event": "财政部拟发行特别国债注资大行",
            "body": "详细新闻正文...",
            "fact": "大盘微跌",
        },
        # 情况 2：标题字符串内拼接了事实与前缀
        {
            "title": "【标题】昇腾迎来突破，算力却领跌，该抄底还是止损？ | 【事实】昇腾960发布，寒武纪跌3.54%",
        },
        # 情况 3：key 叫 topic，且带换行事实
        {
            "topic": "三桶油放量调整，高股息要减仓吗？\n事实：布伦特原油昨夜跌超4%",
        },
    ]

    rendered_json = render_batch(items)
    data = json.loads(rendered_json)

    assert len(data) == 3
    # 验证字段只有 id 和 topic
    for item in data:
        assert set(item.keys()) == {"id", "topic"}
        assert "事实" not in item["topic"]

    assert data[0]["topic"] == "【标题】银行股还能拿吗？"
    assert data[1]["topic"] == "【标题】昇腾迎来突破，算力却领跌，该抄底还是止损？"
    assert data[2]["topic"] == "【标题】三桶油放量调整，高股息要减仓吗？"

