import sys
from datetime import date, timedelta
import logging

logging.basicConfig(level=logging.INFO)
today = date.today()
days_ahead = 90

# Let's mock busy_dates to be empty
busy_dates = set()

ranges = []
range_start = None
for i in range(1, days_ahead + 1):
    d = today + timedelta(days=i)
    if d not in busy_dates:
        if range_start is None:
            range_start = d
    else:
        if range_start is not None:
            ranges.append({"start": range_start.isoformat(), "end": (d - timedelta(days=1)).isoformat()})
            range_start = None
if range_start is not None:
    ranges.append({"start": range_start.isoformat(), "end": (today + timedelta(days=days_ahead)).isoformat()})

print(ranges)
