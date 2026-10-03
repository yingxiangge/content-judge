# -*- coding: utf-8 -*-
"""选题排除器单元测试（R1 到 R6 逐条排除低效特征）。

验证内容：
1. 排除器放行：未命中任何低效特征且合规 -> result='pass', hit_rule=None, passed=True；
2. 逐条规则排除：R1 到 R6 任一命中即 reject 淘汰；
3. 合规黑名单一票否决：命中 banned 强制为 reject；
4. LLM 返回结果解析与批量审查完整性；
5. render_batch 用户端格式与事实物理阻断。
"""
import json
from content_judge.potential import Score, score, summary
from content_judge.specs.content_potential import RULE_KEYS, render_batch


def test_eliminator_pass():
    """未命中任何低效特征且通过测试 -> pass 放行。"""
    s = Score(
        title="财政部千亿注资大银行，银行股还能拿吗？",
        result="pass",
        hit_rule=None,
        reason="R1–R6 均已做测试且未命中。触发点原词为「财政部千亿注资大银行」，事件为财政部注资大银行。",
    )
    assert s.passed is True
    assert s.verdict == "pass"
    assert s.total == 100.0
    assert "✓ pass" in s.line()


def test_each_rule_alone_rejects():
    """🔴 逐条证伪：R1 到 R6 任一命中即 reject 淘汰。"""
    for r in RULE_KEYS:
        s = Score(
            title=f"命中 {r} 的测试题",
            result="reject",
            hit_rule=r,
            reason=f"测试触发命中 {r} 特征",
        )
        assert s.passed is False, f"{r} 未能成功阻断"
        assert s.verdict == "reject"
        assert s.total == 0.0
        assert r in s.line()


def test_compliance_block_overrides_pass():
    """合规拦截词一票否决：即便模型返回 pass，命中合规词也强制判定为 reject。"""
    s = Score(
        title="荐股测试题",
        result="pass",
        hit_rule=None,
        blocked=["荐股"],
        reason="模型误判为 pass",
    )
    assert s.passed is False
    assert s.verdict == "reject"
    assert s.total == 0.0


def test_score_batch_parsing():
    """验证 score() 函数对 LLM 返回的合法纯 JSON 格式解析准确性。"""
    fake_items = [
        {"name": "美光爆单，股价却无动于衷，A股存储芯片该止盈吗？"},
        {"name": "财政部千亿注资大银行，银行股还能拿吗？"},
    ]
    fake_llm_response = json.dumps({
        "items": [
            {
                "id": 1,
                "result": "reject",
                "hit_rule": "R4",
                "reason": "触发点「美光爆单」的行为主体为境外公司美光，映射到「A股存储芯片」，命中 R4。"
            },
            {
                "id": 2,
                "result": "pass",
                "hit_rule": None,
                "reason": "R1–R6 均已做测试且未命中。触发点原词为「财政部千亿注资大银行」，事件为财政部注资大银行。"
            }
        ]
    })

    def fake_llm(prompt: str) -> str:
        return fake_llm_response

    scores = score(fake_items, llm=fake_llm)
    assert len(scores) == 2

    # 条目 1：reject R4
    assert scores[0].passed is False
    assert scores[0].result == "reject"
    assert scores[0].hit_rule == "R4"
    assert "美光" in scores[0].reason

    # 条目 2：pass
    assert scores[1].passed is True
    assert scores[1].result == "pass"
    assert scores[1].hit_rule is None
    assert "财政部" in scores[1].reason

    # 摘要汇报
    sum_text = summary(scores)
    assert "1条通过(pass)" in sum_text
    assert "1条淘汰(reject)" in sum_text
    assert "R4:1" in sum_text


def test_render_batch_strictly_strips_facts():
    """验证 render_batch 无论输入什么字典或字符串，送给模型的 user JSON 数组绝对只含净标题，物理阻断事实。"""
    items = [
        # 情况 1：字典里带单独的 event/fact/body 字段
        {
            "name": "银行股还能拿吗？",
            "event": "财政部拟发行特别国债注资大行",
            "body": "详细新闻正文...",
            "fact": "大盘微跌",
        },
        # 情况 2：标题字符串内拼接了事实与前缀
        {
            "title": "【标题】昇腾迎来突破，算力却领跌，该抄底还是止损？ | 【事实】昇腾960发布，寒武纪跌3.54%",
        },
        # 情况 3：key 叫 topic，且带换行事实
        {
            "topic": "三桶油放量调整，高股息要减仓吗？\n事实：布伦特原油昨夜跌超4%",
        },
    ]

    rendered_json = render_batch(items)
    data = json.loads(rendered_json)

    assert len(data) == 3
    # 验证字段只有 id 和 topic
    for item in data:
        assert set(item.keys()) == {"id", "topic"}
        assert "事实" not in item["topic"]

    assert data[0]["topic"] == "【标题】银行股还能拿吗？"
    assert data[1]["topic"] == "【标题】昇腾迎来突破，算力却领跌，该抄底还是止损？"
    assert data[2]["topic"] == "【标题】三桶油放量调整，高股息要减仓吗？"


