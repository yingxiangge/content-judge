"""评分入口。

    judge(text, spec, source=...) -> Verdict

`spec` 定义这类内容该按什么标准评。**阈值不写死在代码里** —— 报错文和小说章节的
合理长度差一个量级，把一套阈值硬套到另一类内容上，正是让模型注水或编造的常见起因。

主观维度（LLM）是可选的：不给 `llm` 就只跑客观项。
这样任何项目都能零成本先用起来，成本和随机性都由调用方决定要不要引入。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from .dimensions import objective as obj
from .types import DimensionScore, Issue, Severity, Verdict, tier_of


@dataclass
class Spec:
    """一类内容的评分标准。"""
    name: str
    # 客观项
    length_floor: int = 0
    length_target: int = 0
    length_full: float = 0.0
    code_blocks_need: int = 0
    code_blocks_full: float = 0.0
    symbols_full: float = 0.0
    check_format: bool = True
    check_fabrication: bool = True
    # 主观项：维度名 -> 满分
    subjective: dict[str, float] = field(default_factory=dict)
    # 主观项的评分说明，拼进 LLM prompt
    subjective_brief: str = ""

    @property
    def full(self) -> float:
        return (self.length_full + self.code_blocks_full + self.symbols_full
                + sum(self.subjective.values()))


_JSON = re.compile(r"\{.*\}", re.S)


def _parse(raw: str) -> dict:
    m = _JSON.search(raw or "")
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _llm_prompt(text: str, spec: Spec) -> str:
    dims = "\n".join(f'  "{k}": {{"score": <0-{v}>, "evidence": "<≤20字原文>"}}'
                     for k, v in spec.subjective.items())
    return (f"给以下内容打分。{spec.subjective_brief}\n\n"
            f"只输出 JSON，每项都要带原文证据（没有证据的项按 0 分算）：\n"
            f"{{\n{dims}\n}}\n\n内容：\n{text[:14000]}")


def judge(text: str, spec: Spec, source: str = "",
          symbols: list[str] | None = None,
          llm: Callable[[str], str] | None = None) -> Verdict:
    """`llm` 传一个 `prompt -> str` 的可调用对象；不传则只跑客观项。

    `source` 是允许出现的事实来源（素材原文 + 检索资料），用于编造检测。
    """
    v = Verdict(full=spec.full or 100.0)

    if spec.length_full:
        v.dimensions.append(obj.score_length(text, spec.length_floor,
                                             spec.length_target, spec.length_full))
    if spec.code_blocks_full:
        v.dimensions.append(obj.score_code_blocks(text, spec.code_blocks_need,
                                                  spec.code_blocks_full))
    if spec.symbols_full:
        v.dimensions.append(obj.score_symbols(text, symbols or [], spec.symbols_full))

    if spec.check_format:
        v.issues += obj.check_format(text)
    if spec.check_fabrication and source:
        v.issues += obj.check_fabrication(text, source)

    if spec.subjective and llm is not None:
        data = _parse(llm(_llm_prompt(text, spec)))
        for name, full in spec.subjective.items():
            row = data.get(name) or {}
            score = float(row.get("score") or 0)
            ev = str(row.get("evidence") or "")
            # 无证据 = 0 分。V4 的原则：分会飘，证据不会。
            if not ev.strip():
                score = 0.0
                v.issues.append(Issue(name, "no_evidence", Severity.LOW,
                                      "该项未给出原文证据，按 0 分计"))
            v.dimensions.append(DimensionScore(name, round(score, 1), full,
                                               objective=False, evidence=ev))

    # 🔴 分母按**实际评过的维度**算，不是 spec 的理论满分。
    # 否则只跑客观项时，主观项那几十分会计进分母却永远拿不到 —— 一篇好文
    # 会被判成 37/100 的 C 档。分档要有意义，就必须相对于真正评了的东西。
    v.total = sum(d.score for d in v.dimensions)
    v.full = sum(d.full for d in v.dimensions) or 100.0
    v.tier = tier_of(v.total, v.full)
    # 有阻断级问题（编造）时直接压到 C —— 事实错了，写得再好也不能发
    if any(i.severity is Severity.HIGH for i in v.issues):
        v.tier = "C"
    return v
