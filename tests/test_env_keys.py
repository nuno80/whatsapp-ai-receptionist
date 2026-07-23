import os
import pytest
import httpx
from dotenv import load_dotenv

load_dotenv()

@pytest.mark.asyncio
async def test_nvidia_api_key():
    api_key = os.getenv("NVIDIA_API_KEY")
    assert api_key, "NVIDIA_API_KEY not found in environment"
    
    # Simple call to NVIDIA's chat completions endpoint using the correct URL and model
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gemma2-9b-it", # standardizing ollama endpoint test name for gemma
        "messages": [{"role": "user", "content": "Say 'hello' in one word."}],
        "max_tokens": 10
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=10.0
        )
        
    assert response.status_code == 200, f"NVIDIA API failed: {response.text}"
    data = response.json()
    assert "choices" in data
    assert len(data["choices"]) > 0

@pytest.mark.asyncio
async def test_whatsapp_auth():
    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    
    assert token, "WHATSAPP_ACCESS_TOKEN not found"
    assert phone_id, "WHATSAPP_PHONE_NUMBER_ID not found"
    
    # Just check if the WhatsApp token is valid by doing a simple GET request
    # This URL fetches business profile info (which is standard and non-destructive)
    url = f"https://graph.facebook.com/v22.0/{phone_id}"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        
    assert response.status_code == 200, f"WhatsApp API token/phone_id invalid: {response.text}"
