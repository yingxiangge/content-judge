# -*- coding: utf-8 -*-
"""内容潜力打分器 —— 批量评「原料」，不评成品。

用法（`llm` / `count_numbers` / `banned` 全部由调用方注入）：

    from content_judge.potential import score
    res = score(items, llm=my_llm, count_numbers=my_counter, banned=WORDS)
    for r in res:
        print(r.title, r.gate, r.total, r.blocked)

🔴 **三个注入点都是刻意的**：
  · `llm` —— 同 `judge()`：不给就只跑客观项，包不持有全局状态；
  · `count_numbers` —— 数字判据**已经存在于业务侧**（闸①②在用同一个函数）。
    在这里再实现一份，两份哪天分叉了，同一个数会被闸和打分给出不同结论；
  · `banned` —— 本包不含一个业务词（同 horizon/goofish 的分工）。

**定位是淘汰器不是预测器**，详见 `specs/content_potential.py` 文件头。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .specs.content_potential import (GATES, SYSTEM_BLOCKS, WEIGHTS,
                                      render_batch)

_JSON = re.compile(r"```json\s*(.+?)\s*```", re.S)


@dataclass
class Score:
    """一条原料的打分结果。"""
    title: str
    gate: Optional[str] = None            # "A"/"B"/"C"/None —— None = 三条转发理由都不沾
    relevance: int = 0
    tension: int = 0
    utility: int = 0
    specificity: int = 0                  # 可核验数字个数（客观项·代码算）
    blocked: list[str] = field(default_factory=list)   # 命中的合规词
    why: str = ""

    @property
    def total(self) -> float:
        """三维加权。**只用于排序，不用于淘汰**（淘汰看 `passed`）。"""
        return round(
            self.relevance * WEIGHTS["relevance"]
            + self.tension * WEIGHTS["tension"]
            + self.utility * WEIGHTS["utility"], 1) / 10

    @property
    def passed(self) -> bool:
        """过不过闸。🔴 **只看硬门与合规，与分数无关。**"""
        return self.gate in GATES and not self.blocked

    def line(self) -> str:
        g = f"闸{self.gate}" if self.gate else "无转发理由"
        b = f" · 🚫{','.join(self.blocked)}" if self.blocked else ""
        return (f"[{'✓' if self.passed else '✗'}] {self.total:>5.1f} {g:<10} "
                f"R{self.relevance} T{self.tension} U{self.utility} "
                f"S{self.specificity}{b} · {self.title[:26]} · {self.why[:40]}")


def _parse(raw: str) -> list[dict]:
    m = _JSON.search(raw or "")
    blob = m.group(1) if m else (raw or "").strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
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
    out = [Score(title=str(it.get("title", ""))) for it in items]
    if not items:
        return out

    # ── 客观项：代码算，不依赖模型 ──
    for i, it in enumerate(items):
        blob = f"{it.get('title', '')}\n{it.get('body', '')}"
        if count_numbers:
            out[i].specificity = count_numbers(blob)
        # 🔴 **选题标题只扫营销词，不扫操作词**（2026-09-01 实测修正）。
        # 首跑实测：「新股破发能抄底吗」64.5 分、闸 A 过了，却因标题含「抄底」被拦 ——
        # 而那是**真人的问法**，不是我们在建议抄底。`belief_facts` 早写过同一条：
        # 「F1 豁免（真人问句原样，「割」「补仓」本就是问法的一部分）」。
        # ⇒ 调用方传进来的 `banned` 应当只含**营销类**（涨停/买入/推荐/牛股 ——
        #   标题出现这些说明这个选题本身就是荐股）；操作类（抄底/止损/加仓）
        #   由出片链的闸③在**我们自己写的文案**上拦，那里才是红线所在。
        # ⚠️ 正文一律不扫：正文是别人的原始素材，拦它等于把整个财经语料判死。
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
        out[idx].gate = g if g in GATES else None
        for k in ("relevance", "tension", "utility"):
            try:
                out[idx].__dict__[k] = max(0, min(10, int(r.get(k, 0))))
            except (TypeError, ValueError):
                pass
        out[idx].why = str(r.get("why", ""))[:120]
    return out


def summary(scores: Sequence[Score]) -> str:
    """一行体检，给日志和人工看。"""
    ok = [s for s in scores if s.passed]
    gates = {g: sum(1 for s in scores if s.gate == g) for g in GATES}
    return (f"[potential] {len(ok)}/{len(scores)} 过闸 · "
            + " ".join(f"{g}:{n}" for g, n in gates.items())
            + f" · 无理由:{sum(1 for s in scores if not s.gate)}"
            + f" · 合规拦截:{sum(1 for s in scores if s.blocked)}")
