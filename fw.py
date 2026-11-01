#!/usr/bin/env python
"""Farewatch command line.

    python fw.py run              fetch, rank, write out/index.html
    python fw.py run --offline    same, from cache only
    python fw.py run --open       and open it in a browser
    python fw.py run --alert      and notify on new deals and price drops
    python fw.py top -n 15        print the ranking to the terminal
    python fw.py stats            what the database has collected
    python fw.py rejects          what the parser threw away, and why
    python fw.py calibrate        where observed prices disagree with the cost data
python fw.py watch            cruises you are watching, and whether a sale is real
python fw.py share            send the deals to the group trip site
"""

import argparse
import json
import os
import sys
import webbrowser
from datetime import date, timedelta

from farewatch import (alerts, baselines, dotfares, feeds, fx, parse, places,
                       positioning, render, score, share, store, watch)

ROOT = os.path.dirname(os.path.abspath(__file__))
DOT_CHECK = os.path.join(ROOT, "data", "cache", "dot-check.json")
DOT_CHECK_DAYS = 7


def load_profile(path=None):
    path = path or os.path.join(ROOT, "config", "profile.json")
    # A fresh clone has only the example. Fall back to it so the tool runs, but
    # say so - ranking against someone else's airports silently is the exact
    # kind of confidently-wrong output this project is built to avoid.
    if not os.path.exists(path):
        example = os.path.join(ROOT, "config", "profile.example.json")
        if os.path.exists(example):
            sys.stderr.write(
                "No config/profile.json - using config/profile.example.json. "
                "Copy it and edit it; every ranking below is about Chicago.\n")
            path = example
    with open(path, encoding="utf-8") as fh:
        profile = json.load(fh)
    profile.pop("_comment", None)
    return profile


def refresh_dot(profile, log, today=None, bp=None, br=None):
    """Rebuild the DOT fare tables when DOT has published a newer quarter.

    DOT publishes a quarter about every three months, two quarters behind, and
    a table nobody remembers to rebuild quietly ages into the wrong prices. So
    the daily run asks DOT for its newest quarter once a week - one small
    request - and rebuilds only a table that lacks it. The positioning table is
    only refreshed, never created: building it is a choice about your base.
    Never fatal; a failed check leaves both tables as they were. `bp` and `br`
    are the two build tools, injectable for tests.
    """
    today = today or date.today()
    try:
        with open(DOT_CHECK, encoding="utf-8") as fh:
            checked = date.fromisoformat(json.load(fh)["checked_on"])
        if today - checked < timedelta(days=DOT_CHECK_DAYS):
            return []
    except (OSError, ValueError, KeyError):
        pass

    if bp is None or br is None:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import build_positioning as bp
        import build_routes as br
    rebuilt = []
    try:
        latest = bp.latest_quarter()
        if latest not in (dotfares.load().get("quarters") or []):
            table = br.build(br.fetch())
            if table["routes"]:
                br.save(table)
                rebuilt.append("routes")
        hops = positioning.measured_fares()
        base = positioning.base_key(profile)
        if (hops.get("market") and base
                and (hops.get("base") != base or latest not in (hops.get("quarters") or []))):
            table = bp.build(bp.fetch(hops["market"]), hops["market"], base)
            if table["fares"]:
                bp.save(table, positioning.FARES_PATH)
                rebuilt.append("positioning")
    except Exception as exc:  # network, DOT, or a changed schema: keep what we have
        log("DOT check failed, tables unchanged: %s" % exc)
        return rebuilt
    os.makedirs(os.path.dirname(DOT_CHECK), exist_ok=True)
    with open(DOT_CHECK, "w", encoding="utf-8") as fh:
        json.dump({"checked_on": today.isoformat(), "latest": latest}, fh)
    # Drop the cached tables so this run scores against the new ones.
    dotfares._TABLE = None
    positioning._FARES = None
    log("DOT newest quarter %s%s" % (latest, "; rebuilt " + ", ".join(rebuilt) if rebuilt else ""))
    return rebuilt


def collect(args, log, sync=True):
    """Fetch, parse and rank. `sync` records what was seen and logs the run,
    which decides what the next run calls new; only `run` and `top` do."""
    profile = load_profile(args.profile)
    if not args.offline:
        refresh_dot(profile, log)
    sources = feeds.load_sources(args.sources)

    log("Fetching %d sources%s" % (len(sources), " (offline)" if args.offline else ""))
    entries, errors = feeds.collect(
        sources, max_age=0 if args.refresh else feeds.DEFAULT_MAX_AGE,
        offline=args.offline, log=log)

    log("Rates")
    rates = fx.load(offline=args.offline, log=log)

    deals, rejects = parse.build_all(entries)
    log("Parsed %d deals from %d entries (%d unreadable)"
        % (len(deals), len(entries), len(rejects)))

    # Everything ever seen, used to correct the eyeballed fare curve where there
    # is enough of it to be worth trusting.
    conn = store.connect()
    history = baselines.load(conn)
    summary = history.summary()
    log("History %d baselines ready across %d levels (%dd window)"
        % (summary["ready"],
           sum(1 for k, v in summary.items()
               if k.endswith("_ready") and v), summary["window_days"]))
    for level in baselines.FLIGHT_LEVELS:
        ready = summary["flight_%s_ready" % level]
        if ready:
            log("  flight/%-12s %d of %d keys ready"
                % (level, ready, summary["flight_%s" % level]))
    for level in baselines.LODGING_LEVELS:
        ready = summary["lodging_%s_ready" % level]
        if ready:
            log("  stay/%-14s %d of %d keys ready"
                % (level, ready, summary["lodging_%s" % level]))

    ranked = score.rank(deals, profile, rates, history)
    if args.min_score:
        ranked = [d for d in ranked if d.score >= args.min_score]
    if args.limit:
        ranked = ranked[:args.limit]

    if sync:
        new_count = store.sync(conn, ranked)
        store.record_run(conn, len(entries), len(deals), len(ranked), new_count)
        log("Ranked %d deals, %d new since last run" % (len(ranked), new_count))
    else:
        log("Ranked %d deals (nothing recorded)" % len(ranked))
    conn.close()
    meta = {"fetched": len(entries), "parsed": len(deals), "errors": errors,
            "rejects": rejects, "sources": [s["name"] for s in sources],
            "affiliates": {s["name"]: s.get("affiliate", "") for s in sources},
            "history": summary}
    return profile, rates, ranked, meta


def cmd_run(args):
    log = (lambda m: None) if args.quiet else (lambda m: print(m))
    profile, rates, ranked, meta = collect(args, log)

    state = watch.load()
    found = watch.feed_matches(state, ranked)
    watching = render.watch_html(state, found, profile, rates, score.expected_flight_usd)
    path = render.render(ranked, profile, rates, meta, watching=watching)
    log("Wrote %s" % path)
    # Fresh feeds only: an offline run has nothing new for the group trip site.
    if not args.offline:
        share.push(ranked, profile, log=log)
    if args.json:
        log("Wrote %s" % render.render_json(ranked, args.json))
    status = 0
    if args.alert or args.alert_dry_run:
        # Alerts print even under --quiet: they are the point of the run.
        _alerts, failures = alerts.run(ranked, profile, report_path=path,
                                       log=print, dry_run=args.alert_dry_run)
        if failures:
            status = 3
        if _watch_alerts(state, found, profile, path, args.alert_dry_run):
            status = 3
    if args.open:
        webbrowser.open("file:///" + path.replace("\\", "/"))
    return status


def _watch_alerts(state, found, profile, report_path, dry_run):
    """New feed-watch matches, and on sale days a nudge to price the sailings.
    Returns True when a backend failed."""
    fresh = watch.new_matches(state, found)
    due = watch.needs_reminder(state)
    lines, items = [], []
    for feed, deal in fresh:
        total = (deal.trip or {}).get("total_usd")
        lines.append("%s: %s, all-in $%s" % (feed["name"], deal.title[:70],
                                            format(int(round(total or 0)), ",")))
        items.append(alerts.Alert("new", deal.fingerprint, feed["name"], deal.score,
                                  deal.title, deal.url, price=total))
    if due:
        lines.append("%s is on: record today's price for %s (fw.py watch price)" % (
            state["sale"]["name"], ", ".join(s["name"] for s in due)))
    if not lines:
        if not dry_run:
            watch.save(state)
        return False
    title = "Farewatch: cruise watch"
    body = "\n".join(lines[:6])
    print("%s\n%s" % (title, body))
    if dry_run:
        return False
    failed = False
    try:
        chosen = alerts.notifiers(alerts.settings(profile))
    except ValueError as exc:
        print("Watch alerts not sent: %s" % exc)
        chosen, failed = [], True
    for notifier in chosen:
        try:
            notifier.send(title, body, items, report_path)
        except Exception as exc:  # one bad backend never stops the rest
            print("Watch alert via %s failed: %s" % (notifier.name, exc))
            failed = True
    if due:
        state["reminded"].append(date.today().isoformat())
    watch.save(state)
    return failed


def cmd_share(args):
    """Send the current deals to the group trip site now, recording nothing."""
    profile, _rates, ranked, _meta = collect(args, lambda m: None, sync=False)
    return 0 if share.push(ranked, profile) else 1


def cmd_watch(args):
    """Sailings priced by hand, feed watches, and the sale window."""
    state = watch.load()
    action = args.action or "list"
    if action == "sailing":
        entry = watch.add_sailing(state, args.name, args.price,
                                  basis="total" if args.total else "per_person",
                                  nights=args.nights, port=args.port,
                                  cabin=args.cabin, url=args.url or "")
        watch.save(state)
        print("Watching sailing %d: %s" % (entry["id"], entry["name"]))
    elif action == "price":
        when = date.fromisoformat(args.date) if args.date else None
        try:
            entry = watch.record_price(state, args.id, args.price,
                                       "total" if args.total else "per_person", when)
        except KeyError as exc:
            print(exc)
            return 1
        watch.save(state)
        print("%s: %s" % (entry["name"], watch.verdict(entry, state["sale"])["text"]))
    elif action == "feed":
        entry = watch.add_feed(state, args.name, regions=args.region,
                               min_nights=args.min_nights, max_nights=args.max_nights,
                               max_all_in=args.max_all_in, ports=args.port_group)
        watch.save(state)
        print("Watching feeds for %d: %s (%s)" % (entry["id"], entry["name"],
                                                 watch.describe_feed(entry)))
    elif action == "drop":
        gone = watch.drop_sailing(state, args.id) if args.what == "sailing" \
            else watch.drop_feed(state, args.id)
        watch.save(state)
        print("dropped" if gone else "nothing with that id")
    elif action == "sale":
        state["sale"].update({k: v for k, v in (("name", args.name), ("start", args.start),
                                                ("end", args.end)) if v})
        watch.save(state)
        print("Sale window: %(name)s, %(start)s to %(end)s" % state["sale"])
    else:
        sale = state["sale"]
        print("Sale window: %(name)s, %(start)s to %(end)s" % sale)
        if not state["sailings"]:
            print("No sailings watched. Add one:  fw.py watch sailing \"Ship, 7 nights, Mar 14\" "
                  "--price 1840 --nights 7 --port mobile")
        for entry in state["sailings"]:
            history = ", ".join("%s $%s" % (p["date"][5:], format(int(round(p["per_person"])), ","))
                                for p in entry["prices"][-6:])
            print("\n[%d] %s" % (entry["id"], entry["name"]))
            print("    %s" % history)
            print("    %s" % watch.verdict(entry, sale)["text"])
        for feed in state["feeds"]:
            print("\nfeed [%d] %s: %s" % (feed["id"], feed["name"], watch.describe_feed(feed)))
    return 0


def cmd_top(args):
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))
    profile, rates, ranked, _meta = collect(args, log)
    home = (profile.get("home_currency") or "USD").upper()

    print()
    print("%-3s %-5s %-8s %-30s %10s %11s  %s"
          % ("#", "score", "kind", "route", "deal", "all-in", "why"))
    print("-" * 108)
    for i, deal in enumerate(ranked, 1):
        route = places.label(deal.destination)
        if deal.origin:
            route = "%s > %s" % (places.city(deal.origin)["name"], route)
        trip = deal.trip or {}
        print("%-3d %-5.1f %-8s %-30s %10s %11s  %s" % (
            i, deal.score, deal.kind, route[:30],
            score._money(trip.get("deal_home"), home),
            score._money(trip.get("total_home"), home),
            "; ".join(deal.reasons[:2])[:40]))
    print()
    return 0


def cmd_rejects(args):
    """Show what the parser dropped, grouped by reason.

    Around 40% of entries never become deals. Most of that is correct - deal
    blogs publish news and Travelzoo publishes theatre tickets - but a single
    counter cannot tell you which part is correct rejection and which part is a
    parser that has quietly stopped understanding a feed whose format drifted.
    """
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))
    # Read-only: looking at what was thrown away must not change what the next
    # run calls new, which it did until 2026-10-24.
    _profile, _rates, _ranked, meta = collect(args, log, sync=False)
    rejects = meta.get("rejects", [])
    if not rejects:
        print("Nothing was rejected.")
        return 0

    by_reason = {}
    by_source = {}
    for r in rejects:
        by_reason.setdefault(r["reason"], []).append(r)
        key = (r["source"], r["reason"])
        by_source[key] = by_source.get(key, 0) + 1

    total = meta.get("fetched", 0)
    print()
    print("%d of %d entries rejected (%.0f%%)"
          % (len(rejects), total, 100.0 * len(rejects) / max(1, total)))
    print()

    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print("%-30s %4d" % (reason, len(items)))
        per_source = {}
        for it in items:
            per_source[it["source"]] = per_source.get(it["source"], 0) + 1
        print("   by source: %s" % ", ".join(
            "%s %d" % (k, v) for k, v in sorted(per_source.items(),
                                                key=lambda kv: -kv[1])))
        for it in items[:args.samples]:
            title = it["title"][:88].encode("ascii", "replace").decode("ascii")
            print("   . %s" % title)
        print()
    return 0


def cmd_calibrate(args):
    """Compare observed deal prices against the hand-authored cost data.

    This never edits anything. Deal prices sit below market by construction, so
    a destination whose observed median is somewhat under the authored figure is
    behaving exactly as expected. What is worth a human look is the extremes -
    those suggest the authored number in tools/build_data.py is simply wrong, the
    way the Maldives hotel figure is skewed by resorts when the deals that show
    up are local guesthouses.
    """
    conn = store.connect()
    history = baselines.load(conn, window_days=args.window)

    def authored(destination):
        _ground, lodging = __import__(
            "farewatch.costs", fromlist=["costs"]).daily_rates(destination, "mid")
        return lodging

    rows = baselines.divergences(history, authored, min_samples=args.min_samples)
    summary = history.summary()
    print()
    print("Baselines ready: %d (need >=%d observations at a level)"
          % (summary["ready"], baselines.MIN_SAMPLES))
    print("Window         : %d days" % summary["window_days"])
    print()

    if not rows:
        print("No destination yet has %d hotel observations to compare."
              % args.min_samples)
        print("Keep running; the daily scheduled task builds this up on its own.")
        conn.close()
        return 0

    print("%-22s %8s %9s %7s %5s  %s"
          % ("destination", "observed", "authored", "ratio", "n", "read"))
    print("-" * 78)
    for r in rows:
        if r["ratio"] < 0.45:
            read = "authored may be too high"
        elif r["ratio"] > 1.25:
            read = "authored may be too low"
        else:
            read = "normal deal discount"
        print("%-22s %8.0f %9.0f %7.2f %5d  %s"
              % (places.label(r["destination"])[:22], r["observed_median"],
                 r["authored"], r["ratio"], r["n"], read))
    print()
    print("Edit tools/build_data.py and rerun it to change an authored figure.")
    conn.close()
    return 0


def cmd_stats(args):
    conn = store.connect()
    s = store.stats(conn)
    print("deals tracked : %d" % s["deals"])
    print("first seen    : %s" % (s["since"] or "-"))
    print("runs recorded : %d" % s["runs"])
    rows = conn.execute(
        "SELECT destination, COUNT(*) n, MIN(price_usd) cheapest FROM deals"
        " WHERE destination IS NOT NULL GROUP BY destination"
        " ORDER BY n DESC LIMIT 12").fetchall()
    if rows:
        print("\nmost-seen destinations")
        for r in rows:
            print("  %-22s %3d deals, cheapest $%s"
                  % (places.label(r["destination"]), r["n"],
                     format(int(r["cheapest"] or 0), ",")))
    conn.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="farewatch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--profile", help="path to profile.json")
        p.add_argument("--sources", help="path to sources.json")
        p.add_argument("--offline", action="store_true",
                       help="use cached feeds and rates only")
        p.add_argument("--refresh", action="store_true",
                       help="ignore the feed cache and refetch")
        p.add_argument("-n", "--limit", type=int, default=0,
                       help="keep only the top N")
        p.add_argument("--min-score", type=float, default=0.0)
        p.add_argument("-q", "--quiet", action="store_true")

    p_run = sub.add_parser("run", help="fetch, rank and write the HTML report")
    common(p_run)
    p_run.add_argument("--open", action="store_true", help="open the report")
    p_run.add_argument("--json", help="also write the ranking as JSON here")
    p_run.add_argument("--alert", action="store_true",
                       help="compare with the last alerting run and notify on "
                            "new deals and price drops (see `alerts` in the profile)")
    p_run.add_argument("--alert-dry-run", action="store_true",
                       help="print what --alert would send; send and save nothing")
    p_run.set_defaults(func=cmd_run)

    p_top = sub.add_parser("top", help="print the ranking to the terminal")
    common(p_top)
    p_top.set_defaults(func=cmd_top)

    p_rej = sub.add_parser("rejects", help="what the parser threw away, and why")
    common(p_rej)
    p_rej.add_argument("--samples", type=int, default=4,
                       help="example headlines to show per reason")
    p_rej.set_defaults(func=cmd_rejects)

    p_cal = sub.add_parser("calibrate",
                           help="where observed prices disagree with the cost data")
    p_cal.add_argument("--window", type=int, default=baselines.WINDOW_DAYS)
    p_cal.add_argument("--min-samples", type=int, default=baselines.MIN_SAMPLES)
    p_cal.set_defaults(func=cmd_calibrate)

    p_sh = sub.add_parser("share", help="send the current deals to the group trip site")
    common(p_sh)
    p_sh.set_defaults(func=cmd_share)

    p_w = sub.add_parser("watch", help="cruises you are watching, and whether a sale is real")
    wsub = p_w.add_subparsers(dest="action")
    w_s = wsub.add_parser("sailing", help="watch a sailing you price by hand")
    w_s.add_argument("name", help='e.g. "Carnival Firenze, 7 nights W. Caribbean, Mar 14"')
    w_s.add_argument("--price", type=float, required=True,
                     help="the price you see, per person unless --total")
    w_s.add_argument("--total", action="store_true", help="the price is for both of you")
    w_s.add_argument("--nights", type=int)
    w_s.add_argument("--port", help="departure port, e.g. mobile, galveston, tampa")
    w_s.add_argument("--cabin", default="balcony", help="the cabin the price is for")
    w_s.add_argument("--url")
    w_p = wsub.add_parser("price", help="record today's price for a watched sailing")
    w_p.add_argument("id", type=int)
    w_p.add_argument("price", type=float)
    w_p.add_argument("--total", action="store_true", help="the price is for both of you")
    w_p.add_argument("--date", help="YYYY-MM-DD, if not today")
    w_f = wsub.add_parser("feed", help="watch the feeds for cruises that fit")
    w_f.add_argument("name")
    w_f.add_argument("--region", action="append",
                     help="caribbean, bahamas, mexican_riviera, alaska, mediterranean... (repeat)")
    w_f.add_argument("--min-nights", type=int)
    w_f.add_argument("--max-nights", type=int)
    w_f.add_argument("--max-all-in", type=float, help="ceiling on the party's all-in, USD")
    w_f.add_argument("--port-group", action="append", help="gulf, florida, or a port (repeat)")
    w_d = wsub.add_parser("drop", help="stop watching")
    w_d.add_argument("what", choices=["sailing", "feed"])
    w_d.add_argument("id", type=int)
    w_w = wsub.add_parser("sale", help="change the sale window")
    w_w.add_argument("--name")
    w_w.add_argument("--start", help="YYYY-MM-DD")
    w_w.add_argument("--end", help="YYYY-MM-DD")
    wsub.add_parser("list", help="what is watched, and what each price history says")
    p_w.set_defaults(func=cmd_watch)

    p_stats = sub.add_parser("stats", help="what the database has collected")
    p_stats.set_defaults(func=cmd_stats)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
