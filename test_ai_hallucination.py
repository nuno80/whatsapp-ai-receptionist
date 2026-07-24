from core.ai import build_system_prompt, get_client, _model, extract_intent
import os

os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"  # won't work but we don't need real API if we can just look at prompt

config = {
    "client": {"name": "TestHotel"},
    "bot_persona": {"name": "Giulia", "tone": "friendly"},
    "modules": {"booking": True},
    "booking": {
        "pricing_periods": [],
    }
}

free_ranges = [
    {"start": "2024-07-24", "end": "2024-08-04"},
    {"start": "2024-08-11", "end": "2024-10-21"}
]

prompt = build_system_prompt(config, "Knowledge", free_ranges, "it")
print("PROMPT:")
for line in prompt.split('\n'):
    if "Pre-calculated" in line or "From" in line:
        print(line)

