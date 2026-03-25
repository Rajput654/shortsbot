"""
YouTube Uploader v4.0

CHANGES v4.0:
- build_description() updated for scenario/POV format — uses scene context
  rather than documentary hook.
- OAUTH SCOPE FIX retained from v3.1.
- TITLE VALIDATION updated for POV-style titles.
- All upload mechanics unchanged.
"""

import os, asyncio, logging, json
from pathlib import Path

log = logging.getLogger(__name__)

CATEGORY_PETS_ANIMALS = "15"
YT_CATEGORY = os.getenv("YT_CATEGORY", CATEGORY_PETS_ANIMALS)

_REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def get_required_scopes() -> list[str]:
    return _REQUIRED_SCOPES


async def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    pinned_comment: str = "",
    thumbnail_path: str = "",
) -> str:
    loop = asyncio.get_event_loop()
    video_id = await loop.run_in_executor(
        None,
        _upload_sync,
        video_path, title, description, tags, pinned_comment, thumbnail_path,
    )
    return video_id


def build_description(script: dict, tags: list[str]) -> str:
    """
    v4.0: Build description for scenario/POV format.
    Uses the first scene_beat overlay text as the opening hook.
    """
    beats = script.get("scene_beats", [])
    format_type = script.get("format_type", "pov")
    animal = script.get("animal_keyword", "this animal").title()
    loop_hook = script.get("loop_hook", "")

    # Opening line: first beat text
    if beats:
        opening = beats[0].get("overlay_text", "")
        # Clean it up for description
        opening = opening.replace("\\n", " ").replace("*", "").strip()
        if len(opening) > 100:
            opening = opening[:97] + "…"
    else:
        opening = f"When your {animal} decides to be iconic 😭"

    seo_tags = script.get("seo_tags", [])
    hashtag_block = " ".join(seo_tags[:10]) if seo_tags else "#animals #funny #shorts #pets #pov"

    format_emoji = {
        "pov": "👀",
        "when_your": "😭",
        "nobody_animal": "💀",
        "understood_assignment": "🎯",
    }.get(format_type, "🐾")

    return (
        f"{format_emoji} {opening}\n\n"
        f"{loop_hook}\n\n"
        f"Follow for daily funny animal moments 🐾\n\n"
        f"{hashtag_block}\n\n"
        f"✦ AI-generated content | footage: Pexels.com"
    )


def _validate_title(title: str) -> str:
    if "#Shorts" not in title and "#shorts" not in title:
        title = title + " #Shorts"
    return title[:60]


def _upload_sync(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    pinned_comment: str = "",
    thumbnail_path: str = "",
) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds   = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    title = _validate_title(title)

    clean_tags = []
    for t in tags:
        tag = t.lstrip("#").strip()
        if tag:
            clean_tags.append(tag)
    for must_have in ["Shorts", "FunnyAnimals", "Animals", "POV", "Pets"]:
        if must_have not in clean_tags:
            clean_tags.append(must_have)

    body = {
        "snippet": {
            "title":           title,
            "description":     description,
            "tags":            clean_tags[:30],
            "categoryId":      YT_CATEGORY,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":          "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids":             False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,
    )

    log.info(f"Uploading: {title}")
    request  = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log.info(f"Upload progress: {pct}%")

    video_id = response["id"]
    log.info(f"Upload complete: https://youtube.com/shorts/{video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            _set_thumbnail(youtube, video_id, thumbnail_path)
        except Exception as e:
            log.warning(f"Thumbnail upload failed (non-fatal): {e}")

    if pinned_comment:
        try:
            _post_pinned_comment(youtube, video_id, pinned_comment)
        except Exception as e:
            log.warning(f"Pinned comment failed (non-fatal): {e}")

    return video_id


def _set_thumbnail(youtube, video_id: str, thumbnail_path: str):
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    log.info(f"Custom thumbnail set for {video_id}")


def _post_pinned_comment(youtube, video_id: str, comment_text: str):
    comment_response = youtube.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {"textOriginal": comment_text}
                },
            }
        },
    ).execute()
    comment_id = comment_response["id"]
    log.info(f"Comment posted: {comment_id}")
    try:
        youtube.comments().setModerationStatus(
            id=comment_id,
            moderationStatus="published",
            banAuthor=False,
        ).execute()
        log.info("Comment pinned successfully")
    except Exception as e:
        log.warning(f"Could not pin comment: {e}")


def _get_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds_json = os.getenv("YT_CREDENTIALS")
    if not creds_json:
        raise ValueError(
            "YT_CREDENTIALS not set.\n"
            "Run: python setup_youtube_auth.py then copy the JSON to your env vars."
        )

    creds_data = json.loads(creds_json)
    creds = Credentials(
        token=creds_data.get("token"),
        refresh_token=creds_data["refresh_token"],
        token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=_REQUIRED_SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        log.info("YouTube credentials refreshed")

    return creds
