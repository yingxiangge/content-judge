# -*- coding: utf-8 -*-
"""X 回帖判据测试。

## 2026-09-10 v7：加法十维 → 乘法四因子，编造检测从程序层挪进语义层

🔴 **本次改判据时，旧测试一条都没删，只做迁移** —— 09-04 那次的教训是
   「改判分把 R7 防线改没了，**连回归单测也一起删了**」（`cfa56f0`），
   于是防线消失得悄无声息。本文件每一条迁移过的测试都在 docstring 里写明
   「原来测什么、为什么改」，让后来人能判断是不是又把防线删了。
"""
import pytest

from content_judge import judge
from content_judge.specs import X_REPLY


def _post(factors: dict, *, fabrication=False, notes="ok") -> str:
    """构造一份合规的语义层返回。"""
    import json
    base = {"relevance": 0, "attention": 0, "identity": 0, "curiosity": 0}
    base.update(factors)
    return json.dumps({"decision": "POST", "skip": "none",
                       "fabrication": fabrication, "factors": base, "notes": notes})


class TestXReplyJudge:
    """整链路：`judge()` 级别的行为。"""

    def test_clean_reply_passes(self):
        source = "Just hit $10k MRR with my micro SaaS built on Next.js."
        reply = "Congrats on reaching $10k MRR! What was the main growth channel?"
        res = judge(reply, X_REPLY, source=source, context={"source": source})
        assert res.blocking == []

    @pytest.mark.parametrize("normal_tech_reply", [
        "Same here — pinning to 3.11.2 fixed it for us.",
        "Try bumping the runner to 16 GB memory.",
        "The fix landed in deadbeef and will release next week.",
        "Check out PR #1234 on github.",
        # 🔴 2026-09-10 新增两条：程序层旧闸对它们的**误杀已实测复现**
        "Cache the system prompt separately — that cut our token spend by 100%.",
        "Wrap it in a schema check that returns 0 on malformed args.",
    ])
    def test_normal_tech_replies_not_falsely_blocked(self, normal_tech_reply):
        """防误杀：版本号、容量、commit、Issue 编号属于正常解答，严禁误杀。

        后两条是 09-10 查出的真误杀：
          · `"100%"` 在 `PURE_AGREEMENT` 里是**子串**匹配 → 被判「纯附和」一票否决；
          · `_METRIC_NUM_RE` 的 `returns?` 命中**普通英语动词** → 被判「编造指标」。
        两条闸都需要为正当用途开口子 ⇒ 按判据一，它们本来就不该在程序层。
        """
        source = "Experiencing mysterious OOM and segfaults on Ubuntu 24.04."
        res = judge(normal_tech_reply, X_REPLY, source=source, context={"source": source})
        assert res.blocking == [], f"正常技术回帖被误杀: {normal_tech_reply} -> {res.blocking}"


class TestProgramLayer:
    """程序层：零 token 的机械规则。**只留「永远没有正当理由」的那几条。**"""

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

    def test_replies_over_25_words_not_penalized(self):
        """2026-09-03 废除 R4：只要在 280 字符内，优质长回复不扣分。"""
        long_reply = (
            "When building distributed systems, pinning your database schema migrations "
            "behind read-only replicas prevents cascade outages, even if write latency "
            "occasionally spikes during peak deployments."
        )
        score, blocked, ev = self._score(long_reply)
        assert not blocked and score == 100 and "A1" in ev

    def test_clean_reply_full_score_unmetered(self):
        """未注入 LLM 时只跑程序层，A1 未触发则全绿放行。"""
        score, blocked, ev = self._score(
            "Bidding on legends without asking is bold, but hoping it works isn't a strategy.")
        assert not blocked and score == 100 and "A1" in ev

    def test_hundred_percent_no_longer_in_wordlist(self):
        """🔴 `"100%"` 必须已撤出附和词表（2026-09-10）。

        它是子串匹配，而 `100%` 在技术回帖里极常见。这条断言的作用是：
        **将来有人想把它加回去时，测试会先炸**。
        """
        from content_judge.specs.x_reply import PURE_AGREEMENT
        assert "100%" not in PURE_AGREEMENT


class TestSemanticLayer:
    """语义层：SKIP 门禁 + 诚信判定 + 四因子几何平均。"""

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

    def test_geometric_mean_scoring(self):
        """v7：四因子几何平均。四项全 8 分 = 80 分。

        取代 v6 的 `test_llm_dimensions_scoring_and_accumulation`（十维相加）。
        """
        llm = lambda p: _post({"relevance": 8, "attention": 8, "identity": 8, "curiosity": 8})
        score, blocked, ev = self._score("A solid technical reply.", llm=llm)
        assert not blocked
        assert score == pytest.approx(80.0, abs=0.1)
        assert "relevance8" in ev

    @pytest.mark.parametrize("zero_key", ["relevance", "attention", "identity", "curiosity"])
    def test_any_zero_factor_zeroes_total(self, zero_key):
        """🔴 **乘法的全部意义**：任何一项为 0，总分即 0。

        这条断言取代了 09-03 立、09-04 被删的 R7（跑题 -30）——
        **防线由结构保证，而不是由一条会被后人顺手删掉的规则保证。**
        """
        facs = {"relevance": 9, "attention": 9, "identity": 9, "curiosity": 9}
        facs[zero_key] = 0
        score, blocked, _ = self._score("Reply.", llm=lambda p: _post(facs))
        assert score == 0, f"{zero_key}=0 时总分必须为 0"

    def test_off_topic_reply_scores_zero(self):
        """C1 · 09-03 老板亲自抓出的那条跑题样本，新结构下必须判 0。

        原推是 AI 代码评测，回帖扯量化交易的 trade counts。
        v6 加法结构下它最坏只丢 relevance(10)+gap_fit(8)+context_fit(7)=25 分
        ⇒ 100−25 = **75，恰好等于当时的门槛，放行**。
        """
        from content_judge.specs.x_reply import PASS_SCORE
        source = "New slop code bench for Fable, GLM and the other new coding models."
        reply = "Benchmarks without trade counts are just model cosplay. Show me the losing runs."
        # 语义层判定跑题 ⇒ relevance 0（其余项即便给高分也不救）
        llm = lambda p: _post({"relevance": 0, "attention": 8, "identity": 7, "curiosity": 7},
                              notes="off-topic: trading metrics on a code bench")
        score, blocked, _ = self._score(reply, source=source, llm=llm)
        assert score == 0
        assert score < PASS_SCORE

    def test_fabrication_blocks_and_takes_no_denominator(self):
        """C3 · 编造 / 冒充亲历 → 阻断，且不占分母。

        取代 v6 的 `test_fabrication_check_emits_no_dimension`：判据没变，
        执行者从程序层正则换成了语义层（判据一：需要为公共事实开口子的闸，
        本来就不该是纯字面匹配）。
        """
        from content_judge.types import DimensionScore
        from content_judge.specs.x_reply import check_reply_rules, FULL_SCORE
        llm = lambda p: _post({"relevance": 9, "attention": 9, "identity": 9, "curiosity": 9},
                              fabrication=True, notes="claims personal benchmark run")
        out = check_reply_rules("We tested this and saw win rate 40%.",
                                {"source": "no numbers here", "llm": llm})
        dims = [r for r in out if isinstance(r, DimensionScore)]
        assert len(dims) == 1 and dims[0].score == 0
        assert dims[0].full == FULL_SCORE, "阻断项不该改变分母"
        assert any(getattr(i, "kind", "") == "fabricated" for i in out)

    def test_judgement_is_not_a_claim_of_experience(self):
        """C3 反向 · 「像干过的人说话」必须放行，不能被当成「声称干过」。

        🔴 这条是 09-10 定目的时的核心分寸：让陌生人点进主页的最大驱动力
        就是「这人有我没有的东西」，把它一并禁掉等于禁掉目的本身。
        """
        llm = lambda p: _post({"relevance": 8, "attention": 8, "identity": 9, "curiosity": 8})
        score, blocked, _ = self._score(
            "The hard part isn't building agents. It's keeping them useful after week two.",
            llm=llm)
        assert not blocked and score > 0

    def test_skip_rule_blocks(self):
        """硬过滤：原推不值得回（SKIP）直接阻断，总分判 0。"""
        skip_json = '{"decision":"SKIP","skip":"S1","factors":{},"notes":"no controversy"}'
        score, blocked, ev = self._score("Whatever reply.", llm=lambda p: skip_json)
        assert blocked and score == 0 and "SKIP" in ev

    def test_markdown_fence_json_parsed(self):
        """模型带 markdown ```json 围栏时仍能鲁棒解析。"""
        fenced = ('Here is the audit result:\n```json\n'
                  + _post({"relevance": 7, "attention": 7, "identity": 7, "curiosity": 7})
                  + '\n```\nHope this helps!')
        score, blocked, _ = self._score("Reply with fence.", llm=lambda p: fenced)
        assert not blocked
        assert score == pytest.approx(70.0, abs=0.1)

    def test_unparsable_llm_output_blocks(self):
        """模型没按格式答 → 显式阻断，**绝不静默当成满分**。"""
        score, blocked, ev = self._score("Fine reply.", llm=lambda p: "GRADE: A\nSCORE: 95")
        assert blocked and score == 0
        assert "输出" in ev or "解析" in ev

    def test_llm_exception_blocks(self):
        def boom(p):
            raise RuntimeError("api down")
        score, blocked, _ = self._score("Fine reply.", llm=boom)
        assert blocked and score == 0

    def test_missing_factor_counts_as_zero(self):
        """缺项按 0 算 —— 不猜、不补默认值。缺一项即总分 0（乘法）。"""
        import json
        partial = json.dumps({"decision": "POST", "skip": "none", "fabrication": False,
                              "factors": {"relevance": 9, "attention": 9}, "notes": "partial"})
        score, _, _ = self._score("Reply.", llm=lambda p: partial)
        assert score == 0


class TestStructuralConstraints:
    def test_prompt_factors_generated_from_table(self):
        """prompt 里的因子必须由 FACTORS 动态生成，禁止手抄。"""
        from content_judge.specs.x_reply import SEMANTIC_RUBRIC, FACTORS
        for key in FACTORS:
            assert f"{key} (0-10)" in SEMANTIC_RUBRIC, f"{key} 未正确生成到 prompt"

    def test_prompt_contains_no_wordlist(self):
        """词表只在程序层，prompt 里一个词都不该出现 —— 于是无需同步。"""
        from content_judge.specs.x_reply import SEMANTIC_RUBRIC, PURE_AGREEMENT, AI_FILLER_OPENER
        for w in tuple(PURE_AGREEMENT) + tuple(AI_FILLER_OPENER):
            assert w not in SEMANTIC_RUBRIC.lower(), f"词表「{w}」泄漏进 prompt"

    def test_program_layer_no_longer_has_metric_regex(self):
        """🔴 编造检测已挪进语义层，程序层不得再有那条正则。

        将来有人想「顺手加回一个正则闸」时，这条会先炸。
        """
        import content_judge.specs.x_reply as m
        assert not hasattr(m, "_METRIC_NUM_RE")
        assert not hasattr(m, "check_metric_fabrication")
