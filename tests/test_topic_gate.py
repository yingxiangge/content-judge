# -*- coding: utf-8 -*-
"""四要素闸：Good Case 放行 + Bad Case 阻断，语料全部来自 2026-09-06 实测。"""
from content_judge.topic_gate import check_testable, filter_topics, missing_parts

# 🔴 真实产出（09-06 实测 gemini-3.8-flash 的三条），必须全放行
GOOD = [
    "A股油运概念板块历史数据中，中东突发油轮遇袭或航道袭击事件首个交易日，"
    "统计后续5/10/20个交易日区间收益中位数与正收益概率",
    "中证智能汽车主题指数历史数据中，特斯拉发布Robotaxi商业运营重大进展当日，"
    "统计后续5/20/60个交易日收益中位数、最大回撤及正收益概率",
    "万得新型城镇化概念指数历史数据中，各省市出台老旧小区自主更新财政奖补政策当日，"
    "统计后续1/3/5个交易日相对沪深300的超额收益中位数与胜率",
]

# 🔴 必须拦下的：每条只缺一样，用来定位是哪个要素在起作用
BAD = [
    # 典型废话：四样一个都没有 —— 这正是这道闸要拦的东西
    ("用历史数据回测看看效果",                          {"asset", "condition", "horizon", "metric"}),
    # 「沪深300」必须被认作 asset —— 补正则前这条会误报缺 asset（写测试时抓到的真漏洞）
    ("统计沪深300在政策出台后的表现",                    {"horizon", "metric"}),
    ("统计5/20/60个交易日的收益中位数和正收益概率",       {"asset", "condition"}),
    ("沪深300指数在单日跌超5%后的走势",                  {"horizon", "metric"}),
    ("",                                               {"asset", "condition", "horizon", "metric"}),
]


def test_good_all_pass():
    for t in GOOD:
        assert missing_parts(t) == [], f"误杀：{t[:24]} 缺 {missing_parts(t)}"


def test_bad_all_blocked():
    for t, want_missing in BAD:
        got = set(missing_parts(t))
        assert got, f"漏放：{t[:24]!r} 竟然过闸了"
        assert got == want_missing, f"{t[:24]!r} 期望缺 {want_missing}，实得 {got}"


def test_filter_reports_rejections():
    """拒收必须留痕 —— 分不清「热点差」和「prompt 坏了」是事故的温床。"""
    topics = ([{"name": f"good{i}", "testable": t} for i, t in enumerate(GOOD)]
              + [{"name": "bad", "testable": "用历史数据回测看看效果"}])
    keep, rejected = filter_topics(topics)
    assert len(keep) == 3
    assert len(rejected) == 1
    name, miss = rejected[0]
    assert name == "bad"
    assert set(miss) == {"asset", "condition", "horizon", "metric"}


def test_four_parts_are_independent():
    """四个要素各判各的，不许一个命中带过全部。"""
    got = check_testable("沪深300指数")
    assert got["asset"] is True
    assert got["horizon"] is False and got["metric"] is False
