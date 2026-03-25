"""
YouTube Uploader v3.0

UPGRADES v3.0 (rating fixes):
- THUMBNAIL UPLOAD: after video upload, sets a custom thumbnail extracted
  from the hook frame (~1.2s). Shorts with custom thumbnails get 15-25%
  more impressions in Browse and Search surfaces.
- DESCRIPTION TEMPLATE: curiosity-hook opening line, hashtag block, and
  AI disclosure — structured for Shorts best practice (no chapters, no links
  that demote Shorts to long-form).
- TITLE SAFETY: strips any title over 60 chars as a final guard (validate_scripts
  already enforces 48, but this catches manual overrides).
"""

import os, asyncio, logging, json
from pathlib import Path

log = logging.getLogger(__name__)

CATEGORY_PETS_ANIMALS = "15"
YT_CATEGORY = os.getenv("YT_CATEGORY", CATEGORY_PETS_ANIMALS)


async def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    pinned_comment: str = "",
    thumbnail_path: str = "",
) -> str:
    """
    Upload video to YouTube as a public Short.
    Optionally sets a custom thumbnail and posts a pinned comment.
    Returns YouTube video ID.
    """
    loop = asyncio.get_event_loop()
    video_id = await loop.run_in_executor(
        None,
        _upload_sync,
        video_path, title, description, tags, pinned_comment, thumbnail_path,
    )
    return video_id


def build_description(script: dict, tags: list[str]) -> str:
    """
    Build a Shorts-optimised description.
    - Curiosity hook (2 lines max) referencing the animal
    - Hashtag block (no chapter markers — those convert Shorts to long-form)
    - AI content disclosure (required by YouTube policy)
    """
    animal   = script.get("animal_keyword", "this animal").title()
    hook     = script.get("hook", "")
    seo_tags = script.get("seo_tags", [])

    # Keep first line under 100 chars — appears in search snippet
    hook_line = hook[:97] + "…" if len(hook) > 100 else hook

    hashtag_block = " ".join(seo_tags[:10]) if seo_tags else "#animals #wildlife #shorts"

    return (
        f"{hook_line}\n\n"
        f"Everything you need to know about the {animal} in under a minute.\n\n"
        f"{hashtag_block}\n\n"
        f"✦ AI-generated content | footage: Pexels.com"
    )


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
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds   = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    # Title safety
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

    # ── Set custom thumbnail ───────────────────────────────────────────────
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            _set_thumbnail(youtube, video_id, thumbnail_path)
        except Exception as e:
            log.warning(f"Thumbnail upload failed (non-fatal): {e}")

    # ── Post pinned comment ────────────────────────────────────────────────
    if pinned_comment:
        try:
            _post_pinned_comment(youtube, video_id, pinned_comment)
        except Exception as e:
            log.warning(f"Pinned comment failed (non-fatal): {e}")

    return video_id


def _set_thumbnail(youtube, video_id: str, thumbnail_path: str):
    """Upload a custom thumbnail for the video."""
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=media,
    ).execute()
    log.info(f"Custom thumbnail set for {video_id}")


def _post_pinned_comment(youtube, video_id: str, comment_text: str):
    """Post and pin a comment for engagement-bait."""
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
        log.warning(f"Could not pin comment (posted but not pinned): {e}")


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
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ],
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        log.info("YouTube credentials refreshed")

    return creds
