"""YouTube upload publisher tool.

Uploads a finished render to YouTube via the YouTube Data API v3. Defaults to
``privacyStatus=private`` so nothing ever goes public without an explicit human
decision in YouTube Studio.

Multi-channel by design: the ``channel`` input selects which stored OAuth token
to use (``.secrets/youtube/<channel>.json``), so a single OpenMontage checkout
can publish to several channels (e.g. ``informatizzato`` and ``deepinbusiness``).

Auth model
----------
- A one-time interactive consent per channel mints a long-lived refresh token via
  ``scripts/youtube_auth.py`` (headless-friendly copy/paste flow).
- ``execute()`` is fully non-interactive: it loads the stored token and silently
  refreshes the short-lived access token when needed. Safe to run on a headless
  box / from a pipeline.

CLI
---
    python -m tools.publishers.youtube_upload \
        --video projects/<id>/renders/final.mp4 \
        --channel informatizzato \
        --title "..." --description-file desc.txt --tags "a,b,c"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

# youtube.upload — insert videos; youtube — set thumbnail, manage playlists.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TOKEN_DIR = REPO_ROOT / ".secrets" / "youtube"
CLIENT_SECRET_BASENAME = "client_secret.json"

# YouTube enforces these caps server-side; trim locally for a clean error path.
MAX_TITLE_LEN = 100
MAX_DESCRIPTION_LEN = 5000
MAX_TAGS_TOTAL_CHARS = 480  # YouTube caps total tag characters at 500


def token_dir() -> Path:
    return Path(os.environ.get("YOUTUBE_TOKEN_DIR", str(DEFAULT_TOKEN_DIR)))


def client_secret_file() -> Path:
    env = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE")
    return Path(env) if env else token_dir() / CLIENT_SECRET_BASENAME


def token_file(channel: str) -> Path:
    return token_dir() / f"{channel}.json"


class YouTubeUpload(BaseTool):
    name = "youtube_upload"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "youtube"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["python:googleapiclient", "python:google_auth_oauthlib"]
    install_instructions = (
        "Install the Google client libraries into the OpenMontage venv:\n"
        "  uv pip install google-api-python-client google-auth-oauthlib google-auth-httplib2\n"
        "Then mint a per-channel OAuth token once (headless copy/paste flow):\n"
        "  python scripts/youtube_auth.py --channel <name>\n"
        "Requires a Desktop-app OAuth client JSON at .secrets/youtube/client_secret.json "
        "(Google Cloud Console -> APIs & Services -> Credentials, with YouTube Data API v3 enabled)."
    )
    fallback_tools: list[str] = []
    agent_skills: list[str] = []

    capabilities = [
        "video_upload",
        "privacy_control",
        "scheduled_publish",
        "thumbnail_set",
        "playlist_add",
        "multi_channel",
    ]
    supports = {
        "offline": False,
        "multi_channel": True,
        "resumable_upload": True,
        "scheduled_publish": True,
    }
    best_for = [
        "uploading finished renders to YouTube as private drafts for human review",
        "scheduled private->public publishing via publish_at",
        "publishing to multiple channels from one checkout",
    ]
    not_good_for = [
        "one-click public publishing with no human review",
        "fully offline / privacy-constrained workflows",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path", "title", "channel"],
        "properties": {
            "video_path": {"type": "string", "description": "Path to the rendered .mp4"},
            "channel": {
                "type": "string",
                "description": "Channel key selecting .secrets/youtube/<channel>.json",
            },
            "title": {"type": "string", "description": f"Video title (<= {MAX_TITLE_LEN} chars)"},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "category_id": {
                "type": "string",
                "default": "27",
                "description": "YouTube category id (27=Education, 28=Science&Tech, 22=People&Blogs)",
            },
            "privacy_status": {
                "type": "string",
                "default": "private",
                "enum": ["private", "unlisted", "public"],
            },
            "publish_at": {
                "type": "string",
                "description": "ISO 8601 UTC; schedules a private video to go public. Requires privacy_status=private.",
            },
            "thumbnail_path": {"type": "string"},
            "playlist_id": {"type": "string"},
            "made_for_kids": {"type": "boolean", "default": False},
            "language": {
                "type": "string",
                "description": "BCP-47 code (e.g. 'it', 'en'). Sets defaultLanguage/defaultAudioLanguage when given; omitted otherwise.",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=10, network_required=True
    )
    retry_policy = RetryPolicy(
        max_retries=5,
        backoff_seconds=2.0,
        retryable_errors=["rate_limit", "timeout", "backend_error"],
    )
    idempotency_key_fields = ["video_path", "channel", "title"]
    side_effects = ["uploads a video to YouTube", "creates a YouTube video resource"]
    user_visible_verification = [
        "Open the returned studio_url and confirm the video is present and set to the expected privacy",
        "Confirm the upload landed on the intended channel",
    ]

    DEFAULT_CATEGORY_ID = "27"  # Education
    DEFAULT_PRIVACY = "private"

    # ---- status ----

    def get_status(self) -> ToolStatus:
        try:
            import googleapiclient  # noqa: F401
            import google_auth_oauthlib  # noqa: F401
        except ImportError:
            return ToolStatus.UNAVAILABLE
        if not client_secret_file().is_file():
            return ToolStatus.DEGRADED  # libs present but no OAuth client configured
        tdir = token_dir()
        has_channel_token = tdir.is_dir() and any(
            p.name != CLIENT_SECRET_BASENAME for p in tdir.glob("*.json")
        )
        return ToolStatus.AVAILABLE if has_channel_token else ToolStatus.DEGRADED

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0  # YouTube upload itself is free (quota-limited, not billed)

    # ---- execution ----

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            result = self._upload(inputs)
        except Exception as exc:
            return ToolResult(success=False, error=f"YouTube upload failed: {exc}")
        result.duration_seconds = round(time.time() - start, 2)
        return result

    def _load_credentials(self, channel: str):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        tf = token_file(channel)
        if not tf.is_file():
            raise RuntimeError(
                f"No OAuth token for channel '{channel}' at {tf}. "
                f"Run: python scripts/youtube_auth.py --channel {channel}"
            )
        creds = Credentials.from_authorized_user_file(str(tf), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                tf.write_text(creds.to_json())
            else:
                raise RuntimeError(
                    f"Token for '{channel}' is invalid and not refreshable. "
                    f"Re-run: python scripts/youtube_auth.py --channel {channel}"
                )
        return creds

    def _upload(self, inputs: dict[str, Any]) -> ToolResult:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"Video file not found: {video_path}")

        channel = inputs["channel"]
        title = (inputs.get("title") or "").strip()[:MAX_TITLE_LEN]
        if not title:
            return ToolResult(success=False, error="A non-empty title is required.")
        description = (inputs.get("description") or "")[:MAX_DESCRIPTION_LEN]
        tags = self._clean_tags(inputs.get("tags") or [])
        category_id = str(inputs.get("category_id") or self.DEFAULT_CATEGORY_ID)
        privacy = inputs.get("privacy_status") or self.DEFAULT_PRIVACY
        publish_at = inputs.get("publish_at")
        made_for_kids = bool(inputs.get("made_for_kids", False))
        language = (inputs.get("language") or "").strip() or None

        if publish_at and privacy != "private":
            return ToolResult(
                success=False,
                error="publish_at requires privacy_status='private' (YouTube schedules private->public).",
            )

        creds = self._load_credentials(channel)
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

        status: dict[str, Any] = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        }
        if publish_at:
            status["publishAt"] = publish_at

        snippet: dict[str, Any] = {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        }
        if language:
            snippet["defaultLanguage"] = language
            snippet["defaultAudioLanguage"] = language
        body = {"snippet": snippet, "status": status}

        media = MediaFileUpload(
            str(video_path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/*"
        )
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        retries = 0
        while response is None:
            try:
                _, response = request.next_chunk()
            except HttpError as e:
                if getattr(e, "resp", None) is not None and e.resp.status in (500, 502, 503, 504) and retries < 5:
                    retries += 1
                    time.sleep(2 ** retries)
                    continue
                raise

        video_id = response["id"]

        warnings: list[str] = []
        thumbnail_path = inputs.get("thumbnail_path")
        if thumbnail_path and Path(thumbnail_path).is_file():
            try:
                youtube.thumbnails().set(
                    videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))
                ).execute()
            except HttpError as e:
                warnings.append(f"thumbnail not set: {e}")

        playlist_id = inputs.get("playlist_id")
        if playlist_id:
            try:
                youtube.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        }
                    },
                ).execute()
            except HttpError as e:
                warnings.append(f"playlist add failed: {e}")

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "channel": channel,
                "video_id": video_id,
                "privacy_status": privacy,
                "publish_at": publish_at,
                "watch_url": f"https://youtu.be/{video_id}",
                "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
                "title": title,
                "warnings": warnings,
            },
            artifacts=[str(video_path)],
        )

    @staticmethod
    def _clean_tags(tags: list[str]) -> list[str]:
        cleaned: list[str] = []
        total = 0
        for t in tags:
            t = str(t).strip()
            if not t:
                continue
            # YouTube counts a tag containing spaces as length+2 (it gets quoted).
            cost = len(t) + (2 if " " in t else 0)
            if total + cost > MAX_TAGS_TOTAL_CHARS:
                break
            cleaned.append(t)
            total += cost
        return cleaned


# --------------------------------------------------------------------------- #
# CLI wrapper — lets the orchestrator call the uploader without importing it.
# --------------------------------------------------------------------------- #


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload a video to YouTube (default: private).")
    parser.add_argument("--video", required=True, help="Path to the rendered .mp4")
    parser.add_argument("--channel", required=True, help="Channel key (.secrets/youtube/<channel>.json)")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--description-file", help="Read description from a file (overrides --description)")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--category-id", default=YouTubeUpload.DEFAULT_CATEGORY_ID)
    parser.add_argument(
        "--privacy", default="private", choices=["private", "unlisted", "public"]
    )
    parser.add_argument("--publish-at", help="ISO 8601 UTC; schedules a private video to go public")
    parser.add_argument("--thumbnail", help="Path to a thumbnail image")
    parser.add_argument("--playlist-id")
    parser.add_argument("--made-for-kids", action="store_true")
    parser.add_argument("--language", help="BCP-47 code, e.g. it or en (optional)")
    args = parser.parse_args(argv)

    description = args.description
    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8")

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    result = YouTubeUpload().execute(
        {
            "video_path": args.video,
            "channel": args.channel,
            "title": args.title,
            "description": description,
            "tags": tags,
            "category_id": args.category_id,
            "privacy_status": args.privacy,
            "publish_at": args.publish_at,
            "thumbnail_path": args.thumbnail,
            "playlist_id": args.playlist_id,
            "made_for_kids": args.made_for_kids,
            "language": args.language,
        }
    )

    print(json.dumps({"success": result.success, "error": result.error, **result.data}, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(_main())
