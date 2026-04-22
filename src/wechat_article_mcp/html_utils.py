from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


def is_valid_mp_article_url(url: str) -> bool:
    try:
        return urlparse(url).hostname == "mp.weixin.qq.com"
    except Exception:
        return False


def _clean_article_dom(raw_html: str) -> tuple[BeautifulSoup, Any]:
    soup = BeautifulSoup(raw_html, "html.parser")
    js_article = soup.select_one("#js_article") or soup.body or soup

    js_content = js_article.select_one("#js_content")
    if js_content is not None:
        js_content.attrs.pop("style", None)

    for selector in [
        "#js_top_ad_area",
        "#js_tags_preview_toast",
        "#content_bottom_area",
        "#js_pc_qr_code",
        "#wx_stream_article_slide_tip",
        "script",
    ]:
        for node in js_article.select(selector):
            node.decompose()

    for img in soup.find_all("img"):
        data_src = img.get("data-src")
        src = img.get("src")
        if data_src and not src:
            img["src"] = data_src

    return soup, js_article


def normalize_article_html(raw_html: str) -> str:
    soup, js_article = _clean_article_dom(raw_html)
    body = soup.body
    body_class = ""
    if body is not None:
        classes = body.get("class", [])
        body_class = " ".join(classes) if isinstance(classes, list) else str(classes)

    page_content = str(js_article)
    return f"""<!DOCTYPE html>
<html lang="zh_CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=0,viewport-fit=cover">
  <meta name="referrer" content="no-referrer">
  <style>
    #js_row_immersive_stream_wrap {{
      max-width: 667px;
      margin: 0 auto;
    }}
    #js_row_immersive_stream_wrap .wx_follow_avatar_pic {{
      display: block;
      margin: 0 auto;
    }}
    #page-content,
    #js_article_bottom_bar,
    .__page_content__ {{
      max-width: 667px;
      margin: 0 auto;
    }}
    img {{
      max-width: 100%;
    }}
    .sns_opr_btn::before {{
      width: 16px;
      height: 16px;
      margin-right: 3px;
    }}
  </style>
</head>
<body class="{body_class}">
{page_content}
</body>
</html>
"""


def extract_account_name(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    node = soup.select_one(".wx_follow_nickname")
    return node.get_text(strip=True) if node else ""


def extract_article_metadata(raw_html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(raw_html, "html.parser")
    title = ""
    for selector in ["meta[property='og:title']", "h1#activity-name", "#activity-name"]:
        node = soup.select_one(selector)
        if node is None:
            continue
        title = node.get("content", "").strip() if node.name == "meta" else node.get_text(strip=True)
        if title:
            break

    author_name = ""
    for selector in ["#js_name", ".wx_tap_link.js_wx_tap_highlight.weui-wa-hotarea"]:
        node = soup.select_one(selector)
        if node is not None:
            author_name = node.get_text(strip=True)
            if author_name:
                break

    account_name = extract_account_name(raw_html)

    cover = ""
    for selector in ["meta[property='og:image']", "meta[name='twitter:image']"]:
        node = soup.select_one(selector)
        if node is not None:
            cover = node.get("content", "").strip()
            if cover:
                break

    publish_time = None
    for pattern in [
        r"""\bvar\s+ct\s*=\s*["']?(?P<ts>\d{8,})""",
        r'''"publish_time"\s*:\s*"(?P<ts>\d{8,})"''',
    ]:
        match = re.search(pattern, raw_html)
        if match:
            publish_time = int(match.group("ts"))
            break

    query = parse_qs(urlparse(url).query)
    return {
        "title": title,
        "author_name": author_name,
        "account_name": account_name,
        "cover": cover,
        "publish_time": publish_time,
        "url": url,
        "mid": query.get("mid", [None])[0],
        "idx": query.get("idx", [None])[0],
        "__biz": query.get("__biz", [None])[0],
        "sn": query.get("sn", [None])[0],
    }
