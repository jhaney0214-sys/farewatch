"""Export the ranking's components so Assay can audit Farewatch's own score.

    python tools/components.py            # writes out/components.csv and .json
    python ../Assay/ax.py audit out/components.json

A deal's score is a weighted sum of eight 0..1 components (score.py's
DEFAULT_WEIGHTS, overridden by the profile): exactly the shape of index Assay
tests. So the questions it asks of EPI apply here. Are the eight components
eight things, or fewer? Which one does the ranking actually lean on, against
the weights? How far would a deal's place move if the weights were argued
differently?

**Read-only.** `fw.py run` and `fw.py top` both end in store.sync, which
records what has been seen and so decides what the next alert calls new. This
runs the same steps from cache and stops before that, so it can be run at any
time without changing tomorrow's alert. It writes only to out/, which is
gitignored: the ranking reflects one person's profile.
"""

import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from farewatch import baselines, feeds, fx, parse, score, store  # noqa: E402
import fw  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "components.csv"))
    args = ap.parse_args()

    profile = fw.load_profile(None)
    sources = feeds.load_sources(None)
    entries, _errors = feeds.collect(sources, max_age=feeds.DEFAULT_MAX_AGE,
                                     offline=True, log=lambda m: None)
    rates = fx.load(offline=True, log=lambda m: None)
    deals, _rejects = parse.build_all(entries)
    conn = store.connect()
    try:
        history = baselines.load(conn)          # read only; nothing is synced
    finally:
        conn.close()
    ranked = score.rank(deals, profile, rates, history)
    if not ranked:
        raise SystemExit("no deals in the cache; run fw.py once first")

    names = list(ranked[0].parts)
    weights = dict(score.DEFAULT_WEIGHTS)
    weights.update(profile.get("weights") or {})
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        # The score on the components' own 0..1 scale (score.py prints it out
        # of 100), so Assay's recomputation compares like with like.
        w.writerow(["deal"] + names + ["score"])
        for d in ranked:
            label = "%s [%s]" % ((d.title or "")[:60], d.fingerprint[:8])
            w.writerow([label] + [d.parts[n] for n in names] + [d.score / 100.0])
    spec = {
        "name": "Farewatch deal score, %d deals" % len(ranked),
        "data": os.path.basename(args.out),
        "entity_col": "deal",
        "score_cols": names,
        "published_col": "score",
        "weights": {n: weights.get(n, 0) for n in names},
        "claimed_dimensions": len(names),
        "aggregation_form": "linear",
        "orient": True,
        "source": "Farewatch score.py over the cached feeds (tools/components.py)",
        "note": ("Eight components weighted by score.DEFAULT_WEIGHTS and the "
                 "profile. claimed_dimensions is the component count: the score "
                 "treats them as eight separate considerations."),
    }
    with open(args.out.replace(".csv", ".json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2)
        fh.write("\n")
    print("%d deals, %d components written to %s" % (len(ranked), len(names), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
