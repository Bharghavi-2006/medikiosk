"""Saaras realtime streaming STT (saaras:v3-realtime) for one kiosk interview.

One persistent WebSocket per interview session. The browser streams raw PCM
(s16le, mono, 16 kHz) continuously while it is listening; Saaras runs
server-side VAD turn detection and pushes:

    ("session_begin",)              connection accepted
    ("vad_start", idx)              patient started speaking
    ("partial", text)               interim transcript while speaking
    ("final", text, idx)            finalized utterance -> treat as the answer
    ("error", message)              non-fatal or fatal error
    ("closed", reason)              connection ended (idle timeout, fatal...)

into an asyncio.Queue that the FastAPI WebSocket handler pumps to the kiosk.

Why the realtime endpoint rather than the legacy `/speech-to-text/ws`:
typed partial/final events with utterance indices, native linear16 PCM input
(no WAV framing per chunk), and endpointing handled by the model itself —
which is what makes the interview turns feel fast. Falls back to the
per-utterance REST path whenever the connection cannot be established.
"""
import asyncio
import base64
import logging

from .config import settings

log = logging.getLogger("medikiosk.stt")

# The realtime endpoint spells Odia "or-IN" (the REST API uses "od-IN").
_LANG_FIX = {"od-IN": "or-IN"}


class RealtimeSTT:
    def __init__(self, api_key: str, language: str = "hi-IN"):
        self.api_key = api_key
        self.language = _LANG_FIX.get(language, language)
        self.events: asyncio.Queue = asyncio.Queue()
        self.connected = False
        self.stopping = False
        self._client = None
        self._ws = None
        self._ctx = None

    # ---------- lifecycle ----------
    async def start(self, client=None) -> None:
        """Connect (raises on failure so the caller can fall back to REST).

        `client` lets tests inject a fake AsyncSarvamAI-compatible client.
        """
        if client is None:
            from sarvamai import AsyncSarvamAI
            client = AsyncSarvamAI(api_subscription_key=self.api_key)
        self._client = client
        await self._connect()

    async def _connect(self) -> None:
        self._ctx = self._client.speech_to_text_realtime_streaming.connect(
            language_code=self.language,
            model=settings.REALTIME_MODEL,          # saaras:v3-realtime
            mode="transcribe",
            endpointing="vad",                    # server-side turn detection
            encoding="linear16",
            sample_rate="16000",
            silence_duration_ms=settings.REALTIME_SILENCE_MS,
            min_speech_duration_ms="250",
        )
        self._ws = await self._ctx.__aenter__()
        self.connected = True
        self.stopping = False
        self._reader = asyncio.create_task(self._read())
        log.info("realtime STT connected (lang=%s)", self.language)

    async def stop(self) -> None:
        self.stopping = True
        self.connected = False
        reader = getattr(self, "_reader", None)
        if reader and not reader.done():
            reader.cancel()
        if self._ws is not None:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                log.warning("realtime close error: %s", e)
        self._ws = None

    async def reconnect(self) -> bool:
        """Best-effort reconnect after an idle drop. Returns success."""
        if self.stopping:
            return False
        try:
            await self.stop()          # clears the old reader/context
            self.stopping = False
            await self._connect()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("realtime reconnect failed: %s", e)
            self.connected = False
            return False

    # ---------- data in ----------
    async def feed_pcm(self, pcm: bytes) -> None:
        """Feed one raw PCM s16le chunk (mono, 16 kHz). Safe no-op when down."""
        if not self.connected or self._ws is None:
            return
        try:
            from sarvamai.types.realtime_audio_input import RealtimeAudioInput
            await self._ws.send_realtime_audio_input(RealtimeAudioInput(
                audio=base64.b64encode(pcm).decode("utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning("feed_pcm failed: %s", e)
            self.connected = False
            await self.events.put(("error", str(e)))

    # ---------- events out ----------
    async def _read(self) -> None:
        try:
            async for msg in self._ws:
                ev = getattr(msg, "event", None)
                if ev == "transcript.partial":
                    await self.events.put(("partial", msg.text))
                elif ev == "transcript.final":
                    await self.events.put(("final", msg.text, msg.utterance_idx))
                elif ev == "vad.speech_start":
                    await self.events.put(("vad_start", msg.utterance_idx))
                elif ev == "error":
                    await self.events.put(("error", f"{msg.code}: {msg.message}"))
                    if msg.is_fatal:
                        break
                # session.begin / vad.speech_end / config echoes: ignored
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            await self.events.put(("error", str(e)))
        finally:
            self.connected = False
            if not self.stopping:
                await self.events.put(("closed", "connection ended"))
