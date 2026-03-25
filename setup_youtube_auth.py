"""
setup_youtube_auth.py — Run this ONCE on your local machine.
It opens a browser for Google login, then prints the credentials JSON.
Copy that JSON into Railway/Render/GitHub Secrets as the YT_CREDENTIALS env var.

FIX v3.1: Scopes are now imported from core.youtube_uploader.get_required_scopes()
so setup_youtube_auth.py and the uploader are ALWAYS in sync. Previously the
token was generated with only youtube.upload but the bot also needs
youtube.force-ssl and youtube.readonly — causing "invalid_scope: Bad Request"
on every run.

Usage:
  pip install google-auth-oauthlib google-api-python-client
  python setup_youtube_auth.py

You need: client_secret.json from Google Cloud Console
  1. Go to console.cloud.google.com
  2. Create project → Enable YouTube Data API v3
  3. Credentials → Create OAuth 2.0 Client ID → Desktop App → Download JSON
  4. Save as client_secret.json in this folder
  5. Run this script
"""

import json, os, sys

SECRET_FILE = "client_secret.json"


def main():
    # FIX v3.1: import scopes from the single source of truth
    try:
        from core.youtube_uploader import get_required_scopes
        SCOPES = get_required_scopes()
    except ImportError:
        # Fallback if run from a different working directory
        SCOPES = [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
            "https://www.googleapis.com/auth/youtube.readonly",
        ]

    print(f"\nRequesting scopes:")
    for s in SCOPES:
        print(f"  - {s}")
    print()

    if not os.path.exists(SECRET_FILE):
        print(f"ERROR: Missing {SECRET_FILE}")
        print("Download it from: console.cloud.google.com → APIs → Credentials → OAuth 2.0")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    print("Opening browser for Google login...")
    flow  = InstalledAppFlow.from_client_secrets_file(SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    creds_dict = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
    }

    output = json.dumps(creds_dict)
    print("\n" + "=" * 60)
    print("SUCCESS! Copy this entire line into Railway / GitHub Secrets")
    print("as environment variable: YT_CREDENTIALS")
    print("=" * 60)
    print(output)
    print("=" * 60)

    # Also save locally as backup
    with open("yt_credentials.json", "w") as f:
        json.dump(creds_dict, f, indent=2)
    print("\nAlso saved to yt_credentials.json (keep this private — add to .gitignore!)")


if __name__ == "__main__":
    main()
