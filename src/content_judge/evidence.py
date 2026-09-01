# -*- coding: utf-8 -*-
"""证据层 —— TopicFit 精排 + Evidence Pack 组装。

    fit(topic, claims, facts, llm)   → list[Fit]      每条事实对今天这题的贴合度
    assemble(claims, facts, fits)    → EvidencePack   按层配齐 + 结构检查

🔴 **不是「Top N 事实」，是「证据组合」**。选最好的 5 条事实，很可能 5 条
都在回答同一层 —— 成品看着有数据，其实只答了五分之一。要的是
`C1←F03 · C2←F17 · C3←F08` 这样**每层各有一条**。

🔴 **结构检查按 claim 各自的类型走，不一刀切**：争议型缺反例才算不完整，
事实型不需要反例 —— 强行要求就是为形式完整添垃圾（`always.md`
「闸误杀的代价是回落」）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .specs.topic_fit import DIRECTIONS, SYSTEM_BLOCKS, render

_JSON = re.compile(r"```json\s*(.+?)\s*```", re.S)

MIN_FIT = 30            # 低于此不进 Pack —— 硬凑的事实会占掉 20 秒里的宝贵时间
MIN_SOURCE_TYPES = 2    # Diversity：至少两种来源类型


@dataclass
class Fit:
    """一条事实对今天这道题的评判。**不持久化。**"""
    index: int                                  # 对应 facts[index]
    topic_fit: int = 0
    covers: list[str] = field(default_factory=list)
    direction: str = "neutral"
    why: str = ""

    @property
    def usable(self) -> bool:
        return self.topic_fit >= MIN_FIT and bool(self.covers)


@dataclass
class EvidencePack:
    """组装结果。`ok=False` 时 `missing` 说明缺哪一层的哪类证据。"""
    slots: dict[str, list[int]] = field(default_factory=dict)   # claim_id → facts 下标
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ok: bool = False

    def used(self) -> list[int]:
        seen: list[int] = []
        for ids in self.slots.values():
            for i in ids:
                if i not in seen:
                    seen.append(i)
        return seen


def _parse(raw: str) -> list[dict]:
    m = _JSON.search(raw or "")
    try:
        data = json.loads(m.group(1) if m else (raw or "").strip())
    except json.JSONDecodeError:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def fit(topic: str, claims: Sequence[Any], facts: Sequence[Any],
        llm: Callable[[str], str]) -> list[Fit]:
    """批量精排。返回**与 facts 等长、顺序一致**的结果。

    ⚠️ 模型漏答某条时留一个空 `Fit`（`topic_fit=0` ⇒ 自动不可用），
    **不静默丢弃** —— 少一条就是少一个候选，而调用方看不出来。
    """
    out = [Fit(index=i) for i in range(len(facts))]
    if not facts or not claims:
        return out
    prompt = "\n\n".join(SYSTEM_BLOCKS) + "\n\n" + render(topic, list(claims), list(facts))
    valid_ids = {c.id for c in claims}
    for r in _parse(llm(prompt)):
        try:
            i = int(r.get("id", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= i < len(out):
            continue
        try:
            out[i].topic_fit = max(0, min(100, int(r.get("topic_fit", 0))))
        except (TypeError, ValueError):
            pass
        # 🔴 只收真实存在的 claim id —— 模型偶尔会造出 "C9"，
        #    放进去会让覆盖检查以为某层齐了。
        cov = r.get("covers")
        out[i].covers = [str(c) for c in cov if str(c) in valid_ids] if isinstance(cov, list) else []
        d = str(r.get("direction") or "neutral")
        out[i].direction = d if d in DIRECTIONS else "neutral"
        out[i].why = str(r.get("why", ""))[:120]
    return out


def assemble(claims: Sequence[Any], facts: Sequence[Any],
             fits: Sequence[Fit]) -> EvidencePack:
    """按层配齐证据，再做结构检查。

    每层选 `topic_fit` 最高的；争议型额外单独找一条 `counter` ——
    **反例不能靠运气**：按分数排，反例几乎总是排在支持证据后面。
    """
    pack = EvidencePack()
    usable = [f for f in fits if f.usable]

    for c in claims:
        picked: list[int] = []
        cand = sorted([f for f in usable if c.id in f.covers],
                      key=lambda x: -x.topic_fit)
        need = set(c.required_evidence)
        if cand:
            picked.append(cand[0].index)
        # 需要反例的层：单独挑一条 direction=counter，且不能与上面那条重复
        if "counter" in need:
            ctr = next((f for f in cand if f.direction == "counter"
                        and f.index not in picked), None)
            if ctr:
                picked.append(ctr.index)
            else:
                pack.missing.append(f"{c.id}[{c.type}] 缺反例/边界证据")
        if not picked:
            pack.missing.append(f"{c.id}[{c.type}] 一条证据都没有")
        if picked:
            pack.slots[c.id] = picked

    used = pack.used()
    # ── Diversity：不是「证据越多越好」，是**结构完整** ──
    types = {getattr(facts[i], "source_type", "") for i in used}
    types.discard("")
    if len(types) < MIN_SOURCE_TYPES and len(used) >= MIN_SOURCE_TYPES:
        pack.warnings.append(f"来源类型只有 {len(types)} 种（{'/'.join(types) or '未知'}）"
                             f"，建议 ≥{MIN_SOURCE_TYPES} 种")
    if used and not any(getattr(facts[i], "source_type", "") in
                        ("original_data", "calculation") for i in used):
        pack.warnings.append("没有一条原始数据或回测证据，全是二手转述")

    pack.ok = not pack.missing
    return pack


def summary(pack: EvidencePack, claims: Sequence[Any]) -> str:
    lines = [f"[pack] {'✅ 完整' if pack.ok else '❌ 不完整'} · "
             f"{len(pack.slots)}/{len(claims)} 层有证据 · 用 {len(pack.used())} 条事实"]
    for c in claims:
        ids = pack.slots.get(c.id, [])
        lines.append(f"   {'✓' if ids else '✗'} {c.id} [{c.type}] "
                     f"need={'+'.join(c.required_evidence)} → facts{ids or '（无）'}")
    for m in pack.missing:
        lines.append(f"   🔴 {m}")
    for w in pack.warnings:
        lines.append(f"   ⚠️ {w}")
    return "\n".join(lines)
