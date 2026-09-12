"""The output: one self-contained HTML page you can open, host or email.

No build step and no assets, because the whole thing is meant to be published by
a GitHub Action to GitHub Pages for nothing.
"""

import html
import json
import os
import urllib.parse
from datetime import datetime, timezone

from . import costs, places
from .score import _money

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "out", "index.html")

KIND_LABEL = {"flight": "Flight", "hotel": "Hotel",
              "package": "Package", "cruise": "Cruise", "other": "Other"}

CSS = """
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#14171c; --muted:#5d6672; --line:#e3e6ea;
  --accent:#1f6feb; --good:#0f7b4f; --good-bg:#e3f5ec; --warn:#8a5a00;
  --warn-bg:#fdf3dd; --chip:#eef1f5; --shadow:0 1px 2px rgba(16,24,40,.06);
}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0f1216; --card:#171b21; --ink:#e8ecf1; --muted:#98a2b3; --line:#252b33;
    --accent:#5aa2ff; --good:#4ade80; --good-bg:#10291d; --warn:#f5c451;
    --warn-bg:#2a2213; --chip:#212831; --shadow:none;
  }
}
:root[data-theme="dark"]{
  --bg:#0f1216; --card:#171b21; --ink:#e8ecf1; --muted:#98a2b3; --line:#252b33;
  --accent:#5aa2ff; --good:#4ade80; --good-bg:#10291d; --warn:#f5c451;
  --warn-bg:#2a2213; --chip:#212831; --shadow:none;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:28px 18px 64px}
header h1{margin:0 0 4px;font-size:24px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:13px;margin-bottom:18px}
.sub b{color:var(--ink);font-weight:600}
.bar{display:flex;flex-wrap:wrap;gap:6px;margin:18px 0 20px;
  position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:5;
  border-bottom:1px solid var(--line)}
button.f{border:1px solid var(--line);background:var(--card);color:var(--muted);
  padding:5px 12px;border-radius:999px;font-size:13px;cursor:pointer}
button.f[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);
  color:#fff;font-weight:600}
.deal{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:14px 16px;margin-bottom:10px;box-shadow:var(--shadow);
  display:grid;grid-template-columns:52px 1fr;gap:14px}
.score{font-size:19px;font-weight:700;text-align:center;line-height:1.1;
  padding-top:2px}
.score small{display:block;font-size:10px;font-weight:500;color:var(--muted);
  letter-spacing:.06em;text-transform:uppercase}
.title{font-weight:600;margin:0 0 4px}
.title a{color:inherit;text-decoration:none}
.title a:hover{color:var(--accent);text-decoration:underline}
.route{color:var(--muted);font-size:13px;margin-bottom:8px}
.tags{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}
.tag{font-size:11.5px;padding:2px 8px;border-radius:999px;background:var(--chip);
  color:var(--muted);white-space:nowrap}
.tag.kind{background:var(--accent);color:#fff;font-weight:600}
.tag.new{background:var(--good-bg);color:var(--good);font-weight:600}
.tag.good{background:var(--good-bg);color:var(--good)}
.tag.warn{background:var(--warn-bg);color:var(--warn)}
.cost{display:flex;flex-wrap:wrap;gap:0 22px;font-size:13px;
  border-top:1px dashed var(--line);padding-top:9px}
.cost div{padding:2px 0}
.cost b{font-weight:600}
.cost .big{font-size:15px}
.muted{color:var(--muted)}
details{margin-top:8px}
summary{font-size:12.5px;color:var(--muted);cursor:pointer}
.prices{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;
  color:var(--muted);margin-top:7px}
.empty{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:28px;text-align:center;color:var(--muted)}
footer{margin-top:34px;color:var(--muted);font-size:12px;line-height:1.7;
  border-top:1px solid var(--line);padding-top:14px}
code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12px}
@media (max-width:560px){
  .deal{grid-template-columns:44px 1fr;gap:10px;padding:12px}
  .cost{gap:0 14px}
}
"""

JS = """
(function(){
  var kind='all', newOnly=false;
  function apply(){
    document.querySelectorAll('.deal').forEach(function(el){
      var okKind = (kind==='all') || el.dataset.kind===kind;
      var okNew  = !newOnly || el.dataset.new==='1';
      el.style.display = (okKind && okNew) ? '' : 'none';
    });
    var shown=document.querySelectorAll('.deal:not([style*="none"])').length;
    var c=document.getElementById('count'); if(c) c.textContent=shown;
  }
  document.querySelectorAll('button.f[data-kind]').forEach(function(b){
    b.addEventListener('click',function(){
      kind=b.dataset.kind;
      document.querySelectorAll('button.f[data-kind]').forEach(function(o){
        o.setAttribute('aria-pressed', String(o===b));});
      apply();
    });
  });
  var nb=document.getElementById('newonly');
  if(nb) nb.addEventListener('click',function(){
    newOnly=!newOnly; nb.setAttribute('aria-pressed',String(newOnly)); apply();
  });
})();
"""


def _esc(text):
    return html.escape(str(text or ""))


def affiliate_url(url, template):
    """Rewrite an outbound link through an affiliate tracker.

    `template` is whatever the network gives you, with {url} where the
    destination goes - for example
    "https://prf.hn/click/camref:1011l123/destination:{url}". An empty or absent
    template leaves the link exactly as it was, which is the default: a
    misconfigured tracker that silently breaks every link out of the report
    would be worse than earning nothing.
    """
    if not template or not url or "{url}" not in template:
        return url
    return template.replace("{url}", urllib.parse.quote(url, safe=""))


def _route_line(deal):
    if deal.origin:
        return "%s &rarr; %s" % (_esc(places.label(deal.origin)),
                                 _esc(places.label(deal.destination)))
    return _esc(places.label(deal.destination))


def _deal_html(deal, rates, home_currency, affiliates=None):
    trip = deal.trip or {}
    tags = ['<span class="tag kind">%s</span>' % KIND_LABEL.get(deal.kind, deal.kind)]
    if deal.is_new:
        tags.append('<span class="tag new">new</span>')
    if deal.cabin != "economy":
        tags.append('<span class="tag">%s class</span>' % _esc(deal.cabin))
    if deal.roundtrip:
        tags.append('<span class="tag">roundtrip</span>')

    for reason in deal.reasons:
        cls = "good"
        low = reason.lower()
        if "above" in low or "not one of yours" in low or "over your" in low \
                or "outside the months" in low or "days old" in low:
            cls = "warn"
        tags.append('<span class="tag %s">%s</span>' % (cls, _esc(reason)))

    also = trip.get("also_seen_on") or []
    src = _esc(deal.source)
    if also:
        src += " +%d more" % len(also)

    cost_bits = []
    # Quote the price the way the source quoted it - a reader recognises "$819
    # per person", not the party total under a per-person label.
    headline = _money(trip.get("unit_home") or trip.get("deal_home"), home_currency)
    cost_bits.append('<div><span class="muted">Deal</span> <b class="big">%s</b>'
                     '<span class="muted"> %s</span></div>'
                     % (headline, _esc(_basis_label(deal))))
    if trip.get("known") and trip.get("total_home") is not None:
        cost_bits.append('<div><span class="muted">All-in %d nights, %d %s</span> '
                         '<b class="big">%s</b></div>'
                         % (trip.get("nights", 0), trip.get("travelers", 1),
                            "traveller" if trip.get("travelers") == 1 else "travellers",
                            _money(trip.get("total_home"), home_currency)))
        cost_bits.append('<div><span class="muted">Per day</span> <b>%s</b></div>'
                         % _money(trip.get("per_day_home"), home_currency))

    detail = ""
    if trip.get("known"):
        rows = []
        rows.append("Deal price %s for %d" % (
            _money(trip.get("deal_home"), home_currency), trip.get("travelers", 1)))
        if trip.get("lodging_home"):
            rows.append("lodging %s" % _money(trip.get("lodging_home"), home_currency))
        if trip.get("ground_home"):
            label = "onboard + shore" if deal.kind == "cruise" else "food, transit, local"
            rows.append("%s %s" % (label, _money(trip.get("ground_home"), home_currency)))
        samples = costs.sample_prices(deal.destination, rates, home_currency)
        sample_html = "".join(
            "<span>%s <b>%s</b></span>" % (_esc(n), _money(v, home_currency))
            for n, v in samples)

        # Say whether these local prices were measured or guessed. Five
        # countries were checked against real listings; everywhere else is still
        # hand-authored, and a reader deserves to know which they are looking at.
        country = places.country_of(deal.destination) or {}
        if country.get("verified"):
            provenance = ('<span class="tag good">cost data measured %s</span>'
                          % _esc(country["verified"].split(",")[0]))
        else:
            provenance = ('<span class="tag">cost data estimated, '
                          'not verified</span>')

        detail = ('<details><summary>How this adds up</summary>'
                  '<div class="prices">%s</div>'
                  '<div class="prices">%s</div>'
                  '<div class="tags" style="margin-top:8px">%s</div></details>'
                  % (" &middot; ".join(_esc(r) for r in rows), sample_html,
                     provenance))

    link = affiliate_url(deal.url, (affiliates or {}).get(deal.source))

    return """<article class="deal" data-kind="%s" data-new="%s">
  <div class="score">%s<small>score</small></div>
  <div>
    <p class="title"><a href="%s" target="_blank" rel="noopener">%s</a></p>
    <div class="route">%s &middot; <span class="muted">%s</span></div>
    <div class="tags">%s</div>
    <div class="cost">%s</div>
    %s
  </div>
</article>""" % (
        _esc(deal.kind), "1" if deal.is_new else "0", int(round(deal.score)),
        _esc(link), _esc(deal.title), _route_line(deal), src,
        "".join(tags), "".join(cost_bits), detail)


def _basis_label(deal):
    return {"per_person": "per person", "per_night": "per night",
            "per_room_night": "per room / night", "total": ""}.get(deal.basis, "")


def render(deals, profile, rates, meta, path=None):
    path = path or OUT_PATH
    home_currency = (profile.get("home_currency") or "USD").upper()
    now = datetime.now(timezone.utc).astimezone()

    counts = {}
    for deal in deals:
        counts[deal.kind] = counts.get(deal.kind, 0) + 1
    new_count = sum(1 for d in deals if d.is_new)

    chips = ['<button class="f" data-kind="all" aria-pressed="true">All %d</button>'
             % len(deals)]
    for kind in ("flight", "hotel", "package", "cruise"):
        if counts.get(kind):
            chips.append('<button class="f" data-kind="%s" aria-pressed="false">'
                         '%s %d</button>' % (kind, KIND_LABEL[kind], counts[kind]))
    chips.append('<button class="f" id="newonly" aria-pressed="false">New only %d</button>'
                 % new_count)

    affiliates = meta.get("affiliates") or {}
    body = "".join(_deal_html(d, rates, home_currency, affiliates) for d in deals)
    if not body:
        body = ('<div class="empty">No deals cleared your filters this run.<br>'
                'Loosen <code>config/profile.json</code> or wait for the next pull.</div>')

    home_label = ", ".join(profile.get("home_airports", [])) or "anywhere"
    fx_note = "FX %s" % (rates.as_of or "unavailable")
    if rates.stale:
        fx_note += " (cached)"

    doc = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Farewatch</title>
<style>%s</style>
</head><body><div class="wrap">
<header>
  <h1>Farewatch</h1>
  <div class="sub">
    <b id="count">%d</b> deals ranked for <b>%s</b> &middot;
    <b>%d</b> new since last run &middot;
    %d fetched, %d parsed &middot; %s &middot;
    generated %s
  </div>
</header>
<div class="bar">%s</div>
%s
<footer>
  Prices are converted at today&rsquo;s rate. All-in totals add estimated food,
  local transport and lodging for <b>%s</b> travel at the destination, adjusted
  for how far %s currently goes against its 1-year average &mdash; they are for
  ranking deals against each other, not for budgeting to the dollar.
  Cost data: <code>data/destinations.json</code>. Rates: ECB via frankfurter.dev
  and open.er-api.com. Sources: %s.
</footer>
</div><script>%s</script></body></html>""" % (
        CSS, len(deals), _esc(home_label), new_count,
        meta.get("fetched", 0), meta.get("parsed", 0), _esc(fx_note),
        now.strftime("%Y-%m-%d %H:%M %Z"),
        "".join(chips), body,
        _esc(profile.get("travel_style", "mid")), _esc(home_currency),
        _esc(", ".join(meta.get("sources", []))), JS)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path


def render_json(deals, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([d.to_dict() for d in deals], fh, indent=1, default=str)
    return path
