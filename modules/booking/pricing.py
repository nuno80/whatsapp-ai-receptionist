from datetime import date, timedelta
from typing import List, Dict, Any


class UnpricedNightError(Exception):
    pass


def _inclusive_dates(start_str: str, end_str: str):
    s = date.fromisoformat(start_str)
    e = date.fromisoformat(end_str)
    return s, e


def price_for_stay(checkin: date, checkout: date, pricing_periods: List[Dict[str, Any]]) -> int:
    total = 0
    current = checkin
    while current < checkout:
        price = None
        # last matching period wins
        for period in pricing_periods:
            s, e = _inclusive_dates(period["start_date"], period["end_date"])
            if s <= current <= e:
                price = period["price_per_night"]

        if price is None:
            raise UnpricedNightError(f"No price defined for night {current}")

        total += price
        current += timedelta(days=1)

    return total


def min_nights_required(checkin: date, checkout: date, minimum_stay_periods: List[Dict[str, Any]]) -> int:
    required = 0
    current = checkin
    while current < checkout:
        for period in minimum_stay_periods:
            s, e = _inclusive_dates(period["start_date"], period["end_date"])
            if s <= current <= e:
                if period["min_nights"] > required:
                    required = period["min_nights"]
        current += timedelta(days=1)

    return required
