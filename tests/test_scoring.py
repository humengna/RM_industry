# coding: utf-8
"""打分窗口、历史分数序列与排名，重点验证"不使用当前 bar"。"""

import numpy as np
import pytest

from momentum_timing.indicators import momentum_score
from momentum_timing.scoring import (
    bars_needed_for_history, bars_needed_for_rank, momentum_score_history,
    pick_top, rank_pool, score_for_offset, window_excluding_current,
)

LOOKBACK = 5


def ref_score_history(closes, lookback=LOOKBACK, history_days=5):
    """原脚本 rank_stock_change 的切片逻辑。"""
    scores = []
    for i in range(history_days, 0, -1):
        window = closes[-(lookback + 1 + i):-(i + 1)]
        score = momentum_score(window) if len(window) >= lookback else None
        scores.append(score if score is not None else 0.0)
    latest = closes[-(lookback + 1):-1]
    score = momentum_score(latest) if len(latest) >= lookback else None
    scores.append(score if score is not None else 0.0)
    return scores


def test_window_excludes_current_bar():
    closes = [1, 2, 3, 4, 5, 6, 7]
    assert window_excluding_current(closes, lookback=5, offset=0) == [2, 3, 4, 5, 6]


def test_window_offset_shifts_backwards():
    closes = list(range(1, 13))
    assert window_excluding_current(closes, lookback=5, offset=1) == [6, 7, 8, 9, 10]
    assert window_excluding_current(closes, lookback=5, offset=3) == [4, 5, 6, 7, 8]


def test_window_insufficient_data():
    assert window_excluding_current([1, 2, 3], lookback=5, offset=0) == []


def test_score_ignores_current_bar():
    """当前 bar 无论怎么变，都不能影响分数（避免未来函数）。"""
    base = [10.0, 10.1, 10.2, 10.3, 10.4, 10.5]
    spiked = base[:-1] + [99.0]
    assert score_for_offset(base, LOOKBACK, 0) == score_for_offset(spiked, LOOKBACK, 0)


def test_score_for_offset_insufficient_data():
    assert score_for_offset([10.0, 10.1], LOOKBACK, 0) is None


def test_bars_needed():
    assert bars_needed_for_rank(5) == 7
    assert bars_needed_for_history(5, 5) == 12


def test_history_length_and_order():
    closes = [10.0 + 0.1 * i for i in range(15)]
    scores = momentum_score_history(closes, LOOKBACK, 5)
    assert len(scores) == 6
    # 末位是最新（offset=0）的分数
    assert scores[-1] == pytest.approx(score_for_offset(closes, LOOKBACK, 0))


def test_history_matches_original_slicing():
    rng = np.random.RandomState(11)
    closes = list(10 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 20))))
    got = momentum_score_history(closes, LOOKBACK, 5)
    expected = ref_score_history(closes, LOOKBACK, 5)
    assert got == pytest.approx(expected, rel=1e-9)


def test_history_pads_zero_when_data_short():
    closes = [10.0 + i for i in range(8)]
    scores = momentum_score_history(closes, LOOKBACK, 5)
    assert len(scores) == 6
    assert scores[0] == 0.0  # 最远的窗口取不到，补 0


def test_rank_pool_sorted_desc():
    up = [10.0, 10.3, 10.6, 11.0, 11.5, 12.0]
    flat = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    down = [12.0, 11.5, 11.0, 10.6, 10.3, 10.0]
    ranked = rank_pool({'A.SH': up, 'B.SH': flat, 'C.SH': down}, LOOKBACK)
    assert [s for s, _ in ranked] == ['A.SH', 'B.SH', 'C.SH']
    assert pick_top({'A.SH': up, 'C.SH': down}, LOOKBACK) == 'A.SH'


def test_rank_pool_skips_bad_series():
    good = [10.0, 10.3, 10.6, 11.0, 11.5, 12.0]
    short = [10.0, 10.1]
    nan_series = [10.0, float('nan'), 10.6, 11.0, 11.5, 12.0]
    ranked = rank_pool({'A.SH': good, 'B.SH': short, 'C.SH': nan_series, 'D.SH': None}, LOOKBACK)
    assert [s for s, _ in ranked] == ['A.SH']


def test_pick_top_empty_pool():
    assert pick_top({}, LOOKBACK) is None
