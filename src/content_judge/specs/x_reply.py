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

### 分层（这是关键）

    机械规则  → 程序判，零 token：字符数、词数、语种、固定句式、编造数字
    语义规则  → LLM 判：S1/S2/S3（判原推）+ R0/R2/R3/R5/R6（判回帖）

**附带好处：词表全留在程序层，prompt 里一个词都不出现** ⇒ always.md 判据二
「需要同步给 prompt 的词就不该在闸里」在这里自动满足，没有需要同步的东西。

### 只做垃圾过滤，不做审美裁判

绝不加「有洞察 +10」这类加分项 —— 那会立刻退回 v4.1 的老路。
选哪条发是人在 TG 里做的事，打分器只负责把明显不能发的挡掉。
"""
from __future__ import annotations

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
MAX_WORDS = 25           # R4：超此词数扣分

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

# R1 扣分 —— 典型 LLM 套话结构
AI_SYNTAX = (
    "this highlights", "the real opportunity is", "the real challenge is",
    "in today's fast-paced", "as the industry evolves",
    "at the end of the day", "the key is balancing", "it's worth noting",
    "this raises the question", "the bottom line is",
)

# 🔴 **扣分表是唯一真相**：下面 prompt 里的分值全部从这里生成，禁止手抄
#    （always.md：prompt 的负向清单必须从闸的常量生成）。
PENALTY = {
    # 判原推
    "S1": 30,   # 低讨论价值
    "S2": 25,   # 缺乏可进入性
    "S3": 25,   # 纯个人生活
    # 判回帖
    "R0": 20,   # 无新增信息
    "R1": 25,   # AI 腔句式        ← 程序判
    "R2": 20,   # 通用废话
    "R3": 15,   # 复述原推
    "R4": 10,   # 超 25 词          ← 程序判
    "R5": 20,   # 伪反常识/强行唱反调
    "R6": 10,   # 解释性拖沓
}

_LLM_CODES = ("S1", "S2", "S3", "R0", "R2", "R3", "R5", "R6")

_LATIN = re.compile(r"[A-Za-z]")
_NON_LATIN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\u0400-\u04ff\u0600-\u06ff]")
_WORD = re.compile(r"\b[\w'-]+\b")

# ══════════════════════════════════════════════════════════════════
# v5 LLM 层：只判「原推与回帖之间的关系」这类真需要理解的
# ══════════════════════════════════════════════════════════════════
#
# 🔴 逐行输出不是给人看的 —— 审核调用关了 thinking，**写出来是模型唯一的思考手段**。
#    省掉这几行 ≈ 90 token/条 ≈ 月增 0.1 元，换来的是它真的逐项检查而不是拍脑袋。
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

SEMANTIC_RUBRIC = f"""You are a garbage filter, not a writing critic.
Only penalize the explicit violations defined below. Never invent additional
quality criteria. Never reward insight, humor or cleverness — deciding which
reply is best is a human's job, not yours.

【SOURCE deductions — judge the SOURCE TWEET】
- S1 Low discussion value (-{PENALTY['S1']}): the source carries no opinion,
  judgment, question, conflict or controversy; an ordinary reader has no natural
  motive to respond. A bare product announcement or plain fact belongs here.
- S2 Not enterable (-{PENALTY['S2']}): missing context, insider jargon, or an
  unexplained abbreviation / foreign phrase makes it unclear to the target reader
  what is being discussed, so any reply gets no meaningful exposure.
  NOTE: being technical is NOT a violation — our readers are developers.
  Penalize only when context is absent, never because the topic is specialized.
- S3 Purely personal (-{PENALTY['S3']}): personal milestone / daily life / pet /
  scenery / family, with no public stake for readers.

【REPLY deductions — judge the REPLY】
- R0 No added information (-{PENALTY['R0']}): adds no new fact, judgment,
  inference, experience, counter-example or verifiable angle. The reader ends up
  with nothing they did not already have.
- R2 Generic filler (-{PENALTY['R2']}): would still hold verbatim under almost
  any other tweet on the internet.
- R3 Restates the source (-{PENALTY['R3']}): merely rephrases what the source
  already said.
- R5 Manufactured contrarianism (-{PENALTY['R5']}): negates the source to
  manufacture disagreement, without substance, evidence or a new angle.
- R6 Explanatory padding (-{PENALTY['R6']}): one judgment padded with unnecessary
  set-up, causal explanation or subordinate clauses.

Be strict about evidence: if you cannot point to the specific text that triggers
a rule, answer 未触发.

SOURCE TWEET:
\"\"\"{{source}}\"\"\"

REPLY:
\"\"\"{{reply}}\"\"\"

Output exactly these 8 lines, nothing else:
S1: 触发/未触发 | <if triggered, why a reader has no motive to respond>
S2: 触发/未触发 | <if triggered, which part is unreadable without context>
S3: 触发/未触发
R0: 触发/未触发 | <if triggered, what it failed to add>
R2: 触发/未触发
R3: 触发/未触发
R5: 触发/未触发 | <if triggered, quote the negation, note missing substance>
R6: 触发/未触发
"""

_VERDICT_LINE = re.compile(
    r"^\s*(" + "|".join(_LLM_CODES) + r")\s*[:：]\s*(触发|未触发)", re.M)


def check_reply_rules(text: str, ctx: dict) -> list:
    """X 回帖 v5 打分：程序层 + LLM 层，扣分制，满分 100。

    `ctx["source"]` 原推；`ctx["llm"]` 可选，签名 `prompt -> str`。
    不传 llm 就只跑程序层（毫秒级、零 token），此时只有 A1/R1/R4 生效。
    """
    source = str(ctx.get("source") or "")
    reply = text or ""
    low = reply.lower()
    issues: list = []
    penalty = 0.0
    hits: list[str] = []

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
        issues.append(DimensionScore("回帖质量", 0.0, 100.0, objective=True,
                                     evidence="; ".join(rejects)))
        return issues

    # ── 程序层扣分 ──
    for p in AI_SYNTAX:
        if p in low:
            penalty += PENALTY["R1"]
            hits.append(f"R1 AI腔「{p}」-{PENALTY['R1']}")
            break
    wc = len(_WORD.findall(reply))
    if wc > MAX_WORDS:
        penalty += PENALTY["R4"]
        hits.append(f"R4 {wc}词>{MAX_WORDS} -{PENALTY['R4']}")

    # ── LLM 层扣分 ──
    llm = ctx.get("llm")
    if callable(llm):
        raw = ""
        try:
            raw = llm(SEMANTIC_RUBRIC.format(source=source, reply=reply)) or ""
        except Exception as e:                                   # noqa: BLE001
            issues.append(Issue("semantic", "llm_error", Severity.HIGH,
                                f"语义层调用失败（安全阻断）：{type(e).__name__}: {e}"))
            issues.append(DimensionScore("回帖质量", 0.0, 100.0, objective=False,
                                         evidence="LLM 调用失败"))
            return issues
        found = _VERDICT_LINE.findall(raw)
        if not found:
            # 🔴 解析不到 = 模型没按格式答 ⇒ 显式阻断。
            #    绝不静默当成「无扣分」—— 那正是「静默失效」的经典形态。
            issues.append(Issue("semantic", "unparsable", Severity.HIGH,
                                f"语义层未按逐行格式输出（安全阻断）：{raw[:80]!r}"))
            issues.append(DimensionScore("回帖质量", 0.0, 100.0, objective=False,
                                         evidence="输出格式不合规"))
            return issues
        for code, verdict in found:
            if verdict == "触发":
                penalty += PENALTY[code]
                hits.append(f"{code} -{PENALTY[code]}")

    score = max(0.0, 100.0 - penalty)
    issues.append(DimensionScore(
        "回帖质量", score, 100.0, objective=not callable(llm),
        evidence="; ".join(hits) if hits else "无扣分",
    ))
    return issues


X_REPLY = Spec(
    name="x_reply",
    length_full=0.0,
    code_blocks_full=0.0,
    symbols_full=0.0,
    check_format=False,
    check_fabrication=False,  # 🔴 必须为 False：不误杀正常的版本号/容量/commit 建议
    # 🔴 v5：扣分制走 extra_objective 而不是框架的 `subjective`（后者是加分制，
    #    且加分制下模型倾向给中间分；扣分制是二元的「触发/未触发」，可复现）。
    #    LLM 经 `context={"llm": fn}` 注入，见 check_reply_rules。
    extra_objective=[check_metric_fabrication, check_reply_rules],
)

# 通过线（GPT 建议 75）：任意一票否决直接 REJECT，与分数无关。
PASS_SCORE = 75
