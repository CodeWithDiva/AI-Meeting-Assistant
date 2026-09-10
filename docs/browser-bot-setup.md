# Apna Meeting Agent — Setup Guide

Ye agent **Zoom RTMS, Zoom Marketplace App, ya kisi vendor SDK ka istemal nahi
karta**. Ye Playwright se ek real Chromium browser kholta hai aur meeting me ek
aam participant ki tarah join hota hai — **Zoom** aur **Google Meet** dono par.
Audio OS-level virtual audio cable devices ke zariye aata-jata hai.

Sirf wo machine jo bot chalati hai use ye setup chahiye. Baqi backend in ke
baghair bhi chalta rahega (bot "simulated mode" me chala jayega).

---

## Kyun virtual audio cable zaroori hai

Browser khud "sun" ya "bol" nahi sakta jab tak OS level par ek virtual audio
device na ho jo:

1. **Meeting ka audio capture kare** — jo participants bol rahe hain, wo bot ke
   "kaan" tak pohanche.
2. **Ava ka TTS jawab meeting ke mic me inject kare** — bot ki "awaaz".

---

## Step 1 — Virtual Audio Cables install karein (Windows)

Do alag cables chahiye, taake capture aur playback aapas me mix na hon:

| Cable | Kaam |
|---|---|
| Cable 1 | **Capture** — bot ka sunna |
| Cable 2 | **Playback** — bot ka bolna |

Download: <https://vb-audio.com/Cable/> — VB-CABLE install karein, phir
**VB-Audio Point** (ya VB-CABLE A+B) doosre cable ke liye. Install ke baad PC
restart karein.

## Step 2 — Windows Sound Settings

1. **Playback devices** → Cable 1 ka *Input* side system ka **default playback
   device** banayein, taake Chrome/meeting ka audio wahin jaye.
2. **Recording devices** → Cable 1 ka *Output* side wo hai jahan se Python
   record karega (naam `.env` me `BOT_MIC_CAPTURE_DEVICE`).
3. Browser ka mic Cable 2 ke *Output* side par set karein — sab se aasan tareeqa
   ye hai ke Cable 2 ka Output OS ka default **recording** device bana dein,
   taake Chromium khud hi wahi chun le.
4. Ava ka jawab Python Cable 2 ke *Input* side par play karega
   (`BOT_SPEAKER_PLAYBACK_DEVICE`).

## Step 3 — Device names `.env` me daalein

```bash
cd backend
.venv\Scripts\python.exe scripts\list_audio_devices.py
```

Exact naam copy karke `.env` me daalein:

```env
BOT_MIC_CAPTURE_DEVICE=CABLE Output (VB-Audio Virtual Cable)
BOT_SPEAKER_PLAYBACK_DEVICE=Output (VB-Audio Point)
```

> **Note:** Windows par ek hi cable har host API (MME, DirectSound, WASAPI,
> WDM-KS) ke liye alag alag dikhta hai. Agent khud sahi endpoint chun leta hai —
> aisa jo 16 kHz support karta ho — aur agar naam kisi device se match na kare to
> **error deta hai**, chupke se laptop ka apna mic use nahi karta. Chahein to
> naam ki jagah seedha device **index** (jaise `9`) bhi daal sakte hain.

## Step 4 — Playwright browser install

```bash
cd backend
.venv\Scripts\pip.exe install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
```

## Step 5 — AI models

```bash
ollama pull qwen2.5:7b        # Urdu ke liye llama3.2:3b se bohat behtar
```

Whisper `small` model pehli baar chalne par khud download ho jata hai (~480 MB).
`.env` me:

```env
OLLAMA_MODEL=qwen2.5:7b
WHISPER_MODEL=small
WHISPER_LANGUAGE=            # khali = Urdu/English khud pehchano
```

## Step 6 — Agent chalayein

1. Dashboard kholein.
2. **"Send the assistant to a meeting"** box me Zoom ya Google Meet ka link
   paste karein → **Join meeting**.
3. Meeting page khud khul jayega, jahan live status dikhega:
   `JOINING → IN_MEETING → PROCESSING → COMPLETE`.
4. Meeting me bol kar test karein: **"Ava, deployment kab hai?"** — bot sunega,
   transcript me save karega, aur jawab Cable 2 ke zariye meeting me bolega.
5. Kaam khatam hone par **Leave meeting & write notes** — summary, decisions aur
   assigned tasks khud ban jayenge.

---

## Notes aur limitations

- **`BOT_HEADLESS=False` rakhein.** Headless Chromium real audio devices
  reliably use nahi kar pata; ek visible browser window chalegi.
- **Google Meet me host ko bot ko admit karna hoga** (guest lobby). Agar host
  "Quick access" on kar de to bot seedha andar aa jayega.
- **Zoom aur Meet apne HTML/selectors badalte rehte hain.** Agar join fail ho to
  agent khud `backend/debug/` me screenshot + page ke saare controls ka dump
  save karta hai — usi se selectors theek kiye ja sakte hain. Selectors yahan
  hain: `app/agents/platforms/zoom.py` aur `app/agents/platforms/google_meet.py`.
- **Recording by default band hai.** Join karte waqt checkbox se on karein; consent
  timestamp DB me save hota hai. Audio `backend/recordings/` me WAV banta hai.
- Naya platform add karna ho to sirf `app/agents/platforms/` me ek module aur
  `app/agents/platforms/__init__.py` me ek entry chahiye — baqi kuch change nahi
  karna parta.
