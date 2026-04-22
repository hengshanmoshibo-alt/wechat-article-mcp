from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .client import WechatArticleClient
from .store import StateStore


app = Server("wechat-article-mcp")
store = StateStore()
client = WechatArticleClient(store)


def _text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="start_login_session",
            description="Start a WeChat public-platform QR-code login session and return a local QR image path.",
            inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}}},
        ),
        Tool(
            name="check_login_session",
            description="Poll a QR-code login session for current scan/confirm status.",
            inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]},
        ),
        Tool(
            name="complete_login",
            description="Finalize a confirmed QR-code login session and persist cookies/token locally.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "auth_key": {"type": "string"},
                    "make_default": {"type": "boolean", "default": True},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="list_saved_accounts",
            description="List locally saved WeChat public-platform login accounts.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="check_account_alive",
            description="Check whether a locally saved login session is still valid.",
            inputSchema={"type": "object", "properties": {"auth_key": {"type": "string"}}},
        ),
        Tool(
            name="set_default_account",
            description="Set the default saved account used by account-search and article-list tools.",
            inputSchema={"type": "object", "properties": {"auth_key": {"type": "string"}}, "required": ["auth_key"]},
        ),
        Tool(
            name="search_accounts",
            description="Search public accounts by keyword with a saved login session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "auth_key": {"type": "string"},
                    "begin": {"type": "integer", "default": 0},
                    "size": {"type": "integer", "default": 5},
                },
                "required": ["keyword"],
            },
        ),
        Tool(
            name="list_articles",
            description="List articles for a public account fakeid with a saved login session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "fakeid": {"type": "string"},
                    "auth_key": {"type": "string"},
                    "begin": {"type": "integer", "default": 0},
                    "size": {"type": "integer", "default": 5},
                    "keyword": {"type": "string", "default": ""},
                },
                "required": ["fakeid"],
            },
        ),
        Tool(
            name="get_latest_article",
            description="Resolve a public account by name and return its latest article.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_name": {"type": "string"},
                    "auth_key": {"type": "string"},
                },
                "required": ["account_name"],
            },
        ),
        Tool(
            name="get_latest_article_content",
            description="Resolve a public account by name, find its latest article, and return normalized HTML directly.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_name": {"type": "string"},
                    "auth_key": {"type": "string"},
                },
                "required": ["account_name"],
            },
        ),
        Tool(
            name="search_articles_by_date",
            description="Resolve a public account by name, paginate its articles, and filter them by date range locally.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_name": {"type": "string"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"},
                    "keyword": {"type": "string", "default": ""},
                    "auth_key": {"type": "string"},
                    "max_items": {"type": "integer", "default": 20},
                    "page_size": {"type": "integer", "default": 5},
                    "use_update_time": {"type": "boolean", "default": False},
                },
                "required": ["account_name"],
            },
        ),
        Tool(
            name="get_article_content",
            description="Fetch a WeChat article url and return normalized HTML plus metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="export_article",
            description="Export either a WeChat article url or the latest article of an account name to a local HTML file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url_or_account_name": {"type": "string"},
                    "output_path": {"type": "string"},
                    "auth_key": {"type": "string"},
                },
                "required": ["url_or_account_name", "output_path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "start_login_session":
            return _text(await asyncio.to_thread(client.start_login_session, arguments.get("session_id")))
        if name == "check_login_session":
            return _text(await asyncio.to_thread(client.check_login_session, arguments["session_id"]))
        if name == "complete_login":
            return _text(
                await asyncio.to_thread(
                    client.complete_login,
                    arguments["session_id"],
                    arguments.get("auth_key"),
                    bool(arguments.get("make_default", True)),
                )
            )
        if name == "list_saved_accounts":
            return _text(await asyncio.to_thread(client.list_saved_accounts))
        if name == "check_account_alive":
            return _text(await asyncio.to_thread(client.check_account_alive, arguments.get("auth_key")))
        if name == "set_default_account":
            return _text(await asyncio.to_thread(client.set_default_account, arguments["auth_key"]))
        if name == "search_accounts":
            return _text(
                await asyncio.to_thread(
                    client.search_accounts,
                    arguments["keyword"],
                    arguments.get("auth_key"),
                    int(arguments.get("begin", 0)),
                    int(arguments.get("size", 5)),
                )
            )
        if name == "list_articles":
            return _text(
                await asyncio.to_thread(
                    client.list_articles,
                    arguments["fakeid"],
                    arguments.get("auth_key"),
                    int(arguments.get("begin", 0)),
                    int(arguments.get("size", 5)),
                    arguments.get("keyword", ""),
                )
            )
        if name == "get_latest_article":
            return _text(
                await asyncio.to_thread(
                    client.get_latest_article,
                    arguments["account_name"],
                    arguments.get("auth_key"),
                )
            )
        if name == "get_latest_article_content":
            return _text(
                await asyncio.to_thread(
                    client.get_latest_article_content,
                    arguments["account_name"],
                    arguments.get("auth_key"),
                )
            )
        if name == "search_articles_by_date":
            return _text(
                await asyncio.to_thread(
                    client.search_articles_by_date,
                    arguments["account_name"],
                    arguments.get("start_date"),
                    arguments.get("end_date"),
                    arguments.get("keyword", ""),
                    arguments.get("auth_key"),
                    int(arguments.get("max_items", 20)),
                    int(arguments.get("page_size", 5)),
                    bool(arguments.get("use_update_time", False)),
                )
            )
        if name == "get_article_content":
            return _text(
                await asyncio.to_thread(
                    client.get_article_content,
                    arguments["url"],
                )
            )
        if name == "export_article":
            return _text(
                await asyncio.to_thread(
                    client.export_article,
                    arguments["url_or_account_name"],
                    arguments["output_path"],
                    arguments.get("auth_key"),
                )
            )
        return _text({"success": False, "message": f"Unknown tool: {name}"})
    except Exception as exc:
        return _text({"success": False, "message": str(exc)})


async def run() -> None:
    options = app.create_initialization_options(notification_options=NotificationOptions())
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, options, raise_exceptions=False)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
