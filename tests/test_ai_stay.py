import pytest
from unittest.mock import patch, MagicMock
from core.ai import build_system_prompt, extract_intent, load_knowledge, MODEL, _PROVIDER
import json

@pytest.mark.skipif(_PROVIDER != "anthropic", reason="anthropic-only model assertion")
def test_model_is_sonnet():
    assert "sonnet" in MODEL.lower()

def test_extract_intent_stay_schema():
    response_text = "Ecco la tua prenotazione.\n\n" + json.dumps({
        "intent": "booking_requested",
        "checkin": "2026-05-10",
        "checkout": "2026-05-15",
        "guests": 2,
        "user_name": "Mario Rossi",
        "lang": "it"
    })
    
    intent, visible = extract_intent(response_text)
    
    assert visible == "Ecco la tua prenotazione."
    assert intent["intent"] == "booking_requested"
    assert intent["checkin"] == "2026-05-10"
    assert intent["checkout"] == "2026-05-15"
    assert intent["guests"] == 2
    assert intent["user_name"] == "Mario Rossi"
    assert intent["lang"] == "it"

def test_build_system_prompt_persona(tmp_path):
    config = {
        "client": {"name": "B&B Roma"},
        "bot_persona": {
            "name": "Giulia",
            "tone": "cordiale-professionale",
            "declares_as_ai": True
        },
        "booking": {
            "max_guests": 2
        }
    }
    
    prompt = build_system_prompt(config, "Knowledge test", [], detected_lang="it")
    
    assert "Giulia" in prompt
    assert "cordiale-professionale" in prompt
    assert "virtual assistant" in prompt.lower() or "assistente" in prompt.lower()
    assert "*single asterisks*" in prompt
    
def test_build_system_prompt_stay_intent(tmp_path):
    config = {
        "client": {"name": "B&B Roma"},
        "modules": {"booking": True},
        "bot_persona": {"name": "Giulia"},
        "booking": {"max_guests": 2}
    }
    
    prompt = build_system_prompt(config, "", [])
    
    # Check that old fields are removed
    assert "service" not in prompt
    assert "location" not in prompt
    assert "duration" not in prompt
    
    # Check new fields are present
    assert "checkin" in prompt
    assert "checkout" in prompt
    assert "guests" in prompt
    assert "lang" in prompt
    assert "booking_requested" in prompt

def test_build_system_prompt_injected_ranges(tmp_path):
    config = {
        "client": {"name": "B&B Roma"},
        "modules": {"booking": True},
        "bot_persona": {"name": "Giulia"},
        "booking": {"max_guests": 2}
    }
    
    free_ranges = [{"start": "2026-06-01", "end": "2026-06-15"}]
    prompt = build_system_prompt(config, "", free_ranges)
    
    assert "2026-06-01" in prompt
    assert "2026-06-15" in prompt
