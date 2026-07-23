import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from modules.approval.workflow import is_approver, handle_approval_message, create_request, get_pending_requests
import redis.asyncio as redis

@pytest.fixture
def mock_redis():
    mock = AsyncMock(spec=redis.Redis)
    return mock

@pytest.fixture
def mock_config():
    return {
        "authorized_approvers": [
            {"phone": "+393000000001", "name": "Anna"},
            {"phone": "+393000000002", "name": "Marco"}
        ]
    }

@pytest.fixture
def mock_whatsapp():
    mock = AsyncMock()
    return mock

def test_is_approver(mock_config):
    assert is_approver("+393000000001", mock_config) == "Anna"
    assert is_approver("+393000000002", mock_config) == "Marco"
    assert is_approver("+393000000003", mock_config) is None

@pytest.mark.asyncio
async def test_create_request_fans_out(mock_redis, mock_config, mock_whatsapp):
    request_data = {"type": "create", "guest_phone": "+1234", "guest_name": "John", "total": 240, "dates": "10-12 Oct"}
    
    mock_redis.set = MagicMock(return_value=True)
    
    req_id = await create_request(mock_redis, mock_config, mock_whatsapp, request_data)
    
    assert req_id is not None
    assert len(req_id) == 4
    mock_redis.set.assert_called_once()
    assert mock_whatsapp.send_message.call_count == 2
    # Check that message contains the ID
    first_call_args = mock_whatsapp.send_message.call_args_list[0][1]
    assert req_id in first_call_args['text']
    assert first_call_args['to'] == "+393000000001"

@pytest.mark.asyncio
async def test_handle_approval_multiple_pending_requires_id(mock_redis, mock_config, mock_whatsapp):
    # Setup redis to return multiple pending
    mock_redis.keys = MagicMock(return_value=[b"approval:req1", b"approval:req2"])
    
    # Approver sends bare OK
    result = await handle_approval_message(mock_redis, mock_config, mock_whatsapp, "+393000000001", "OK")
    
    assert result == "pending_list"
    mock_whatsapp.send_message.assert_called_with(to="+393000000001", text=pytest.approx("Ci sono più richieste in attesa. Rispondi con OK <id> o NO <id>:\n- req1\n- req2"))
    mock_redis.setnx.assert_not_called()

@pytest.mark.asyncio
async def test_handle_approval_claim_wins_ok(mock_redis, mock_config, mock_whatsapp, mocker):
    mock_redis.keys = MagicMock(return_value=[b"approval:r123"])
    mock_redis.get = MagicMock(return_value=b'{"type": "create", "guest_phone": "+1234", "checkin": "2026-03-16", "checkout": "2026-03-18", "guests": 2, "total": 200, "lang": "it", "guest_name": "Jane"}')
    mock_redis.setnx = MagicMock(return_value=True) # Claim won
    mock_redis.delete = MagicMock(return_value=1)
    
    mock_cal = MagicMock()
    mocker.patch("modules.approval.workflow._get_calendar_client", return_value=mock_cal)
    
    result = await handle_approval_message(mock_redis, mock_config, mock_whatsapp, "+393000000001", "OK r123")
    
    assert result == "approved"
    mock_redis.setnx.assert_called_with("approval:claim:r123", "Anna")
    
    # Calendar event created
    mock_cal.create_event.assert_called_once()
    # Soft lock released
    mock_cal.release_range.assert_called_once()
    
    # Guest notified
    guest_call = [call for call in mock_whatsapp.send_message.call_args_list if call.kwargs['to'] == '+1234'][0]
    assert "Confermata" in guest_call.kwargs['text']
    
    # Other approver notified
    other_call = [call for call in mock_whatsapp.send_message.call_args_list if call.kwargs['to'] == '+393000000002'][0]
    assert "approvata da Anna" in other_call.kwargs['text']

@pytest.mark.asyncio
async def test_handle_approval_claim_wins_no(mock_redis, mock_config, mock_whatsapp, mocker):
    mock_redis.keys = MagicMock(return_value=[b"approval:r123"])
    mock_redis.get = MagicMock(return_value=b'{"type": "create", "guest_phone": "+1234", "checkin": "2026-03-16", "checkout": "2026-03-18"}')
    mock_redis.setnx = MagicMock(return_value=True) # Claim won
    mock_redis.delete = MagicMock(return_value=1)
    
    mock_cal = MagicMock()
    mocker.patch("modules.approval.workflow._get_calendar_client", return_value=mock_cal)
    
    result = await handle_approval_message(mock_redis, mock_config, mock_whatsapp, "+393000000001", "NO r123")
    
    assert result == "rejected"
    
    # Calendar event NOT created
    mock_cal.create_event.assert_not_called()
    # Soft lock released
    mock_cal.release_range.assert_called_once()
    
    # Guest notified
    guest_call = [call for call in mock_whatsapp.send_message.call_args_list if call.kwargs['to'] == '+1234'][0]
    assert "non possiamo ospitarti" in guest_call.kwargs['text']

@pytest.mark.asyncio
async def test_handle_approval_cancel_wins_ok(mock_redis, mock_config, mock_whatsapp, mocker):
    mock_redis.keys = MagicMock(return_value=[b"approval:r123"])
    mock_redis.setnx = MagicMock(return_value=True) # Claim won
    mock_redis.delete = MagicMock(return_value=1)
    
    mock_cal = MagicMock()
    mocker.patch("modules.approval.workflow._get_calendar_client", return_value=mock_cal)
    
    mock_config["booking"] = {"cancellation_policy": {"free_cancellation_days_before": 7}}
    
    mock_redis.get = MagicMock(return_value=b'{"type": "cancel", "guest_phone": "+1234", "event_id": "event_1", "checkin_str": "Monday March 16, 2030"}')
    
    result = await handle_approval_message(mock_redis, mock_config, mock_whatsapp, "+393000000001", "OK r123")
    
    assert result == "approved"
    mock_redis.setnx.assert_called_with("approval:claim:r123", "Anna")
    
    # Calendar event deleted
    mock_cal.delete_event.assert_called_with("event_1")
    
    # Guest notified about free cancellation
    guest_call = [call for call in mock_whatsapp.send_message.call_args_list if call.kwargs['to'] == '+1234'][0]
    assert "gratuita" in guest_call.kwargs['text']
    assert "confermata" in guest_call.kwargs['text']
@pytest.mark.asyncio
async def test_handle_approval_claim_loses(mock_redis, mock_config, mock_whatsapp):
    mock_redis.keys = MagicMock(return_value=[b"approval:r123"])
    
    def mock_get(key):
        if b"claim" in (key.encode() if isinstance(key, str) else key):
            return b'Marco'
        return b'{"type": "create", "guest_phone": "+1234"}'
        
    mock_redis.get = MagicMock(side_effect=mock_get)
    mock_redis.setnx = MagicMock(return_value=False) # Claim lost
    
    result = await handle_approval_message(mock_redis, mock_config, mock_whatsapp, "+393000000001", "OK r123")
    
    assert result == "already_claimed"
    # Inform the loser that Marco took it
    mock_whatsapp.send_message.assert_any_call(to="+393000000001", text="Richiesta r123 già gestita da Marco.")
    # Guest not notified again
    assert mock_whatsapp.send_message.call_count == 1
