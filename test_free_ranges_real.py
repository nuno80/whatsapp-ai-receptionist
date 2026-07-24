import os
import sys
from core.main import _get_free_ranges
from modules.booking.calendar import CalendarClient

os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = "missing" # We can't actually run this, but we can see the log output if it's stored.
