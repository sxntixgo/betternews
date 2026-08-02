"""OPML in and out.

Extracted so the HTML routes and the JSON API share one understanding of the
format. Two copies would drift the first time either side changed a field, and
the whole point of the API is that both clients agree.
"""

import xml.etree.ElementTree as ET
from html import escape

from sqlalchemy import text as sql


def document(rows) -> str:
    """An OPML file listing the given feeds.

    `title` falls back to the URL: an outline with an empty text attribute is
    valid OPML and useless in every reader that imports it.
    """
    body = "\n".join(
        f'      <outline type="rss" text="{escape(r["title"] or r["url"])}" '
        f'title="{escape(r["title"] or r["url"])}" xmlUrl="{escape(r["url"])}"/>'
        for r in rows
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<opml version="2.0">\n'
        '  <head><title>Better News feeds</title></head>\n'
        '  <body>\n'
        f'{body}\n'
        '  </body>\n'
        '</opml>\n'
    )


def urls_from(data: bytes) -> list[str]:
    """Feed URLs in an OPML document.

    Raises ValueError with a message worth showing, for both the unparseable
    case and the parseable-but-empty one -- an OPML with no xmlUrl attributes is
    usually the wrong file rather than an empty subscription list.
    """
    try:
        tree = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"invalid OPML: {exc}") from exc
    urls = [
        outline.attrib["xmlUrl"].strip()
        for outline in tree.iter("outline")
        if outline.attrib.get("xmlUrl")
    ]
    if not urls:
        raise ValueError("no feeds found in OPML")
    return urls


def import_urls(db, urls: list[str]) -> int:
    """Subscribe to each URL, returning how many were new.

    ON CONFLICT DO NOTHING rather than a try/except per row: a duplicate raising
    inside a transaction aborts the whole thing, which is how an OPML import
    silently added nothing on Postgres.
    """
    added = 0
    for url in urls:
        res = db.execute(
            sql("INSERT INTO feeds (url) VALUES (:url) ON CONFLICT (url) DO NOTHING"),
            {"url": url},
        )
        added += res.rowcount
    db.commit()
    return added
