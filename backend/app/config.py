"""App configuration, loaded from environment variables (see .env.example)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    gitea_public_url: str    # as the user's browser reaches Gitea (OAuth redirects)
    gitea_internal_url: str  # as this backend reaches Gitea (token exchange, API)
    app_public_url: str      # as the user's browser reaches this app
    oauth_client_id: str
    oauth_client_secret: str
    session_secret: str
    repo_owner: str
    repo_name: str
    cookie_secure: bool
    db_path: str
    session_max_age: int = 12 * 3600  # seconds

    @property
    def redirect_uri(self) -> str:
        # Must EXACTLY match the redirect URI registered on the OAuth app in Gitea.
        return f"{self.app_public_url}/auth/callback"

    @property
    def repo_api(self) -> str:
        return f"/repos/{self.repo_owner}/{self.repo_name}"


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    return Settings(
        gitea_public_url=_require("GITEA_PUBLIC_URL").rstrip("/"),
        gitea_internal_url=_require("GITEA_INTERNAL_URL").rstrip("/"),
        app_public_url=_require("APP_PUBLIC_URL").rstrip("/"),
        oauth_client_id=_require("OAUTH_CLIENT_ID"),
        oauth_client_secret=_require("OAUTH_CLIENT_SECRET"),
        session_secret=_require("SESSION_SECRET"),
        repo_owner=os.environ.get("REPO_OWNER", "bank"),
        repo_name=os.environ.get("REPO_NAME", "prompt-library"),
        cookie_secure=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
        db_path=os.environ.get("DB_PATH", "./data/app.db"),
    )


settings = load_settings()
