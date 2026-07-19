import io
import logging
import os

import openai

logger = logging.getLogger(__name__)

_client: openai.OpenAI | None = None


def _get_client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/ogg", lang: str = "it") -> str:
    """Transcribe audio bytes using OpenAI Whisper."""
    ext_map = {
        "audio/ogg": "ogg",
        "audio/ogg; codecs=opus": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/wav": "wav",
    }
    ext = ext_map.get(mime_type, "ogg")
    file = io.BytesIO(audio_bytes)
    file.name = f"audio.{ext}"

    client = _get_client()
    
    # We pass the guest's language explicitly to guide Whisper
    # If the guest switches language, Whisper can still auto-detect if the audio is obviously different,
    # but providing the hint is usually better, with fallback to "it"
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=file,
        language=lang,
    )
    return transcript.text
