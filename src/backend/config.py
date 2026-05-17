"""Application configuration for the backend.

This module provides configuration settings for the application, including
the database URL, secret key, and maximum login attempts. It can load
environment variables from a '.env' file in the repository root and
automatically adjusts settings when running inside a Docker container.

Classes:
    Settings: Stores configuration values such as database URL, secret key,
        and maximum login attempts.

Attributes:
    settings (Settings): An instance of the Settings class containing
        the loaded configuration values.
    in_docker (bool): True if the application is running inside a container,
        False otherwise.
    env_path (Path): Path to the '.env' file in the repository root, if present.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class Settings:
    """Configuration settings for the application.

    Attributes:
        DATABASE_URL (str): URL for connecting to the database.
        SECRET_KEY (str): Secret key used for cryptographic operations.
        max_attempts (int): Maximum allowed login attempts.
    """
    DATABASE_URL: str
    SECRET_KEY: str
    max_attempts: int


def _running_in_container() -> bool:
    """Determine if the application is running inside a container.

    Checks common indicators for Docker or other container environments:
    - 'RUNNING_IN_DOCKER' environment variable.
    - Existence of '/.dockerenv' file.
    - Entries in '/proc/1/cgroup' containing known container keywords.

    Returns:
        bool: True if running inside a container, False otherwise.
    """
    if os.getenv("RUNNING_IN_DOCKER", "").lower() in {"1", "true", "yes"}:
        return True

    if Path("/.dockerenv").exists():
        return True

    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8", errors="ignore") as f:
            data = f.read()
        if any(token in data for token in ("docker", "kubepods", "containerd")):
            return True
    except FileNotFoundError:
        pass

    return False


def _replace_local_host(url: str, new_host: str) -> str:
    """Replace 'localhost' in a URL with a new host.

    This is useful when an application runs in a container and cannot
    reach services using 'localhost'.

    Args:
        url (str): Original URL, potentially pointing to localhost.
        new_host (str): Hostname to replace localhost with.

    Returns:
        str: Updated URL with localhost replaced by 'new_host', if applicable.
    """
    parsed = urlsplit(url)
    if parsed.hostname in {"localhost", "127.0.0.1", "[::1]"}:
        username = parsed.username or ""
        password = parsed.password or ""
        port = parsed.port
        host = new_host

        auth = ""
        if username:
            auth = username
            if password:
                auth += f":{password}"
            auth += "@"

        netloc = auth + host
        if port:
            netloc += f":{port}"

        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    return url


settings = Settings()

# Load .env from repo root if present.
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

in_docker = _running_in_container()

settings.DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://app:app@localhost:5432/appdb",
)
if in_docker:
    settings.DATABASE_URL = _replace_local_host(settings.DATABASE_URL, "postgres")

settings.SECRET_KEY = os.getenv("SECRET_KEY", "key")
settings.max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))
