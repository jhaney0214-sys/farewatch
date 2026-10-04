"""A GET-and-cache-to-disk helper, generalised from Outcrop's `sources.py`.

Five projects in this workstation each fetch free public data over HTTP and
cache it: Farewatch (RSS feeds, an FX rate), Greenlight (SteamSpy and Steam
store JSON), Assay (V-Dem, HDI, EPI tables), Outcrop (PBDB, Macrostrat, USGS
elevation), Sextant (nothing live - it ships a static extract). Each wrote its
own version. Outcrop's is the best of the four: sha1-keyed cache files, an
atomic tmp-then-replace write so a killed process cannot leave a half-written
entry, and a per-source throttle because these are grant-funded services run
by people, not vendors.

This is that module, generalised rather than reinvented, plus the two things
the other three projects needed that Outcrop's did not:

  bytes, not just JSON     Farewatch parses RSS/XML; a cache keyed to "this
                            call returns parsed JSON" cannot serve that call.
                            `fetch()` returns raw bytes. `fetch_json()` is the
                            thin convenience wrapper Outcrop's callers want.
  an expiry, not just "forever until you delete it"
                            Outcrop's geology does not change under it, so its
                            cache has no TTL. Farewatch's flight prices and
                            Greenlight's review counts do. `max_age` is
                            optional and defaults to "forever", which keeps
                            Outcrop's behaviour exactly as it was.

Nothing else changes. Same cache layout (`<cache_dir>/<source>/<sha1>.bin`,
with a `.meta.json` alongside so a byte cache can still be introspected), same
atomic write, same per-source throttle, same raised `SourceError` rather than
a swallowed one.

This module is meant to be VENDORED, not imported across a repo boundary.
Every project in this workstation is a separate, independently cloneable git
repository with no runtime dependency on another - that is deliberate, and a
shared import would break that for the first person who clones one project
without the others. Copy `netcache.py` into a project's own package directory
and adjust the cache directory and user agent for that project. This copy, in
`AI Workstation/tools/`, is the one with tests; treat it as the source of
truth and diff a vendored copy against it periodically rather than hand
patching both independently.

    from netcache import Cache
    cache = Cache(pathlib.Path("data/cache"), user_agent="MyProject/0.1 (...)")
    raw = cache.fetch("pbdb", url)                     # bytes, cached forever
    raw = cache.fetch("steamspy", url, max_age=86400)  # cached for a day
    data = cache.fetch_json("vdem", url)               # bytes, parsed as JSON
"""

import hashlib
import json
import pathlib
import time
import urllib.request


class SourceError(RuntimeError):
    """A fetch failed, or the response could not be parsed as promised.

    Raised rather than returning None or an empty result, because a caller
    that gets nothing back and treats it as "no data" cannot tell that apart
    from a network error - which is exactly the silent-failure shape that
    produces a confident number from no data.
    """


class Cache:
    """One project's on-disk HTTP cache.

    `cache_dir` is that project's own `data/cache` (or wherever it already
    keeps one) - this does not impose a location, only a layout under it.
    """

    def __init__(self, cache_dir, user_agent, offline=False):
        self.dir = pathlib.Path(cache_dir)
        self.user_agent = user_agent
        self.offline = offline
        self._throttle = {}
        self._last = {}

    def set_throttle(self, source, seconds):
        """Minimum gap between live calls to one source. Cached reads wait
        for nothing - this only slows the process down when it is actually
        reaching the network, which is what makes it safe to set generously.
        """
        self._throttle[source] = seconds

    def _wait(self, source):
        gap = self._throttle.get(source, 0.0)
        if gap <= 0:
            return
        since = time.time() - self._last.get(source, 0.0)
        if since < gap:
            time.sleep(gap - since)
        self._last[source] = time.time()

    def _paths(self, source, url):
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        base = self.dir / source / key
        return base.with_suffix(".bin"), base.with_suffix(".meta.json")

    def fetch(self, source, url, timeout=120, max_age=None, refresh=False,
              headers=None):
        """GET `url`, from disk if it has ever been fetched and is not
        stale. Returns raw bytes; use `fetch_json` for parsed JSON.

        `max_age` is in seconds. `None` (the default) means the cache never
        expires on its own - delete the source's subdirectory to force a
        refetch, which is Outcrop's original behaviour and the right default
        for data that does not change under the process asking for it.

        `headers` are sent with a live request and are not part of the cache
        key or the metadata file, so an API key passed as a header is never
        written to disk. Only pass headers that do not change the response.
        """
        data_path, meta_path = self._paths(source, url)
        if data_path.exists() and not refresh:
            if max_age is None or self._age(meta_path) <= max_age:
                return data_path.read_bytes()

        if self.offline:
            raise SourceError(
                "%s: no usable cache entry and offline mode is on - %s"
                % (source, url[:120]))

        self._wait(source)
        req = urllib.request.Request(
            url, headers=dict(headers or {}, **{"User-Agent": self.user_agent}))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except Exception as exc:                  # noqa: BLE001 - reraised, not swallowed
            raise SourceError("%s: %s" % (url[:120], exc)) from exc

        self._write(data_path, meta_path, raw, url, source)
        return raw

    def fetch_json(self, source, url, timeout=120, max_age=None, refresh=False,
                   headers=None):
        """`fetch()`, parsed as JSON. Raises SourceError on non-JSON rather
        than returning None, for the same reason `fetch` raises on a failed
        GET - a caller must not be able to mistake "malformed" for "empty".
        """
        raw = self.fetch(source, url, timeout=timeout, max_age=max_age,
                         refresh=refresh, headers=headers)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise SourceError(
                "%s returned non-JSON (%d bytes): %s"
                % (source, len(raw), url[:120])) from exc

    def _write(self, data_path, meta_path, raw, url, source):
        data_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(data_path)                    # never a half-written entry

        meta = {"url": url, "source": source, "fetched_at": time.time(),
                "bytes": len(raw)}
        tmp_meta = meta_path.with_suffix(".tmp")
        tmp_meta.write_text(json.dumps(meta), encoding="utf-8")
        tmp_meta.replace(meta_path)

    def _age(self, meta_path):
        """Seconds since fetched, or infinity if there is no metadata to
        read - which forces a refetch rather than trusting an ageless file.
        """
        if not meta_path.exists():
            return float("inf")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return time.time() - meta["fetched_at"]
        except (ValueError, KeyError, OSError):
            return float("inf")

    def size(self):
        """(files, bytes) currently cached, for reporting rather than logic."""
        n = total = 0
        for p in self.dir.rglob("*.bin"):
            n += 1
            total += p.stat().st_size
        return n, total

    def purge_older_than(self, seconds):
        """Delete cache entries older than `seconds`. Returns how many.

        For a scheduled job that wants to keep a cache bounded without
        deleting everything - Outcrop's cache is meant to grow forever, but
        not every project wants that, and this is the one operation none of
        the five original implementations had.
        """
        removed = 0
        for meta_path in list(self.dir.rglob("*.meta.json")):
            if self._age(meta_path) > seconds:
                data_path = meta_path.parent / (meta_path.name[:-len(".meta.json")] + ".bin")
                data_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                removed += 1
        return removed
