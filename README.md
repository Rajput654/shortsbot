# 🤖 AnimalShortsBot — Full Automation Pipeline

Fully automated YouTube Shorts bot. Runs 100% free on GitHub Actions or Railway/Render.

**Pipeline:** Claude AI Script → Edge TTS Voiceover → Pexels Footage → FFmpeg Video → YouTube Upload

---

## ✅ What's 100% Free

| Component | Tool | Cost |
|---|---|---|
| Script generation | Claude API (free tier) | $0 |
| Text-to-speech | Edge-TTS (Microsoft) | $0 forever |
| Animal footage | Pexels API | $0 forever |
| Video assembly | FFmpeg | $0 forever |
| Scheduling | GitHub Actions | $0 (2000 min/month) |
| YouTube upload | YouTube Data API v3 | $0 (10k units/day) |

---

## 🚀 Setup in 5 Steps

### Step 1 — Get your API keys (all free)

**Claude API key:**
1. Go to https://console.anthropic.com
2. Create account → API Keys → Create Key
3. Copy key (starts with `sk-ant-...`)

**Pexels API key:**
1. Go to https://www.pexels.com/api/
2. Create free account → Your API Key
3. Copy key

**YouTube OAuth credentials:**
1. Go to https://console.cloud.google.com
2. Create new project → name it "ShortsBot"
3. APIs & Services → Library → search "YouTube Data API v3" → Enable
4. APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
5. Application type: Desktop App → Create → Download JSON
6. Save as `client_secret.json` in this folder
7. On your LOCAL machine run:
   ```bash
   pip install google-auth-oauthlib google-api-python-client
   python setup_youtube_auth.py
   ```
8. Browser opens → log in with your YouTube channel's Google account
9. Copy the JSON output — you'll need it in Step 3

---

### Step 2 — Deploy to GitHub Actions (Recommended — Easiest)

1. Create a new GitHub repository (private)
2. Push this entire folder to it:
   ```bash
   git init
   git add .
   git commit -m "initial"
   git remote add origin https://github.com/YOUR-USERNAME/shortsbot.git
   git push -u origin main
   ```
3. Go to your repo → Settings → Secrets and variables → Actions
4. Add these secrets (click "New repository secret" for each):
   - `ANTHROPIC_API_KEY` → your Claude key
   - `PEXELS_API_KEY` → your Pexels key  
   - `YT_CREDENTIALS` → the JSON from setup_youtube_auth.py

That's it. The bot will automatically run 4x daily at:
- 8:00 AM IST
- 12:00 PM IST  
- 6:00 PM IST ⭐ (best time)
- 9:00 PM IST

---

### Step 3 — Deploy to Railway (Alternative — Keep Server Running)

1. Go to https://railway.app → New Project → Deploy from GitHub repo
2. Connect your GitHub account → select this repo
3. Railway auto-detects nixpacks.toml and installs FFmpeg
4. Go to Variables tab → add all keys from .env.example
5. Set Start Command: `python server.py`
6. Deploy → copy your Railway URL (e.g. https://shortsbot.up.railway.app)

Then in GitHub repo secrets add:
- `BOT_WEBHOOK_URL` → https://your-railway-url.up.railway.app/run
- `BOT_SECRET` → same as BOT_SECRET in Railway vars

GitHub Actions will call your Railway server 4x daily instead of running directly.

---

### Step 4 — Add Background Music (Optional)

1. Go to https://www.youtube.com/audiolibrary
2. Download 3-5 free tracks (filter: No attribution required)
3. Save them to `assets/music/` folder
4. Push to GitHub — the bot will randomly pick one per video

---

### Step 5 — Test it

Run manually to test:
```bash
# Local test
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your keys
python main.py

# Or trigger GitHub Actions manually:
# Go to Actions tab → Daily Animal Shorts Bot → Run workflow
```

---

## 📁 Project Structure

```
shortsbot/
├── main.py                  # Orchestrator — runs full pipeline
├── server.py                # Optional FastAPI webhook server
├── setup_youtube_auth.py    # Run once locally to get YT credentials
├── requirements.txt         # Python dependencies
├── nixpacks.toml            # Railway deployment config
├── Dockerfile               # Render deployment config
├── .env.example             # Environment variables template
├── .github/
│   └── workflows/
│       └── daily_shorts.yml # GitHub Actions cron schedule
├── core/
│   ├── script_generator.py  # Claude AI script generation
│   ├── tts_engine.py        # Edge-TTS voiceover (free)
│   ├── footage_fetcher.py   # Pexels footage downloader
│   ├── video_assembler.py   # FFmpeg video assembly + captions
│   ├── youtube_uploader.py  # YouTube Data API upload
│   └── scheduler.py         # IST timing logic
├── assets/
│   ├── music/               # Add background music MP3s here
│   └── font.ttf             # Caption font (auto-downloaded)
└── output/                  # Temp video files (auto-cleaned)
```

---

## ⚠️ YouTube Policy Reminders

- ✅ All footage from Pexels (free commercial license)
- ✅ Edge-TTS is Microsoft's service — no copyright issues
- ✅ AI content disclosure added automatically to descriptions
- ✅ #Shorts tag added automatically to all titles
- ❌ Never reuse other creators' clips
- ❌ Never claim facts that aren't verified
- ❌ Never use BBC/NatGeo/Discovery footage

---

## 🛠 Troubleshooting

**"YT_CREDENTIALS not set"** → Run setup_youtube_auth.py and copy the output JSON

**"FFmpeg not found"** → Railway: nixpacks.toml handles it. Local: install ffmpeg

**"Pexels no results"** → The footage_fetcher has fallback search terms built in

**"Claude API error"** → Check your ANTHROPIC_API_KEY and free tier quota

**Videos not appearing as Shorts** → Ensure video is exactly 9:16 (1080x1920) and under 60 seconds
