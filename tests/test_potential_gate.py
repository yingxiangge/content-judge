# -*- coding: utf-8 -*-
"""三道硬门：全过才放行，缺一条即拦。语料取 2026-09-06 实测的真实判定。"""
from content_judge.potential import Score
from content_judge.specs.content_potential import GATE_KEYS, HOOK_TYPES, WEIGHTS

ALL_PASS = {"account_action": True, "secondary_market": True,
            "content_hook": True, "hook_type": "warning"}


def test_all_three_gates_pass():
    s = Score(title="中东油轮遇袭油运股能不能追", gate=dict(ALL_PASS),
              relevance=8, tension=8, utility=8)
    assert s.passed is True
    assert s.hook_type == "warning"
    assert s.total == 80.0          # 8×35 + 8×40 + 8×25 = 800 → /10


def test_each_gate_alone_can_block():
    """🔴 逐门证伪：任一门为 False 都必须拦下 —— 不是「大部分过了就算过」。"""
    for k in GATE_KEYS:
        g = dict(ALL_PASS)
        g[k] = False
        s = Score(title="x", gate=g, relevance=10, tension=10, utility=10)
        assert s.passed is False, f"{k}=False 竟然放行了"
        assert k in s.line(), f"line() 没说明缺的是 {k}"


def test_high_score_cannot_buy_a_pass():
    """满分也救不了硬门 —— 淘汰只由硬门决定，不由分数决定。"""
    s = Score(title="x", gate=None, relevance=10, tension=10, utility=10)
    assert s.total == 100.0 and s.passed is False


def test_legacy_string_gate_is_not_accepted():
    """模型偶尔回旧格式 "A"/"B"/"C" —— 必须当没过，不许静默塞进去。"""
    s = Score(title="x", gate="A", relevance=9, tension=9, utility=9)
    assert s.passed is False


def test_compliance_block_overrides_gates():
    s = Score(title="x", gate=dict(ALL_PASS), blocked=["荐股"],
              relevance=9, tension=9, utility=9)
    assert s.passed is False


def test_weights_match_comment():
    """注释公式 == 代码公式：35/40/25，总分 = Σ(维度×权重)/10。"""
    assert WEIGHTS == {"relevance": 35, "tension": 40, "utility": 25}
    assert sum(WEIGHTS.values()) == 100
    s = Score(title="x", relevance=10, tension=0, utility=0)
    assert s.total == 35.0
    assert set(HOOK_TYPES) == {"warning", "debunk", "counterintuitive"}
