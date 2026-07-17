from datetime import date

import pytest

from modules.booking.pricing import price_for_stay, min_nights_required, UnpricedNightError


def _period(start, end, price_per_night):
    return {"start_date": start, "end_date": end, "price_per_night": price_per_night}


def test_price_single_period_sums_nights():
    periods = [_period("2026-07-01", "2026-07-31", 120)]
    total = price_for_stay(date(2026, 7, 10), date(2026, 7, 13), periods)
    assert total == 360


def test_price_one_night():
    periods = [_period("2026-07-01", "2026-07-31", 120)]
    total = price_for_stay(date(2026, 7, 10), date(2026, 7, 11), periods)
    assert total == 120


def test_price_last_matching_period_wins_for_a_night():
    periods = [
        _period("2026-07-01", "2026-07-31", 100),
        _period("2026-07-10", "2026-07-20", 150),
    ]
    total = price_for_stay(date(2026, 7, 12), date(2026, 7, 14), periods)
    assert total == 300


def test_price_crosses_periods_with_inclusive_boundaries():
    periods = [
        _period("2026-07-01", "2026-07-10", 100),
        _period("2026-07-11", "2026-07-20", 130),
    ]
    total = price_for_stay(date(2026, 7, 9), date(2026, 7, 13), periods)
    assert total == 460


def test_price_uncovered_night_raises():
    periods = [_period("2026-07-01", "2026-07-10", 100)]
    with pytest.raises(UnpricedNightError):
        price_for_stay(date(2026, 7, 9), date(2026, 7, 13), periods)


def _min_period(start, end, min_nights):
    return {"start_date": start, "end_date": end, "min_nights": min_nights}


def test_min_nights_single_period():
    periods = [_min_period("2026-07-01", "2026-07-31", 2)]
    assert min_nights_required(date(2026, 7, 10), date(2026, 7, 13), periods) == 2


def test_min_nights_max_of_touched_periods():
    periods = [
        _min_period("2026-07-01", "2026-07-10", 2),
        _min_period("2026-07-08", "2026-07-20", 5),
    ]
    assert min_nights_required(date(2026, 7, 9), date(2026, 7, 12), periods) == 5


def test_min_nights_none_touched_returns_zero():
    periods = [_min_period("2026-08-01", "2026-08-31", 3)]
    assert min_nights_required(date(2026, 7, 9), date(2026, 7, 12), periods) == 0
