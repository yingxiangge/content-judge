# -*- coding: utf-8 -*-
"""Claim 层 —— 选题拆解，以及由类型推出的证据要求。

用法：

    from content_judge.claims import decompose
    claims = decompose("大跌之后该抄底还是扛着", llm=my_llm, gate="B 打脸")
    for c in claims:
        print(c.id, c.type, c.required_evidence, c.recall_keys())

🔴 `required_evidence` **由 `type` 推出，不让模型自由给** —— 模型每次给的
组合会飘，而"争议型需要反例、事实型不需要"是**规则**不是判断。
`type` 本身也由层位置定（2026-09-11 起），模型只写子问题与检索词。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .specs.claim_decompose import (EVIDENCE_BY_TYPE, LAYER_TYPES, SYSTEM_BLOCKS,
                                    render_topic)

_JSON = re.compile(r"```json\s*(.+?)\s*```", re.S)
DEFAULT_TYPE = "factual"     # 类型判不出时的落点：**事实型要求最松**，
                             # 不会去找不存在的反方证据 ⇒ 不会造成误杀式阻断


@dataclass
class Claim:
    """选题的一层。`type` 由层位置定（`LAYER_TYPES`），`search` 是这一层的检索词。

    ⚠️ `asset` / `condition` / `action` 已不再由拆层产出（2026-09-11），字段保留只为兼容
    旧调用方构造；`action` 恒为 none ⇒ 召回里的方向过滤与负召回实际不生效（早于本次即如此）。
    """
    id: str
    question: str
    type: str = DEFAULT_TYPE
    asset: str = ""
    condition: str = ""
    action: str = "none"
    why: str = ""
    # 新闻检索关键词（空格分隔）—— 补搜按层各搜一次用它，不再拿选题问句去搜
    search: str = ""

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
                f"{self.question[:30]} · search={self.search}")


def _parse(raw: str) -> dict | list[dict]:
    m = _JSON.search(raw or "")
    text = m.group(1) if m else (raw or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data


def decompose(topic: str, llm: Callable[[str], str],
              gate: str = "", why: str = "", max_claims: int = 5) -> list[Claim]:
    """热点事件 → 4 维度客观事实 claims。拆不出返回空列表。

    2026-09-11 老板定：接入 4 维度客观事实检索词（政策通报/规模供需/核心企业/价格市场）。
    """
    prompt = "\n\n".join(SYSTEM_BLOCKS) + "\n\n" + render_topic(topic, gate, why)
    parsed = _parse(llm(prompt))
    out: list[Claim] = []

    # 优先解析 4 维度字典: {"政策通报": "...", "规模供需": "...", "核心企业": "...", "价格市场": "..."}
    dim_keys = ("政策通报", "规模供需", "核心企业", "价格市场")
    if isinstance(parsed, dict) and any(k in parsed for k in dim_keys):
        for i, name in enumerate(dim_keys, 1):
            sq = str(parsed.get(name) or "").strip()
            if not sq:
                continue
            t = LAYER_TYPES[i - 1] if i <= len(LAYER_TYPES) else DEFAULT_TYPE
            out.append(Claim(id=f"C{i}", question=f"{name}事实", type=t, search=sq))
    elif isinstance(parsed, dict) and "claims" in parsed:
        items = parsed.get("claims") or []
        for i, r in enumerate(items, 1):
            if not isinstance(r, dict):
                continue
            q = str(r.get("question") or "").strip()
            sq = str(r.get("search") or "").strip()
            if not q and not sq:
                continue
            t = LAYER_TYPES[i - 1] if i <= len(LAYER_TYPES) else DEFAULT_TYPE
            out.append(Claim(id=f"C{i}", question=q or f"维度{i}", type=t, search=sq))
    elif isinstance(parsed, list):
        for i, r in enumerate(parsed, 1):
            if not isinstance(r, dict):
                continue
            q = str(r.get("question") or "").strip()
            sq = str(r.get("search") or "").strip()
            if not q and not sq:
                continue
            t = LAYER_TYPES[i - 1] if i <= len(LAYER_TYPES) else DEFAULT_TYPE
            out.append(Claim(id=f"C{i}", question=q or f"维度{i}", type=t, search=sq))

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
