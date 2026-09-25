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

That registers a Windows Scheduled Task. Add `-Remove` to undo it.

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
| `score.py` | eight weighted components, each returning a value and its own explanation. |
| `faremodel.py` | the fare curve, alone in a module so the scorer and the baselines can share it without a cycle. |
| `baselines.py` | files observed prices as ratios at five levels of specificity, and corrects the curve where evidence supports it. |
| `store.py` | sqlite. Powers "new since last run" and banks the price history the baselines are built from. |
| `render.py` | one self-contained HTML file. No assets, no CDN, light and dark. |

### Layout

```
fw.py                  CLI: run, top, rejects, calibrate, stats
Farewatch.cmd          double-click launcher (refresh + open)
config/profile.example.json  the template, tracked
config/profile.json    who you are and what you want      <- copy and edit this (gitignored)
config/sources.json    the feeds, and why the dead ones are off
data/destinations.json generated cost/currency data
farewatch/             the package
tests/                 199 tests, fixtures are real captured feeds
tools/build_data.py    regenerates destinations.json
tools/check_fx.py      is the currency table still what the ECB publishes?
tools/claims.py        vendored; checks claims.json's counts against the source
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
of Los Angeles plus a $277 hop from home is still a $1,017 trip, and refusing to show it leaves you with an empty flight list
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
  A nonstop hop prices at the fare curve; one needing its own connection is
  marked up 35%, because fewer segments and more competition is the whole
  difference. Of 20 positioned flights in the last run, 11 were nonstop.
- **`max_positioning_usd` stops the nonsense.** Repositioning to Prague to catch
  a Prague-origin fare costs $873 a head and is never what you want. The ceiling
  drops it. Everything that survives is a domestic hop.

The **self-connect risk is surfaced, not priced.** Separate tickets mean a missed
connection is your problem, not the airline's, and no cost model should quietly
bury that in a number.

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

Five countries out of 150 have measured figures. Every other row in
`destinations.json` is hand-authored and unchecked, and the report says so on
each deal — `cost data measured 2026-08-29` or `cost data estimated, not
verified`. Of the 158 deals in the current run, 51 rest on measured data and 107
do not.

---

## What it doesn't do

Worth knowing before trusting a number:

- **Cost data is measured for five countries and guessed for 145.** The measured
  ones are marked in the report. The bet is that consistent relative error is
  harmless — validation showed that bet was partly wrong, because the errors were
  not consistent: they ran in opposite directions in rich and cheap countries.
- **Travel dates mostly aren't in the feeds.** `preferred_months` only fires when
  a headline names a month or season. Most don't.
- **The fare curve starts fitted by eye** (`FARE_BASE_USD + FARE_PER_KM ×
  distance`, times a cabin multiplier) and is corrected as history accumulates.
  Where no level has four observations yet it is still the bare straight line, so
  a "% below typical" figure is an estimate while "cheaper than N of M tracked"
  is a measurement. `fw.py run` prints which levels are ready.
- **No deal has been booked.** Fares, hotel rates and local prices have been
  checked against live listings, which is not the same as living through a trip
  at the quoted total. Airport transfers, baggage, seat fees, tips and the
  general friction of travel are in none of these numbers.
- **Trip length is often assumed.** Where a headline doesn't state nights, the
  value score is pulled toward neutral and the deal is labelled
  "duration assumed" rather than quietly ranked on a guess.
- **Currency history covers ~30 currencies**, being what the ECB publishes. For
  the rest the tailwind is simply unavailable and scores neutral.
- **Positioning fares are modelled, not quoted.** The hop from your base is the same
  eyeballed distance curve, times 1.35 when it needs its own connection. It is
  the right order of magnitude and it is not a real fare. Check the actual price
  before believing an all-in total.
- **`nonstop_from_base` goes stale on an airline schedule**, not on its own.
  It was correct in August 2026. Recheck it when routes change.
- **Self-connect risk is flagged, never priced.** Separate tickets mean a missed
  connection is your problem. No number in here accounts for that.
- **No award/points availability.** The good data there costs money.
