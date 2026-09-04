# Apna Browser Meeting Bot — Setup Guide

Yeh bot Zoom RTMS ya Zoom Marketplace App **use nahi karta**. Yeh seedha
Zoom Web Client mein ek real browser participant ki tarah join hota hai
(Playwright se), aur audio ek virtual audio cable device se sunta/bolta hai.

## Kyun zaroori hai

Browser khud "sun" ya "bol" nahi sakta jab tak OS level par ek virtual audio
device na ho jo:
1. Meeting ka audio (jo participants bol rahe hain) capture kare — bot ke
   "kaan" ke liye.
2. Ava ka TTS jawab Zoom ke andar "mic" ki tarah inject kare — bot ki
   "awaaz" ke liye.

## Step 1 — Virtual Audio Cable install karein (Windows)

Do virtual cables chahiye:

- **VB-CABLE** (ya **VB-Audio Virtual Cable A+B**) — free version se ek
  cable milta hai jo dono direction ke liye kaam chala sakta hai, lekin
  behtar hoga do alag cables use karein taake capture aur playback mix na
  hon:
  - Cable 1 → "capture" (bot ka sunna)
  - Cable 2 → "playback" (bot ka bolna)

Download: `https://vb-audio.com/Cable/` — install karke PC restart karein.

## Step 2 — Windows Sound Settings

1. **Playback devices** mein Cable 1 ke "Input" ko System **default
   playback device** set karein (taake Zoom/Chrome ka audio wahin jaye).
2. **Recording devices** mein Cable 1 ke "Output" side se hum python
   se record karenge (device name .env mein daalna hoga).
3. Bot ke Chrome/Zoom Web Client mic input Cable 2 ke "Output" side par set
   karein (Zoom join hone ke baad audio settings mein select kar sakte hain,
   ya OS default recording device Cable 2 set kar dein taake browser
   automatically wahi chune).
4. Python jab Ava ka jawab bolega, wo Cable 2 ke "Input" side par play
   karega.

## Step 3 — Device names .env mein daalna

```bash
cd backend
.venv\Scripts\python.exe scripts\list_audio_devices.py
```

Yeh saari devices list karega. Jo exact naam dikhe wahi copy karke
`.env` mein daal dein:

```env
BOT_MIC_CAPTURE_DEVICE=CABLE Output (VB-Audio Virtual Cable)
BOT_SPEAKER_PLAYBACK_DEVICE=CABLE-B Input (VB-Audio Cable B)
```

## Step 4 — Playwright browser install

```bash
cd backend
.venv\Scripts\pip.exe install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
```

## Step 5 — Bot chalayein

Backend restart karein, phir admin dashboard se same purana flow use
karein:

1. Meeting open karein → Agent tab.
2. Zoom meeting URL/ID daalein.
3. **Start Zoom Agent** click karein — ab yeh humara apna
   `BrowserMeetingBot` chalayega, Zoom App/RTMS wala step (authorize) is
   path mein zaroori nahi hai.
4. Meeting ke andar bol kar test karein: **"Ava, deployment kab hai?"**
   — bot sunega, transcript mein save hoga, aur agar transcript mein "Ava"
   wake-word mile to jawab Cable 2 ke through Zoom mic mein bolega.

## Notes

- `BOT_HEADLESS=False` rakhein — headless Chromium real audio device use
  nahi kar pata reliably; ek visible browser window chalegi is machine par.
- Zoom apni Web Client ka HTML/selectors kabhi kabhi badal deta hai —
  agar join automatic na ho to `backend/app/agents/browser_bot.py` mein
  `_launch_browser_and_join` ke selectors update karne padenge.
- Purana RTMS code (`app/integrations/zoom_rtms.py`,
  `app/integrations/zoom/rtms_client.py`) chhua nahi gaya — agar future
  mein RTMS wapas chahiye ho to available hai, lekin `/api/zoom/*` routes
  ab is naye browser bot ko use karte hain.
