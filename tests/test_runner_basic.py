import pytest
from build_zone.automation_runner import eval_cond, get_window_bbox_by_xdotool


def test_eval_cond_true():
    assert eval_cond("true", {}) is True


def test_eval_cond_expr():
    assert eval_cond("attempts > 2", {"attempts": 3}) is True
    assert eval_cond("last_match_score >= 0.5", {"last_match_score": 0.6}) is True


def test_xdotool_fallback_none():
    # If xdotool is not present or no window, function should return None (can't assert system-specific)
    res = get_window_bbox_by_xdotool("unlikely_window_name_12345")
    assert res is None or (isinstance(res, tuple) and len(res) == 4)
