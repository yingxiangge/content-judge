"""
Test suite for Anti-Slop dimension in content-judge
"""
import pytest
from content_judge.dimensions.anti_slop import scan_slop_violations, check_anti_slop, assert_no_slop

def test_clean_engineer_text():
    text = """
    在近 7 天的生产调用中，我们分析了 22 个会话与 12.06 亿 Token 的实际消耗。
    实测表明：>500k 上下文的请求消耗了 50.5% 的成本。
    治理方案是换任务立即 /clear，并通过 subagent 隔离独立调研上下文。
    """
    violations = scan_slop_violations(text)
    assert len(violations) == 0
    issues = check_anti_slop(text)
    assert len(issues) == 0
    assert_no_slop(text)

def test_marketing_superlative_detection():
    dirty_text = "炸裂！这篇封神级教程强烈推荐，赶紧冲！"
    violations = scan_slop_violations(dirty_text)
    assert len(violations) >= 4
    with pytest.raises(ValueError):
        assert_no_slop(dirty_text)

def test_pseudo_conflict_detection():
    dirty_text = "很多人不知道，其实很多人都错了，颠覆你的认知！"
    violations = scan_slop_violations(dirty_text)
    assert len(violations) >= 3

def test_fake_engagement_detection():
    dirty_text = "大家平时会经常 /clear 吗？欢迎在评论区交流讨论！"
    violations = scan_slop_violations(dirty_text)
    assert len(violations) >= 2

def test_empty_transition_detection():
    dirty_text = "话不多说直接上干货，下面带大家深入了解。"
    violations = scan_slop_violations(dirty_text)
    assert len(violations) >= 2
