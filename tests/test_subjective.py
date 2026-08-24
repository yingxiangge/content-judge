"""测试 content_judge 主观项（LLM 证据打分与无证据降级）逻辑。"""
import json
from content_judge import judge, Spec


SPEC = Spec(
    name="test_subjective",
    subjective={"结构清晰": 20.0, "论述有力": 30.0},
    subjective_brief="评估技术文章结构与论据",
)


class TestSubjectiveJudge:
    def test_subjective_with_valid_evidence(self):
        def mock_llm(prompt: str) -> str:
            return json.dumps({
                "结构清晰": {"score": 18, "evidence": "第一步分析问题排查原因"},
                "论述有力": {"score": 28, "evidence": "根据日志报错串推导出断点"},
            })

        res = judge("技术博客正文...", SPEC, llm=mock_llm)
        assert res.total == 46.0
        assert res.full == 50.0
        assert res.tier in ("S", "A")
        assert len(res.issues) == 0

    def test_missing_evidence_drops_to_zero(self):
        """原则：分会飘证据不会。没有证据的项强制按 0 分计并出 Issue。"""
        def mock_llm(prompt: str) -> str:
            return json.dumps({
                "结构清晰": {"score": 20, "evidence": ""},  # 空证据
                "论述有力": {"score": 25, "evidence": "提供了复现配置"},
            })

        res = judge("技术博客正文...", SPEC, llm=mock_llm)
        assert res.total == 25.0  # 结构清晰被置 0
        assert any(i.kind == "no_evidence" for i in res.issues)

    def test_malformed_llm_json_handled_gracefully(self):
        """LLM 吐非合法 JSON 时优雅降级为 0 分，不抛异常崩溃。"""
        def mock_llm(prompt: str) -> str:
            return "不好意思，我无法打分"

        res = judge("技术博客正文...", SPEC, llm=mock_llm)
        assert res.total == 0.0
        assert res.tier == "C"
