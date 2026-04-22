from __future__ import annotations

import base64
import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from .html_utils import (
    extract_account_name,
    extract_article_metadata,
    is_valid_mp_article_url,
    normalize_article_html,
)
from .store import StateStore


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)

DEFAULT_HEADERS = {
    "Referer": "https://mp.weixin.qq.com/",
    "Origin": "https://mp.weixin.qq.com",
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "identity",
}

STATUS_LABELS = {
    0: "waiting_scan",
    1: "confirmed",
    2: "expired",
    3: "canceled",
    4: "scanned_waiting_confirm",
    5: "mail_not_bound",
    6: "scanned_waiting_confirm",
}


class WechatArticleClient:
    def __init__(self, store: StateStore) -> None:
        self.store = store

    def _relogin_hint(self) -> str:
        return "login session expired; please run start_login_session -> check_login_session -> complete_login"

    def _session(self, cookies: dict[str, str] | None = None) -> requests.Session:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        if cookies:
            for key, value in cookies.items():
                session.cookies.set(key, value, domain="mp.weixin.qq.com", path="/")
        return session

    def _extract_base_resp_error(self, payload: dict[str, Any], fallback: str) -> str:
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict) and base_resp.get("err_msg"):
            return str(base_resp["err_msg"])
        return fallback

    def start_login_session(self, session_id: str | None = None) -> dict[str, Any]:
        sid = session_id or f"{int(time.time() * 1000)}{random.randint(10, 99)}"
        session = self._session()

        payload = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "login_type": 3,
            "sessionid": sid,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }

        response = session.post(
            "https://mp.weixin.qq.com/cgi-bin/bizlogin",
            params={"action": "startlogin"},
            data=payload,
            timeout=30,
        )
        response.raise_for_status()
        start_data = response.json()
        if start_data.get("base_resp", {}).get("ret") != 0:
            raise RuntimeError(self._extract_base_resp_error(start_data, "failed to start login session"))

        qr_response = session.get(
            "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode",
            params={"action": "getqrcode", "random": int(time.time() * 1000)},
            timeout=30,
        )
        qr_response.raise_for_status()

        qr_path = self.store.qr_dir / f"{sid}.png"
        qr_path.write_bytes(qr_response.content)
        qr_base64 = base64.b64encode(qr_response.content).decode("ascii")

        session_record = {
            "session_id": sid,
            "created_at": int(time.time()),
            "cookies": session.cookies.get_dict(),
            "qr_code_path": str(qr_path),
        }
        self.store.upsert_login_session(sid, session_record)
        return {
            "success": True,
            "session_id": sid,
            "qr_code_path": str(qr_path),
            "qr_code_base64": qr_base64,
            "message": "Scan the QR code with the public account admin WeChat.",
        }

    def check_login_session(self, session_id: str) -> dict[str, Any]:
        session_record = self.store.get_login_session(session_id)
        if not session_record:
            raise RuntimeError(f"login session not found: {session_id}")

        session = self._session(session_record.get("cookies"))
        response = session.get(
            "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode",
            params={"action": "ask", "token": "", "lang": "zh_CN", "f": "json", "ajax": 1},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        session_record["cookies"] = session.cookies.get_dict()
        session_record["last_status"] = data
        session_record["updated_at"] = int(time.time())
        self.store.upsert_login_session(session_id, session_record)

        status = int(data.get("status", -1))
        return {
            "success": data.get("base_resp", {}).get("ret") == 0,
            "session_id": session_id,
            "status": status,
            "status_label": STATUS_LABELS.get(status, "unknown"),
            "acct_size": data.get("acct_size"),
            "binduin": data.get("binduin"),
            "ready_to_complete_login": status == 1,
            "raw": data,
        }

    def _fetch_account_info(self, session: requests.Session, token: str) -> dict[str, Any]:
        response = session.get(
            "https://mp.weixin.qq.com/cgi-bin/home",
            params={"t": "home/index", "token": token, "lang": "zh_CN"},
            timeout=30,
        )
        response.raise_for_status()
        html = response.text

        nickname = ""
        match = re.search(r'wx\.cgiData\.nick_name\s*=\s*"(?P<value>[^"]+)"', html)
        if match:
            nickname = match.group("value")

        avatar = ""
        match = re.search(r'wx\.cgiData\.head_img\s*=\s*"(?P<value>[^"]+)"', html)
        if match:
            avatar = match.group("value")

        return {"nickname": nickname, "avatar": avatar}

    def complete_login(self, session_id: str, auth_key: str | None = None, make_default: bool = True) -> dict[str, Any]:
        session_record = self.store.get_login_session(session_id)
        if not session_record:
            raise RuntimeError(f"login session not found: {session_id}")

        session = self._session(session_record.get("cookies"))
        payload = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": 0,
            "cookie_cleaned": 0,
            "plugin_used": 0,
            "login_type": 3,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        response = session.post(
            "https://mp.weixin.qq.com/cgi-bin/bizlogin",
            params={"action": "login"},
            data=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        redirect_url = data.get("redirect_url")
        if not redirect_url:
            raise RuntimeError(self._extract_base_resp_error(data, "login was not confirmed yet"))

        token = parse_qs(urlparse(f"http://localhost{redirect_url}").query).get("token", [None])[0]
        if not token:
            raise RuntimeError("token not found in login redirect url")

        info = self._fetch_account_info(session, token)
        final_auth_key = auth_key or f"{int(time.time() * 1000)}{random.randint(1000, 9999)}"
        account_record = {
            "nickname": info.get("nickname", ""),
            "avatar": info.get("avatar", ""),
            "token": token,
            "cookies": session.cookies.get_dict(),
            "created_at": int(time.time()),
            "source_session_id": session_id,
        }
        self.store.upsert_account(final_auth_key, account_record, make_default=make_default)
        self.store.delete_login_session(session_id)
        return {
            "success": True,
            "auth_key": final_auth_key,
            "account": {
                "nickname": account_record["nickname"],
                "avatar": account_record["avatar"],
                "token": token,
            },
        }

    def list_saved_accounts(self) -> dict[str, Any]:
        return {
            "success": True,
            "default_auth_key": self.store.state.get("default_auth_key"),
            "accounts": self.store.list_accounts(),
        }

    def check_account_alive(self, auth_key: str | None = None) -> dict[str, Any]:
        account = self.store.get_account(auth_key)
        if not account:
            raise RuntimeError("login account not found; run complete_login first")

        session = self._session(account.get("cookies"))
        response = session.get(
            "https://mp.weixin.qq.com/cgi-bin/home",
            params={"t": "home/index", "token": account["token"], "lang": "zh_CN"},
            timeout=30,
            allow_redirects=True,
        )
        response.raise_for_status()

        html = response.text
        final_url = response.url
        nickname = account.get("nickname", "")

        has_nickname_marker = 'wx.cgiData.nick_name' in html
        has_avatar_marker = 'wx.cgiData.head_img' in html
        redirected_to_login = "cgi-bin/loginpage" in final_url or "/cgi-bin/bizlogin" in final_url
        token_missing = "token=" not in final_url

        alive = (has_nickname_marker or has_avatar_marker) and not redirected_to_login and not token_missing
        message = "login session is valid" if alive else "login session is no longer valid; re-login is likely required"

        detected_nickname = ""
        if has_nickname_marker:
            match = re.search(r'wx\.cgiData\.nick_name\s*=\s*"(?P<value>[^"]+)"', html)
            if match:
                detected_nickname = match.group("value")

        return {
            "success": True,
            "alive": alive,
            "auth_key": auth_key or self.store.state.get("default_auth_key"),
            "nickname": nickname,
            "detected_nickname": detected_nickname,
            "final_url": final_url,
            "cookie_count": len(session.cookies.get_dict()),
            "message": message,
            "needs_relogin": not alive,
            "relogin_hint": None if alive else self._relogin_hint(),
            "checked_at": int(time.time()),
        }

    def _ensure_account_alive(self, auth_key: str | None = None) -> dict[str, Any]:
        result = self.check_account_alive(auth_key)
        if not result.get("alive"):
            raise RuntimeError(self._relogin_hint())
        return result

    def set_default_account(self, auth_key: str) -> dict[str, Any]:
        ok = self.store.set_default_account(auth_key)
        return {"success": ok, "auth_key": auth_key}

    def _resolve_account(self, account_name: str, auth_key: str | None = None) -> dict[str, Any]:
        result = self.search_accounts(account_name, auth_key=auth_key, begin=0, size=10)
        accounts = result.get("accounts", [])
        if not accounts:
            raise RuntimeError(f"account not found: {account_name}")

        for account in accounts:
            if account.get("nickname") == account_name:
                return account
        for account in accounts:
            if account.get("alias") == account_name:
                return account
        return accounts[0]

    def _parse_date_boundary(self, value: str | None, is_end: bool) -> int | None:
        if not value:
            return None

        text = value.strip()
        formats = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S")
        for fmt in formats:
            try:
                dt = datetime.strptime(text, fmt)
                if is_end and "H" not in fmt:
                    dt = dt + timedelta(days=1) - timedelta(seconds=1)
                return int(dt.timestamp())
            except ValueError:
                continue
        raise RuntimeError(f"unsupported date format: {value}")

    def search_accounts(self, keyword: str, auth_key: str | None = None, begin: int = 0, size: int = 5) -> dict[str, Any]:
        account = self.store.get_account(auth_key)
        if not account:
            raise RuntimeError("login account not found; run complete_login first")
        self._ensure_account_alive(auth_key)

        session = self._session(account.get("cookies"))
        response = session.get(
            "https://mp.weixin.qq.com/cgi-bin/searchbiz",
            params={
                "action": "search_biz",
                "begin": begin,
                "count": size,
                "query": keyword,
                "token": account["token"],
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("base_resp", {}).get("ret") != 0:
            raise RuntimeError(f"{self._extract_base_resp_error(data, 'search_accounts failed')}; {self._relogin_hint()}")
        return {
            "success": data.get("base_resp", {}).get("ret") == 0,
            "accounts": data.get("list", []),
            "total": data.get("total", 0),
            "raw": data,
        }

    def list_articles(
        self,
        fakeid: str,
        auth_key: str | None = None,
        begin: int = 0,
        size: int = 5,
        keyword: str = "",
    ) -> dict[str, Any]:
        account = self.store.get_account(auth_key)
        if not account:
            raise RuntimeError("login account not found; run complete_login first")
        self._ensure_account_alive(auth_key)

        session = self._session(account.get("cookies"))
        is_searching = bool(keyword)
        response = session.get(
            "https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
            params={
                "sub": "search" if is_searching else "list",
                "search_field": "7" if is_searching else "null",
                "begin": begin,
                "count": size,
                "query": keyword,
                "fakeid": fakeid,
                "type": "101_1",
                "free_publish_type": 1,
                "sub_action": "list_ex",
                "token": account["token"],
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("base_resp", {}).get("ret") != 0:
            raise RuntimeError(f"{self._extract_base_resp_error(data, 'list_articles failed')}; {self._relogin_hint()}")

        articles: list[dict[str, Any]] = []
        if data.get("base_resp", {}).get("ret") == 0 and data.get("publish_page"):
            publish_page = json.loads(data["publish_page"])
            for item in publish_page.get("publish_list", []):
                publish_info_raw = item.get("publish_info")
                if not publish_info_raw:
                    continue
                publish_info = json.loads(publish_info_raw)
                articles.extend(publish_info.get("appmsgex", []))

        return {
            "success": data.get("base_resp", {}).get("ret") == 0,
            "articles": articles,
            "count": len(articles),
            "raw": data,
        }

    def get_latest_article(self, account_name: str, auth_key: str | None = None) -> dict[str, Any]:
        account = self._resolve_account(account_name, auth_key=auth_key)
        listing = self.list_articles(account["fakeid"], auth_key=auth_key, begin=0, size=5)
        articles = listing.get("articles", [])
        if not articles:
            raise RuntimeError(f"no articles found for account: {account_name}")

        latest = max(articles, key=lambda item: (item.get("update_time") or 0, item.get("create_time") or 0))
        return {
            "success": True,
            "account": account,
            "article": latest,
        }

    def get_latest_article_content(
        self,
        account_name: str,
        auth_key: str | None = None,
    ) -> dict[str, Any]:
        latest = self.get_latest_article(account_name, auth_key=auth_key)
        article = latest["article"]
        link = article.get("link")
        if not link:
            raise RuntimeError(f"latest article link missing for account: {account_name}")

        content = self.get_article_content(link)
        return {
            "success": True,
            "account": latest["account"],
            "article": article,
            "content": content.get("content"),
            "metadata": content.get("metadata"),
            "format": "html",
        }

    def search_articles_by_date(
        self,
        account_name: str,
        start_date: str | None = None,
        end_date: str | None = None,
        keyword: str = "",
        auth_key: str | None = None,
        max_items: int = 20,
        page_size: int = 5,
        use_update_time: bool = False,
    ) -> dict[str, Any]:
        if max_items <= 0:
            raise RuntimeError("max_items must be > 0")
        if page_size <= 0:
            raise RuntimeError("page_size must be > 0")

        start_ts = self._parse_date_boundary(start_date, is_end=False)
        end_ts = self._parse_date_boundary(end_date, is_end=True)
        if start_ts and end_ts and start_ts > end_ts:
            raise RuntimeError("start_date must be earlier than or equal to end_date")

        account = self._resolve_account(account_name, auth_key=auth_key)
        begin = 0
        matched: list[dict[str, Any]] = []
        scanned_articles = 0
        scanned_pages = 0

        while len(matched) < max_items:
            listing = self.list_articles(
                account["fakeid"],
                auth_key=auth_key,
                begin=begin,
                size=page_size,
                keyword=keyword,
            )
            articles = listing.get("articles", [])
            if not articles:
                break

            scanned_pages += 1
            scanned_articles += len(articles)

            for article in articles:
                ts = int(article.get("update_time") if use_update_time else article.get("create_time") or 0)
                if start_ts is not None and ts < start_ts:
                    continue
                if end_ts is not None and ts > end_ts:
                    continue
                matched.append(article)
                if len(matched) >= max_items:
                    break

            oldest_ts = min(int(article.get("update_time") if use_update_time else article.get("create_time") or 0) for article in articles)
            if start_ts is not None and oldest_ts < start_ts:
                break

            begin += page_size

        matched.sort(key=lambda item: int(item.get("update_time") if use_update_time else item.get("create_time") or 0), reverse=True)
        return {
            "success": True,
            "account": account,
            "filters": {
                "start_date": start_date,
                "end_date": end_date,
                "keyword": keyword,
                "use_update_time": use_update_time,
                "max_items": max_items,
                "page_size": page_size,
            },
            "scanned_pages": scanned_pages,
            "scanned_articles": scanned_articles,
            "count": len(matched),
            "articles": matched[:max_items],
        }

    def fetch_article(self, url: str) -> str:
        if not is_valid_mp_article_url(url):
            raise RuntimeError("only mp.weixin.qq.com article urls are supported")

        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
        response.raise_for_status()
        return response.text

    def get_article_content(self, url: str) -> dict[str, Any]:
        raw_html = self.fetch_article(url)
        metadata = extract_article_metadata(raw_html, url)
        content = normalize_article_html(raw_html)

        metadata["account_name"] = metadata["account_name"] or extract_account_name(raw_html)
        return {
            "success": True,
            "format": "html",
            "metadata": metadata,
            "content": content,
        }

    def export_article(
        self,
        url_or_account_name: str,
        output_path: str,
        auth_key: str | None = None,
    ) -> dict[str, Any]:
        if not output_path.strip():
            raise RuntimeError("output_path cannot be empty")

        if is_valid_mp_article_url(url_or_account_name):
            article_url = url_or_account_name
            article_info = None
            account_info = None
            source_type = "url"
        else:
            latest = self.get_latest_article(url_or_account_name, auth_key=auth_key)
            article_info = latest.get("article")
            account_info = latest.get("account")
            article_url = article_info.get("link") if article_info else None
            if not article_url:
                raise RuntimeError(f"latest article link missing for account: {url_or_account_name}")
            source_type = "account_name"

        target = Path(output_path).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        raw_html = self.fetch_article(article_url)
        metadata = extract_article_metadata(raw_html, article_url)
        metadata["account_name"] = metadata["account_name"] or extract_account_name(raw_html)
        content = normalize_article_html(raw_html)

        target.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "source_type": source_type,
            "output_path": str(target),
            "format": "html",
            "bytes_written": target.stat().st_size,
            "metadata": metadata,
            "article": article_info,
            "account": account_info,
        }
