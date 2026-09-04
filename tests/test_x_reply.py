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

    # ── 程序层规则 ────────────────────────────────────────────
    def test_replies_over_25_words_not_penalized(self):
        """2026-09-03 废除 R4：只要在 280 字符内，优质长回复（如 30-45 词）不扣分。"""
        long_reply = (
            "When building distributed systems, pinning your database schema migrations "
            "behind read-only replicas prevents cascade outages, even if write latency "
            "occasionally spikes during peak deployments."
        )
        score, blocked, ev = self._score(long_reply)
        assert not blocked
        assert score == 100
        assert "A1" in ev

    def test_clean_reply_full_score_unmetered(self):
        """未注入 LLM 时只跑程序层，A1 未触发则全绿放行。"""
        score, blocked, ev = self._score(
            "Bidding on legends without asking is bold, but hoping it works isn't a strategy.")
        assert not blocked and score == 100 and "A1" in ev

    # ── LLM 层（v6 维度制与 SKIP 门禁）────────────────────────
    def test_llm_dimensions_scoring_and_accumulation(self):
        """v6: 维度得分累计，总分唯一定义为各项之和。"""
        from content_judge.specs.x_reply import PASS_SCORE
        sample_json = (
            '{"decision":"POST","skip":"none","subscores":{'
            '"value":20,"specificity":14,"relevance":10,"readability":8,"tone":5,'
            '"replyability":11,"followup":7,"hook":5,"gap_fit":7,"context_fit":6},'
            '"notes":"high quality operator perspective"}'
        )
        score, blocked, ev = self._score("A solid technical reply.", llm=lambda p: sample_json)
        assert not blocked
        assert score == 93
        assert score >= PASS_SCORE
        assert "增量价值20/22" in ev
        assert "high quality" in ev

    def test_skip_rule_blocks(self):
        """硬过滤：原推不值得回（SKIP）直接阻断，总分判 0。"""
        skip_json = '{"decision":"SKIP","skip":"S1","subscores":{},"notes":"no controversy"}'
        score, blocked, ev = self._score("Whatever reply.", llm=lambda p: skip_json)
        assert blocked
        assert score == 0
        assert "SKIP" in ev

    def test_markdown_fence_json_parsed(self):
        """模型带有 markdown ```json 围栏时仍能鲁棒解析。"""
        fenced_json = (
            'Here is the audit result:\n```json\n'
            '{"decision":"POST","skip":"none","subscores":{'
            '"value":15,"specificity":10,"relevance":10,"readability":6,"tone":5,'
            '"replyability":8,"followup":6,"hook":4,"gap_fit":6,"context_fit":5},'
            '"notes":"decent answer"}\n```\nHope this helps!'
        )
        score, blocked, ev = self._score("Reply with fence.", llm=lambda p: fenced_json)
        assert not blocked
        assert score == 75

    def test_unparsable_llm_output_blocks(self):
        """模型没按逐行格式答 → 显式阻断，**绝不静默当成无扣分**。"""
        score, blocked, ev = self._score("Fine reply.", llm=lambda p: "GRADE: A\nSCORE: 95")
        assert blocked and score == 0
        assert "输出" in ev or "解析" in ev

    def test_llm_exception_blocks(self):
        def boom(p):
            raise RuntimeError("api down")
        score, blocked, _ = self._score("Fine reply.", llm=boom)
        assert blocked and score == 0

    # ── 结构约束 ──────────────────────────────────────────────
    def test_prompt_scores_generated_from_dimensions_table(self):
        """prompt 里的分值必须由 DIMENSIONS 动态生成，合计必须 100。"""
        from content_judge.specs.x_reply import SEMANTIC_RUBRIC, DIMENSIONS, FULL_SCORE
        assert FULL_SCORE == 100
        for key, (full, name) in DIMENSIONS.items():
            assert f"{key} (0-{full})" in SEMANTIC_RUBRIC, f"{key} 未正确生成到 prompt"

    def test_prompt_contains_no_wordlist(self):
        """词表只在程序层，prompt 里一个词都不该出现 —— 于是无需同步。"""
        from content_judge.specs.x_reply import SEMANTIC_RUBRIC, PURE_AGREEMENT, AI_FILLER_OPENER
        for w in tuple(PURE_AGREEMENT) + tuple(AI_FILLER_OPENER):
            assert w not in SEMANTIC_RUBRIC.lower(), f"词表「{w}」泄漏进 prompt"

    def test_fabrication_check_emits_no_dimension(self):
        """编造检测是一票否决项，不该占分母（否则扣分值被稀释一半）。"""
        from content_judge.specs.x_reply import check_metric_fabrication
        from content_judge.types import DimensionScore
        out = check_metric_fabrication("win rate 40% proves it", {"source": "no numbers here"})
        assert not any(isinstance(r, DimensionScore) for r in out)
        assert out, "编造仍必须报 Issue"
