# -*- coding: utf-8 -*-
"""A股散户热点源头过滤器单元测试与正反向证伪。"""
from __future__ import annotations

import json
import pytest

from content_judge.hotspot_filter import judge_hotspots
from content_judge.specs.hotspot_filter import parse_response, render_prompt


def test_render_prompt_structure():
    items = [
        {"id": 1, "time": "2026-10-03 09:30", "topic": "财政部宣布发行特别国债为国有大型商业银行注资千亿充实核心一级资本"},
        {"id": 2, "time": "2026-10-02 15:00", "topic": "传统小盘厨具企业宣称人形机器人落地百家门店，概念股随后大幅杀跌腰斩"}
    ]
    prompt = render_prompt(items, now_str="2026-10-03 10:00")
    assert "A股散户热点源头过滤器" in prompt
    assert "Q0 时效" in prompt
    assert "Q1 直接性" in prompt
    assert "Q2 覆盖面" in prompt
    assert "Q3 信息增量" in prompt
    assert "财政部宣布发行特别国债" in prompt
    assert "2026-10-03 10:00" in prompt


def test_parse_response_clean_json():
    raw_json = json.dumps({
        "items": [
            {
                "id": 1,
                "q0_fresh": {"pass": True, "evidence": "发布时间 2026-10-03 09:30，距当前半小时"},
                "q1_direct": {"pass": True, "evidence": "「国有大型商业银行」直接对应 A 股大行标的"},
                "q2_coverage": {"pass": True, "evidence": "「国有大行」是国民级大市值底盘；普通人持有的原因：低估值高股息底仓配置"},
                "q3_increment": {"pass": True, "evidence": "删除盘面表现后剩下：「财政部宣布发行特别国债注资千亿充实资本」这一国家级财政动作"},
                "result": "pass",
                "failed": None
            },
            {
                "id": 2,
                "q0_fresh": {"pass": True, "evidence": "发布时间 2026-10-02 15:00，距当前19小时"},
                "q1_direct": {"pass": True, "evidence": "「厨具企业」对应 A 股个股"},
                "q2_coverage": {"pass": False, "evidence": "「传统小盘厨具企业」为边缘小微票，普通散户账户极少持有"},
                "q3_increment": {"pass": True, "evidence": "删除盘面表现后剩下：「人形机器人落地百家门店」"},
                "result": "reject",
                "failed": "q2"
            }
        ]
    })
    res = parse_response(raw_json)
    assert len(res) == 2
    assert res[0]["id"] == 1
    assert res[0]["result"] == "pass"
    assert res[0]["failed"] is None
    assert res[1]["id"] == 2
    assert res[1]["result"] == "reject"
    assert res[1]["failed"] == "q2"


def test_parse_response_markdown_fence():
    raw = """```json
{
  "items": [
    {
      "id": 3,
      "q0_fresh": { "pass": false, "evidence": "没有发布时间" },
      "q1_direct": { "pass": true, "evidence": "「黄金股」" },
      "q2_coverage": { "pass": true, "evidence": "「黄金」" },
      "q3_increment": { "pass": false, "evidence": "删除盘面表现后什么都不剩" },
      "result": "reject",
      "failed": "q0"
    }
  ]
}
```"""
    res = parse_response(raw)
    assert len(res) == 1
    assert res[0]["id"] == 3
    assert res[0]["result"] == "reject"
    assert res[0]["failed"] == "q0"


def test_judge_hotspots_end_to_end_mock():
    items = [
        {"id": 20, "time": "2026-10-03 09:30", "topic": "财政部宣布发行特别国债注资国有大行"},
        {"id": 26, "time": "2026-10-03 09:00", "topic": "厨具企业爱仕达门店摆人形机器人"},
    ]

    def dummy_llm(prompt: str) -> str:
        assert "A股散户热点源头过滤器" in prompt
        assert "财政部宣布发行特别国债" in prompt
        return json.dumps({
            "items": [
                {
                    "id": 20,
                    "q0_fresh": {"pass": True, "evidence": "发布时间在48h内"},
                    "q1_direct": {"pass": True, "evidence": "「国有大行」直接对应A股标的"},
                    "q2_coverage": {"pass": True, "evidence": "普通人持有的原因：国民大市值资产"},
                    "q3_increment": {"pass": True, "evidence": "删除盘面后剩下：「特别国债注资」"},
                    "result": "pass",
                    "failed": None
                },
                {
                    "id": 26,
                    "q0_fresh": {"pass": True, "evidence": "发布时间在48h内"},
                    "q1_direct": {"pass": True, "evidence": "「厨具企业」"},
                    "q2_coverage": {"pass": False, "evidence": "细分小微题材，普通散户账户无持仓理由"},
                    "q3_increment": {"pass": True, "evidence": "摆机器人"},
                    "result": "reject",
                    "failed": "q2"
                }
            ]
        })

    results = judge_hotspots(items, llm=dummy_llm, now_str="2026-10-03 10:00")
    assert len(results) == 2
    assert results[0]["id"] == 20
    assert results[0]["result"] == "pass"
    assert results[1]["id"] == 26
    assert results[1]["result"] == "reject"
    assert results[1]["failed"] == "q2"
