"""Project-local private settings; public defaults work in a standalone checkout."""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = PROJECT_ROOT / "private" / "local-config.json"


def private_path(value: str | Path) -> Path:
    """Resolve current private references against the module, never caller cwd."""
    path = Path(value)
    path = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
    if not path.is_relative_to((PROJECT_ROOT / "private").resolve()):
        raise ValueError("文件路径超出本模块 private 目录")
    return path


def private_reference(value: str | Path) -> str:
    """Persist a portable reference, resolving its physical location only on use."""
    return private_path(value).relative_to(PROJECT_ROOT).as_posix()


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
