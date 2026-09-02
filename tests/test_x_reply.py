"""测试 X (Twitter) 回帖编造拦截规范（覆盖全部指标词表与防误杀用例）。"""
import pytest
from content_judge import judge
from content_judge.specs import X_REPLY


class TestXReplyJudge:
    def test_clean_reply_passes(self):
        source = "Just hit $10k MRR with my micro SaaS built on Next.js."
        reply = "Congrats on reaching $10k MRR! What was the main growth channel?"
        res = judge(reply, X_REPLY, source=source, context={"source": source})
        assert res.blocking == []
        assert res.tier in ("S", "A")

    @pytest.mark.parametrize("bad_snippet", [
        # 英文指标
        "CAGR 12%",
        "annualized 18%",
        "leverage 3x",
        "P/E 45",
        "win-rate 55%",
        "win rate 40%",
        "yield 7%",
        "returns 22%",
        "churn 40%",
        "sharpe 1.8",
        # 中文指标
        "波动率 30%",
        "杠杆 3 倍",
        "换手率 80%",
        "月化 5%",
        "盈亏比 2.5",
        "IC值 0.08",
        "超额 12%",
        "胜率 65%",
        "回撤 15%",
    ])
    def test_all_metric_fabrication_cases_blocked(self, bad_snippet):
        """19 个经典量化/增长指标数字编造必须 100% 拦截。"""
        source = "We are testing a momentum trading algorithm in the crypto market."
        reply = f"I evaluated your track record and the {bad_snippet} looks unsustainable."
        res = judge(reply, X_REPLY, source=source, context={"source": source})
        assert any(i.kind == "fabricated_metric" for i in res.blocking), f"未能拦截编造指标: {bad_snippet}"
        assert res.tier == "C"

    @pytest.mark.parametrize("normal_tech_reply", [
        "Same here — pinning to 3.11.2 fixed it for us.",
        "Try bumping the runner to 16 GB memory.",
        "The fix landed in deadbeef and will release next week.",
        "Check out PR #1234 on github.",
    ])
    def test_normal_tech_replies_not_falsely_blocked(self, normal_tech_reply):
        """防误杀：版本号、容量、commit、Issue 编号等属于正常回帖解答，严禁误杀。"""
        source = "Experiencing mysterious OOM and segfaults on Ubuntu 24.04."
        res = judge(normal_tech_reply, X_REPLY, source=source, context={"source": source})
        assert res.blocking == [], f"正常技术回帖被误杀: {normal_tech_reply} -> {res.blocking}"
        assert res.tier in ("S", "A")


class TestXReplyV5Rules:
    """v5 打分器（2026-09-02）：程序层机械规则 + LLM 层语义规则的扣分制。

    起因见 specs/x_reply.py 文件头：v4.1 的 A/B/C/D 四档让
    `Mannenprobleem!`（一个荷兰语单词）拿到 A 档 95 分推送给老板。
    """

    def _score(self, reply, source="Some tweet about AI tooling.", llm=None):
        from content_judge.specs.x_reply import check_reply_rules
        from content_judge.types import DimensionScore, Issue
        ctx = {"source": source}
        if llm is not None:
            ctx["llm"] = llm
        out = check_reply_rules(reply, ctx)
        dim = [r for r in out if isinstance(r, DimensionScore)][0]
        blocked = [i for i in out if isinstance(i, Issue) and i.severity.name == "HIGH"]
        return dim.score, bool(blocked), dim.evidence

    # ── A1 一票否决 ────────────────────────────────────────────
    @pytest.mark.parametrize("reply,why", [
        ("这条是中文回帖", "非英文"),
        ("Good point, totally agree.", "纯附和"),
        ("Thanks for sharing, useful stuff here.", "AI 客套开场"),
        ("x" * 281, "超 280 字符"),
    ])
    def test_a1_hard_reject(self, reply, why):
        score, blocked, _ = self._score(reply)
        assert blocked, f"{why} 未被一票否决"
        assert score == 0

    def test_ai_filler_only_at_opening(self):
        """AI 客套只判开头 —— 句中出现「great post」不该误杀。"""
        score, blocked, _ = self._score(
            "Shipping beats polishing; that great post you linked proves it.")
        assert not blocked
        assert score == 100

    # ── 程序层扣分 ────────────────────────────────────────────
    def test_r1_ai_syntax(self):
        from content_judge.specs.x_reply import PENALTY
        score, blocked, ev = self._score("This highlights how teams underestimate infra cost.")
        assert not blocked
        assert score == 100 - PENALTY["R1"]
        assert "R1" in ev

    def test_r4_word_limit(self):
        from content_judge.specs.x_reply import PENALTY, MAX_WORDS
        long_reply = " ".join(["word"] * (MAX_WORDS + 5))
        score, _, ev = self._score(long_reply)
        assert score == 100 - PENALTY["R4"]
        assert "R4" in ev

    def test_clean_reply_full_score(self):
        score, blocked, ev = self._score(
            "Bidding on legends without asking is bold, but hoping it works isn't a strategy.")
        assert not blocked and score == 100 and ev == "无扣分"

    # ── LLM 层 ────────────────────────────────────────────────
    def test_llm_deductions_accumulate(self):
        from content_judge.specs.x_reply import PENALTY
        fake = lambda p: ("S1: 触发 | no motive\nS2: 未触发\nS3: 未触发\n"
                          "R0: 触发 | adds nothing\nR2: 未触发\nR3: 未触发\n"
                          "R5: 未触发\nR6: 未触发")
        score, blocked, ev = self._score("A perfectly fine short reply.", llm=fake)
        assert not blocked
        assert score == 100 - PENALTY["S1"] - PENALTY["R0"]
        assert "S1" in ev and "R0" in ev

    def test_unparsable_llm_output_blocks(self):
        """模型没按逐行格式答 → 显式阻断，**绝不静默当成无扣分**。

        「解析不到就当通过」正是静默失效的经典形态（见 BUG_LOG 多起）。
        """
        score, blocked, ev = self._score("Fine reply.", llm=lambda p: "GRADE: A\nSCORE: 95")
        assert blocked and score == 0
        assert "格式" in ev

    def test_llm_exception_blocks(self):
        def boom(p):
            raise RuntimeError("api down")
        score, blocked, _ = self._score("Fine reply.", llm=boom)
        assert blocked and score == 0

    # ── 结构约束 ──────────────────────────────────────────────
    def test_prompt_scores_generated_from_penalty_table(self):
        """prompt 里的分值必须由 PENALTY 生成，禁止手抄（always.md）。"""
        from content_judge.specs.x_reply import SEMANTIC_RUBRIC, PENALTY, _LLM_CODES
        for code in _LLM_CODES:
            assert f"-{PENALTY[code]}" in SEMANTIC_RUBRIC, f"{code} 分值未出现在 prompt"

    def test_prompt_contains_no_wordlist(self):
        """词表只在程序层，prompt 里一个词都不该出现 —— 于是无需同步。"""
        from content_judge.specs.x_reply import SEMANTIC_RUBRIC, AI_SYNTAX, PURE_AGREEMENT
        for w in tuple(AI_SYNTAX) + tuple(PURE_AGREEMENT):
            assert w not in SEMANTIC_RUBRIC.lower(), f"词表「{w}」泄漏进 prompt"

    def test_no_bonus_dimensions(self):
        """只扣分，不加分 —— 加分项会让打分器退回 v4.1 的审美裁判老路。"""
        from content_judge.specs.x_reply import SEMANTIC_RUBRIC
        assert "+1" not in SEMANTIC_RUBRIC and "bonus" not in SEMANTIC_RUBRIC.lower()

    def test_fabrication_check_emits_no_dimension(self):
        """编造检测是一票否决项，不该占分母（否则扣分值被稀释一半）。"""
        from content_judge.specs.x_reply import check_metric_fabrication
        from content_judge.types import DimensionScore
        out = check_metric_fabrication("win rate 40% proves it", {"source": "no numbers here"})
        assert not any(isinstance(r, DimensionScore) for r in out)
        assert out, "编造仍必须报 Issue"
