"""Project-local private settings; public defaults work in a standalone checkout."""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = PROJECT_ROOT / "private" / "local-config.json"


def configured_path(key: str, default: str | Path, environment: str | None = None) -> Path:
    settings = {}
    if LOCAL_CONFIG.is_file():
        try:
            settings = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("无法读取 private/local-config.json") from error
        if not isinstance(settings, dict):
            raise ValueError("private/local-config.json 必须是 JSON 对象")
    value = (os.environ.get(environment) if environment else None) or settings.get(key, default)
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(f"本机配置路径无效：{key}")
    path = Path(value)
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
