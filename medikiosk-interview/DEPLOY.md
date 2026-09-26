# Deploying MediKiosk

Four deployment paths, in increasing order of seriousness:

| Path | Use it for | What you need |
|---|---|---|
| A. Laptop (localhost) | development, judge demo on one machine | Python 3.10+ |
| B. Laptop + hotspot | SIH demo day, tablet as the kiosk | same laptop, phone hotspot |
| C. Server + domain | hospital pilot, always-on | any Linux box / VPS, a DNS name |
| D. Hospital LAN | on-prem, no public internet exposure | server on the hospital network |

The one rule that decides everything: **the kiosk browser only gets microphone
access on `localhost` or HTTPS.** Paths A/B dodge it; C/D solve it with Caddy.

## Quick shareable link (nothing of your own to run)

Two ways to hand someone a URL:

**1. Tunnel from your laptop (best for demos — voice works, key stays private).**
Start the app locally, then expose it through a tunnel — both give you a real
HTTPS URL, so the microphone works on any device:

```bash
# terminal 1 — run the server (with your SARVAM_API_KEY exported)
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000

# terminal 2 — no account, no install needed for the quick variant:
cloudflared tunnel --url http://localhost:8000
#   -> https://<random-name>.trycloudflare.com   (changes each run)
# or, with an ngrok account:
ngrok http 8000
```

The link lives as long as your laptop and tunnel stay up. Ideal for showing
judges / teammates on their phones. Use HTTPS everywhere you can.

**2. Free host (persistent link, e.g. for a submission form).**

```bash
git init && git add -A && git commit -m "MediKiosk interview engine"
git remote add origin git@github.com:<you>/medikiosk.git && git push -u origin main
# then: dashboard.render.com -> New + -> Blueprint -> select the repo
```

The repo already contains `render.yaml` (Docker runtime, health check on
`/api/health`). Deploy-time prompt for `SARVAM_API_KEY`:

- **Leave it empty** -> the public link runs in **mock mode**: full interview
  flow, touch input, questions spoken by the browser's built-in voice. No
  credits at risk — this is the right choice for a link you post publicly.
- **Set the key** -> full Saaras voice — but anyone with the link spends your
  credits. For private voice demos prefer the tunnel (option 1), and take
  the link down afterwards.

Free-plan caveats: the instance sleeps after ~15 min idle (first visitor then
waits ~30–60 s), and the URL is `https://<name>.onrender.com`. Railway, Koyeb
and Fly.io work the same way with the included `Dockerfile`.

---

```
[ kiosk tablet ]  --HTTPS/WSS-->  [ Caddy (TLS) ]  -->  [ uvicorn / FastAPI ]
   Chrome kiosk                     reverse proxy          app + interview engine
   mic 16 kHz PCM                                          |
                                                           +-- HTTPS --> api.sarvam.ai
                                                               (Saaras realtime WS,
                                                                Bulbul TTS, 105B chat)
```

The server holds no database yet — all state lives in the WebSocket session,
so one modest box serves many kiosks (see Scaling).

---

## A. Laptop (localhost)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SARVAM_API_KEY="sk_..."        # or skip -> mock mode
uvicorn app.main:app --reload
# open http://localhost:8000
```

`localhost` is a secure context, so the mic works with no TLS. This is also
the fallback if the demo venue has no internet: `STT_PROVIDER=rest` plus touch
input keeps the interview working even when Saaras is unreachable.

## B. SIH demo day (laptop + hotspot + tablet)

1. Run the server as in A, but bind to the network:
   `uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. Share a hotspot from your phone; connect the laptop and the tablet.
3. Find the laptop's hotspot IP: `ip addr show` (e.g. `192.168.43.10`).
4. On the tablet open `http://192.168.43.10:8000`.

HTTP on a LAN IP means **no microphone** — so demo with touch input, or use
path C-style TLS (`tls internal`) if you want voice on the tablet. Practise
both: the safest SIH demo is voice on the laptop (localhost) + the tablet
mirroring the touch flow.

## C. Single server with a domain (pilot-grade)

Any 1 vCPU / 1 GB box (DigitalOcean/AWS Lightsail/e2-standard in India, or a
mini-PC in the hospital) works. Ports 80/443 open, 8000 NOT exposed publicly.

```bash
# on the server, once:
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git   # or docker-ce + compose plugin
git clone <your-repo> medikiosk && cd medikiosk
cp .env.example .env
nano .env           # set SARVAM_API_KEY and KIOSK_DOMAIN=kiosk.yourdomain.in

docker compose --profile tls up -d --build
docker compose logs -f medikiosk     # health: GET https://kiosk.yourdomain.in/api/health
```

Caddy obtains and renews the Let's Encrypt certificate automatically (it
needs the domain's DNS A record pointing at the server, and port 80 reachable
for the ACME challenge). WebSockets — both `/ws/interview` and the outbound
Saaras realtime connection — are proxied with no extra config.

Firewall:

```bash
sudo ufw allow 22,80,443/tcp && sudo ufw enable
```

Updates:

```bash
git pull && docker compose --profile tls up -d --build   # zero-downtime-ish restart
```

## D. Hospital LAN, no public domain

Same as C, but the server never leaves the hospital network:

```bash
KIOSK_DOMAIN=kiosk.hospital.internal docker compose --profile tls up -d --build
```

and change the Caddyfile site block to use internal certificates:

```
kiosk.hospital.internal {
	tls internal
	reverse_proxy medikiosk:8000
}
```

Tablets visit `https://kiosk.hospital.internal` and accept the internal CA
warning once (or import the Caddy root CA via MDM). If the hospital network is
fully air-gapped from the internet, remember the server still needs
`api.sarvam.ai` reachability — Sarvam offers VPC/on-prem arrangements for
that scenario; short of it, this path won't have live AI.

---

## Kiosk tablet setup

- Chrome on Android (or a locked-down Android tablet with a kiosk/MDM app
  such as Fully Kiosk Browser or Google's kiosk mode).
- Open the URL; Chrome will prompt for mic permission — allow and pin it
  ("Always allow for this site"), and enable **Remember** so patients aren't
  re-prompted.
- On-device settings that matter: screen always-on, maximum brightness,
  auto-launch the browser at boot, disable notifications, USB debugging off.
- Hardware: 10-inch+ tablet, noise-cancelling USB/boom mic or headset
  (the `echoCancellation` flag in the app suppresses the spoken question
  bleeding into the mic), inline UPS.
- Verify on the tablet: `https://.../api/health` in a tab, then the interview
  flow, before the OPD day starts.

## Environment variables (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `SARVAM_API_KEY` | — | key from dashboard.sarvam.ai; empty = mock mode |
| `LLM_MODEL` | `sarvam-105b-conversations` | extraction/summary chat model |
| `STT_PROVIDER` | `auto` | `realtime` / `rest` / `auto` (realtime when a key exists) |
| `REALTIME_MODEL` | `saaras:v3-realtime` | streaming STT model |
| `REALTIME_SILENCE_MS` | `600` | end-of-turn silence; raise in noisy OPDs |
| `TTS_MODEL` | `bulbul:v2` | `v3` for better voices, `v2` for cost |
| `TTS_SPEAKER` | `anushka` | Bulbul voice |
| `KIOSK_DOMAIN` | — | used by the Caddy TLS profile |
| `FRONTEND_PATH` | (set in Docker) | only override for bare-metal runs |

## Day-2 operations

- **Logs:** `docker compose logs -f` — each interview logs STT fallbacks,
  LLM failures, and reconnects; treat a rising `realtime reconnect failed`
  rate as a network/bandwidth problem.
- **Cost watch:** Sarvam bills per second of STT, per character of TTS, per
  token of chat. Rough per-patient cost is in the blueprint (₹10–18); watch
  the Sarvam dashboard, and alert on unexpected spikes (a stuck kiosk
  streaming silence is the usual suspect — the app streams only while
  listening, but verify).
- **Key hygiene:** rotate `SARVAM_API_KEY` by editing `.env` and
  `docker compose up -d`. Never bake it into the image or commit `.env`.

## Security & compliance checklist

- [x] TLS everywhere (Caddy auto-HTTPS or `tls internal`)
- [x] Key lives in `.env`, never in code or images; `.env` git-ignored
- [x] App port bound to loopback/LAN only; firewall allows 22/80/443
- [x] Container runs as non-root
- [ ] Before real patients: HTTPS-only cookies are N/A (no cookies yet), but
      add authentication for the physician portal before it touches PHI
- [ ] Session data currently lives only in memory (lost on restart — a
      feature for privacy at this stage); persist to an **encrypted** store
      only when you build the HIS/FHIR integration, with a retention policy
- [ ] DPDP Act 2023: consent notice at the kiosk, purpose limitation, and a
      DPIA before any hospital pilot
- [ ] Keep Sarvam processing in India (default) — required for regulated
      health data

## Scaling

One uvicorn process comfortably handles ~50 concurrent kiosk sessions on a
small box (the app is mostly I/O-bound waiting on Sarvam). For more kiosks:

- `docker compose up -d --scale medikiosk=N` and let Caddy round-robin
  (each WebSocket pins to one instance; sessions are independent).
- The realtime STT connection is per-interview, so capacity is really
  bounded by your Sarvam rate limits — check them on the dashboard.
- When you add the database (FHIR persistence, Module D), move to
  Postgres + Redis and keep the stateless interview servers in front.
