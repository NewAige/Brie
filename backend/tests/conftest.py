"""Shared test setup.

`app.config` loads settings at import time, so the dummy environment must be
in place before any `app.` import — pytest imports conftest first, which makes
`python -m pytest tests` work with no environment prepared. Real values from
a developer's shell (`.env` sourced, etc.) win over these via setdefault.
"""

import os
import tempfile

os.environ.setdefault("GITEA_PUBLIC_URL", "http://gitea.test")
os.environ.setdefault("GITEA_INTERNAL_URL", "http://gitea.test")
os.environ.setdefault("APP_PUBLIC_URL", "http://app.test")
os.environ.setdefault("OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("OAUTH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault(
    "DB_PATH", os.path.join(tempfile.mkdtemp(prefix="pl-test-"), "app.db"))
