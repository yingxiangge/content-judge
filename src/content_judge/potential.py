# -*- coding: utf-8 -*-
"""内容潜力打分器 —— 批量评「原料」，不评成品。

用法（`llm` / `count_numbers` / `banned` 全部由调用方注入）：

    from content_judge.potential import score
    res = score(items, llm=my_llm, count_numbers=my_counter, banned=WORDS)
    for r in res:
        print(r.title, r.gate, r.total, r.verdict, r.blocked)

🔴 **三个注入点都是刻意的**：
  · `llm` —— 同 `judge()`：不给就只跑客观项，包不持有全局状态；
  · `count_numbers` —— 数字判据**已经存在于业务侧**（闸①②在用同一个函数）；
  · `banned` —— 本包不含一个业务词（同 horizon/goofish 的分工）。

🔴 **定位：爆款门禁（2026-09-30 重构）**：
  “视频定的是爆款才发，平庸不发，宁缺毋滥（战略空仓）”。
  详见 `specs/content_potential.py` 文件头。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .specs.content_potential import (GATE_KEYS, SYSTEM_BLOCKS,
                                      WEIGHTS, render_batch)

_JSON = re.compile(r"```json\s*(.+?)\s*```", re.S)


@dataclass
class Score:
    """一条原料的打分结果。"""
    title: str
    gate: Optional[dict] = None
    expected: str = ""
    test: str = ""
    # 新版三维张力评分 (0-5)
    decision_urgency: int = 0
    event_tension: int = 0
    cost_of_error: int = 0
    # 历史字段兼容
    audience: int = 0
    relevance: int = 0
    tension: int = 0
    utility: int = 0
    specificity: int = 0                  # 可核验数字个数（客观项·代码算）
    blocked: list[str] = field(default_factory=list)   # 命中的合规词
    why: str = ""

    @property
    def total(self) -> float:
        """总分：G1×6 + G2×8 + G3×6（满分 100 分）。由代码死公式算，禁止 LLM 自算漂移。"""
        # 兼容旧打分模式
        if self.decision_urgency == 0 and self.event_tension == 0 and self.cost_of_error == 0:
            if any((self.audience, self.relevance, self.tension, self.utility)):
                return round(
                    self.audience * 3.0
                    + self.relevance * 2.5
                    + self.tension * 2.5
                    + self.utility * 2.0, 1)
        return float(
            self.decision_urgency * WEIGHTS.get("decision_urgency", 6)
            + self.event_tension * WEIGHTS.get("event_tension", 8)
            + self.cost_of_error * WEIGHTS.get("cost_of_error", 6)
        )

    @property
    def verdict(self) -> str:
        """三档裁决：publish（顶级爆款才发）/ hold（平庸扣下不发）/ eliminated（淘汰）。"""
        hard_ok = (
            isinstance(self.gate, dict)
            and all(self.gate.get(k) is True for k in GATE_KEYS)
            and not self.blocked
        )
        if not hard_ok:
            return "eliminated"
        if (
            self.decision_urgency >= 3
            and self.event_tension >= 3
            and self.cost_of_error >= 3
            and self.total >= 70.0
        ):
            return "publish"
        return "hold"

    @property
    def passed(self) -> bool:
        """过不过闸。🔴 只有达到 publish 标准的顶级爆款才算过闸放行！

        硬门淘汰（eliminated）与平庸及格品（hold）均不过闸，坚决空仓。
        """
        return self.verdict == "publish"

    @property
    def hook_type(self) -> str:
        return self.verdict

    def line(self) -> str:
        if not isinstance(self.gate, dict):
            g = "硬门未过"
        else:
            miss = [k for k in GATE_KEYS if self.gate.get(k) is not True]
            g = f"缺{','.join(miss)}" if miss else self.verdict
        b = f" · 🚫{','.join(self.blocked)}" if self.blocked else ""
        return (f"[{'✓' if self.passed else '✗'}] {self.total:>5.1f} {g:<10} "
                f"G1:{self.decision_urgency} G2:{self.event_tension} G3:{self.cost_of_error} "
                f"{b} · {self.title[:26]} · {self.why[:40]}")


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
    """批量打分。返回**与输入等长、顺序一致**的结果。

    ⚠️ 顺序与长度必须对得上 —— 调用方要拿 `items[i]` 配 `result[i]`。
    模型漏答某条时补一个空 `Score`（`gate=None` ⇒ 自动被判不过闸），
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
        g = r.get("gate")
        out[idx].gate = g if isinstance(g, dict) else None
        
        scores_obj = r.get("scores") if isinstance(r.get("scores"), dict) else r
        for k, attr in (
            ("decision_urgency", "decision_urgency"),
            ("event_tension", "event_tension"),
            ("cost_of_error", "cost_of_error"),
            ("audience", "audience"),
            ("relevance", "relevance"),
            ("tension", "tension"),
            ("utility", "utility"),
        ):
            try:
                val = scores_obj.get(k)
                if val is not None:
                    out[idx].__dict__[attr] = max(0, min(10, int(val)))
            except (TypeError, ValueError):
                pass
        
        out[idx].expected = str(r.get("expected", ""))[:120]
        out[idx].test = str(r.get("test", ""))[:120]
        out[idx].why = str(r.get("why", ""))[:240]
    return out


def summary(scores: Sequence[Score]) -> str:
    """一行体检，给日志和人工看。"""
    pub = [s for s in scores if s.passed]
    hld = [s for s in scores if s.verdict == "hold"]
    elm = [s for s in scores if s.verdict == "eliminated"]
    return (f"[potential] {len(pub)}条爆款(publish) · {len(hld)}条平庸扣下(hold) · "
            f"{len(elm)}条硬门淘汰(eliminated)"
            f"{f' · 合规拦截:{sum(1 for s in scores if s.blocked)}' if any(s.blocked for s in scores) else ''}")
