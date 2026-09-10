"""X (Twitter) 回帖质检标准。

核心防御：
1. **量化指标与数字编造拦截**：出现「指标名 + 数字」（如 win rate 40%, ARR $5M, 胜率 80%, CAGR 12%），
   而该数字在原推（source）中不存在 → 判定为编造，严重度 HIGH（直接阻断）。
2. **拒绝通用编造误杀**：`check_fabrication=False`。X 回帖的本质是技术交流与答疑（如「pinning to 3.11.2 fixed it」
   或「bump to 16 GB」），版本号/容量/commit 属于回答本身，要求它们在原推里有出处是错误判据。
3. **零 LLM、纯客观项**：毫秒级响应，杜绝 LLM 裁判的打分波动。

## v5（2026-09-02）：从「四档凭感觉」改回扣分制，并分层

起因：v4.1(08-24) 把扣分制换成 A/B/C/D 四档，理由是「废除主观扣分项」，
但换上来的档位描述（"Sharp, insightful, witty"、"Stops the scroll"）**比原来的
扣分项更主观** —— 为了治主观，把唯一能算的公式也扔了。09-02 实测后果：
`Mannenprobleem!`（一个荷兰语单词、♥3、发布 2 分钟）拿到 A 档 95 分推给老板。

叠加第二个病：审核调用显式关了 thinking（`{"thinking":{"type":"disabled"}}`，
08-30 为防思维链吃满 max_tokens 而加）。**模型没有内部思考，而 rubric 却要求它
「先在心里问三个问题」——它做不到**；唯一能推理的地方是输出，而旧输出格式只有
GRADE/SCORE/REASON 三行，没给判断留位置。

⇒ 照小说 V4 的思路重写：**明确的扣分红线 + 每项可解释可复现 + 分数只服务于筛选**。

### 分层（这是关键，v6 沿用）

    机械规则  → 程序判，零 token：字符数（<=280 物理上限）、语种、固定句式、编造数字
    语义规则  → LLM 判

**词表全留在程序层，prompt 里一个词都不出现** ⇒ always.md 判据二
「需要同步给 prompt 的词就不该在闸里」在这里自动满足，没有需要同步的东西。

## v6（2026-09-04）：扣分制 → 维度得分制（老板定，照 grok 方案）

v5 那句「绝不加加分项，否则退回 v4.1 老路」**已作废**，因为它的前提没了：

- v5 是为「**非推理模型 + 显式关 thinking**」设计的。一票扣固定值（触发即 -30）
  是那个前提下唯一可靠的形态 —— 模型不会推理，只能做二元判断。
- 09-04 起判分改走**带推理的免费池**（不传 thinking 参数 = 用模型默认，实测单条
  思考 1000~4000 token）。**前提变了，为旧前提定的结论就不该继续当标准。**
- 一杆子扣分本身也不合理：同一条 R0 触发，「毫无信息」和「信息略少」扣一样多的
  20 分，把连续的质量差异压成了二元开关。

v6 形态（分值见 `DIMENSIONS`，prompt 从常量生成）：

    A1 一票否决    → 非英文 / 超 280 字符 / 纯附和 / AI 客套开场（程序层，零 token）
    硬过滤（SKIP） → 原推值不值得回：S1/S2/S3，触发即阻断，不进打分
    维度得分 100   → 内容质量 60 + 互动潜力 25 + 上下文匹配 15
    发布门槛       → PASS_SCORE

🔴 **分数只有一个来源：维度得分。维度之外不加分、不扣分**（老板 2026-09-04 定）。
   加减分是双重计分 —— 「一手经验」本来就该在 specificity 拿分，「AI 腔」本来就该在
   readability 丢分，在总分外再算一次是重复计量，还让分数不再等于「各项挣到多少」。
   ⇒ 已删除：`BONUS_MAX`（原 +15）、`PENALTY["R1"]`（原 -25）及其 `AI_SYNTAX` 词表。

⚠️ 选哪条发仍然是人在 TG 里做的事，打分器只负责排序与挡住明显不能发的。
"""
from __future__ import annotations

import json
import re

from ..judge import Spec
from ..types import DimensionScore, Issue, Severity

# 🔴 **2026-09-10：编造检测从程序层挪进语义层**（老板定「可以有外部数据源，
#    只是不能说错误的或编造的」）。原 `_METRIC_NUM_RE` + `check_metric_fabrication`
#    的判据是「指标词 + 原推里没有的数字 ⇒ 一票否决」，是纯字面匹配，有两个病：
#
#    ① **误杀**：`returns?` 命中的是普通英语动词 —— 实测
#       `a schema check that returns 0 on malformed args` 被判编造指标毙掉。
#    ② **判据本身就错**：它禁的是「原推没有的数字」，而真正该禁的是
#       「**关于原作者/其项目的**数字，却不是原推给的」。公共技术事实
#       （版本号、默认值）是身份信号的载体，禁掉它等于禁掉目的本身。
#
#    「这个数字是在描述谁」需要语义判断，正则永远分不出来 —— 按 `always.md` 判据一
#    「一条规则如果需要豁免，它就不是闸」：它需要为公共事实开口子，说明它本来就不该在闸里。
#    ⇒ 判定移入 `SEMANTIC_RUBRIC` 的 `fabrication` 字段，程序层不再管。
#    ⚠️ 08-13「首条候选就编造他人交易数据」那次事故的**防线没有撤**，只是换了执行者。

# ══════════════════════════════════════════════════════════════════
# v5 程序层：机械规则，零 token
# ══════════════════════════════════════════════════════════════════

MAX_CHARS = 280          # X 单推硬上限

# A1 一票否决 —— 纯附和 / 空洞捧场
# ⚠️ **"100%" 已于 2026-09-10 撤出**：它是**子串**匹配，而 `100%` 在技术回帖里
#    极常见 —— 实测 `cut our token spend by 100% on repeated calls` 被判「纯附和」
#    一票否决。判据一：一条规则如果需要为正当用途开口子，它就不是闸。
#    单独成句的 "100%" 确实是附和，但那要看语境，交给语义层的 attention 维度评低分即可。
PURE_AGREEMENT = (
    "good point", "i agree", "totally agree", "well said", "so true",
    "couldn't agree more", "exactly this",
)

# A1 一票否决 —— AI 客套开场（只判开头，句中出现不算）
AI_FILLER_OPENER = (
    "thanks for sharing", "interesting perspective", "fascinating take",
    "great post", "great point", "love this take", "well put",
)

# ☠️ 原 `AI_SYNTAX` 词表（10 个 LLM 套话句式）与 R1 -25 扣分已于 2026-09-04 删除：
#    分数只能来自维度得分，AI 腔 = readability / value 不得分，不在总分外另扣。
#    更严重的客套开场仍由上面的 `AI_FILLER_OPENER` 一票否决拦着，
#    且生成端 prompt（`content_writer.specs.x_reply`）本就明令禁止这类句式。

# ══════════════════════════════════════════════════════════════════
# v7（2026-09-10 老板定）：加法十维 → 乘法四维
# ══════════════════════════════════════════════════════════════════
#
# ## 为什么推翻 v6
#
# v6 是十个维度**相加**，衡量的是「这条回帖本身好不好」。而老板 09-10 把目的定死：
#
#     回帖不是为了和原作者聊天，也不是为了让原作者点赞。
#     是借热帖流量，让陌生人注意到你 → 点进主页 → Follow。
#
# 加法结构与这个目的有两处硬冲突：
#
# ① **跑题帖能压线放行**。09-03 为治跑题立的 R7（-30 分硬扣），09-04 改维度制时
#    随扣分制一起删掉、**连回归单测也删了**（`cfa56f0`）。此后跑题只能靠
#    relevance(10) + gap_fit(8) + context_fit(7) 丢分 ⇒ 最坏 100−25 = **75，
#    恰好等于门槛，放行**。改成乘法后 relevance=0 ⇒ 总分 0，**这道防线由结构保证，
#    不再需要单独一条会被后人删掉的规则**。
# ② **没有一个维度在管转化**。十项全在衡量「写得好不好」，而目的是「会不会被点进主页」。
#
# ## 四个因子（`Exposure` 不在这里 —— 那是阶段 0 `x_hot_filter` 的活）
#
#     Reply Value = Relevance × Attention × Identity × Curiosity
#
# ## 🔴 为什么用**几何平均**而不是直接连乘
#
# 直接连乘（四个 0~10 相乘再 /100）分布过陡：四项全 8 分只有 41 分，
# 全 9 分才 66 分 —— 分数会失去可读性，且没人说得清 41 分意味着什么。
# 几何平均 `(r·a·i·c)^(1/4) × 10` **保住了乘法的全部性质**（任何一项为 0 ⇒ 总分 0），
# 同时让分数回到「大致等于平均水平」的直观尺度：四项全 8 分 = 80 分。
FACTORS: dict[str, str] = {
    "relevance":  "是不是在回这条推。跑题、套话、能原样贴在任何帖子下面 → 0",
    "attention":  "在一屏评论区里，读者会不会停在这句。正确但平庸 → 低分",
    "identity":   "读完能否隐约看出这人是干什么的。通用聪明人腔调、无实践视角 → 低分",
    "curiosity":  "会不会让人想「这谁？他还知道什么？」。话说尽了、结论闭合 → 低分",
}

FULL_SCORE = 100.0      # 几何平均后的满分

# ── 硬过滤：判「这条原推值不值得回」，触发即 SKIP，不进打分 ──────────────
# 对应 grok 流程的第 2 步「决定回不回」——他把它放在打分之前，不是打分的一个维度。
# 保留 09-02 加这三条的原始理由：没有它，`Mannenprobleem!`（一个荷兰语单词、♥3）
# 那类源推会因为「回帖写得妙」被放行。
SKIP_RULES = {
    "S1": "源推没有观点、判断、提问或冲突，普通读者没有回应的动机",
    "S2": "缺上下文/未解释的缩写或黑话，读者看不出在讨论什么（题材专业不算，读者是开发者）",
    "S3": "纯个人生活/纪念日/宠物/风景，读者没有公共利害",
}

_LATIN = re.compile(r"[A-Za-z]")
_NON_LATIN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\u0400-\u04ff\u0600-\u06ff]")
_WORD = re.compile(r"\b[\w'-]+\b")

# ══════════════════════════════════════════════════════════════════
# v5 LLM 层：只判「原推与回帖之间的关系」这类真需要理解的
# ══════════════════════════════════════════════════════════════════
#
# 🔴 **2026-09-04 更正**：原文写「审核调用关了 thinking，写出来是模型唯一的思考手段」——
#    那是 08-30 为防思维链吃满 max_tokens 而关 thinking 时代的理由，**现在判分已改走
#    带推理的免费池（不传 thinking 参数 = 用模型默认）**，那个前提不成立了。
#    结构化输出保留下来的理由变成两条：① 逐项举证可审计；
#    ② 解析不到就阻断，杜绝「静默当成无问题」这一经典失效形态。
#
# ⚠️ **调用方的 max_tokens 至少给 4000**（2026-09-02 实测，同一条样本同一模型）：
#        max_tokens=800   finish_reason=length  completion=27  → 输出被截且在复述 prompt
#        max_tokens=4000  finish_reason=stop    completion=47  → 完整 8 行
#    注意 completion 只有 27 却报 length —— OpenAI 兼容层下 Gemini 的 max_tokens
#    不等于「实际能写多少」，给小了会**在还没开始答就被截断**。
#    当天首轮 A/B 就栽在这里：给了 800，Gemini 三个型号全部「输出格式不合规」被判 0 分，
#    差点得出「Gemini 不达标」的错误结论 —— 实为参数配错，与模型能力无关。
#    ⇒ 同 `BUG_LOG @ 2026-08-30`「max_tokens 配小 → 静默失效」的第 N 次，
#      判据不变：**看 finish_reason，不要看分数**。

SEMANTIC_RUBRIC = """You are judging one X (Twitter) reply. Three jobs, in order.

## Job 1 — is this SOURCE POST worth replying to at all?

If any rule fires, the whole thing is a SKIP and you score nothing:
{skip_rules}

## Job 2 — integrity check

Set "fabrication" to true if the reply does either of these:
- states a number, metric or result about the author or their project that does
  not appear in the source post;
- claims the writer personally did, tested, built or witnessed something.
A confident general fact is NOT fabrication. A judgement phrased as a judgement
is NOT a claim of personal experience.

## Job 3 — score four factors, each 0 to 10

The reply exists to make a stranger scrolling this thread want to check who the
writer is. It is not for the author, and not for likes. Score against that goal.

{factor_rules}

Score what the reply actually earns. An average reply lands mid-range.
A reply that only rephrases the source, only cheerleads, or could sit unchanged
under a thousand unrelated posts earns 0 on relevance.

There is no separate bonus or penalty outside these four factors: the total is
their geometric mean, so any factor scored 0 makes the whole reply score 0.

SOURCE POST:
\"\"\"{{source}}\"\"\"

REPLY:
\"\"\"{{reply}}\"\"\"

Output ONE JSON object, nothing else — no prose, no code fence:
{{{{"decision":"POST","skip":"none","fabrication":false,"factors":{{{{{factor_keys}}}}},"notes":"one short line of evidence"}}}}

When skipping, set decision to "SKIP", skip to the rule id that fired, and leave
every factor at 0.
""".format(
    skip_rules="\n".join(f"- {k} ({v})" for k, v in SKIP_RULES.items()),
    factor_rules="\n".join(f"- {k} (0-10): {v}" for k, v in FACTORS.items()),
    factor_keys=",".join(f'"{k}":0' for k in FACTORS),
)

# 模型可能把 JSON 包在代码围栏或前后加话，做鲁棒提取
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.I)


def _parse_verdict(raw: str) -> dict | None:
    """从模型输出里抠出 JSON。抠不出返回 None（调用方据此阻断，绝不静默放行）。"""
    text = (raw or "").strip()
    if not text:
        return None

    # 1. 尝试从 markdown 围栏中提取
    m_fence = _FENCE_RE.search(text)
    candidates = [m_fence.group(1).strip()] if m_fence else []
    candidates.append(text)

    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 2. 括号匹配提取首个有效顶层 JSON 对象
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start : i + 1]
                try:
                    data = json.loads(chunk)
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
                break

    return None


def check_reply_rules(text: str, ctx: dict) -> list:
    """X 回帖 v6 打分：程序层硬否决 + LLM 层维度得分，满分 100。

    `ctx["source"]` 原推；`ctx["llm"]` 可选，签名 `prompt -> str`。
    不传 llm 就只跑程序层（毫秒级、零 token），此时只有 A1/R1 生效。
    """
    source = str(ctx.get("source") or "")
    reply = text or ""
    low = reply.lower()
    issues: list = []

    # ── A1 一票否决 ──
    rejects: list[str] = []
    if _NON_LATIN.search(reply):
        rejects.append("非英文（含中日韩/西里尔/阿拉伯字符）")
    elif not _LATIN.search(reply):
        rejects.append("非英文（无拉丁字母）")
    if len(reply) > MAX_CHARS:
        rejects.append(f"超 {MAX_CHARS} 字符（{len(reply)}）")
    for p in PURE_AGREEMENT:
        if p in low:
            rejects.append(f"纯附和「{p}」")
            break
    head = low.lstrip('"\u201c \t')
    for p in AI_FILLER_OPENER:
        if head.startswith(p):
            rejects.append(f"AI 客套开场「{p}」")
            break
    if rejects:
        for r in rejects:
            issues.append(Issue("A1", "hard_reject", Severity.HIGH,
                                f"A1 一票否决：{r}", evidence=reply[:60]))
        issues.append(DimensionScore("回帖质量", 0.0, float(FULL_SCORE), objective=True,
                                     evidence="; ".join(rejects)))
        return issues

    # ── LLM 层：维度得分（分数的唯一来源）──
    llm = ctx.get("llm")
    if not callable(llm):
        # 没注入 llm = 只跑 A1 硬否决（毫秒级、零 token）。此时没有维度分可言，
        # 给满分表示「A1 没拦住」，由调用方决定这种模式下要不要放行。
        issues.append(DimensionScore(
            "回帖质量", float(FULL_SCORE), float(FULL_SCORE), objective=True,
            evidence="仅 A1 硬否决层（未注入 llm，无维度分）",
        ))
        return issues

    try:
        raw = llm(SEMANTIC_RUBRIC.format(source=source, reply=reply)) or ""
    except Exception as e:                                       # noqa: BLE001
        issues.append(Issue("semantic", "llm_error", Severity.HIGH,
                            f"语义层调用失败（安全阻断）：{type(e).__name__}: {e}"))
        issues.append(DimensionScore("回帖质量", 0.0, float(FULL_SCORE), objective=False,
                                     evidence="LLM 调用失败"))
        return issues

    data = _parse_verdict(raw)
    if data is None:
        # 🔴 解析不到 = 模型没按格式答 ⇒ 显式阻断。
        #    绝不静默当成「满分」—— 那正是「静默失效」的经典形态。
        issues.append(Issue("semantic", "unparsable", Severity.HIGH,
                            f"语义层未输出可解析 JSON（安全阻断）：{raw[:80]!r}"))
        issues.append(DimensionScore("回帖质量", 0.0, float(FULL_SCORE), objective=False,
                                     evidence="输出格式不合规"))
        return issues

    # 硬过滤：原推不值得回 → 直接阻断（grok 流程第 2 步，与打分分离）
    skip = str(data.get("skip") or "none").strip().upper()
    if str(data.get("decision") or "").strip().upper() == "SKIP" or skip in SKIP_RULES:
        why = SKIP_RULES.get(skip, str(data.get("notes") or "未说明"))
        issues.append(Issue("source", "skip", Severity.HIGH,
                            f"源推不值得回帖（{skip}）：{why}", evidence=source[:60]))
        issues.append(DimensionScore("回帖质量", 0.0, float(FULL_SCORE), objective=False,
                                     evidence=f"SKIP {skip}"))
        return issues

    # 诚信：编造关于作者的数字 / 声称亲自做过 → 阻断（2026-09-10 从程序层挪来）
    if bool(data.get("fabrication")):
        issues.append(Issue("事实", "fabricated", Severity.HIGH,
                            f"编造或冒充亲历：{str(data.get('notes') or '未说明')[:80]}",
                            evidence=reply[:60]))
        issues.append(DimensionScore("回帖质量", 0.0, FULL_SCORE, objective=False,
                                     evidence="fabrication"))
        return issues

    # 四因子几何平均。缺项按 0 算（不猜、不补默认值）。
    # 🔴 **乘法不是加法**：任何一项为 0，总分即 0 —— 跑题（relevance=0）由此
    #    被结构挡住，不再依赖一条会被后人删掉的规则（09-03 立、09-04 删的 R7）。
    facs = data.get("factors")
    facs = facs if isinstance(facs, dict) else {}
    vals: list[float] = []
    detail: list[str] = []
    for key in FACTORS:
        try:
            v = float(facs.get(key, 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        v = max(0.0, min(10.0, v))
        vals.append(v)
        detail.append(f"{key}{v:.0f}")

    if any(v <= 0 for v in vals):
        score = 0.0
    else:
        prod = 1.0
        for v in vals:
            prod *= v
        score = (prod ** (1.0 / len(vals))) * 10.0

    note = str(data.get("notes") or "").strip()
    ev = " ".join(detail) + f" → {score:.0f}"
    if note:
        ev += f" | {note[:60]}"

    issues.append(DimensionScore("回帖质量", round(score, 1), FULL_SCORE,
                                 objective=False, evidence=ev))
    return issues


X_REPLY = Spec(
    name="x_reply",
    length_full=0.0,
    code_blocks_full=0.0,
    symbols_full=0.0,
    check_format=False,
    check_fabrication=False,  # 🔴 必须为 False：不误杀正常的版本号/容量/commit 建议
    # 走 extra_objective（而非框架的 `subjective`）：本 spec 要在**同一次** LLM 调用里
    # 同时做「硬过滤 SKIP」「诚信判定」「四因子打分」，框架的 subjective 只能打分。
    # LLM 经 `context={"llm": fn}` 注入，见 check_reply_rules。
    # 🔴 2026-09-10 `check_metric_fabrication` 已删除 —— 判据挪进语义层，见文件上方。
    extra_objective=[check_reply_rules],
)

# 发布门槛（2026-09-04 老板定 75）：任意 A1 一票否决 / SKIP / 解析失败
# 直接 REJECT，与分数无关。
# ⚠️ 沿革：80(v4.1 档位) → 75(v5 扣分) → 70(v6 初版) → 75(v6 老板定) → 70(v7 待校准)。
#    **分制换过，同一个数字就不是同一个意思**，每次都要重新理解：
#      v5 的 75 = 「100 起扣，最多扣一项 R0」
#      v6 的 75 = 「十个维度相加实际挣到 75」
#      v7 的 70 = 「四因子几何平均 70」，即**平均每项 7 分**
#    几何平均下四项全 8 分 = 80、全 7 分 = 70、全 6 分 = 60，尺度直观但**分布未知**。
# 🔴 **这个 70 是占位值，必须用真实语料校准**（老板 09-10 定「跑分布再定门槛」）。
#    09-04 那次的教训正是「分制换了却沿用旧数字」—— 当时 v6 的 Good 样本只有 72 分，
#    卡在 75 门槛下，而没人发现是门槛跟分制脱节。**校准前别把它当结论引用。**
PASS_SCORE = 70
