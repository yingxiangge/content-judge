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
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .specs.topic_fit import DIRECTIONS, SYSTEM_BLOCKS, render

logger = logging.getLogger(__name__)

# 模型可能把 JSON 包在代码围栏里（带或不带 `json` 标记），或前后再加几句话。
# ⚠️ 与 `specs/x_reply.py:_FENCE_RE` 是同一条正则 —— 两处重复，改一处要改两处。
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.I)

MIN_FIT = 30            # 低于此不进 Pack —— 硬凑的事实会占掉 20 秒里的宝贵时间
MIN_SOURCE_TYPES = 2    # Diversity：至少两种来源类型


@dataclass
class Fit:
    """一条事实对今天这道题的评判。**不持久化。**"""
    index: int                                  # 对应 facts[index]
    topic_fit: int = 0
    covers: list[str] = field(default_factory=list)
    direction: str = "neutral"
    # 🔴 与哪条讲的是同一件事（**更靠前**那条的 index）；不重复为 None。
    #    由模型判 —— 「两条事实是不是同一件事」是语义问题，字面规则做不了：
    #    09-05 实测字面判据在 28 对里误杀 26 对，而模型本来就在逐条读这些事实，
    #    顺手多输出一个编号，零额外调用。调用方据此①挑证据时跳过②写回库永久生效。
    same_as: int | None = None
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
    """从模型输出里抠出 items 列表。抠不出返回 `[]`，**但必须喊一声**。

    🔴 **2026-09-05 修：原来只认 ```` ```json ```` 这一种围栏，且失败时静默返回 []。**
    deepseek-chat 恰好总是吐带 `json` 标记的围栏，于是这个脆弱点一直没暴露；
    当天精排换成 gemini-3.8-flash 后格式稍有不同，**24 条事实全部解析失败**，
    `fit()` 里每个 Fit 停在默认值 ⇒ 日志上是清一色「0分 covers=— why 空」，
    看起来像"模型把所有事实都毙了"，实际是**根本没解析到模型的回答**。

    ⚠️ 同一个包里 `specs/x_reply.py` 早就修过同样的问题（commit `cfa56f0`
    「鲁棒解析 Markdown JSON」），**但没同步到这里** —— 两处各写一份解析必然漂移。
    这里照搬它的三级策略；后续应抽成公共函数，两处共用（改进点，未实施）。
    """
    text = (raw or "").strip()
    if not text:
        logger.warning("[fit] 模型返回空文本 —— 无法解析")
        return []

    def _items(data):
        items = data.get("items") if isinstance(data, dict) else data
        return items if isinstance(items, list) else None

    # ① 围栏内（```json 或裸 ```，前后有话也能提）② 全文直接当 JSON
    m = _FENCE_RE.search(text)
    for cand in ([m.group(1).strip()] if m else []) + [text]:
        try:
            got = _items(json.loads(cand))
            if got is not None:
                return got
        except Exception:      # noqa: BLE001
            pass

    # ③ 括号匹配，抠出首个完整的顶层 JSON 对象
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        got = _items(json.loads(text[start:i + 1]))
                        if got is not None:
                            return got
                    except Exception:      # noqa: BLE001
                        pass
                    break

    # 🔴 **解析不出必须留痕** —— 静默返回 [] 正是这次「全 0 分」查了半天的原因
    logger.warning("[fit] JSON 解析失败，前 200 字：%s", text[:200])
    return []


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
        # 🔴 只收**指向更靠前一条**的编号：模型偶尔会填自己或往后指，
        #    照单全收会绕成环（A 说重复 B、B 说重复 A ⇒ 两条全被跳过，整层空）。
        try:
            s = int(r.get("same_as"))
            out[i].same_as = s - 1 if 0 <= s - 1 < i else None
        except (TypeError, ValueError):
            out[i].same_as = None
        out[i].why = str(r.get("why", ""))[:120]

    # 🔴 **精排结果必须留痕**（2026-09-05 立）：在此之前每条事实的
    #    `topic_fit`/`covers`/`why` 全都算出来了却一行不打，失败时日志只说
    #    「某层没证据」，说不出**为什么**——09-05 老板问「搜了为什么还是没出片」，
    #    只能反查 SQLite 的 facts 表倒推，而且倒推不出模型的判断，白跑一轮。
    #    ⚠️ 这不是「加日志」这种小事：**算了分不留痕 = 这一层永远无法诊断**。
    #    每层各自的问题原文也一并打——`summary()` 只打 id/type/need，
    #    而「C1 到底问的是什么」恰恰是判断模型判得对不对的前提。
    if logger.isEnabledFor(logging.INFO):
        for c in claims:
            logger.info("[fit] %s [%s] %s", c.id, getattr(c, "type", "?"),
                        str(getattr(c, "question", ""))[:60])
        for f, o in zip(facts, out):
            logger.info("[fit] #%-2d %3d分 covers=%-10s %-7s %s | %s",
                        o.index + 1, o.topic_fit, ",".join(o.covers) or "—",
                        o.direction, str(getattr(f, "claim", ""))[:40], o.why[:60])
    return out


def assemble(claims: Sequence[Any], facts: Sequence[Any],
             fits: Sequence[Fit]) -> EvidencePack:
    """按层配齐证据，再做结构检查。

    每层选 `topic_fit` 最高的；争议型额外单独找一条 `counter` ——
    **反例不能靠运气**：按分数排，反例几乎总是排在支持证据后面。
    """
    pack = EvidencePack()
    usable = [f for f in fits if f.usable]

    # 🔴 **一期片子里不许出现同一件事的两个副本**（2026-09-05 加）。
    #    各层原本独立挑「本层最高分」，互相不知道对方挑了什么 —— 09-05 实证：
    #    C1 挑中 #4、C2 挑中 #3，而 #3/#4 是同一份统计的两种措辞，
    #    写稿层收到 4 条副本后按「facts 高度重复」直接拒绝出片，当天缺片。
    #    ⇒ 记下已挑中的**同事组代表**，后面几层遇到同组的往下顺延。
    #    判据用模型给的 `same_as`（语义），不用字面相似度（那玩意 28 对误杀 26 对）。
    def _group(f: Fit) -> int:
        """顺着 same_as 往前找到这一组的代表（同一件事 → 同一个代表）。"""
        seen, i = set(), f.index
        by_idx = {x.index: x for x in fits}
        while True:
            cur = by_idx.get(i)
            if cur is None or cur.same_as is None or i in seen:
                return i
            seen.add(i)
            i = cur.same_as

    allocated_groups: set[int] = set()
    for c in claims:
        picked: list[int] = []
        cand = sorted([f for f in usable if c.id in f.covers],
                      key=lambda x: -x.topic_fit)
        need = set(c.required_evidence)

        # 优先挑选未被前面层挑中的 group 代表，避免多层无脑重复取同一条事实
        if cand:
            best_group = None
            for f in cand:
                g = _group(f)
                if g not in allocated_groups:
                    best_group = g
                    break
            # 若所有 candidate 的 group 都已被前面层挑过（无新鲜事实），则降级复用最高分的 group 代表，保证不因硬锁定而饿死
            if best_group is None:
                best_group = _group(cand[0])
            picked.append(best_group)
            allocated_groups.add(best_group)

        # 需要反例的层：单独挑一条 direction=counter，且不能与上面那条同组
        if "counter" in need:
            ctr = next((f for f in cand if f.direction == "counter"
                        and _group(f) not in picked), None)
            if ctr:
                g_ctr = _group(ctr)
                picked.append(g_ctr)
                allocated_groups.add(g_ctr)
            else:
                pack.missing.append(f"{c.id}[{c.type}] 缺反例/边界证据")
        if not picked:
            pack.missing.append(f"{c.id}[{c.type}] 一条证据都没有")
        if picked:
            pack.slots[c.id] = picked

    # 🔴 第二轮补齐（2026-09-08）：若配完各层主事实后仍有未分配的可用事实（_group 未进 allocated_groups），
    # 按 covers 补进对应层（落实「4 条事实全落在同一层，照播」—— 不让好事实因层槽限制被闲置、进而误触发条数下限流产）
    for c in claims:
        cand = sorted([f for f in usable if c.id in f.covers],
                      key=lambda x: -x.topic_fit)
        for f in cand:
            g = _group(f)
            if g not in allocated_groups:
                if c.id not in pack.slots:
                    pack.slots[c.id] = []
                pack.slots[c.id].append(g)
                allocated_groups.add(g)

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
    # 🔴 **只陈述，不判「完整/不完整」**（2026-09-06 改）：配齐几层已经不是
    #    出片条件了（见 `video_evidence.Result.ok`），再打「❌ 不完整」会让人以为
    #    这期出问题了 —— 而它照样发得出去。**内容硬度要看得见，但不是失败信号。**
    n, total = len(pack.slots), len(claims)
    mark = "●" * n + "○" * max(0, total - n)
    lines = [f"[pack] {mark} {n}/{total} 层有证据 · 用 {len(pack.used())} 条事实"]
    for c in claims:
        ids = pack.slots.get(c.id, [])
        lines.append(f"   {'✓' if ids else '✗'} {c.id} [{c.type}] "
                     f"need={'+'.join(c.required_evidence)} → facts{ids or '（无）'}")
    for m in pack.missing:
        lines.append(f"   · 缺：{m}")   # 不阻断，只留痕
    for w in pack.warnings:
        lines.append(f"   ⚠️ {w}")
    return "\n".join(lines)
