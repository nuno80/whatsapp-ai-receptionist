import json
import pytest
from core.ai import extract_booking_intent, build_system_prompt


def test_extract_booking_intent_present():
    response = 'Great, your appointment is confirmed. {"intent": "booking_confirmed", "service": "Dental Cleaning", "date": "2026-03-17", "time": "10:00", "location": "Downtown Office", "user_name": "Jane"}'
    intent, visible = extract_booking_intent(response)
    assert intent is not None
    assert intent["intent"] == "booking_confirmed"
    assert intent["service"] == "Dental Cleaning"
    assert "intent" not in visible
    assert "Great" in visible


def test_extract_booking_intent_absent():
    response = "Hi, how can I help you?"
    intent, visible = extract_booking_intent(response)
    assert intent is None
    assert visible == response


def test_build_system_prompt_core_only():
    config = {
        "client": {"name": "Test Dentist"},
        "modules": {"booking": False, "payments": False},
    }
    knowledge = "Services: Dental Cleaning $150"
    prompt = build_system_prompt(config, knowledge)
    assert "Test Dentist" in prompt
    assert "Services: Dental Cleaning" in prompt
    assert "booking_confirmed" not in prompt  # booking disabled


def test_build_system_prompt_with_booking():
    config = {
        "client": {"name": "Test"},
        "modules": {"booking": True, "payments": False},
        "booking": {
            "max_guests": 2,
            "min_stay_nights": 2,
        }
    }
    prompt = build_system_prompt(config, "knowledge")
    assert "booking_requested" in prompt
