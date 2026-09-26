"""Sarvam AI backend wrappers (speech, chat, translation) with a mock mode.

Mock mode: when SARVAM_API_KEY is not set, every call short-circuits so the
whole app runs without a key or network — touch input works end to end,
which is handy for UI development and for judge demos as a fallback.
"""
import base64
import json
import logging
import tempfile

from .config import settings

log = logging.getLogger("medikiosk.sarvam")

# Deterministic mock responses (mock mode)
_MOCK_EXTRACTION = json.dumps({
    "understood": True, "slot_values": {}, "red_flag": False, "follow_up": None,
})


class SarvamBackend:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.SARVAM_API_KEY
        self._client = None
        self._translation_cache: dict[tuple[str, str], str] = {}

    # ---------- plumbing ----------
    @property
    def mock(self) -> bool:
        return not self.api_key

    def _client_(self):
        if self._client is None:
            from sarvamai import SarvamAI  # imported lazily so tests run without it
            self._client = SarvamAI(api_subscription_key=self.api_key)
        return self._client

    @staticmethod
    def _get(obj, *names, default=None):
        """Read the first present attribute/key (SDK objects vs dicts)."""
        for n in names:
            if isinstance(obj, dict) and n in obj:
                return obj[n]
            if hasattr(obj, n):
                v = getattr(obj, n)
                if v is not None:
                    return v
        return default

    # ---------- chat ----------
    def chat(self, system: str, user: str, temperature: float = 0.1) -> str:
        """One-shot chat completion. Returns the assistant message text."""
        if self.mock:
            return _MOCK_EXTRACTION
        try:
            resp = self._client_().chat.completions(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=600,
            )
            try:
                return resp.choices[0].message.content or ""
            except (AttributeError, IndexError, TypeError):
                # SDK objects vs plain dicts — read defensively
                choices = self._get(resp, "choices", default=[]) or []
                if choices:
                    msg = self._get(choices[0], "message", default={}) or {}
                    return self._get(msg, "content", default="") or ""
                return ""
        except Exception as e:  # noqa: BLE001 — degrade, never crash the interview
            log.warning("chat failed: %s", e)
            return ""

    # ---------- speech to text ----------
    def transcribe_wav(self, wav_bytes: bytes, language: str = "hi-IN") -> str:
        """Transcribe one utterance (WAV, mono 16 kHz, < 30 s) via Saaras REST.

        Per-utterance REST keeps the MVP simple and reliable. The upgrade path
        is the Saaras WebSocket streaming API (docs.sarvam.ai ->
        "Streaming Speech-to-Text API"), which gives interim transcripts
        while the patient is still speaking.
        """
        if self.mock or not wav_bytes:
            return ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                path = f.name
            resp = self._client_().speech_to_text.transcribe(
                file_path=path, language=language, model=settings.STT_MODEL,
            )
            return (self._get(resp, "transcript", "text", default="") or "").strip()
        except Exception as e:  # noqa: BLE001
            log.warning("transcribe failed: %s", e)
            return ""

    # ---------- text to speech ----------
    def tts(self, text: str, language: str = "hi-IN") -> bytes | None:
        """Speak `text` with Bulbul. Returns WAV bytes, or None on any failure
        (the frontend then falls back to the browser's built-in speech)."""
        if self.mock or not text:
            return None
        tts_lang = language if language in settings.TTS_LANGUAGES else (
            "en-IN" if language == "en-IN" else "hi-IN")
        try:
            resp = self._client_().text_to_speech.convert(
                text=text,
                target_language_code=tts_lang,
                model=settings.TTS_MODEL,
                speaker=settings.TTS_SPEAKER,
                speech_sample_rate=16000,
            )
            audio_b64 = self._get(resp, "audio", default="")
            if not audio_b64:
                return None
            return base64.b64decode(audio_b64)
        except Exception as e:  # noqa: BLE001
            log.warning("tts failed: %s", e)
            return None

    # ---------- translation ----------
    def translate(self, text: str, target_language: str, source_language: str = "en-IN") -> str:
        """Translate question text on the fly for languages without bundled
        translations. Cached. Falls back to the input text on failure."""
        key = (text, target_language)
        if key in self._translation_cache:
            return self._translation_cache[key]
        if self.mock:
            return text
        try:
            resp = self._client_().text.translate(
                input=text,
                source_language_code=source_language,
                target_language_code=target_language,
            )
            out = self._get(resp, "translated_text", default=text) or text
        except Exception as e:  # noqa: BLE001
            log.warning("translate failed: %s", e)
            out = text
        self._translation_cache[key] = out
        return out
