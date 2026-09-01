# -*- coding: utf-8 -*-
"""Claim 层 —— 选题拆解，以及由类型推出的证据要求。

用法：

    from content_judge.claims import decompose
    claims = decompose("大跌之后该抄底还是扛着", llm=my_llm, gate="B 打脸")
    for c in claims:
        print(c.id, c.type, c.required_evidence, c.recall_keys())

🔴 `required_evidence` **由 `type` 推出，不让模型自由给** —— 模型每次给的
组合会飘，而"争议型需要反例、事实型不需要"是**规则**不是判断。
模型只负责判 `type`（那才是判断），映射由代码做。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .specs.claim_decompose import (EVIDENCE_BY_TYPE, SYSTEM_BLOCKS,
                                    render_topic)

_JSON = re.compile(r"```json\s*(.+?)\s*```", re.S)
VALID_ACTIONS = {"buy", "sell", "hold", "none"}
DEFAULT_TYPE = "factual"     # 类型判不出时的落点：**事实型要求最松**，
                             # 不会去找不存在的反方证据 ⇒ 不会造成误杀式阻断


@dataclass
class Claim:
    """选题的一层。**带检索键** —— 拆完直接能喂给 `factstore.recall()`。"""
    id: str
    question: str
    type: str = DEFAULT_TYPE
    asset: str = ""
    condition: str = ""
    action: str = "none"
    why: str = ""

    @property
    def required_evidence(self) -> tuple[str, ...]:
        """这一层需要哪几类证据。**由类型推出，不由模型给。**"""
        return EVIDENCE_BY_TYPE.get(self.type, EVIDENCE_BY_TYPE[DEFAULT_TYPE])

    def recall_keys(self) -> dict:
        """直接可用的召回条件。"""
        return {"asset": self.asset, "condition": self.condition,
                "action": self.action if self.action != "none" else ""}

    def line(self) -> str:
        return (f"{self.id} [{self.type:<13}] need={'+'.join(self.required_evidence):<22} "
                f"{self.question[:30]} · {self.asset}/{self.condition}/{self.action}")


def _parse(raw: str) -> list[dict]:
    m = _JSON.search(raw or "")
    try:
        data = json.loads(m.group(1) if m else (raw or "").strip())
    except json.JSONDecodeError:
        return []
    items = data.get("claims") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def decompose(topic: str, llm: Callable[[str], str],
              gate: str = "", why: str = "", max_claims: int = 5) -> list[Claim]:
    """选题 → claims。拆不出返回空列表（调用方据此换选题或退回整题处理）。

    ⚠️ **超出 `max_claims` 的截断从后往前** —— prompt 已要求按重要性排序，
    20 秒讲不完时该砍的是最边缘那层，不是随机丢。
    """
    prompt = "\n\n".join(SYSTEM_BLOCKS) + "\n\n" + render_topic(topic, gate, why)
    out: list[Claim] = []
    for i, r in enumerate(_parse(llm(prompt)), 1):
        if not isinstance(r, dict):
            continue
        q = str(r.get("question") or "").strip()
        if not q:
            continue
        t = str(r.get("type") or "").strip().lower()
        if t not in EVIDENCE_BY_TYPE:
            t = DEFAULT_TYPE           # 判不出走最松的，避免误杀式阻断
        a = str(r.get("action") or "none").strip().lower()
        out.append(Claim(
            id=str(r.get("id") or f"C{i}"), question=q, type=t,
            asset=str(r.get("asset") or ""), condition=str(r.get("condition") or ""),
            action=a if a in VALID_ACTIONS else "none",
            why=str(r.get("why") or "")[:100]))
    return out[:max_claims]


def coverage_report(claims: Sequence[Claim], filled: dict) -> str:
    """哪几层配齐了证据、哪几层缺。`filled` = {claim_id: [证据类型…]}。

    🔴 这是 Evidence Pack 判「完整」的依据 —— **按 claim 各自的类型查**，
    不是一刀切要求每层都有反例。
    """
    lines = []
    for c in claims:
        have = set(filled.get(c.id, ()))
        miss = [e for e in c.required_evidence if e not in have]
        lines.append(f"  {'✓' if not miss else '✗'} {c.id} [{c.type}] "
                     + (f"缺 {'+'.join(miss)}" if miss else "齐"))
    return "\n".join(lines)
