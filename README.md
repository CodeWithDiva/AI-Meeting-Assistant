# AI Meeting Assistant

Paste a Zoom or Google Meet link. The assistant joins the meeting as a
participant, listens in **Urdu and English**, and when it leaves it writes the
summary, the decisions, and the tasks — assigned to the right people and pushed
to their notification feed.

## How it joins

The assistant uses **its own browser agent**, not a vendor integration. There is
no Zoom Marketplace app, no OAuth handshake, and no RTMS webhook anywhere in the
codebase. Playwright opens a real Chromium window, joins the meeting's web
client the way a person would, and moves audio through two OS-level virtual
audio cables.

| Platform | Status |
|---|---|
| Zoom | Supported — joins the Zoom Web Client |
| Google Meet | Supported — joins as a guest (host must admit, unless Quick access is on) |

Adding another platform means one module in `backend/app/agents/platforms/` —
nothing else changes.

## What it does in a meeting

- **Transcribes Urdu, English and mixed Roman Urdu.** Whisper `small` or larger,
  with the meeting's language detected once and then held steady so it can't
  flip mid-sentence. Audio is cut at speech pauses rather than on a fixed timer,
  so sentences arrive whole. Whisper's silence filler ("Thank you.", "شکریہ") is
  filtered out instead of flooding the transcript.
- **Knows who is talking.** The agent reads the active speaker and the
  participant roster off the meeting UI, so transcript lines are attributed by
  name — which is what makes task assignment work.
- **Answers out loud.** Say "Ava, …" in the meeting and the assistant answers
  through its virtual microphone, using the meeting's own transcript as context.
- **Records, if you ask it to.** Off by default; enabling it stamps a consent
  timestamp and writes a WAV to `backend/recordings/`.

## What it produces afterwards

- A summary **written in the meeting's own language** — an Urdu meeting gets
  Urdu notes.
- The decisions the group actually settled on.
- Action items with an owner, an assigner, and a deadline in the words used.
  Each owner is matched to a registered user (email, full name, or a unique
  first name) and notified. An ambiguous or unknown name is left unassigned
  rather than guessed at.

## Setup

Full instructions, including the virtual audio cables the agent needs, are in
[docs/browser-bot-setup.md](docs/browser-bot-setup.md).

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium

# Models
ollama pull qwen2.5:7b      # Urdu quality; llama3.2:3b is noticeably worse

# Config
cp .env.example .env        # then fill in the two BOT_*_DEVICE names

# Run
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
cd ../frontend && npm install && npm run dev
```

`GET /api/system/capabilities` reports which optional pieces (Chromium, audio
devices, Whisper, TTS) are actually installed — the admin settings page shows
this, so a half-configured machine is visible rather than silently degraded.

## API

The whole product is one call:

```http
POST /api/agent/join
{ "link": "https://meet.google.com/abc-defg-hij", "title": "Sprint sync", "record": false }
```

It returns immediately with a `meeting_id` — joining can take a minute, so
progress arrives over the meeting's WebSocket as `agent_state` events
(`JOINING → IN_MEETING → PROCESSING → COMPLETE`).

| Endpoint | Purpose |
|---|---|
| `POST /api/agent/join` | Create a meeting from a link and send the assistant in |
| `POST /api/agent/join/{meeting_id}` | Send it into a meeting that already exists |
| `POST /api/agent/leave/{meeting_id}` | Leave, then write notes, decisions and tasks |
| `GET /api/agent/status/{meeting_id}` | Lifecycle state, active speaker, roster |
| `GET /api/agent/sessions` | Every meeting the assistant is currently in |
| `GET /api/meetings/{id}/recording/download` | Download the recorded WAV |

## When the local AI is unavailable

If Ollama is offline the app does not fail — it falls back to a deterministic
extractor that only lifts sentences already containing an explicit decision or
assignment marker (English, Urdu script, and Roman Urdu). It never invents
people, decisions, or dates. If the configured model simply isn't pulled yet,
the app uses the best model that *is* installed and logs which one.

## Technology

**Frontend** Next.js · TypeScript · **Backend** FastAPI · SQLAlchemy · Pydantic
· **AI** faster-whisper · Ollama · Piper/pyttsx3 TTS · **Automation** Playwright
· sounddevice · **Realtime** WebSocket · **DB** SQLite (local) / PostgreSQL

## Architecture

```text
Meeting link
     │
     ▼
POST /api/agent/join ──────► Meeting row created, returns immediately
     │
     ▼
BrowserMeetingBot (Playwright + Chromium)
     ├── platforms/zoom.py · platforms/google_meet.py   join, speaker, roster
     └── virtual audio cables
             │
             ▼
     LiveMeetingPipeline
       ├── speech-boundary windowing
       ├── faster-whisper (Urdu / English, sticky language)
       ├── speaker-attributed transcript  ──► WebSocket ──► live UI
       ├── optional WAV recording
       └── AvaVoiceAssistant ──► TTS ──► back into the meeting
             │
             ▼ (on leave)
     Ollama ──► summary · decisions · action items
             │
             ▼
     persist_meeting_notes ──► tasks assigned to users + notifications
```
