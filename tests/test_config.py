import os
import pytest
from pathlib import Path
from config.loader import load_config, ConfigError

MINIMAL_CONFIG = """
client:
  name: "Test Client"
  timezone: "America/Argentina/Buenos_Aires"
modules:
  booking: false
  payments: false
  reminders: false
"""

def test_load_minimal_config(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(MINIMAL_CONFIG)
    config = load_config(f)
    assert config["client"]["name"] == "Test Client"
    assert config["modules"]["booking"] is False

def test_env_var_substitution(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "abc123")
    f = tmp_path / "config.yaml"
    f.write_text('token: "${MY_TOKEN}"')
    config = load_config(f)
    assert config["token"] == "abc123"

def test_missing_env_var_raises(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text('token: "${NONEXISTENT_VAR_XYZ}"')
    with pytest.raises(ConfigError, match="NONEXISTENT_VAR_XYZ"):
        load_config(f)

def test_file_not_found_raises():
    with pytest.raises(ConfigError):
        load_config(Path("/nonexistent/config.yaml"))


REAL_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def _load_real_config(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "mytoken")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "test@calendar")
    monkeypatch.setenv("GOOGLE_CALENDAR_OWNER_EMAIL", "test@test.com")
    return load_config(REAL_CONFIG)


def test_config_yaml_has_bnb_schema(monkeypatch):
    config = _load_real_config(monkeypatch)

    assert config["client"]["timezone"] == "Europe/Rome"

    assert config["bot_persona"]["name"] == "Giulia"
    assert config["bot_persona"]["declares_as_ai"] is True

    approvers = config["authorized_approvers"]
    assert len(approvers) == 4
    assert all("phone" in a and "name" in a for a in approvers)

    booking = config["booking"]
    assert booking["max_guests"] == 2
    assert "checkin_time" in booking
    assert "checkout_time" in booking
    assert "free_cancellation_days_before" in booking["cancellation_policy"]
    assert booking["pricing_periods"]
    assert booking["minimum_stay_periods"]
    assert "services" not in booking
    assert "locations" not in booking
    assert "business_hours" not in booking

    assert config["payment_mode"] in ("deposit", "full_on_site", "full_online")

    assert "ota" in config
    assert "reminders" in config
