# -*- coding: utf-8 -*-
"""A股散户热点源头过滤器执行器。

对原始热点事实进行非黑即白物理审查（Q0 时效、Q1 直接性、Q2 覆盖面、Q3 信息增量）。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .specs.hotspot_filter import parse_response, render_prompt

logger = logging.getLogger("content_judge.hotspot_filter")


def judge_hotspots(
    items: List[Dict[str, Any]],
    llm: Callable[[str], str],
    now_str: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """对原始热点事实列表进行源头审查。

    参数:
        items: 每条包含 {'id': 1, 'time': 'YYYY-MM-DD HH:MM', 'topic'/'fact': '...'}
        llm: 文本大模型调用函数 (prompt: str) -> str
        now_str: 当前时间（可选，默认系统当前时间）

    返回:
        每条热点的审查结果列表（包含 id, result: pass/reject, failed, q0~q3 详情）
    """
    if not items:
        return []
    prompt = render_prompt(items, now_str=now_str)
    raw_output = llm(prompt)
    results = parse_response(raw_output)
    return results
