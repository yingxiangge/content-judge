# -*- coding: utf-8 -*-
"""内容潜力排除器 —— 批量评「原料」，不评成品。

用法（`llm` / `count_numbers` / `banned` 全部由调用方注入）：

    from content_judge.potential import score
    res = score(items, llm=my_llm, count_numbers=my_counter, banned=WORDS)
    for r in res:
        print(r.title, r.result, r.hit_rule, r.passed, r.reason)

🔴 **三个注入点都是刻意的**：
  · `llm` —— 同 `judge()`：不给就只跑客观项，包不持有全局状态；
  · `count_numbers` —— 数字判据**已经存在于业务侧**（闸①②在用同一个函数）；
  · `banned` —— 本包不含一个业务词（同 horizon/goofish 的分工）。

🔴 **定位：选题排除器（2026-10-03 重构）**：
  “只根据标题本身判断是否命中六类已知低效特征，不打分、不排序、命中任意一类即 reject，全不命中才 pass”。
  详见 `specs/content_potential.py` 文件头。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .specs.content_potential import RULE_KEYS, SYSTEM_BLOCKS, render_batch

_JSON = re.compile(r"```json\s*(.+?)\s*```", re.S)


@dataclass
class Score:
    """一条原料的排除器审查结果。"""
    title: str
    result: str = "reject"                             # pass / reject
    hit_rule: Optional[str] = None                    # R1 / R2 / R3 / R4 / R5 / R6 / None
    reason: str = ""                                  # 规则测试证据说明
    blocked: list[str] = field(default_factory=list)  # 命中的合规词

    # 历史字段兼容（用于向下游保持接口一致）
    gate: Optional[dict] = None
    expected: str = ""
    test: str = ""
    why: str = ""                                     # 同 reason
    specificity: int = 0                              # 可核验数字个数（客观项·代码算）
    decision_urgency: int = 0
    event_tension: int = 0
    cost_of_error: int = 0
    audience: int = 0
    relevance: int = 0
    tension: int = 0
    utility: int = 0

    @property
    def total(self) -> float:
        """排除器不打分，pass 则为满分 100.0，reject 为 0.0。"""
        return 100.0 if self.passed else 0.0

    @property
    def verdict(self) -> str:
        """三档裁决兼容：pass（通过）/ reject（排除淘汰）。"""
        return "pass" if self.passed else "reject"

    @property
    def passed(self) -> bool:
        """过不过闸。🔴 只有通过排除器（pass）且未命中合规词才算过闸放行！"""
        return self.result == "pass" and not self.blocked

    @property
    def hook_type(self) -> str:
        return self.verdict

    def line(self) -> str:
        status = "✓ pass" if self.passed else f"✗ reject ({self.hit_rule or 'blocked'})"
        b = f" · 🚫{','.join(self.blocked)}" if self.blocked else ""
        return f"[{status}] {b} · {self.title[:30]} · {self.reason[:60]}"


def _parse(raw: str) -> list[dict]:
    raw = (raw or "").strip()
    m = _JSON.search(raw)
    blob = m.group(1) if m else raw
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        s = blob.find("{")
        e = blob.rfind("}")
        if s != -1 and e != -1:
            try:
                data = json.loads(blob[s:e+1])
            except Exception:
                return []
        else:
            return []
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def score(items: Sequence[dict],
          llm: Callable[[str], str] | None = None,
          count_numbers: Callable[[str], int] | None = None,
          banned: Sequence[str] = ()) -> list[Score]:
    """批量审查。返回**与输入等长、顺序一致**的结果。

    ⚠️ 顺序与长度必须对得上 —— 调用方要拿 `items[i]` 配 `result[i]`。
    模型漏答某条时补一个默认 `Score(result='reject')`，
    **不许静默丢弃**：少一条就是少一个候选，而调用方看不出来。
    """
    out = [Score(title=str(it.get("name") or it.get("title", ""))) for it in items]
    if not items:
        return out

    # ── 客观项：代码算，不依赖模型 ──
    for i, it in enumerate(items):
        blob = f"{it.get('title', '')}\n{it.get('body', '')}"
        if count_numbers:
            out[i].specificity = count_numbers(blob)
        title = str(it.get("title", ""))
        out[i].blocked = [w for w in banned if w in title]
        if out[i].blocked:
            out[i].result = "reject"
            out[i].hit_rule = "COMPLIANCE"
            out[i].reason = f"命中文本合规拦截词：{','.join(out[i].blocked)}"
            out[i].why = out[i].reason

    if llm is None:
        return out

    prompt = "\n\n".join(SYSTEM_BLOCKS) + "\n\n" + render_batch(list(items))
    for r in _parse(llm(prompt)):
        try:
            idx = int(r.get("id", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= idx < len(out):
            continue
        # 如果已被客观合规项拦截，不被模型覆盖
        if out[idx].blocked:
            continue

        res_str = str(r.get("result", "reject")).strip().lower()
        out[idx].result = "pass" if res_str == "pass" else "reject"
        out[idx].hit_rule = r.get("hit_rule") if out[idx].result == "reject" else None
        out[idx].reason = str(r.get("reason", ""))
        out[idx].why = out[idx].reason
        out[idx].gate = {"passed": out[idx].passed, "hit_rule": out[idx].hit_rule}
    return out


def summary(scores: Sequence[Score]) -> str:
    """一行体检，给日志和人工看。"""
    passed_cnt = sum(1 for s in scores if s.passed)
    rejected_cnt = len(scores) - passed_cnt
    hits: dict[str, int] = {}
    for s in scores:
        if not s.passed and s.hit_rule:
            hits[s.hit_rule] = hits.get(s.hit_rule, 0) + 1
    hit_desc = ", ".join(f"{k}:{v}" for k, v in sorted(hits.items()))
    comp_desc = f" · 合规拦截:{sum(1 for s in scores if s.blocked)}" if any(s.blocked for s in scores) else ""
    return f"[potential] {passed_cnt}条通过(pass) · {rejected_cnt}条淘汰(reject) ({hit_desc or '全部通过'}){comp_desc}"

