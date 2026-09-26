"""Unit test for the Saaras realtime streaming client (no network, no key).

Run:  python -m tests.test_stt_stream   (from the backend/ directory)

We inject a fake AsyncSarvamAI-compatible client whose WebSocket yields the
same typed event models the real socket client produces, and assert that
RealtimeSTT surfaces them on its event queue in order.
"""
import asyncio
import base64
import sys

from sarvamai.types.realtime_audio_input import RealtimeAudioInput
from sarvamai.types.realtime_transcript_partial import RealtimeTranscriptPartial
from sarvamai.types.realtime_transcript_final import RealtimeTranscriptFinal
from sarvamai.types.realtime_vad_speech_start import RealtimeVadSpeechStart
from sarvamai.types.realtime_error import RealtimeError

from app.stt_stream import RealtimeSTT


class FakeWS:
    def __init__(self, events):
        self._events = list(events)
        self.sent = []
        self.closed = False

    async def send_realtime_audio_input(self, message):
        self.sent.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._events:
            return self._events.pop(0)
        raise StopAsyncIteration


class FakeConnect:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *exc):
        self._ws.closed = True
        return None


class FakeRealtimeStreaming:
    def __init__(self, ws):
        self._ws = ws

    def connect(self, **kwargs):
        return FakeConnect(self._ws)


class FakeClient:
    def __init__(self, ws):
        self.speech_to_text_realtime_streaming = FakeRealtimeStreaming(ws)


async def run() -> None:
    events_in = [
        RealtimeVadSpeechStart(utterance_idx=0),
        RealtimeTranscriptPartial(utterance_idx=0, text="seedhe"),
        RealtimeTranscriptPartial(utterance_idx=0, text="seedhe me dard"),
        RealtimeTranscriptFinal(utterance_idx=0, text="सीने में दर्द है"),
        RealtimeError(event="error", code="warn", is_fatal=False, message="non fatal"),
    ]
    ws = FakeWS(events_in)
    stt = RealtimeSTT("fake-key", "hi-IN")
    await stt.start(client=FakeClient(ws))
    assert stt.connected, "should be connected after start"

    # feed one PCM chunk; it must be wrapped base64 in an audio_input message
    pcm = b"\x01\x00" * 160
    await stt.feed_pcm(pcm)
    assert len(ws.sent) == 1 and isinstance(ws.sent[0], RealtimeAudioInput)
    assert ws.sent[0].audio == base64.b64encode(pcm).decode()

    # drain the surfaced events in order
    got = []
    while True:
        ev = await asyncio.wait_for(stt.events.get(), timeout=2.0)
        got.append(ev)
        if ev[0] == "closed":
            break

    assert ("vad_start", 0) in got, got
    assert ("partial", "seedhe") in got, got
    assert ("partial", "seedhe me dard") in got, got
    assert ("final", "सीने में दर्द है", 0) in got, got
    assert any(e[0] == "error" and "non fatal" in e[1] for e in got), got
    assert ("closed", "connection ended") == got[-1], got

    # language fix: Odia is spelled or-IN on the realtime endpoint
    stt2 = RealtimeSTT("k", "od-IN")
    assert stt2.language == "or-IN"

    await stt.stop()
    print("ALL STREAMING CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(run())
