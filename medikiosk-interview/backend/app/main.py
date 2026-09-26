"""MediKiosk interview server — FastAPI WebSocket driving the voice+touch loop.

Two STT transports, negotiated at session start:

  realtime  One persistent Saaras `saaras:v3-realtime` WebSocket per interview
            (app/stt_stream.py). The browser streams raw PCM chunks while it
            is listening; Saaras does server-side VAD turn detection and
            pushes interim transcripts -> the answer finalizes as soon as
            the patient stops speaking (~600 ms). This is the fast path.

  rest      Per-utterance WAV over the Saaras REST API (the original MVP
            path). Kept as automatic fallback — used in mock mode, when the
            realtime connection cannot be established, or if it dies
            mid-interview (STT_PROVIDER=rest also forces it).

Protocol (frontend <-> backend, JSON over /ws/interview):

  client -> server
    {"type": "start", "language": "hi-IN", "mode": "general" | "ayush"}
    {"type": "audio_chunk", "data": "<base64 s16le mono 16kHz PCM>"}   # realtime
    {"type": "audio", "data": "<base64 WAV, one utterance>"}           # rest
    {"type": "answer", "value": "Pain"}        # touch input
    {"type": "skip"}
    {"type": "restart"}

  server -> client
    {"type": "started", "mock_mode", "mode", "stt": "realtime" | "rest"}
    {"type": "question", "id", "section", "text", "options", "index", "total",
     "audio": "<base64 wav | null>"}
    {"type": "partial_transcript", "text"}          # realtime interim text
    {"type": "transcript", "speaker": "patient", "text"}
    {"type": "red_flag", "message"}
    {"type": "summary", "structured", "formatted"}
    {"type": "stt_status", "mode": "rest"}          # realtime degraded to rest
    {"type": "error", "message"}
"""
import asyncio
import base64
import logging
import os
import pathlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .config import settings
from .interview import InterviewSession
from .sarvam_client import SarvamBackend
from .stt_stream import RealtimeSTT

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("medikiosk.server")

# Served kiosk UI. In the repo this resolves to ../frontend/index.html;
# inside Docker set FRONTEND_PATH=/app/frontend/index.html.
FRONTEND_INDEX = os.environ.get(
    "FRONTEND_PATH",
    str(pathlib.Path(__file__).resolve().parents[2] / "frontend" / "index.html"),
)

app = FastAPI(title="MediKiosk Interview Engine", version="0.2.0")


@app.get("/api/health")
async def health():
    return {"ok": True, "mock_mode": not settings.SARVAM_API_KEY,
            "stt_provider": settings.STT_PROVIDER,
            "languages": [l for l, _ in settings.LANGUAGES]}


@app.get("/")
async def index():
    return FileResponse(FRONTEND_INDEX)


# ---------------------------------------------------------------- session
class KioskSession:
    """Everything one kiosk WebSocket connection owns."""

    def __init__(self, ws: WebSocket, backend: SarvamBackend):
        self.ws = ws
        self.backend = backend
        self.session: InterviewSession | None = None
        self.stt: RealtimeSTT | None = None
        self.stt_mode = "rest"
        self.accepting_finals = False      # True between "question sent" and "answered"
        self.answer_lock = asyncio.Lock()
        self.outq: asyncio.Queue = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []

    # ---------- outbound (single writer keeps send_json task-safe) ----------
    async def emit(self, msg: dict) -> None:
        await self.outq.put(msg)

    async def _writer(self) -> None:
        while True:
            msg = await self.outq.get()
            if msg is None:
                break
            await self.ws.send_json(msg)

    # ---------- interview flow ----------
    async def send_question(self) -> None:
        s = self.session
        qid, section, text, options = s.current_question()
        index, total = s.progress
        payload = {"type": "question", "id": qid, "section": section, "text": text,
                   "options": options, "index": index, "total": total}
        audio = await asyncio.to_thread(self.backend.tts, text, s.language)
        payload["audio"] = base64.b64encode(audio).decode() if audio else None
        await self.emit(payload)
        self.accepting_finals = True       # kiosk starts listening after playback

    async def handle_answer(self, answer: str) -> None:
        async with self.answer_lock:
            self.accepting_finals = False
            flags = await asyncio.to_thread(self.session.record_answer, answer)
            for f in flags:
                await self.emit({"type": "red_flag", "message": f})
            if self.session.finished:
                summary = await asyncio.to_thread(self.session.build_summary)
                await self.emit({"type": "summary", **summary})
            else:
                await self.send_question()

    # ---------- realtime STT pump ----------
    async def _stt_pump(self) -> None:
        while True:
            ev = await self.stt.events.get()
            kind = ev[0]
            if kind == "partial":
                await self.emit({"type": "partial_transcript", "text": ev[1]})
            elif kind == "vad_start":
                await self.emit({"type": "state", "state": "hearing"})
            elif kind == "final":
                if not self.accepting_finals:
                    log.info("dropping stray final (not accepting): %r", ev[1][:40])
                    continue
                await self.emit({"type": "transcript", "speaker": "patient",
                                 "text": ev[1]})
                await self.handle_answer(ev[1])
            elif kind == "error":
                log.warning("realtime stt error: %s", ev[1])
                await self.emit({"type": "error", "message": f"STT: {ev[1]}"})
            elif kind == "closed":
                ok = await self.stt.reconnect()
                if not ok:
                    self.stt_mode = "rest"
                    log.warning("realtime STT down — degrading to REST utterances")
                    await self.emit({"type": "stt_status", "mode": "rest",
                                     "message": "Live streaming unavailable — "
                                                "using per-answer recording."})
                    return   # stop pumping; chunks now go down the REST path

    # ---------- lifecycle ----------
    async def start(self, language: str, mode: str) -> None:
        self.session = InterviewSession(backend=self.backend, language=language,
                                         mode=mode)
        want_realtime = (
            settings.STT_PROVIDER == "realtime"
            or (settings.STT_PROVIDER == "auto" and not self.backend.mock)
        )
        if want_realtime:
            self.stt = RealtimeSTT(self.backend.api_key, language)
            try:
                await self.stt.start()
                self.stt_mode = "realtime"
            except Exception as e:  # noqa: BLE001 — fall back, never block the kiosk
                log.warning("realtime STT unavailable (%s); using REST", e)
                self.stt = None
        self.tasks.append(asyncio.create_task(self._writer()))
        if self.stt is not None:
            self.tasks.append(asyncio.create_task(self._stt_pump()))
        await self.emit({"type": "started", "mock_mode": self.backend.mock,
                         "mode": mode, "stt": self.stt_mode})
        await self.send_question()

    async def restart(self) -> None:
        self.session = InterviewSession(backend=self.backend,
                                         language=self.session.language,
                                         mode=self.session.mode)
        await self.send_question()

    async def shutdown(self) -> None:
        for t in self.tasks:
            t.cancel()
        if self.stt is not None:
            await self.stt.stop()


@app.websocket("/ws/interview")
async def interview_ws(ws: WebSocket):
    await ws.accept()
    kiosk = KioskSession(ws, SarvamBackend())

    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")

            if mtype == "start":
                await kiosk.start(msg.get("language", "hi-IN"),
                                  msg.get("mode", "general"))

            elif kiosk.session is None:
                await ws.send_json({"type": "error", "message": "send start first"})

            elif mtype == "audio_chunk":
                if kiosk.stt is not None:
                    pcm = base64.b64decode(msg.get("data", ""))
                    await kiosk.stt.feed_pcm(pcm)

            elif mtype == "audio":
                await kiosk.emit({"type": "state", "state": "processing"})
                wav = base64.b64decode(msg.get("data", ""))
                text = await asyncio.to_thread(
                    kiosk.backend.transcribe_wav, wav, kiosk.session.language)
                if not text:
                    await kiosk.emit({"type": "error",
                                      "message": "Could not transcribe — please try again or tap an option."})
                    await kiosk.send_question()
                    continue
                await kiosk.emit({"type": "transcript", "speaker": "patient",
                                  "text": text})
                await kiosk.handle_answer(text)

            elif mtype == "answer":
                await kiosk.emit({"type": "transcript", "speaker": "patient",
                                  "text": msg.get("value", "")})
                await kiosk.handle_answer(msg.get("value", ""))

            elif mtype == "skip":
                await kiosk.handle_answer("")

            elif mtype == "restart":
                await kiosk.restart()

    except WebSocketDisconnect:
        log.info("kiosk disconnected")
    except Exception as e:  # noqa: BLE001 — keep the socket from dying silently
        log.exception("interview loop error: %s", e)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        await kiosk.shutdown()
