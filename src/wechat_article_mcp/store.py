from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _default_home() -> Path:
    override = os.environ.get("WECHAT_ARTICLE_MCP_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.cwd() / ".wechat_article_mcp").resolve()


class StateStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or _default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.qr_dir = self.home / "qrcodes"
        self.qr_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.home / "state.json"
        self.state = self._load()

    def _empty_state(self) -> dict[str, Any]:
        return {
            "default_auth_key": None,
            "accounts": {},
            "login_sessions": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._empty_state()
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty_state()

    def save(self) -> None:
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert_login_session(self, session_id: str, payload: dict[str, Any]) -> None:
        self.state["login_sessions"][session_id] = payload
        self.save()

    def get_login_session(self, session_id: str) -> dict[str, Any] | None:
        return self.state["login_sessions"].get(session_id)

    def delete_login_session(self, session_id: str) -> None:
        self.state["login_sessions"].pop(session_id, None)
        self.save()

    def upsert_account(self, auth_key: str, payload: dict[str, Any], make_default: bool = True) -> None:
        self.state["accounts"][auth_key] = payload
        if make_default:
            self.state["default_auth_key"] = auth_key
        self.save()

    def get_account(self, auth_key: str | None = None) -> dict[str, Any] | None:
        key = auth_key or self.state.get("default_auth_key")
        if not key:
            return None
        return self.state["accounts"].get(key)

    def set_default_account(self, auth_key: str) -> bool:
        if auth_key not in self.state["accounts"]:
            return False
        self.state["default_auth_key"] = auth_key
        self.save()
        return True

    def list_accounts(self) -> list[dict[str, Any]]:
        default_key = self.state.get("default_auth_key")
        items: list[dict[str, Any]] = []
        for auth_key, account in self.state["accounts"].items():
            value = dict(account)
            value["auth_key"] = auth_key
            value["is_default"] = auth_key == default_key
            items.append(value)
        return items
