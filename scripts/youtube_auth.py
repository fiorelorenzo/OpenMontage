"""One-time YouTube OAuth bootstrap (per channel).

Mints a long-lived refresh token for a channel and stores it at
``.secrets/youtube/<channel>.json``. After this, ``tools/publishers/youtube_upload``
runs fully headless (it silently refreshes the access token).

Headless-friendly: uses a manual copy/paste flow, so it works on a box with no
browser (devbox). You open the printed URL in any browser (e.g. on your Mac),
authorize, and paste back the URL you get redirected to — even though that
``http://localhost:8765/...`` page fails to load, the address bar holds the code.

Prerequisites
-------------
1. Google Cloud Console -> create/select a project.
2. APIs & Services -> Library -> enable **YouTube Data API v3**.
3. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID ->
   Application type **Desktop app**. Download the JSON.
4. Save it as ``.secrets/youtube/client_secret.json`` (or set
   ``YOUTUBE_CLIENT_SECRET_FILE``).
5. OAuth consent screen: while in "Testing", add the channel's Google account as
   a **Test user** (otherwise consent is blocked).

Usage
-----
    python scripts/youtube_auth.py --channel informatizzato
    python scripts/youtube_auth.py --channel deepinbusiness

Re-run for each channel, signing in with that channel's Google account.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Google sometimes returns scopes in a different order / with extras; relax so
# oauthlib doesn't raise on a benign scope mismatch.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOKEN_DIR = REPO_ROOT / ".secrets" / "youtube"
REDIRECT_URI = "http://localhost:8765/"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def token_dir() -> Path:
    return Path(os.environ.get("YOUTUBE_TOKEN_DIR", str(DEFAULT_TOKEN_DIR)))


def client_secret_file() -> Path:
    env = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE")
    return Path(env) if env else token_dir() / "client_secret.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mint a per-channel YouTube OAuth token.")
    parser.add_argument("--channel", required=True, help="Channel key, e.g. informatizzato")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing token")
    args = parser.parse_args(argv)

    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        print(
            "Missing deps. Install into the venv:\n"
            "  uv pip install google-api-python-client google-auth-oauthlib google-auth-httplib2",
            file=sys.stderr,
        )
        return 2

    cs = client_secret_file()
    if not cs.is_file():
        print(
            f"OAuth client JSON not found at {cs}\n"
            "Create a Desktop-app OAuth client (YouTube Data API v3 enabled) and save it there.\n"
            "See the docstring at the top of this script for the exact steps.",
            file=sys.stderr,
        )
        return 2

    out = token_dir() / f"{args.channel}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        out.parent.chmod(0o700)
    except OSError:
        pass
    if out.is_file() and not args.force:
        print(f"Token already exists: {out}\nUse --force to overwrite.", file=sys.stderr)
        return 1

    flow = Flow.from_client_secrets_file(str(cs), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )

    print("\n" + "=" * 72)
    print(f"  Authorize channel: {args.channel}")
    print("=" * 72)
    print("\n1. Open this URL in a browser signed into the channel's Google account:\n")
    print(auth_url)
    print(
        "\n2. Approve access. You'll be redirected to a 'localhost:8765' page that\n"
        "   FAILS TO LOAD — that's expected. Copy the FULL URL from the address bar.\n"
    )
    redirect_response = input("3. Paste that full redirect URL here:\n> ").strip()

    if not redirect_response:
        print("No URL provided. Aborting.", file=sys.stderr)
        return 1

    flow.fetch_token(authorization_response=redirect_response)
    creds = flow.credentials

    if not creds.refresh_token:
        print(
            "WARNING: no refresh_token returned. Revoke prior access at "
            "https://myaccount.google.com/permissions and re-run (prompt=consent forces it).",
            file=sys.stderr,
        )

    out.write_text(creds.to_json())
    try:
        out.chmod(0o600)
    except OSError:
        pass

    print(f"\nToken saved: {out}")
    print("This channel can now be uploaded to headlessly. Test with:")
    print(f"  python -m tools.publishers.youtube_upload --video <file.mp4> --channel {args.channel} --title 'test'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
