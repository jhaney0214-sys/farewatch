# Farewatch

**Status: live.** Refreshes daily via a Windows scheduled task, unattended. See [PRODUCTION.md](../PRODUCTION.md).

A travel opportunity tracker. It pulls public deal feeds — flights, hotels,
packages and cruises — works out what each deal would **actually** cost you once
currency and on-the-ground prices are counted, and ranks what survives against
your own profile.

No third-party packages. No API keys. No paid data. `python fw.py run`.

---

## The idea

The deal newsletters broadcast. They find a $340 fare to Lisbon and mail it to
two million people, most of whom can't fly those dates, don't live near that
airport, and aren't interested in Lisbon. Personalisation is the thing they
charge for, and even the paid tiers are shallow.

Farewatch inverts that. Every deal is scored against constraints you actually
have, and every score comes with its reasons attached:

```
3  71.4  flight  Los Angeles > Bangkok   $1,482  all-in $3,144
      est. 25% below typical · on your list · add $554 to reach Los Angeles
```

The second idea is that **the fare is the smaller half of the truth.** A $300
flight to Zurich and a $450 flight to Bangkok are not a $150 difference. On
measured prices, a week for two costs $4,027 on the ground in Zurich against
$1,108 in Bangkok — so the "expensive" fare is **$2,619 cheaper** to actually
take. No deal feed anywhere tells you that. This one ranks on it, and those
figures come from checked market data rather than an estimate (see
[What validation found](#what-validation-found)).

The third is **currency**. On-the-ground costs are the part of a trip exchange
rates actually move — the fare is already quoted in your own money. A country
whose currency has slid 15% against yours is 15% off on food, hotels and taxis
before any deal is applied. Farewatch compares today's rate to the trailing
year and folds the difference into the trip cost.

---

## Quickstart

Double-click **`Farewatch.cmd`**. It refreshes the feeds, re-ranks everything and
opens the report. Right-click it → Send to → Desktop to make a shortcut.

Or from a terminal:

```bash
python fw.py run --open
```

That fetches every source, ranks everything, writes `out/index.html` and opens
it. Other things you can do:

```bash
python fw.py top -n 20        # ranking in the terminal
python fw.py run --offline    # from cache, no network
python fw.py run --refresh    # ignore the 30-minute feed cache
python fw.py run --alert      # notify on new deals and price drops since the last --alert run
python fw.py stats            # what the database has collected so far
python fw.py rejects          # what the parser threw away, and why
python fw.py calibrate        # where observed prices disagree with the cost data
python -m unittest discover -s tests
```

To have it refresh itself every morning so the report is current before you open
it:

```bash
powershell -ExecutionPolicy Bypass -File tools\install_schedule.ps1 -At "07:00"
```

That registers a Windows Scheduled Task. Add `-Alert` to have each morning's
run notify you of new deals and price drops (see [Alerts](#alerts)), and
`-Remove` to undo it. Running it again replaces the existing task.

Then copy `config/profile.example.json` to `config/profile.json` and edit it,
which is the whole point of the thing. Your copy is gitignored, so your home
airports and budget stay on your machine; without one, every command falls back
to the example and says so.

| field | what it does |
|---|---|
| `home_cities`, `home_airports` | anywhere you'd actually fly out of, including airports you'd drive to. Flights from anywhere else get pushed down hard. |
| `travel_style` | `budget` / `mid` / `luxury`. Drives the food, lodging and local transport estimates. |
| `travelers` | party size. Changes both the total and how a per-person price is read. |
| `wishlist` | cities or countries, matched loosely. |
| `preferred_months` | deals naming a month or season outside these get demoted. |
| `max_trip_budget` | all-in, whole party, in `home_currency`. |
| `unreachable_origins` | `position` prices the hop to the deal's origin and ranks the honest total; `hide` drops those deals; `show` lists them unpriced. |
| `positioning` | Your base airport and the cities it reaches nonstop. See below. |
| `weights` | the eight scoring components. Retune freely. |

---

## Alerts

`python fw.py run --alert` compares the ranking with the one from the last
`--alert` run and tells you about two things only:

- **a new deal**: a route that was not there last time and scores at least
  `new_deal_min_score`;
- **a drop**: a route that was there last time, scoring at least
  `track_min_score`, whose best price fell by `drop_pct` percent or more.
  Flights compare on the fare; hotels, packages and cruises compare per night,
  so a 3-night offer after a 7-night one is not read as a 57% drop.

The first `--alert` run only records a baseline, so turning it on does not send
you the whole list. `--alert-dry-run` prints what would go out and sends and
saves nothing. State lives in `data/alerts-state.json` (gitignored); delete it
to start over.

Everything is set under `alerts` in `config/profile.json`; leave the block out
and these defaults apply:

```json
"alerts": {
  "new_deal_min_score": 68,
  "drop_pct": 15,
  "track_min_score": 50,
  "max_per_run": 5,
  "backends": ["toast"]
}
```

### Where an alert goes, and who else can read it

| backend | on by default | leaves this machine | reaches your phone |
|---|---|---|---|
| `toast` | yes | no | no |
| `email` | no | yes, to your mail provider | yes |
| `ntfy` | no | yes, to the ntfy server you name | yes, through the ntfy app |

The toast is a Windows notification shown by Windows PowerShell. Nothing is
sent anywhere, and it only shows on this PC. Clicking it opens the report.

The other two put trip data (destinations, prices, deal links) on someone else's
server, which is why neither runs until you add it to `backends` yourself.
What that trip data says about you, put together day after day, is when and
where you are thinking of being away from home.

- **ntfy** has no default server on purpose. On the public **ntfy.sh**, a topic
  is readable by anyone who knows or guesses its name. There is no account
  behind it. If you use ntfy.sh anyway, pick a long random topic and treat it
  like a password. A **self-hosted** ntfy server with access control avoids
  this; put its token in the `FAREWATCH_NTFY_TOKEN` environment variable.
  Plain `http://` is refused unless you set `"allow_http": true` for a server
  on your own network.

  ```json
  "backends": ["toast", "ntfy"],
  "ntfy": {"server": "https://ntfy.example.net", "topic": "farewatch-<long-random>"}
  ```

- **email** sends to yourself over SMTP, so only you and your own mail provider
  see it. The password is read from `FAREWATCH_SMTP_PASSWORD`, never from the
  profile. For Gmail that is an app password, not your account password. Port
  465 uses SSL; any other port uses STARTTLS.

  ```json
  "backends": ["toast", "email"],
  "email": {"host": "smtp.gmail.com", "port": 465,
            "user": "you@example.com", "to": "you@example.com"}
  ```

A backend that fails is logged and the others still run; `fw.py run` then
exits 3, which shows up as the scheduled task's last result. State is saved
either way, so a broken mail setup does not replay the same alert every day
once it is fixed.

---

## How it works

```
config/sources.json ──▶ feeds.py ──▶ parse.py ──▶ score.py ──▶ render.py ──▶ out/index.html
                                        │            │
                     data/destinations.json      fx.py (ECB + er-api)
                                                     │
                                        store.py (sqlite) ──▶ baselines.py
                                                     ▲               │
                                                     └───────────────┘
                                              observed prices correct the model
```

| module | job |
|---|---|
| `feeds.py` | fetch and cache RSS/Atom. One bad source never stops a run. |
| `parse.py` | headline → structured deal: kind, price, what the price covers, route, nights, cabin. Conservative — an unreadable deal is dropped, not guessed at. |
| `places.py` | 150 countries, 350 cities, 384 airport codes, 198 aliases. Resolves "Kyrgyzstan", "MCI" and "St. Maarten" alike. |
| `costs.py` | the all-in trip cost: deal + lodging + food + local transport, currency-adjusted. |
| `fx.py` | live rates for ~160 currencies, 1-year history for the ~30 the ECB publishes. |
| `positioning.py` | prices the leg that gets you to where the deal actually starts. |
| `dotfares.py` | reads DOT's average paid per US route, for the value note and its ceiling. |
| `score.py` | eight weighted components, each returning a value and its own explanation. |
| `faremodel.py` | the fare curve, alone in a module so the scorer and the baselines can share it without a cycle. |
| `baselines.py` | files observed prices as ratios at five levels of specificity, and corrects the curve where evidence supports it. |
| `store.py` | sqlite. Powers "new since last run" and banks the price history the baselines are built from. |
| `render.py` | one self-contained HTML file. No assets, no CDN, light and dark. |
| `alerts.py` | compares a run with the last one and notifies on new deals and price drops. Toast by default; email and ntfy only when you name them. |

### Layout

```
fw.py                  CLI: run, top, rejects, calibrate, stats
Farewatch.cmd          double-click launcher (refresh + open)
config/profile.example.json  the template, tracked
config/profile.json    who you are and what you want      <- copy and edit this (gitignored)
config/sources.json    the feeds, and why the dead ones are off
data/destinations.json generated cost/currency data
farewatch/             the package
tests/                 284 tests, fixtures are real captured feeds
tools/build_data.py    regenerates destinations.json
tools/build_positioning.py  measures what hops from your base cost (DOT fares; output gitignored)
tools/build_routes.py  what passengers paid on every big US city pair (DOT; tracked)
tools/check_fx.py      is the currency table still what the ECB publishes?
tools/components.py    the score's eight components, read-only, for Assay to audit
tools/docclaims.py     vendored docclaims v0.3.3; checks claims.json against the source
tools/install_schedule.ps1
.github/workflows/     runs the test suite on every push; publishes nothing
```

### Scoring

| component | default weight | asks |
|---|---:|---|
| `value` | 28 | how far below the expected price for this route/kind? |
| `reachable` | 18 | does it leave from an airport you'd use? |
| `affordable` | 15 | does the all-in total fit your budget? |
| `wishlist` | 12 | do you want to go there? |
| `fx` | 8 | is your money unusually strong there right now? |
| `fresh` | 8 | how long ago was it posted? |
| `timing` | 6 | does it travel in a month you'd travel? |
| `urgency` | 5 | is there a booking deadline? |

Every component is bounded 0–1 and carries its own note, so a score is always
auditable rather than a number to take on faith. `deal.trip["components"]` has
the raw values; `--json` writes them out.

---

## Positioning flights

Deal blogs post from the airports they post from, and for a mid-size city that
mostly means somewhere else. Measured from one regional airport and its three
drive-to alternates, **zero of 76 flights** in a typical pull departed from any of
the four. Hiding them is the obvious response and the wrong one — a $740 fare out
of Los Angeles plus a $489 hop from home is still a $1,229 trip, and refusing to show it leaves you with an empty flight list
while good deals go by.

So Farewatch prices the connecting leg and ranks the honest total:

```
Los Angeles → Bangkok    $1,482    all-in $2,998
   30% below typical · on your list
   add $554 to reach Los Angeles from <your base>
   separate tickets - a missed connection is on you
```

Two things keep this defensible rather than wishful:

- **Nonstop matters enormously.** A regional airport typically reaches the
  big hubs without a connection — the one this was built against reaches 18
  cities nonstop — and those hubs are exactly the cities the feeds post from.
  Of 20 positioned flights in one run, 11 were nonstop.
- **The hop is priced on what people paid, not on the deal curve.** See
  below: the curve was off by a factor of three.
- **`max_positioning_usd` stops the nonsense.** Repositioning to Prague to catch
  a Prague-origin fare costs $873 a head and is never what you want. The ceiling
  drops it. Everything that survives is a domestic hop.

The **self-connect risk is surfaced, not priced.** Separate tickets mean a missed
connection is your problem, not the airline's, and no cost model should quietly
bury that in a number.

### What a hop actually costs

Hops used to be priced on the fare curve, with a 35% markup when the hop needed
its own connection. The curve is fitted to deal-blog postings, the cheapest
fares anyone advertises, and a hop out of a regional airport is not a deal fare.
Measured against DOT's
[Consumer Airfare Report](https://data.transportation.gov/resource/yj5y-b2ir.json)
(Table 6: every city pair with 10+ passengers a day, free, no key) for one
regional base over 2025Q2–2026Q1:

| | median, measured ÷ curve | range |
|---|---|---|
| average paid, all carriers, 15 nonstop cities | 3.9× | 2.1–7.4× |
| average paid on each market's lowest-fare carrier | 3.25× | 1.1–7.4× |

A hop to Chicago the curve put at $120 averaged $368 on the cheapest carrier;
Atlanta, $77 against $571. The only markets near the line were the ones a
low-cost leisure carrier flies. So every positioned deal had been ranked on an
all-in total a few hundred dollars a head too low, and `max_positioning_usd`
could never fire on a domestic hop.

```
python tools/build_positioning.py
```

reads your `positioning.base`, finds its DOT market, and writes
`data/positioning_fares.json` (gitignored: it names your airport). From then on:

- a city DOT measured is priced at the **round-trip fare paid on that market's
  lowest-fare carrier**, passenger-weighted over the latest four quarters
  (DOT's fares are one-way with round trips halved, so the round trip is twice
  the figure). The card says `DOT average paid`.
- a city it did not is the curve times **your base's measured median**, marked
  `est. from DOT fares`. No connection markup on top: DOT's averages already
  include the connections people took.
- with no table, the old curve and markup, marked `est., unmeasured`.

A DOT market is matched to a city only when its distance agrees with ours within
15%, which is what tells Portland, Oregon from Portland, Maine; the tool prints
the markets it could not match. It is an average paid, not a quote; booked
early, a hop can come in under it. DOT publishes about two quarters behind; the
daily run rebuilds this table when a new quarter lands (see below).

On the day it was built, with the same cached feeds: 22 positioned deals became
15, the seven dropped being hops over the profile's own $600 ceiling (Dallas,
San Francisco, Seattle, Portland), and the top ten did not change. But a hop
moved a deal's score by only about a point, because the all-in total reached the
score only through `affordable` (15% of the weight) while `value`, the heaviest
at 28%, judged the fare alone.

### The hop dilutes the saving

So `value` now counts the hop. It is bought at market and carries no discount of
its own, so the dollars a fare saves are divided by the fare plus the hop:

```
discount = (expected - fare) / (expected + hop)
```

$300 off an expected $1,000 fare is 30%; with a $489 hop it is 20%. Only savings
dilute. Spread over a bigger trip an overpriced fare would look less overpriced,
which would have lifted two positioned deals by 19 and 27 places in the first
version, and a hop must never put a deal above the same fare from home. The
"est. % below typical" note says "counting the hop" when one is in it; "cheaper
than N of M tracked" stays a claim about the fare, because the tracked sample is
fares.

Same cache: the Philadelphia, Los Angeles and Miami deals that had sat at 19, 27
and 34 fell to 32, 54 and 58; no positioned deal rose; the top ten did not change.

### Driving to a bigger airport

`home_airports` has always meant airports you would drive to, but every hop was
priced from `base`, and a deal leaving from one of the others counted as leaving
from your door. Both were wrong, and against DOT's fares the first was expensive:
from one regional base, the cheapest carrier's average out of a hub one to four
hours' drive away beat the base's own on 19 of 20 big destinations, by a median
$228 a head (Denver: $241 from the nearer hub against $545 from the base).

So a hop is now the cheaper of two routes:

- **fly from `base`**, priced as above; or
- **drive to another home airport and fly from there**, at DOT's measured fare
  from that airport (never a modelled one: a guessed fare on a guessed drive is
  how a cheap total gets invented), plus the drive.

A drive is road miles (great-circle × 1.3, both ways) at `drive_cost_per_mile`
($0.25: fuel and wear, not the IRS rate, which carries costs you pay anyway),
plus `parking_per_day` ($15) for the trip's nights plus one. Both go in the
total. The choice also counts the hours, at `drive_hour_usd` ($20 for the party,
55 mph): nobody is billed for them, so they never reach the total, but a
seven-hour round trip to save $70 is not a saving. Without that, the first
version routed a Chicago hop through Atlanta to save $70 and the deal fell 39
places, because a hop through an alternate was also graded as a connection. It
is now graded as a nonstop hop, since the drive was already weighed. A deal
leaving straight from a drive-to airport costs the drive and parking, and no
separate-ticket warning.

The card says which:

```
add $916 to reach San Francisco via Atlanta (drive and park $213), DOT average paid
```

Same cache, one regional profile: 23 deals needed a hop where 17 had (six came
in under the `max_positioning_usd` ceiling once routed through a hub; San
Francisco went from $676 a head to $458), ten rose, none fell, and the top ten
did not change. DOT market labels now match with their state, which they had
not: alone, "Birmingham" is the English one, so every Birmingham, AL market had
been dropped.

### What passengers paid on the route

For a US domestic flight there is a measured market price, and the card now
quotes it instead of the curve's estimate:

```
United: Chicago – Los Angeles   $161
   62% under the $422 DOT average paid
```

`python tools/build_routes.py` writes `data/route_fares.json`: every
contiguous-state city pair in DOT's Table 6 (10+ passengers a day), latest four
quarters, matched to Farewatch's cities by the same 15% distance rule. 1,799
pairs; public data naming nobody, so it is tracked. The figure is the round
trip on each market's lowest-fare carrier, economy only; DOT's fares are
each-way ([DOT](https://www.transportation.gov/sites/dot.gov/files/2026-09/Domestic%20Airfare%20Consumer%20Report%202026q1.pdf)),
so a round trip is twice one, and a fare marked one-way is set against half.

It words the note and sets one ceiling; it is not the expected price. Of the 72
domestic economy deals in the history that DOT measured, the median was 0.41x
what the cheapest carrier averaged, so as an expectation it would score almost
every deal at the cap. The ceiling: **a fare within 15% of what people paid is
no deal**, and its value scores no better than neutral whatever the curve says.
That applied to 3 of the 72. On the day it was built, 5 of 211 ranked deals
carried the note (one, Miami to Las Vegas at $263 against $250, "about the DOT
average paid", where the curve had it as a deal) and no score moved: the cap had
nothing to hold down.

Neither table has to be rebuilt by hand. Once a week `fw.py run` asks DOT for
its newest quarter (one small request) and rebuilds a table that lacks it; the
per-base table is only refreshed, never created, since building it is a choice
about your base. A failed check changes nothing and is retried the next day.

### Setting your home base

Positioning needs two settings under `positioning` in your `config/profile.json`,
and nothing in the code assumes an airport — with no `base`, positioning legs are
simply not priced:

```json
"positioning": {
  "base": "DSM",
  "nonstop_from_base": ["ATL", "DEN", "DFW", "LAS", "ORD", "PHX"]
}
```

`base` is your home airport's IATA code. `nonstop_from_base` is every airport it
reaches without a connection, **across every carrier** — build it from the
"Airlines and destinations" table on your airport's Wikipedia page or from the
airport's own route map. Low-cost leisure carriers matter most here: their
seasonal routes are usually the cheapest hops on the list.

This list is typed by hand on purpose. BTS's free on-time file looks like it
could derive it, and for one regional airport it found 10 of 18 real nonstops:
carriers that don't report on-time data to BTS — the low-cost leisure airlines
and several United regionals — are invisible in it, and they are the routes a
small airport depends on.

`nonstop_from_base` is the one part of the model that goes stale on an airline's
schedule rather than on its own. Recheck it when routes change.

---

## Learning from what it has seen

The fare curve is a straight line through distance, fitted by eye. It is wrong
in absolute terms for any single route — it reads an ordinary New York to Punta
Cana fare as "37% above typical" because a straight line does not know Caribbean
routes price high.

Every run banks real prices in sqlite. `baselines.py` reads that back and
corrects the curve. Two decisions carry the whole thing.

### Observations are ratios, not prices

Keying on the exact route was the obvious approach and it does not work. A route
only gains an observation when a genuinely *different* offer appears on it, which
for a given city pair happens a handful of times a year. Measured on real data:
**26 of 27 routes had exactly one observation, and the correction never fired.**

So every observation is stored as `observed / modelled`. A ratio of 0.8 means
"20% under what the curve predicts" and means the same thing on a 900km hop as on
a 12,000km haul — which makes observations from *different* routes poolable. The
correction is then a multiplier on the curve rather than a replacement, so
route-specific shape survives and only the systematic error is removed.

### Coarser keys catch what finer ones miss

Each observation is filed at five levels at once. A lookup walks specific to
general and stops at the first level with enough evidence:

```
route  →  destination  →  destination country  →  distance band  →  cabin
```

Same data, before and after the change:

```
before:  0 baselines ready   (26 of 27 routes had a single observation)
after :  6 baselines ready   across country, distance, cabin and lodging levels
         48 of 150 deals now scored against observed history
```

The level is part of the claim, so the note says which evidence it rests on —
`cheaper than 15 of the 16 tracked in United States` is a different strength of
statement from `...on routes this length`, and you get told which one you have.

| observations at a level | weight |
|---:|---|
| 0–3 | none; fall through to a coarser level |
| 4 | 0.25 — crossing the bar counts for something |
| 5–11 | ramps with evidence |
| 12+ | 1.0, the observed ratio applies in full |

Ratios outside 0.15–6.0 are refused outright. That guard earns its keep: a Tulum
deal that parsed to 18× the local nightly rate was kept out of the median instead
of poisoning every lookup that reached that level.

### The trap this design avoids

Observed prices here are *deal* prices — a sample biased low by construction,
since nobody posts an average fare to a deal blog. That cuts two ways:

- **For judging a deal**, comparing against other deals is better than a guessed
  market rate, as long as the claim is framed as a percentile among tracked
  deals. It is, and the code never calls it a discount off retail.
- **For estimating a trip's cost**, deal prices are the wrong input entirely. If
  you book your own hotel alongside a flight deal you pay near market, not near
  promotional. So **nothing learned here feeds the cost model.** `costs.py` keeps
  using the hand-authored figures.

Which leaves those authored numbers needing their own check:

```bash
python fw.py calibrate
```

It compares observed medians against the authored cost data and reports the gaps.
It never edits anything — deals sitting somewhat below market is expected and
healthy; it is the extremes that mean an authored figure is wrong.

It earned its keep immediately. It flagged Bangkok hotels at ten times the
authored rate, which turned out to be a category landing page ("Thailand travel
offers and trip inspiration") priced as a hotel, and a *weeklong* $779 getaway
banked as a nightly rate. Both parser bugs, not data bugs. Then it flagged the
Maldives figure as too high — that one was real, skewed by resorts when the deals
that actually appear are local guesthouses, and `hotel_mid` went $220 → $150.

Lodging observations are normalised to one night before they are compared,
because averaging a weeklong stay with a nightly rate produced a $414 "typical
night" for Phuket, roughly eight times the real figure.

---

## Knowing what you threw away

About a third of feed entries never become deals. `fw.py rejects` groups them by
reason so you can tell correct rejection from a parser quietly rotting as a feed
drifts:

```
134 of 382 entries rejected (35%)

no price in the headline    63   travelzoo 38, reddit-awardtravel 23, ...
not a travel deal           60   travelzoo 60
destination not recognised  10   travelzoo 9, reddit-awardtravel 1
reads as news, not an offer  1   travelzoo 1
```

This paid for itself immediately. It found that Travelzoo files real hotel
getaways under `/local-deals/` — the phrase means "sold through a local
merchant", not "not travel" — so a Tulum resort and a Nutcracker ticket shared a
URL prefix and both were being discarded. It also surfaced 23 destinations the
place data was missing, from Hilton Head to the Galapagos. Fixing both took the
reject rate from 42% to 35% and added 27 deals.

A second read, on 2026-10-24, took 163 of 436 rejected (37%) to 147 (34%) and
added 14 deals. Nine places had real offers and no row (Knoxville, Chattanooga,
the Florida Keys, Biltmore Village, Carmel, Jupiter, Big Bear, the Berkshires,
Rhode Island). A bare "& more" had been taken for a roundup and threw out a
Norway cruise and a Tokyo trip. It also found three misreads among what was
kept: "$100 off" taken as a $100 stay, lift tickets taken as a hotel because the
title said "Resort", and "Resort stays" filed under Travelzoo's vacations ranked
28th as a cheap package week when it is $215 a night (now 184th). And the
command itself had been recording each look as a run, changing what the next
run called new; it no longer writes anything.

What remains rejected is genuinely unparseable: percentage-only offers with no
absolute price, award bookings quoted in points, and region-level cruise copy
("Europe river cruises") with no single destination.

---

## Free, forever, by design

Nothing here costs money to run, which was a hard constraint.

- **Data**: public RSS/Atom, fetched with a normal browser user agent and cached
  for 30 minutes. `api.frankfurter.dev` (ECB reference rates, with history) and
  `open.er-api.com` (breadth). No keys anywhere.
- **Currency history** covers only the ~30 currencies the ECB publishes, listed
  by hand in `fx.HISTORY_SYMBOLS` - a mirror of the service's own vocabulary,
  which had drifted by one currency before anybody looked. Check it against what
  the service currently lists:

  ```bash
  python tools/check_fx.py    # 0 in step, 1 drifted, 2 could not check
  ```

  **Exit 2 is not a pass**: an unreachable service says nothing about the table.
  A stale symbol silently vanishes from responses rather than erroring, which is
  why this needs running occasionally rather than waiting for a failure. The
  suite tests the comparison offline with a stub; this is the one that asks.
- **Cost data**: `data/destinations.json`, hand-authored and regenerated with
  `python tools/build_data.py`. Rebuilding it costs nothing and it never expires
  the way a paid feed would.
- **Hosting**: none needed. The report is built on your own machine - by hand,
  or each morning by the scheduled task above - into `out/`, which is
  gitignored. `.github/workflows/farewatch.yml` only runs the tests. It used to
  run Farewatch twice a day and publish `out/` to GitHub Pages, and stopped when
  the repository went public: the report is ranked against
  `config/profile.json`, so publishing it would broadcast your home airports,
  budget and wishlist. Pages now serves `docs/`, a static page about the project
  with nothing personal in it.

---

## Sources

Measured, not assumed. See `config/sources.json` for the full list including the
ones that are switched off and why.

| source | carries | notes |
|---|---|---|
| The Flight Deal | flights | The most structured feed of the lot. US origins. |
| Fly4Free | flights, hotels, packages | European origins, EUR/GBP. High volume. |
| Travelzoo | hotels, packages, cruises | The only reliable cruise source here. ~270 items/pull. |
| r/flightdeals | flights | Heavy on European business class. |
| r/awardtravel | flights | Mostly cash-free, so few rows survive parsing. |

Switched off: Cruise Fever and Cruise Hive are news sites, not deal feeds — one
priced item in twenty-nine between them. Secret Flying serves a Cloudflare
challenge instead of its feed. `r/travel_deals` is, despite the name, a coupon
and gift-card resale sub — one parseable item in twenty-five.

**No free feed covers Southeast US flight origins.** The 19 US-origin flights in
a typical pull are all coastal gateways; Atlanta, the busiest airport on earth,
appears zero times. That gap is why positioning exists — and it is also the
underserved niche a solo operator could own.

---

## Where the money would come from

Being straight about this: the build is the easy half, and none of it earns
anything on its own.

1. **Use it yourself first.** If the deals it surfaces are ones you'd actually
   book, the data is good enough to sell. If it's noise, you learned that for
   the cost of a weekend.
2. **Affiliate links.** Booking.com, Trip.com and Hostelworld approve small
   sites readily. `config/sources.json` has an `affiliate` field that is plumbed
   through and currently unused, so wrapping outbound links is a small change.
   Card affiliates pay far better and won't touch you without traffic.
3. **A paid personalisation tier**, once there's traffic to convert. This is
   exactly what Going.com charges $49/yr for.

Niche it hard. "Deals from Kansas City" beats "deals" for a solo operator,
because you can own that search term and the big newsletters won't bother.

---

## What validation found

Everything below was checked against real market data on 2026-08-29, after the
model had been built. Two of the three checks found it wrong.

### The fare: correct

Top-ranked deal, Asiana LAX-BKK, $741 roundtrip, sample dates Nov 5-12:

| | Farewatch said | Reality |
|---|---|---|
| fare | $741 per person | **$742** cheapest on those exact dates |
| verdict | "25% below typical" | Google: **"prices are currently typical"** |
| baseline | $990 expected | market sits at $742-772 |

The **parsing is validated** — price, route, cabin, roundtrip flag and even the
seven-night assumption were all right, the fare to within a dollar. The **value
judgement was wrong**: the same fare appears on a February 2027 search too, so it
is the going rate, not a sale.

The cause is structural. Fares scale sub-linearly with distance and the curve is
a straight line — short haul runs $0.129/km against $0.068 for long haul — so it
overestimates long routes badly. The constants were **not** refitted: seventeen
noisy deal prices and one verified fare is not enough to replace one eyeballed
number with another. Instead the claim now states its provenance, `est. 25% below
typical` from the curve versus `cheaper than 15 of the 16 tracked to Bangkok`
from observation. One is a guess, one is a measurement, and they no longer look
alike.

### The cost data: wrong in two directions at once

Hotel medians from Google Hotels listings, food and transport from Numbeo,
converted at the day's ECB rate:

| country | field | authored | measured | |
|---|---|---:|---:|---|
| US | hotel/night | $165 | **$105** | 57% high |
| US | dinner for two | $75 | **$104** | 28% low |
| JP | hotel/night | $95 | **$68** | 40% high |
| TH | taxi per km | $0.50 | **$1.05** | 52% low |
| TH | transit ticket | $0.60 | **$1.00** | 40% low |
| CH | hotel/night | $200 | **$157** | 27% high |
| TH, PT | hotel/night | — | — | accurate, unchanged |

The two large errors pulled in **opposite directions**, which is why they had
never produced anything obviously broken. The model was overstating what it costs
to sleep in rich countries while understating what it costs to get around cheap
ones — and both biases flattered exactly the comparison this project is built on.

Corrected, the effect on real rankings was material: Tokyo packages fell $659,
Los Angeles flights $359, and Bangkok packages rose up to $450.

### The premise: survives

Re-run on measured figures rather than assumed to hold:

```
7 nights, 2 travellers        fare    lodging     ground     ALL-IN
Zurich, $300 fare              600       1297       2730       4627
Bangkok, $450 fare             900        343        765       2008
```

The cheaper fare still costs $2,619 more to actually take. The gap narrowed once
the flattering errors were removed, which is what an honest correction should do,
and it is still far too large to be an artefact.

### What is still unverified

**Checked for being out of line, 2026-10-13, which is not the same as measured.**
`python tools/check_costs.py` sets every hand-written row against the World
Bank's price level for that country (its PPP conversion factor over the
exchange rate; 143 of the 150 countries have one). Across countries the
written figures follow the price level: r² 0.75 for food, 0.74 for getting
around and 0.70 for a hotel night. Five unmeasured rows sit more than a factor
of two off a line and are the first to look at: Nigeria (every part two to
three times what its price level implies), Egypt and Bulgaria (too dear),
Haiti (well under half) and the Seychelles' hotels. Nigeria and Egypt both
devalued sharply in 2023-24, and a dollar figure recalled from before that
would read too high; that is a guess at the cause, not a finding. Nothing was changed: the
check cannot tell a wrong row from a real exception, and the measured
countries miss the same lines by up to a factor of two (Bangkok's taxis and
transit). The output is in `notes/cost-check-2026-10-13.txt`.

Five countries out of 150 have measured figures. Every other row in
`destinations.json` is hand-authored and unchecked, and the report says so on
each deal — `cost data measured 2026-08-29` or `cost data estimated, not
verified`. Of the 158 deals in the current run, 51 rest on measured data and 107
do not.

---

### The score, audited as an index (2026-10-19)

```bash
python tools/components.py
python ../Assay/ax.py audit out/components.json
```

A deal's score is a weighted sum of eight components, which is the shape of
index [Assay](../Assay) tests, so it was asked the same questions. The export
runs the pipeline from cache and stops before `store.sync`, so it never
changes what the next alert calls new; the database's hash is the same
before and after. Over the 272 deals in the cache that day:

- **Three components barely vary.** `urgency` was 0.5 for 271 deals (a
  deadline was found once), `timing` 0.6 for 98% (no month in the title; summaries now
  add dates for about one deal in ten, see below) and
  `reachable` 0.55 for 86% (no stated departure city, which is most hotels,
  cruises and packages). Those are deliberate neutral defaults, and leaving
  out `timing` or `urgency` moves no deal's rank. But they carry 29% of the
  weight, `reachable` the second-heaviest at 18%, so in practice they add
  about the same amount to every score. **The alert thresholds are absolute
  scores** (`new_deal_min_score` 68, `track_min_score` 50), so they were set
  with that constant inside them: if the feeds began carrying deadlines or
  months, every score would shift and the alerts with them, with no deal
  better than before. Not changed; it is a design choice, now visible.
- **The ranking leans on `affordable` more than on `value`.** Leaving out
  `affordable` (15% of the weight) moves the median deal 32 places; leaving
  out `value`, the heaviest at 28%, moves it 29.
- **Ranks are weight-sensitive.** Under small disagreements about the
  weights, the median deal's rank spans 42% of the field, and an average
  draw changes 4 of the top 10. A difference of a few places is not a
  difference between deals.
- The eight are eight things: the first component holds 20% of the variance
  and nothing resolves into fewer named dimensions. `reachable` and `urgency`
  correlate negatively with the total.

`out/` is gitignored, so the export and the audit stay on this machine.

## What it doesn't do

Worth knowing before trusting a number:

- **Cost data is measured for five countries and guessed for 145.** The measured
  ones are marked in the report. The bet is that consistent relative error is
  harmless — validation showed that bet was partly wrong, because the errors were
  not consistent: they ran in opposite directions in rich and cheap countries.
- **Travel dates mostly aren't in the feeds.** `preferred_months` fires when a
  headline names a month or season, or a summary states a date: a range
  ("November–February"), "through March", or a month beside a day or year.
  Headlines named a month for 10 of 273 deals; summaries add 26, read by hand
  and all correct. A bare month or season in a summary is ignored, because there
  it is as often a resort ("Ocean Coral Spring"), the past ("since July") or
  what to avoid ("dodge the peak summer crowds"). A window a year or more long
  ("through October 2027") says nothing and stays neutral. About nine deals in
  ten still name no dates.
- **The fare curve starts fitted by eye** (`FARE_BASE_USD + FARE_PER_KM ×
  distance`, times a cabin multiplier) and is corrected as history accumulates.
  Where no level has four observations yet it is still the bare straight line, so
  a "% below typical" figure is an estimate while "cheaper than N of M tracked"
  and, on a US domestic route, "under the $X DOT average paid" are measurements. `fw.py run` prints which levels are ready.
- **No deal has been booked.** Fares, hotel rates and local prices have been
  checked against live listings, which is not the same as living through a trip
  at the quoted total. Airport transfers, baggage, seat fees, tips and the
  general friction of travel are in none of these numbers.
- **Trip length is often assumed.** Where a headline doesn't state nights, the
  value score is pulled toward neutral and the deal is labelled
  "duration assumed" rather than quietly ranked on a guess.
- **Currency history covers ~30 currencies**, being what the ECB publishes. For
  the rest the tailwind is simply unavailable and scores neutral.
- **Positioning fares are averages paid, not quotes.** With
  `tools/build_positioning.py` run, a hop is what DOT measured passengers paying
  on the cheapest carrier, about two quarters ago. Without it, the hop is the
  deal-fitted curve, which measured about a third of the real price. Check the
  actual fare before believing an all-in total.
- **`nonstop_from_base` goes stale on an airline schedule**, not on its own.
  It was correct in August 2026. Recheck it when routes change.
- **Self-connect risk is flagged, never priced.** Separate tickets mean a missed
  connection is your problem. No number in here accounts for that.
- **No award/points availability.** The good data there costs money.
