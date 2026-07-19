import os
import json
import hashlib
import hmac
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "mytoken")
os.environ.setdefault("WHATSAPP_APP_SECRET", "appsecret")
os.environ.setdefault("INTERNAL_SECRET", "internalsecret")
os.environ.setdefault("GOOGLE_CALENDAR_ID", "test@calendar")
os.environ.setdefault("GOOGLE_CALENDAR_OWNER_EMAIL", "test@test.com")

from core.main import app

client = TestClient(app)

@pytest.fixture()
def bypass_webhook_verification(monkeypatch, mocker):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "mytoken")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "appsecret")
    mocker.patch("core.main.VERIFY_TOKEN", "mytoken")
    mocker.patch("core.main.validate_webhook_signature", return_value=True)


def test_health_check():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_webhook_verification(mocker):
    mocker.patch("core.main.VERIFY_TOKEN", "mytoken")
    resp = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "mytoken",
        "hub.challenge": "12345",
    })
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_webhook_verification_wrong_token(mocker):
    mocker.patch("core.main.VERIFY_TOKEN", "mytoken")
    resp = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong",
        "hub.challenge": "12345",
    })
    assert resp.status_code == 403


def test_webhook_invalid_signature(mocker):
    mocker.patch("core.main.validate_webhook_signature", return_value=False)
    resp = client.post(
        "/webhook",
        content=b'{"test": "data"}',
        headers={"X-Hub-Signature-256": "sha256=invalid", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_webhook_status_update_ignored(mocker):
    mocker.patch("core.main.validate_webhook_signature", return_value=True)
    body = json.dumps({
        "entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}]
    }).encode()
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()
    resp = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200


@pytest.fixture()
def mock_redis_env(mocker):
    mock = mocker.MagicMock()
    mock.get.return_value = None
    mocker.patch("core.main._get_pending_payment_redis", return_value=mock)

def test_booking_intent_creates_approval_request(mocker, bypass_webhook_verification, mock_redis_env):
    """When a guest requests a booking, it creates an approval request and a soft lock, NOT a calendar event."""
    mocker.patch("core.main.CONFIG", {
        "client": {"name": "Test", "timezone": "Europe/Rome"},
        "modules": {"booking": True, "payments": False, "reminders": False},
        "booking": {
            "calendar_id": "test",
            "calendar_owner_email": "test@test.com",
            "max_guests": 2,
            "minimum_stay_periods": [
                {"start_date": "2027-01-01", "end_date": "2027-12-31", "min_nights": 2}
            ],
            "pricing_periods": [
                {"start_date": "2027-01-01", "end_date": "2027-12-31", "price_per_night": 100}
            ]
        },
        "authorized_approvers": [{"phone": "+393000000001", "name": "Anna"}]
    })
    mock_calendar = mocker.MagicMock()
    mock_calendar.is_range_available.return_value = True
    mocker.patch("core.main._get_calendar_client", return_value=mock_calendar)
    
    mock_send = mocker.patch("core.main.WA.send_text", new_callable=mocker.AsyncMock)
    mock_create_req = mocker.patch("modules.approval.workflow.create_request", new_callable=mocker.AsyncMock, return_value="1234")
    
    # AI returns the requested booking
    mocker.patch("core.main.get_ai_response", return_value=(
        'Attendi conferma. {"intent": "booking_requested", '
        '"checkin": "2027-03-16", "checkout": "2027-03-18", "guests": 2, "user_name": "Jane", "lang": "it"}'
    ))

    mocker.patch("core.main._acquire_message_lock", return_value=True)
    
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "393331234567", "type": "text", "text": {"body": "I want to book"}}
    ]}}]}]}).encode()
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()

    test_client = TestClient(app)
    resp = test_client.post("/webhook", content=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})

    assert resp.status_code == 200
    
    # Calendar event is NOT created
    mock_calendar.create_event.assert_not_called()
    
    # Soft lock is created
    mock_calendar.lock_range.assert_called_once()
    
    # Approval request is created
    mock_create_req.assert_called_once()
    
    # Guest is notified
    assert mock_send.called

def test_cancellation_intent_creates_approval_request(mocker, bypass_webhook_verification, mock_redis_env):
    """When a guest confirms cancellation, it creates an approval request and doesn't auto-delete."""
    mocker.patch("core.main.CONFIG", {
        "client": {"name": "Test", "timezone": "Europe/Rome"},
        "modules": {"booking": True},
        "booking": {
            "calendar_id": "test",
            "calendar_owner_email": "test@test.com"
        },
        "authorized_approvers": [{"phone": "+393000000001", "name": "Anna"}]
    })
    mock_calendar = mocker.MagicMock()
    mocker.patch("core.main._get_calendar_client", return_value=mock_calendar)

    # User already has a pending cancellation context
    mocker.patch("core.main._get_pending_cancellation", return_value=[
        {"id": "evt123", "summary": "Stay", "date": "Monday March 16, 2030", "time": "15:00"}
    ])

    mock_send = mocker.patch("core.main.WA.send_text", new_callable=mocker.AsyncMock)
    mock_create_req = mocker.patch("modules.approval.workflow.create_request", new_callable=mocker.AsyncMock, return_value="1234")

    # AI returns cancellation_confirmed
    mocker.patch("core.main.get_ai_response", return_value=(
        'Ho richiesto la cancellazione. {"intent": "cancellation_confirmed", "event_index": 1}'
    ))

    mocker.patch("core.main._acquire_message_lock", return_value=True)

    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "393331234567", "type": "text", "text": {"body": "Confermo, cancella."}}
    ]}}]}]}).encode()
    sig = "sha256=" + hmac.new(b"appsecret", body, hashlib.sha256).hexdigest()

    test_client = TestClient(app)
    resp = test_client.post("/webhook", content=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})

    assert resp.status_code == 200

    # Calendar event is NOT deleted automatically
    mock_calendar.delete_event.assert_not_called()

    # Approval request is created
    mock_create_req.assert_called_once()
    
    args = mock_create_req.call_args[0][3]
    assert args["type"] == "cancel"
    assert args["event_id"] == "evt123"

    # Guest is notified
    assert mock_send.called
