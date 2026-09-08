# -*- coding: utf-8 -*-
from dataclasses import dataclass
from content_judge.evidence import Fit, assemble, EvidencePack


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


def test_assemble_second_pass_allocates_all_usable_facts():
    """验证当多条可用事实落在同一层时，第二轮补齐会将未分配事实收入 slots，满足条数要求。"""
    claims = [
        DummyClaim(id="C1", type="factual", question="Q1", required_evidence=["direct"]),
        DummyClaim(id="C2", type="controversial", question="Q2", required_evidence=["support", "counter"]),
        DummyClaim(id="C3", type="causal", question="Q3", required_evidence=["mechanism"]),
        DummyClaim(id="C4", type="controversial", question="Q4", required_evidence=["support", "counter"]),
    ]

    # C3 有两条 usable 事实 (fit 82 与 fit 68)，C4 有一条 (fit 75)
    fits = [
        Fit(index=0, topic_fit=68, covers=["C3"], direction="support"),
        Fit(index=1, topic_fit=82, covers=["C3", "C4"], direction="support"),
        Fit(index=2, topic_fit=42, covers=[], direction="neutral"),
        Fit(index=3, topic_fit=75, covers=["C4"], direction="support"),
        Fit(index=4, topic_fit=30, covers=[], direction="neutral"),
    ]
    facts = [DummyFact(f"Fact {i}") for i in range(5)]

    pack = assemble(claims, facts, fits)
    # 应包含 1, 0, 3 全部 3 条可用事实
    assert set(pack.used()) == {0, 1, 3}
    assert 0 in pack.slots["C3"]
    assert 1 in pack.slots["C3"]
    assert 3 in pack.slots["C4"]
