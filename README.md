# AI Meeting Assistant

An AI-powered meeting assistant that can join supported online meetings,
listen to conversations, generate transcripts, create meeting notes,
extract decisions, assign tasks, and answer questions during meetings.

## Project Status

🚧 Day 1 — Project Initialization

The backend foundation is mapped at `backend/app`. The platform decision is deliberately deferred until the Day 2–3 live tests are complete. See [the Day 1 feasibility report](docs/feasibility/day-01-platform-feasibility.md).

## Planned Features

- AI meeting agent
- Meeting joining
- Real-time transcription
- Speaker identification
- Meeting recording (optional)
- Automatic meeting notes
- Decision extraction
- Action item extraction
- Person-to-person task assignment
- Meeting memory
- AI meeting Q&A
- Real-time AI answers
- Voice interaction
- Notifications
- Meeting history

## Technology Stack

### Frontend
- Next.js
- TypeScript
- Tailwind CSS

### Backend
- Python
- FastAPI
- Pydantic
- SQLAlchemy

### Database
- PostgreSQL
- pgvector

### AI
- faster-whisper
- pyannote.audio
- Ollama
- Local LLM
- TTS

### Real-Time Communication
- WebSocket

### Background Processing
- Celery
- Redis

### Desktop
- Electron

### Infrastructure
- Docker
- Docker Compose
- GitHub Actions

## Architecture

```text
User
  │
  ▼
Web Dashboard / Desktop App
  │
  ▼
FastAPI Backend
  │
  ├── Meeting Agent
  ├── Real-Time Audio
  ├── Speech-to-Text
  ├── Speaker Diarization
  ├── AI / LLM
  ├── Meeting Memory
  └── Task Management
  │
  ▼
PostgreSQL + pgvector
