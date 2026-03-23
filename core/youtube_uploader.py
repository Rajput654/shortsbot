"""
YouTube Uploader — uploads finished MP4 to YouTube using Data API v3.
API is completely free. Quota: 10,000 units/day (1 upload = ~1,600 units).
So you can upload ~6 videos/day free.

Auth: Uses OAuth2 refresh token stored as env var (no browser needed on server).
Setup instructions in README.md.
"""

import os, asyncio, logging, json
from pathlib import Path

log = logging.getLogger(__name__)

# YouTube category IDs
CATEGORY_PETS_ANIMALS = "15"
CATEGORY_EDUCATION = "27"

# Default to Animals category for animal facts channel
YT_CATEGORY = os.getenv("YT_CATEGORY", CATEGORY_PETS_ANIMALS)


async def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str]
) -> str:
    """
    Upload video to YouTube as a public Short.
    Returns YouTube video ID.
    Runs in executor to avoid blocking async loop.
    """
    loop = asyncio.get_event_loop()
    video_id = await loop.run_in_executor(
        None,
        _upload_sync,
        video_path, title, description, tags
    )
    return video_id


def _upload_sync(video_path: str, title: str, description: str, tags: list[str]) -> str:
    """Synchronous upload — called from executor."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = _get_credentials()

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    # Ensure #Shorts is in title (required for Shorts algorithm)
    if "#Shorts" not in title and "#shorts" not in title:
        title = title + " #Shorts"

    # Trim title to 60 chars — shorter titles show fully in Shorts feed = better CTR
    title = title[:60]

    # Clean tags — remove # prefix for YouTube tags array
    clean_tags = []
    for t in tags:
        tag = t.lstrip("#").strip()
        if tag:
            clean_tags.append(tag)
    # Always include these for discoverability
    for must_have in ["Shorts", "AnimalFacts", "Animals", "Wildlife"]:
        if must_have not in clean_tags:
            clean_tags.append(must_have)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": clean_tags[:30],  # YouTube allows max 30 tags
            "categoryId": YT_CATEGORY,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        }
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024  # 5MB chunks
    )

    log.info(f"Uploading: {title}")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log.info(f"Upload progress: {pct}%")

    video_id = response["id"]
    log.info(f"Upload complete: https://youtube.com/shorts/{video_id}")
    return video_id


def _get_credentials():
    """
    Load OAuth2 credentials from environment variable.
    YT_CREDENTIALS env var should contain the JSON token string.
    See README for how to generate this once on your local machine.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds_json = os.getenv("YT_CREDENTIALS")
    if not creds_json:
        raise ValueError(
            "YT_CREDENTIALS environment variable not set.\n"
            "Run: python setup_youtube_auth.py to generate credentials.\n"
            "Then copy the output JSON into your Railway/Render env vars."
        )

    creds_data = json.loads(creds_json)
    creds = Credentials(
        token=creds_data.get("token"),
        refresh_token=creds_data["refresh_token"],
        token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        log.info("YouTube credentials refreshed")

    return creds
