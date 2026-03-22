"""
server.py — Optional FastAPI webhook server for Railway/Render.
Exposes a POST /run endpoint that GitHub Actions calls to trigger the bot.
Run with: uvicorn server:app --host 0.0.0.0 --port $PORT

This keeps the bot alive on Railway free tier.
"""

import os, asyncio, logging
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from contextlib import asynccontextmanager

log = logging.getLogger(__name__)
BOT_SECRET = os.getenv("BOT_SECRET", "change-me-in-env")

# Track if pipeline is running (prevent concurrent runs)
running = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🤖 AnimalShortsBot server ready")
    yield

app = FastAPI(title="AnimalShortsBot", lifespan=lifespan)

class RunRequest(BaseModel):
    action: str = "generate_and_upload"
    count: int = 1

@app.get("/")
async def health():
    return {"status": "running", "bot": "AnimalShortsBot", "pipeline": "idle" if not running else "busy"}

@app.post("/run")
async def trigger_pipeline(
    req: RunRequest,
    authorization: str = Header(default="")
):
    global running

    # Verify secret
    expected = f"Bearer {BOT_SECRET}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if running:
        return {"status": "busy", "message": "Pipeline already running"}

    # Run pipeline in background so HTTP response returns immediately
    asyncio.create_task(_run_pipeline(req.count))
    return {"status": "started", "count": req.count}

async def _run_pipeline(count: int):
    global running
    running = True
    try:
        import os
        os.environ["VIDEOS_PER_DAY"] = str(count)
        from main import main
        await main()
    except Exception as e:
        log.error(f"Pipeline error: {e}")
    finally:
        running = False
