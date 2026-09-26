"""Runtime configuration. Everything is read from environment variables.

Set SARVAM_API_KEY before running for live AI; without it the app runs in
mock mode (touch input still works end-to-end, LLM/TTS are stubbed).
"""
import os


class Config:
    SARVAM_API_KEY: str = os.environ.get("SARVAM_API_KEY", "")

    # Chat model for question extraction / summarisation.
    # "sarvam-105b" = flagship reasoning; "sarvam-105b-conversations" = dialogue-tuned.
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "sarvam-105b-conversations")

    STT_MODEL: str = os.environ.get("STT_MODEL", "saaras:v3")   # or "saaras:v4" (REST)

    # --- Realtime streaming STT (saaras:v3-realtime) ---
    # "auto": realtime when an API key is present, REST otherwise
    # "realtime" / "rest": force one path
    STT_PROVIDER: str = os.environ.get("STT_PROVIDER", "auto")
    REALTIME_MODEL: str = os.environ.get("REALTIME_MODEL", "saaras:v3-realtime")
    # End-of-turn silence (ms) — lower is snappier, higher is safer in noisy OPDs
    REALTIME_SILENCE_MS: str = os.environ.get("REALTIME_SILENCE_MS", "600")
    TTS_MODEL: str = os.environ.get("TTS_MODEL", "bulbul:v2")    # v3 = better, v2 = cheaper
    TTS_SPEAKER: str = os.environ.get("TTS_SPEAKER", "anushka")

    # Languages the UI offers at launch (BCP-47 codes).
    LANGUAGES: list = [
        ("hi-IN", "हिन्दी"), ("en-IN", "English"), ("ta-IN", "தமிழ்"),
        ("te-IN", "తెలుగు"), ("bn-IN", "বাংলা"), ("kn-IN", "ಕನ್ನಡ"),
        ("ml-IN", "മലയാളം"), ("mr-IN", "मराठी"), ("gu-IN", "ગુજરાતી"),
        ("pa-IN", "ਪੰਜਾਬੀ"), ("od-IN", "ଓଡ଼ିଆ"),
    ]

    # Bulbul TTS supports these; anything else falls back to en-IN / hi-IN.
    TTS_LANGUAGES = {"bn-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN",
                     "od-IN", "pa-IN", "ta-IN", "te-IN", "en-IN"}


settings = Config()
