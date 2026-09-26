# MediKiosk — Interview Engine (Module A)

Voice + touch multilingual clinical history interview, built on the Sarvam AI stack.
This is the conversational heart of the SIH26047 (Patient Case-Taking Software) platform:
the kiosk asks each question in the patient's language, accepts the answer by **speech
or by tapping options**, extracts structured clinical fields, watches for emergency
red flags, and ends with a physician-ready draft summary.

```
Patient speaks ──▶ mic (browser, 16 kHz) ──▶ FastAPI WebSocket
                                                  │
            ┌─────────────────────────────────────┤
            ▼                                     ▼
  REALTIME PATH (default with API key)      REST fallback path
  persistent saaras:v3-realtime WS          one WAV per utterance
  raw PCM chunks, server-side VAD           /speech-to-text (Saaras)
  interim transcripts while speaking             │
            └───────────────┬─────────────────┘
                            ▼
            Bulbul TTS (/text-to-speech)  +  Sarvam-105B chat
            (spoken questions)              (/v1/chat/completions)
                            ▼
            question text + audio + tappable options ──▶ screen / speakers
```

## STT transports

With an API key, the server opens **one persistent `saaras:v3-realtime`
WebSocket per interview** (`app/stt_stream.py`). The browser streams raw PCM
while listening; Saaras does server-side VAD turn detection, so the answer
finalizes ~600 ms after the patient stops speaking, and the kiosk shows live
partial transcripts as they speak. If the connection can't be established
or drops mid-interview, the server degrades automatically to the
per-utterance REST path and tells the UI (`stt_status`). Force either path:

```bash
export STT_PROVIDER=realtime   # or "rest", or "auto" (default)
export REALTIME_SILENCE_MS=600  # end-of-turn silence; raise for noisy OPDs
```

## Run it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export SARVAM_API_KEY="..."      # get one at dashboard.sarvam.ai
                                # leave unset -> mock mode (touch-only, no network)

uvicorn app.main:app --reload --port 8000
# open http://localhost:8000  (serves frontend/index.html)
```

**Deploying for a demo or a pilot?** See **[DEPLOY.md](DEPLOY.md)** — Docker,
Caddy TLS (required for microphone access off-localhost), the kiosk tablet
setup, and on-prem/hospital-LAN options.

Requirements: Chrome/Edge (needs `AudioContext({sampleRate:16000})` and mic access —
use `localhost` or HTTPS).

## What works today

- **Dual-mode input (FR-6):** every question shows tappable options *and* accepts a
  spoken answer; the patient can mix modes freely.
- **Multilingual:** Hindi + English bundled in the questionnaire; the other launch
  languages are machine-translated on the fly via Sarvam translate (cached). Saaras
  handles 22 Indic languages + English and code-mixed speech.
- **Structured capture (FR-8/9):** answers are extracted into named clinical slots
  (chief complaint, SOCRATES fields, past history, medications, allergies, …) by
  `sarvam-105b` with a strict-JSON contract; the LLM never chooses the topic.
- **AYUSH mode (FR-10):** appends kiosk-adapted Dashavidha Pariksha questions
  (Agni, Koshtha, Ahara Shakti, Vyayama Shakti, Sattva, Samhanana, Nidra, Ahara-Vihara).
  Co-author the final set with an Ayurveda practitioner.
- **Red flags (FR-11):** bilingual keyword rules fire first (never depend on the LLM
  for safety); the LLM judgement is an additional net. The UI shows a triage banner.
- **Streaming STT (realtime):** persistent `saaras:v3-realtime` session per
  interview — interim transcripts while the patient speaks, server-side
  end-of-turn detection, automatic fallback to per-utterance REST.
- **Summary (FR-18..21 lite):** at the end, a physician-facing markdown draft is
  generated from the captured slots + transcript — explicitly a draft for the doctor.
- **Mock mode:** no API key needed for full UI development and demos with touch input.

## Project layout

```
backend/
  app/
    config.py         env-driven settings (models, languages, speaker)
    ontology.py       the questionnaire (plain data — edit freely, review with a doctor)
    prompts.py        LLM prompts (extraction JSON contract, summary format)
    stt_stream.py    Saaras realtime streaming session (saaras:v3-realtime)
    sarvam_client.py  Bulbul TTS + 105B chat + translate + REST STT, with mock mode
    interview.py      the state machine (advance, follow-up, red flags, summary)
    main.py           FastAPI + WebSocket protocol
  tests/
    test_interview_dry.py   full-flow dry run, no API key needed
    test_stt_stream.py      realtime STT reader logic (fake socket, no network)
frontend/
  index.html         single-file kiosk UI (no build step)
```

## Dry-run test (no key, no network)

```bash
cd backend && python -m tests.test_interview_dry
```

## Upgrade path (after the hackathon MVP)

1. ~~**Streaming STT:**~~ done — realtime path above. Next: barge-in (let the
   patient interrupt the spoken question; Saaras already emits
   `vad.speech_start` you can use to duck the audio), and prompt-audio caching
   (pre-render Bulbul audio per language — the biggest cost saver).
2. **Model routing:** `sarvam-105b-conversations` for turn extraction, `sarvam-105b`
   for the final summary.
3. **Triage alert path:** push red flags to a triage console via a server-push channel
   instead of only the kiosk banner.
4. **Persistence + FHIR:** persist `session.structured()` and map to FHIR R4
   (QuestionnaireResponse, Condition, MedicationStatement, AllergyIntolerance, …).
5. **ABDM:** ABHA auth + consent artefacts before the interview starts.

## Notes

- The LLM prompt forbids diagnosis and inventing facts; every summary is a draft the
  physician accepts, amends, or rejects (per the problem statement's Module C).
- Realtime notes: the mic should use `echoCancellation: true` (already set) so the
  spoken question isn't transcribed as an answer; the realtime endpoint spells Odia
  `or-IN` (auto-mapped); connections can idle-drop between long pauses and are
  reconnected or degraded to REST automatically.
- Not medical software; prototype for SIH demonstration purposes.
