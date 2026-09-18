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
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

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


def _cache_path(url):
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".xml")


def fetch(url, max_age=DEFAULT_MAX_AGE, timeout=DEFAULT_TIMEOUT, offline=False):
    """Return feed bytes, from cache when fresh. Falls back to a stale cache on error."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(url)
    cached_age = None
    if os.path.exists(path):
        cached_age = time.time() - os.path.getmtime(path)
        if offline or (max_age is not None and cached_age < max_age):
            with open(path, "rb") as fh:
                return fh.read()
    if offline:
        raise FetchError("offline and nothing cached for %s" % url)

    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Encoding": "gzip, identity",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
    except Exception as exc:  # network, HTTP, TLS - all handled the same way
        if cached_age is not None:
            with open(path, "rb") as fh:
                return fh.read()
        raise FetchError("%s: %s" % (url, exc)) from exc

    with open(path, "wb") as fh:
        fh.write(raw)
    return raw


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
