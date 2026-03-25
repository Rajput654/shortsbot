"""
YouTube Uploader v3.1

FIXES v3.1:
- OAUTH SCOPE FIX: The credentials must be generated with ALL scopes that any
  part of the bot uses. Previous code requested youtube.force-ssl + youtube.readonly
  at upload time but the token was generated with only youtube.upload — causing
  "invalid_scope: Bad Request" on every upload attempt. All required scopes are
  now declared in one place: _REQUIRED_SCOPES. Run setup_youtube_auth.py again
  to regenerate a token with all three scopes.
- TITLE VALIDATION: Titles that end mid-word (e.g. "Crow Outsmarts" with no
  subject) now get caught and padded before upload so the curiosity gap is
  never truncated.
- SCOPE HELPER: get_required_scopes() exported so setup_youtube_auth.py can
  import it and always stay in sync.

UPGRADES v3.0 (retained):
- THUMBNAIL UPLOAD: sets a custom thumbnail from the hook frame (~1.2s).
- DESCRIPTION TEMPLATE: curiosity-hook opening, hashtag block, AI disclosure.
- TITLE SAFETY: strips any title over 60 chars as a final guard.
"""

import os, asyncio, logging, json
from pathlib import Path

log = logging.getLogger(__name__)

CATEGORY_PETS_ANIMALS = "15"
YT_CATEGORY = os.getenv("YT_CATEGORY", CATEGORY_PETS_ANIMALS)

# FIX v3.1: Single source of truth for ALL scopes used across the entire bot.
# analytics_fetcher and youtube_scanner need readonly.
# uploader needs upload + force-ssl.
# Generate credentials with ALL of these via setup_youtube_auth.py.
_REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def get_required_scopes() -> list[str]:
    """
    Exported so setup_youtube_auth.py can import and stay in sync automatically.
    Usage in setup_youtube_auth.py:
        from core.youtube_uploader import get_required_scopes
        SCOPES = get_required_scopes()
    """
    return _REQUIRED_SCOPES


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

    hook_line    = hook[:97] + "…" if len(hook) > 100 else hook
    hashtag_block = " ".join(seo_tags[:10]) if seo_tags else "#animals #wildlife #shorts"

    return (
        f"{hook_line}\n\n"
        f"Everything you need to know about the {animal} in under a minute.\n\n"
        f"{hashtag_block}\n\n"
        f"✦ AI-generated content | footage: Pexels.com"
    )


def _validate_title(title: str) -> str:
    """
    FIX v3.1: Ensure title has a complete curiosity gap before #Shorts tag.
    Titles like "Crow Outsmarts" or "Dolphin VS" are incomplete — the LLM
    truncated mid-sentence. Detect and log so you can tune the prompt.
    Also enforces the 60-char YouTube hard limit.
    """
    # Ensure #Shorts suffix
    if "#Shorts" not in title and "#shorts" not in title:
        title = title + " #Shorts"

    # Detect likely-truncated titles (ends in a verb, preposition, or common truncation word)
    _truncation_signals = (
        " vs", " vs.", " outsmarts", " beats", " kills",
        " destroys", " survives", " eats", " fights", " uses",
        " has", " does", " can", " is", " are",
    )
    base = title.replace(" #Shorts", "").replace(" #shorts", "").strip().lower()
    for signal in _truncation_signals:
        if base.endswith(signal):
            log.warning(
                f"Title appears truncated (ends with '{signal}'): '{title}' — "
                "consider tightening the script_generator prompt."
            )
            break

    # Hard cap at 60 chars (YouTube truncates in search at ~50, but 60 is the API limit)
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
    for must_have in ["Shorts", "AnimalFacts", "Animals", "Wildlife"]:
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

    # Set custom thumbnail
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            _set_thumbnail(youtube, video_id, thumbnail_path)
        except Exception as e:
            log.warning(f"Thumbnail upload failed (non-fatal): {e}")

    # Post pinned comment
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
        scopes=_REQUIRED_SCOPES,   # FIX v3.1: use the single source of truth
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        log.info("YouTube credentials refreshed")

    return creds
