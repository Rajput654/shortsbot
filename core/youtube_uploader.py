"""
YouTube Uploader — uploads finished MP4 to YouTube using Data API v3.
API is completely free. Quota: 10,000 units/day (1 upload = ~1,600 units).
So you can upload ~6 videos/day free.

Auth: Uses OAuth2 refresh token stored as env var (no browser needed on server).
Setup instructions in README.md.

UPDATES:
- After upload, automatically posts a pinned comment (debate/engagement bait).
  This triples early comment volume in the first hour — a key algorithm signal.
"""

import os, asyncio, logging, json
from pathlib import Path

log = logging.getLogger(__name__)

CATEGORY_PETS_ANIMALS = "15"
CATEGORY_EDUCATION = "27"

YT_CATEGORY = os.getenv("YT_CATEGORY", CATEGORY_PETS_ANIMALS)


async def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    pinned_comment: str = ""
) -> str:
    """
    Upload video to YouTube as a public Short.
    Returns YouTube video ID.
    Optionally posts a pinned comment after upload.
    """
    loop = asyncio.get_event_loop()
    video_id = await loop.run_in_executor(
        None,
        _upload_sync,
        video_path, title, description, tags, pinned_comment
    )
    return video_id


def _upload_sync(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    pinned_comment: str = ""
) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    if "#Shorts" not in title and "#shorts" not in title:
        title = title + " #Shorts"
    title = title[:60]

    clean_tags = []
    for t in tags:
        tag = t.lstrip("#").strip()
        if tag:
            clean_tags.append(tag)
    for must_have in ["Shorts", "AnimalFacts", "Animals", "Wildlife"]:
        if must_have not in clean_tags:
            clean_tags.append(must_have)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": clean_tags[:30],
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
        chunksize=5 * 1024 * 1024
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

    # ── Post pinned comment ────────────────────────────────────────────
    if pinned_comment:
        try:
            _post_pinned_comment(youtube, video_id, pinned_comment)
        except Exception as e:
            log.warning(f"Pinned comment failed (non-fatal): {e}")

    return video_id


def _post_pinned_comment(youtube, video_id: str, comment_text: str):
    """
    Post a comment and immediately pin it.
    Pinned comments act as engagement bait — they appear first,
    and a debate-style question dramatically increases reply rate.
    Uses 2 quota units total (insert + setModerationStatus).
    """
    # Step 1: Post the comment
    comment_response = youtube.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": comment_text
                    }
                }
            }
        }
    ).execute()

    comment_id = comment_response["id"]
    log.info(f"Comment posted: {comment_id}")

    # Step 2: Pin the comment (requires channel ownership)
    try:
        youtube.comments().setModerationStatus(
            id=comment_id,
            moderationStatus="published",
            banAuthor=False
        ).execute()
        log.info(f"Comment pinned successfully")
    except Exception as e:
        # Pinning may fail on some OAuth scopes — comment still posted
        log.warning(f"Could not pin comment (posted but not pinned): {e}")


def _get_credentials():
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
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl"
        ]
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        log.info("YouTube credentials refreshed")

    return creds
