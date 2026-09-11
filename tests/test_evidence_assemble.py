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


def test_assemble_one_fact_per_layer_by_fit():
    """每层只取 1 条：精排最高、且未被前面层用过；不再额外配反例，也不再补齐剩余事实。"""
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
    assert pack.slots == {"C1": [5], "C2": [2], "C3": [1], "C4": [3]}   # C4 顺延：#1 已被 C3 用
    assert sorted(pack.used()) == [1, 2, 3, 5]                             # #0、反例 #4 都不再塞进来
