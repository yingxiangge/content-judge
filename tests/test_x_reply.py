"""测试 X (Twitter) 回帖编造拦截规范。"""
from content_judge import judge
from content_judge.specs import X_REPLY


class TestXReplyJudge:
    def test_clean_reply_passes(self):
        source = "Just hit $10k MRR with my micro SaaS built on Next.js."
        reply = "Congrats on reaching $10k MRR! What was the main growth channel?"
        res = judge(reply, X_REPLY, source=source, context={"source": source})
        assert res.blocking == []
        assert res.tier in ("S", "A")

    def test_fabricated_metric_blocked(self):
        source = "Trading crypto with a new momentum strategy."
        reply = "I checked your trades and your win rate is only 38%, which won't survive a bear market."
        res = judge(reply, X_REPLY, source=source, context={"source": source})
        assert any(i.kind == "fabricated_metric" for i in res.blocking)
        assert res.tier == "C"

    def test_fabricated_issue_number_blocked(self):
        source = "Experiencing strange bug in vllm."
        reply = "This was already reported in Issue #998812."
        res = judge(reply, X_REPLY, source=source, context={"source": source})
        assert any(i.kind.startswith("fabricated") for i in res.blocking)
        assert res.tier == "C"
