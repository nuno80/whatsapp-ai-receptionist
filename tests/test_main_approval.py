import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from core.main import app, _get_pending_payment_redis

@pytest.fixture
def mock_redis():
    mock = AsyncMock()
    return mock

@pytest.fixture
def override_deps(mock_redis):
    with patch("core.main._get_pending_payment_redis", return_value=mock_redis):
        yield mock_redis

@pytest.fixture
def mock_wa():
    with patch("core.main.WA") as mock:
        mock.send_text = AsyncMock()
        mock.send_text = AsyncMock()
        yield mock

@pytest.fixture
def mock_config():
    with patch("core.main.CONFIG", {
        "authorized_approvers": [{"phone": "12345", "name": "Test Approver"}]
    }):
        yield

def test_approver_message_routed(override_deps, mock_wa, mock_config):
    # Setup test client
    client = TestClient(app)
    
    # Send a webhook request from the approver
    with patch("core.main.validate_webhook_signature", return_value=True), \
         patch("core.main.handle_approval_message", new_callable=AsyncMock) as mock_handle:
             
        mock_handle.return_value = "approved"
        
        payload = {
            "entry": [{"changes": [{"value": {"messages": [{"from": "12345", "type": "text", "text": {"body": "OK 123"}}]}}]}]
        }
        
        response = client.post("/webhook", json=payload, headers={"X-Hub-Signature-256": "fake"})
        
        assert response.status_code == 200
        mock_handle.assert_called_once()
        
def test_guest_message_not_routed(override_deps, mock_wa, mock_config):
    # Setup test client
    client = TestClient(app)
    
    # Send a webhook request from a guest
    with patch("core.main.validate_webhook_signature", return_value=True), \
         patch("core.main.handle_approval_message", new_callable=AsyncMock) as mock_handle, \
         patch("core.main._acquire_message_lock", return_value=False): # stop processing early
             
        payload = {
            "entry": [{"changes": [{"value": {"messages": [{"from": "99999", "type": "text", "text": {"body": "Hello"}}]}}]}]
        }
        
        response = client.post("/webhook", json=payload, headers={"X-Hub-Signature-256": "fake"})
        
        assert response.status_code == 200
        mock_handle.assert_not_called()
