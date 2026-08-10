"""Yoldaolmak profile defaults."""

from __future__ import annotations

import os
from typing import Dict

from src.utils.config import load_project_env


PROFILE_NAME = "yoldaolmak"
DEFAULT_LANGUAGE = "tr"
DEFAULT_FILTER_PROFILE = "yoldaolmak"


def apply_environment() -> Dict[str, str]:
    # Native API callers use this profile directly, so it must provide the
    # same credential loading guarantee as the CLI import path.
    load_project_env()
    os.environ.setdefault("YO_IMAGE_FILTER_PROFILE", DEFAULT_FILTER_PROFILE)
    return {
        "profile": PROFILE_NAME,
        "language": DEFAULT_LANGUAGE,
        "filter_profile": os.environ.get("YO_IMAGE_FILTER_PROFILE", DEFAULT_FILTER_PROFILE),
    }
