"""Fetching and parsing the public deal feeds.

Deliberately small: urllib plus ElementTree handle RSS 2.0 and Atom well enough,
and avoiding feedparser keeps the whole project installable with nothing but a
Python interpreter.
"""

import email.utils
import gzip
import hashlib
import io
import json
import os
import pathlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .netcache import Cache, SourceError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "cache", "feeds")

# Several of these sites sit behind Cloudflare and refuse anything that looks
# like a script. A normal browser UA is the difference between 200 and 403.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DEFAULT_TIMEOUT = 25
DEFAULT_MAX_AGE = 1800  # seconds; feeds update slowly, be a polite client


class ParseError(RuntimeError):
    """Served something that was not a feed. Distinct from a feed with no items."""


class FetchError(Exception):
    pass


CACHE = Cache(os.path.dirname(CACHE_DIR), user_agent=USER_AGENT)
STALE = Cache(os.path.dirname(CACHE_DIR), user_agent=USER_AGENT, offline=True)
HEADERS = {
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    "Accept-Encoding": "gzip, identity",
    "Accept-Language": "en-US,en;q=0.9",
}


def _adopt_legacy(url):
    """Carry a feed cached before `netcache` (<sha1>.xml, no metadata) across.

    Its age is the file's own modification time, which is what freshness was
    measured from before, so an adopted entry is exactly as fresh as it was.
    """
    key = hashlib.sha1(url.encode()).hexdigest()
    old = os.path.join(CACHE_DIR, key + ".xml")
    new = os.path.join(CACHE_DIR, key + ".bin")
    if not os.path.exists(old) or os.path.exists(new):
        return
    with open(old, "rb") as fh:
        raw = fh.read()
    CACHE._write(pathlib.Path(new), pathlib.Path(new[:-4] + ".meta.json"), raw, url, "feeds")
    meta = new[:-4] + ".meta.json"
    with open(meta, encoding="utf-8") as fh:
        record = json.load(fh)
    record["fetched_at"] = os.path.getmtime(old)
    with open(meta, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    os.remove(old)


def _gunzip(raw):
    # Asked for gzip, and `netcache` stores the body as sent; decoded here, on
    # the way out, so a cached copy and a live one read the same.
    return gzip.decompress(raw) if raw[:2] == bytes((0x1F, 0x8B)) else raw


def fetch(url, max_age=DEFAULT_MAX_AGE, timeout=DEFAULT_TIMEOUT, offline=False):
    """Return feed bytes, from cache when fresh. Falls back to a stale cache on error.

    The cache is `netcache`, whose write is tmp-then-replace: the old direct
    write could leave a truncated feed behind a killed run, and the next run
    would read it as fresh.
    """
    _adopt_legacy(url)
    try:
        if offline:
            return _gunzip(STALE.fetch("feeds", url))
        return _gunzip(CACHE.fetch("feeds", url, timeout=timeout, max_age=max_age,
                                   headers=HEADERS))
    except SourceError as exc:
        try:
            return _gunzip(STALE.fetch("feeds", url))
        except SourceError:
            if offline:
                raise FetchError("offline and nothing cached for %s" % url) from exc
            raise FetchError(str(exc)) from exc


def _strip_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def _text(el):
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean_html(text):
    text = _TAGS.sub(" ", text or "")
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&#8211;", "-").replace("&#8212;", "-")
                .replace("&quot;", '"').replace("&#039;", "'"))
    return _WS.sub(" ", text).strip()


def _parse_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse(raw, strict=False):
    """Parse RSS 2.0 or Atom bytes into a list of entry dicts.

    Returns [] rather than raising on junk, because a feed occasionally serves an
    HTML error page with a 200 and one bad source should not stop a run.

    `strict=True` separates the two things [] used to mean. An empty feed and a
    feed that was not a feed both produced [], and `collect` logged "+ source
    0 items" for each - so a morning where every source served an error page
    read exactly like a quiet day, in the one project here that runs daily,
    unattended, with nobody watching. A network failure was always reported;
    a 200 carrying HTML was not. Callers that want the difference ask for it;
    the default is unchanged, and the tests that assert [] on junk still pass.
    """
    if not raw:
        if strict:
            raise ParseError("empty response")
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        if strict:
            raise ParseError("not XML: %s" % exc) from exc
        return []

    # Valid XML is not the same as a feed. "<html>not a feed</html>" parses
    # perfectly and yields no items, so checking only for a parse error let
    # the commonest junk - an error page that happens to be well-formed -
    # through as an empty feed. The root element is what says this is RSS,
    # Atom or RDF.
    if strict and _strip_ns(root.tag).lower() not in ("rss", "feed", "rdf"):
        raise ParseError("root element <%s> is not a feed" % _strip_ns(root.tag))

    entries = []
    for node in root.iter():
        tag = _strip_ns(node.tag)
        if tag not in ("item", "entry"):
            continue

        title = link = summary = published = ""
        for child in node:
            ctag = _strip_ns(child.tag)
            if ctag == "title" and not title:
                title = _text(child)
            elif ctag == "link":
                href = child.get("href")
                if href:
                    if not link or child.get("rel") in (None, "alternate"):
                        link = href
                elif not link:
                    link = _text(child)
            elif ctag in ("description", "summary", "content", "encoded") and not summary:
                summary = _text(child)
            elif ctag in ("pubDate", "published", "updated", "date") and not published:
                published = _parse_date(_text(child))

        if not title:
            continue
        entries.append({
            "title": clean_html(title),
            "link": link.strip(),
            "summary": clean_html(summary)[:600],
            "published": published,
        })
    return entries


def load_sources(path=None):
    path = path or os.path.join(ROOT, "config", "sources.json")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    return [s for s in cfg["sources"] if s.get("enabled", True)]


def collect(sources, max_age=DEFAULT_MAX_AGE, offline=False, log=None):
    """Fetch every source. Returns (entries, errors); one bad feed never stops the run."""
    out, errors = [], []
    for src in sources:
        try:
            raw = fetch(src["url"], max_age=max_age, offline=offline)
            entries = parse(raw, strict=True)
        except (FetchError, ParseError) as exc:
            errors.append((src["name"], str(exc)))
            if log:
                log("  ! %-16s %s" % (src["name"], exc))
            continue
        for e in entries:
            e["source"] = src["name"]
            e["source_kind"] = src.get("kind", "mixed")
            e["trust_url_kind"] = src.get("trust_url_kind", True)
            e["affiliate"] = src.get("affiliate", "")
            out.append(e)
        if log:
            log("  + %-16s %3d items" % (src["name"], len(entries)))
    return out, errors
