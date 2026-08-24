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
