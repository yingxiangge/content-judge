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

# 🔴 完整中英文量化与增长指标词表（禁止随意删减！包含 08-15 点名补入的 CAGR / churn 等）
_METRIC_NUM_RE = re.compile(
    r'(?:'
    # 中文（量化金融与统计）
    r'夏普|IC值?|年化|月化|日化|周化|回撤|胜率|收益率|波动率|超额|阿尔法|贝塔|'
    r'仓位|杠杆|溢价率?|换手率?|盈亏比|期望值|准确率|月活|留存|转化|'
    # 英文·量化金融（注意：win[- ]?rate 必须支持连字符）
    r'sharpe|alpha|beta|drawdown|win[- ]?rate|accuracy|CAGR|annualized|volatility|'
    r'returns?|ROI|leverage|P/?E|yield|pnl|sortino|calmar|'
    # 英文·产品增长（product_growth 档）
    r'ARR|MRR|churn|retention|conversion|CAC|LTV|DAU|MAU|NPS|margin|runway'
    r')'
    r'[^\d\n]{0,25}'
    r'(\d+(?:\.\d+)?%?)',
    re.I,
)


def check_metric_fabrication(text: str, ctx: dict) -> list:
    """回帖里出现「量化指标 + 数字」而该数字在原推中不存在 → 判定为编造。"""
    source = str(ctx.get("source") or "")
    src_nums = set(re.findall(r'\d+(?:\.\d+)?', source))
    out = []
    penalty = 0.0

    for m in _METRIC_NUM_RE.finditer(text or ""):
        num_part = re.sub(r'[^\d.]', '', m.group(1))
        if num_part and num_part not in src_nums:
            penalty += 100.0
            out.append(Issue(
                dimension="事实",
                kind="fabricated_metric",
                severity=Severity.HIGH,
                detail=f"回帖含编造指标「{m.group(0)}」（原推无此数字）",
                evidence=m.group(0),
            ))

    # 🔴 v5：**只返回 Issue，不再返回 DimensionScore**。
    # 它是一票否决项（Severity.HIGH 直接阻断），阻断项不该同时占分母 ——
    # 留着那个 full=100 的维度，分母会变成 200，下面扣分制的分值（S1 -30 等）
    # 全被稀释一半，「扣 30 分」实际只掉 15 个百分点。
    # 唯一的现有调用方（twitter_monitor._fabricated_metric）只看 verdict.blocking，
    # 不读分数，故去掉它对行为零影响。
    return out


# ══════════════════════════════════════════════════════════════════
# v5 程序层：机械规则，零 token
# ══════════════════════════════════════════════════════════════════

MAX_CHARS = 280          # X 单推硬上限

# A1 一票否决 —— 纯附和 / 空洞捧场
PURE_AGREEMENT = (
    "good point", "i agree", "totally agree", "well said", "so true",
    "100%", "couldn't agree more", "exactly this",
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

# 🔴 **分值表是唯一真相**：下面 prompt 里的分值全部从这里生成，禁止手抄
#    （always.md：prompt 的负向清单必须从闸的常量生成）。

# ── v6 维度得分表（2026-09-04 老板定）──────────────────────────────────────
# 键 = LLM 输出 JSON 的字段名；值 = (满分, 中文名)。三组**合计必须 100**。
#
# 🔴 **分数只有一个来源：维度得分。维度之外不加分、不扣分**（老板定）。
#    加减分是双重计分 —— 「一手经验/可验证细节」本来就是 specificity 该得的分，
#    「AI 腔」本来就是 readability / value 不该得分，在总分外再来一次是重复惩罚，
#    而且让分数不再等于「各项挣到多少」，失去可解释性。
#    ⇒ 已删除的：`BONUS_MAX`（原 +15）、`PENALTY["R1"]`（原 -25）及其 AI_SYNTAX 词表。
#
# grok 原方案是 55+25+15=95（他自己没加对），补的 5 分落在这两处：
#   · value 20→22   增量价值是他给的最高权重，理应最重
#   · specificity 12→15  吸收原 bonus 的「一手经验 / 可验证细节」
DIMENSIONS: dict[str, tuple[int, str]] = {
    # 内容质量 60
    "value":        (22, "增量价值"),
    "specificity":  (15, "具体性"),
    "relevance":    (10, "相关性"),
    "readability":  (8,  "密度与可读性"),
    "tone":         (5,  "建设性语气"),
    # 互动潜力 25
    "replyability": (12, "可被回复性"),
    "followup":     (8,  "二次互动概率"),
    "hook":         (5,  "第一句钩子"),
    # 上下文匹配 15
    "gap_fit":      (8,  "抓住原帖核心缺口"),
    "context_fit":  (7,  "适合该作者语境"),
}

# 满分自查：改动分值时这行会立刻拦住「合计不是 100」的手误
FULL_SCORE = sum(f for f, _ in DIMENSIONS.values())
assert FULL_SCORE == 100, f"维度合计必须为 100，当前 {FULL_SCORE}"

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

SEMANTIC_RUBRIC = """You are scoring one X (Twitter) reply. Two jobs, in order.

## Job 1 — decide whether this SOURCE POST is worth replying to at all

If any rule below fires, the whole thing is a SKIP and you do not score anything:
{skip_rules}

## Job 2 — if not skipped, score the REPLY on these dimensions

Award each dimension from 0 up to its maximum. Award what the reply actually
earns; an average reply should land mid-range, not at the top.
{dimension_rules}

First-hand experience or a verifiable detail belongs in specificity. AI-sounding
filler phrasing belongs in readability. There is no separate bonus or penalty —
everything a reply deserves is expressed inside these dimensions.

Do not reward length. Do not reward cleverness on its own. A reply that only
rephrases the source, only cheerleads, or could sit unchanged under a thousand
unrelated posts earns near zero on value, specificity and relevance.

SOURCE POST:
\"\"\"{{source}}\"\"\"

REPLY:
\"\"\"{{reply}}\"\"\"

Output ONE JSON object, nothing else — no prose, no code fence:
{{{{"decision":"POST","skip":"none","subscores":{{{{{subscore_keys}}}}},"notes":"one short line of evidence"}}}}

When skipping, set decision to "SKIP", skip to the rule id that fired, and leave
every subscore at 0.
""".format(
    skip_rules="\n".join(f"- {k} ({v})" for k, v in SKIP_RULES.items()),
    dimension_rules="\n".join(
        f"- {key} (0-{full}) {name}" for key, (full, name) in DIMENSIONS.items()),
    subscore_keys=",".join(f'"{k}":0' for k in DIMENSIONS),
)

# 模型可能把 JSON 包在代码围栏或前后加话，取第一个 {...} 到最后一个 }
_JSON_RE = re.compile(r"\{.*\}", re.S)


def _parse_verdict(raw: str) -> dict | None:
    """从模型输出里抠出 JSON。抠不出返回 None（调用方据此阻断，绝不静默放行）。"""
    m = _JSON_RE.search(raw or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:                                            # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


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

    # 逐维度收分：模型给的分一律夹在 [0, 满分]，缺项按 0 算（不猜、不补默认值）。
    # 🔴 总分 = 各维度之和，**没有任何维度之外的加减**（老板 2026-09-04 定）。
    subs = data.get("subscores")
    subs = subs if isinstance(subs, dict) else {}
    score = 0.0
    detail: list[str] = []
    for key, (full, name) in DIMENSIONS.items():
        try:
            v = float(subs.get(key, 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        v = max(0.0, min(float(full), v))
        score += v
        detail.append(f"{name}{v:.0f}/{full}")

    note = str(data.get("notes") or "").strip()
    ev = " ".join(detail)
    if note:
        ev += f" | {note[:60]}"

    issues.append(DimensionScore("回帖质量", score, float(FULL_SCORE),
                                 objective=False, evidence=ev))
    return issues


X_REPLY = Spec(
    name="x_reply",
    length_full=0.0,
    code_blocks_full=0.0,
    symbols_full=0.0,
    check_format=False,
    check_fabrication=False,  # 🔴 必须为 False：不误杀正常的版本号/容量/commit 建议
    # v6 仍走 extra_objective（而非框架的 `subjective`）：本 spec 要在同一次 LLM
    # 调用里同时做「硬过滤 SKIP」与「维度打分」，框架的 subjective 只能打分。
    # LLM 经 `context={"llm": fn}` 注入，见 check_reply_rules。
    extra_objective=[check_metric_fabrication, check_reply_rules],
)

# 发布门槛（2026-09-04 老板定 75）：任意 A1 一票否决 / SKIP / 解析失败
# 直接 REJECT，与分数无关。
# ⚠️ 沿革：80(v4.1 档位) → 75(v5 扣分) → 70(v6 初版，grok 建议) → 75(老板定)。
#    **分制换过，同一个数字不是同一个意思**：v5 的 75 是「100 起扣、最多扣一项 R0」，
#    v6 的 75 是「十个维度实际挣到 75 分」，别按旧口径理解。
#    实测同一条回帖三次落在 66/70/72，波动约 4-5 分 —— 门槛附近会抖是已知且可接受的
#    （全程人工点发送，打分器只做排序与挡垃圾；39 分那类废话是被稳定挡住的）。
PASS_SCORE = 75
