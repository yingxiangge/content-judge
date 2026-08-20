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
    # 🔴 **可插拔客观项**（2026-08-20 加）：上面那几项（字数/代码块/技术符号）是
    # 报错文这一类内容的度量，换个场景就完全不适用 —— 量化视频口播只有 60 来字、
    # 零代码块，要量的是「数字是否全部来自 facts」「18 条素材用了几条」，
    # 而 `Spec` 此前**没有任何扩展位**，这类检查只能留在各自的业务代码里手写。
    # 实测后果：同一套「编造检测」在 blog 走 `check_fabrication`、在量化口播是
    # `gen_pk_video.py` 里手写的四道闸、X 回帖那份还没搬 —— 一套逻辑写了两遍半。
    # ⇒ 通用的留在框架里，场景专属的由 spec 注入。签名：
    #     fn(text: str, ctx: dict) -> list[DimensionScore | Issue]
    # `ctx` 由调用方经 `judge(..., context=...)` 传入（口播传 facts/看点候选等）。
    extra_objective: list[Callable[[str, dict], list]] = field(default_factory=list)
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
          llm: Callable[[str], str] | None = None,
          context: dict | None = None) -> Verdict:
    """`llm` 传一个 `prompt -> str` 的可调用对象；不传则只跑客观项。

    `source` 是允许出现的事实来源（素材原文 + 检索资料），用于编造检测。
    `context` 传给 `spec.extra_objective` 里的场景专属检查器（见 Spec 那里的注释）。
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

    # 场景专属客观项。⚠️ **一个检查器抛异常不能拖垮整次评分** —— 它们是各产线自己
    # 注入的代码，质量参差；评分挂掉会让调用方失去唯一的质量信号，比少一项检查更糟。
    for fn in spec.extra_objective:
        try:
            for r in fn(text, context or {}) or []:
                (v.issues if isinstance(r, Issue) else v.dimensions).append(r)
        except Exception as e:      # noqa: BLE001
            v.issues.append(Issue(getattr(fn, "__name__", "extra"), "checker_error",
                                  Severity.LOW, f"客观项检查器异常：{e}"))

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
