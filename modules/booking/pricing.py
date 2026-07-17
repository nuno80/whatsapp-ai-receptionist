from datetime import date, timedelta


class UnpricedNightError(Exception):
    """A stay includes a night not covered by any pricing period."""


def _nights(checkin: date, checkout: date):
    """Yield each occupied night date (checkin inclusive, checkout exclusive)."""
    for i in range((checkout - checkin).days):
        yield checkin + timedelta(days=i)


def price_for_stay(checkin: date, checkout: date, pricing_periods: list) -> int:
    """Total price in EUR for a stay.

    Each night (checkin inclusive ... checkout exclusive) is priced by the last
    pricing period in the list whose inclusive start_date/end_date covers it.
    Raises UnpricedNightError if any night is uncovered — no silent default price.
    """
    total = 0
    for night in _nights(checkin, checkout):
        price = None
        for period in pricing_periods:
            start = date.fromisoformat(period["start_date"])
            end = date.fromisoformat(period["end_date"])
            if start <= night <= end:
                price = period["price_per_night"]
        if price is None:
            raise UnpricedNightError(f"No pricing period covers night {night.isoformat()}")
        total += price
    return total


def min_nights_required(checkin: date, checkout: date, minimum_stay_periods: list) -> int:
    """Minimum nights required for a stay.

    The maximum of min_nights among all minimum-stay periods whose inclusive
    start_date/end_date covers any night of the stay. Returns 0 when no period
    touches the stay (no minimum-stay constraint).
    """
    required = 0
    for period in minimum_stay_periods:
        start = date.fromisoformat(period["start_date"])
        end = date.fromisoformat(period["end_date"])
        if any(start <= night <= end for night in _nights(checkin, checkout)):
            required = max(required, period["min_nights"])
    return required
