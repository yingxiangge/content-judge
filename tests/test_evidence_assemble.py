# -*- coding: utf-8 -*-
from dataclasses import dataclass
from content_judge.evidence import Fit, assemble, EvidencePack, MAX_PACK_FACTS


@dataclass
class DummyClaim:
    id: str
    type: str
    question: str
    required_evidence: list


@dataclass
class DummyFact:
    claim: str
    source_type: str = "news"


def test_assemble_round_robin_sequential_completion():
    """保底每层 1 条后，按维度精排分数降序，轮流顺序补齐次优事实，绝不一股脑偏向单一维度。"""
    claims = [
        DummyClaim(id="C1", type="factual", question="Q1", required_evidence=["direct"]),
        DummyClaim(id="C2", type="controversial", question="Q2", required_evidence=["support", "counter"]),
        DummyClaim(id="C3", type="causal", question="Q3", required_evidence=["mechanism"]),
        DummyClaim(id="C4", type="causal", question="Q4", required_evidence=["mechanism"]),
    ]
    fits = [
        Fit(index=0, topic_fit=68, covers=["C3"], direction="support"),
        Fit(index=1, topic_fit=82, covers=["C3", "C4"], direction="support"),
        Fit(index=2, topic_fit=90, covers=["C2"], direction="support"),
        Fit(index=3, topic_fit=75, covers=["C4"], direction="support"),
        Fit(index=4, topic_fit=70, covers=["C2"], direction="counter"),
        Fit(index=5, topic_fit=95, covers=["C1"], direction="neutral"),
    ]
    facts = [DummyFact(f"Fact {i}") for i in range(6)]

    pack = assemble(claims, facts, fits)
    # 第一轮保底：C1:[5], C2:[2], C3:[1], C4:[3]
    # 第二轮按维度得分(C1 95 > C2 90 > C3 82 > C4 75)轮询：C2 补 #4，C3 补 #0
    assert pack.slots == {"C1": [5], "C2": [2, 4], "C3": [1, 0], "C4": [3]}
    assert sorted(pack.used()) == [0, 1, 2, 3, 4, 5]


def test_assemble_caps_at_max_pack_facts():
    """事实总数严格封顶 MAX_PACK_FACTS (8 条)，防止大库膨胀时塞爆写稿层。"""
    claims = [
        DummyClaim(id="C1", type="factual", question="Q1", required_evidence=["direct"]),
        DummyClaim(id="C2", type="causal", question="Q2", required_evidence=["mechanism"]),
    ]
    # 构造 12 条可用事实，全部覆盖 C1 和 C2
    fits = [Fit(index=i, topic_fit=95 - i, covers=["C1", "C2"], direction="support") for i in range(12)]
    facts = [DummyFact(f"Fact {i}") for i in range(12)]

    pack = assemble(claims, facts, fits)
    assert len(pack.used()) == MAX_PACK_FACTS  # 恒定封顶 8 条
    assert len(pack.used()) == 8


def test_assemble_does_not_dump_all_to_single_dimension():
    """顺序轮流补齐：C1 即使有多个候选，也绝不能在一轮内全吃光，必须把机会留给 C2。"""
    claims = [
        DummyClaim(id="C1", type="factual", question="Q1", required_evidence=["direct"]),
        DummyClaim(id="C2", type="causal", question="Q2", required_evidence=["mechanism"]),
    ]
    fits = [
        Fit(index=0, topic_fit=95, covers=["C1"]),
        Fit(index=1, topic_fit=90, covers=["C2"]),
        Fit(index=2, topic_fit=88, covers=["C1"]),
        Fit(index=3, topic_fit=87, covers=["C1"]),
        Fit(index=4, topic_fit=85, covers=["C2"]),
    ]
    facts = [DummyFact(f"Fact {i}") for i in range(5)]

    pack = assemble(claims, facts, fits)
    # 第一轮：C1 拿 #0，C2 拿 #1
    # 第二轮第 1 圈：C1 拿 #2，C2 拿 #4（C2 在本圈得到平衡分配）
    # 第二轮第 2 圈：C1 拿 #3
    assert pack.slots["C1"] == [0, 2, 3]
    assert pack.slots["C2"] == [1, 4]
