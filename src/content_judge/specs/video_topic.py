# -*- coding: utf-8 -*-
"""topic 形态口播质检 spec（2026-09-05 重建）。

## 它为什么在基础设施包里

原来的 `specs/video_spec.py` 定义了 daily/weekly/preview/topic 四份 spec，
**2026-09-01 17:06 的重构 `11f6666`「移除业务专属 video_spec spec」把引用删了**，
而那个文件**从来没有被 git 跟踪过**（`git log --all --full-history` 查无记录）⇒
文件随之消失，恢复不了。后果是 `SPEC_BY_KIND["daily"]` 从此 KeyError，
被 `narration_judge` 的 `except Exception` 吞掉 ⇒ **口播质检静默失效 4 天**
（09-01 17:06 ~ 09-05），期间所有成片无人把关。

⚠️ **重建时一度放去业务仓 `quant_system/lib/`，当天被老板纠正、已搬回。**
当时的理由是「那次重构说要保持通用，不该被业务 spec 污染」——**这条站不住**：
本目录里 `topic_fit` / `claim_decompose` / `content_potential` 全是视频线的业务判据，
`x_reply` 更是 09-04 明确「**生成与判分双双收归基础设施包**，业务仓只做编排」
（铁律 #1）。同样是内容判据，一个在包里一个在业务仓，就是不一致，
而且绕开了 `SPEC_BY_KIND` 这张注册表。
⇒ **判据一律住这儿；业务仓只负责调用。**

上一份丢失的真正原因也不是"放错仓"，是**它没进 git**。本文件已在版本控制内
⇒「历史即备份」（`always.md` Safe Write SOP）。

## 判据只留今天有实证的，不凭空发明

`always.md` 判据一：**闸只留 100% 确定的**，模糊的交给评分器。下面三项都是可计算的
结构判据，不需要语义理解，也不存在"需要豁免"的情况：

- `每段停顿`   09-05 实证：口播三段全无标点，TTS 无处换气、字幕按长度硬切把
               「正股7元」劈成两半，成片不可读。对应 `video_script.py` 铁律 3。
- `段间不复读` 09-05 实证：seg3「但下修和回售套利基本亏损」与 seg4「其实下修套利和
               回售套利基本亏损」几乎逐字重复。09-01 那份历史记录里
               `不复读(客观)` 本来就占 20 分，是被一起弄丢的判据之一。
- `信息量`     唯一的主观项，交给 LLM。

⚠️ **没有加"上屏与口播同页同事"这一项**：它今天已经在 `video_script.py` 的 prompt
里治了并验证通过，而质检要查它得让调用方额外传 `answer`（big/points/steps）——
改动面更大。等 prompt 那条被证明不够用了再加，不提前造闸（`always.md` 判据三）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _p in ("/mnt/datadisk0/content-judge/src", "/root/content-judge/src"):
    if Path(_p).is_dir() and _p not in sys.path:
        sys.path.append(_p)

from content_judge.judge import Spec                    # noqa: E402
from content_judge.types import DimensionScore, Issue, Severity   # noqa: E402

# 停顿标点：能让 TTS 换气、让字幕切在语义边界上的那些。
# ⚠️ 句号不在内 —— `video_script.py` 铁律 3 明令「每段内禁止出现句号」，
#    把它算成合格停顿会与 prompt 打架（`always.md`：spec 比 prompt 严一个词就是误杀，
#    反过来松一个词就是漏网）。
_PAUSE = re.compile(r"[，,、；;？?！!]")

# 短句本来就不需要断。hook「下修套利真能稳赚吗」9 字，一口气读完最自然。
# 12 是按 4.5 字/秒的语速取的：≈2.7 秒不换气是舒适上限。
_PAUSE_MIN_LEN = 12

# 段间最长公共子串达到这个长度就算复读。
# 09-05 实证：seg3/seg4 重叠「下修套利和回售套利基本亏损」共 13 字。
# 取 8 是为了留出余量 —— 术语本身就长（"转股溢价率"5 字、"可转债"3 字），
# 两段各提一次同一个术语很正常，8 字以上的连续重合才是真复读。
_REPEAT_MIN = 8


def _lcs_len(a: str, b: str) -> tuple[int, str]:
    """最长公共**连续**子串的长度与内容。段数最多 5、每段 ≤25 字，O(n²) 足够。"""
    best, best_s = 0, ""
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k > best:
                best, best_s = k, a[i:i + k]
    return best, best_s


def check_pause(text: str, ctx: dict) -> list:
    """每段必须有停顿标点 —— 满分 15。"""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    bad = [l for l in lines if len(l) >= _PAUSE_MIN_LEN and not _PAUSE.search(l)]
    out: list = []
    if bad:
        out.append(Issue(dimension="每段停顿", kind="no_pause",
                         severity=Severity.HIGH,
                         detail=f"{len(bad)} 段无停顿标点，最长一段 {len(max(bad, key=len))} 字："
                                f"{max(bad, key=len)[:30]}"))
    got = 0.0 if bad else 15.0
    out.append(DimensionScore(name="每段停顿", score=got, full=15.0, objective=True,
                              evidence="" if not bad else
                              f"{len(bad)}/{len(lines)} 段一路读到底，TTS 无处换气、字幕会硬切"))
    return out


def check_no_repeat(text: str, ctx: dict) -> list:
    """段与段之间不许复读 —— 满分 20（沿用 09-01 那份记录里的配分）。"""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    worst, worst_pair = 0, ""
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            n, s = _lcs_len(lines[i], lines[j])
            if n > worst:
                worst, worst_pair = n, s
    out: list = []
    if worst >= _REPEAT_MIN:
        out.append(Issue(dimension="段间不复读", kind="repeat",
                         severity=Severity.HIGH,
                         detail=f"两段重复 {worst} 字：「{worst_pair}」"))
    got = 0.0 if worst >= _REPEAT_MIN else 20.0
    out.append(DimensionScore(name="段间不复读", score=got, full=20.0, objective=True,
                              evidence="" if worst < _REPEAT_MIN else
                              f"最长重复 {worst} 字：{worst_pair}"))
    return out


VIDEO_SPEC_TOPIC = Spec(
    name="topic_narration",
    # 口播是纯文本，没有 markdown 结构与代码块，这几项一律关掉 ——
    # 开着就是拿报错文的度量去量 20 秒口播（正是 09-01 那次「回落 daily spec」
    # 当场判出假 HIGH 的原因）。
    check_format=False,
    check_fabrication=False,   # 数字核验另有两道：facts 回原文核验 + `_fabricated_metric`
    extra_objective=[check_pause, check_no_repeat],
    subjective={"信息量": 15},
    subjective_brief=(
        "信息量：这 5 段口播里有多少条**观众记得住的结论**。\n"
        "- 高分：每段都给出一个带数字的结论，且段与段讲的是不同侧面\n"
        "- 低分：绕来绕去只讲了一件事，或全是过程没有结论\n"
        "⚠️ 不要评文采、不要评是否专业，只评「听完能记住几件事」。"
    ),
)
