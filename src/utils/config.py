from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VIL_DIR = Path.home() / "Downloads" / "VIL"
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"
DEFAULT_VISUAL_MEMORY_DB = PROJECT_ROOT / "data" / "visual_memory.db"
_ENV_LOADED = False


def _parse_env_value(value: str) -> str:
    """Strip surrounding quotes, otherwise drop a trailing inline comment.

    Two different .env readers used to disagree here: one kept the quotes, so a
    quoted app password reached WordPress with its quotes attached and the
    request was rejected as bad credentials.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


def load_project_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        parsed: dict[str, str] = {}
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            # A key repeated in .env resolves to its last definition. Applying
            # os.environ.setdefault per line made the first — usually the
            # stale — definition win instead.
            parsed[key] = _parse_env_value(value)
        for key, value in parsed.items():
            # A real environment variable still outranks the file.
            os.environ.setdefault(key, value)

    _ENV_LOADED = True


def env_str(name: str, default: str | None = None) -> str | None:
    load_project_env()
    value = os.environ.get(name)
    if value is None:
        return default
    stripped = value.strip()
    if not stripped:
        return default
    return stripped


def get_vil_dir() -> Path:
    configured = env_str("YO_VIL_DIR")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_VIL_DIR


def get_visual_memory_db_path() -> Path:
    configured = env_str("YO_VISUAL_MEMORY_DB")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_VISUAL_MEMORY_DB
