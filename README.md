<div align="center">

<img src="tarkov_raidbrief/logo.png" alt="Tarkov Raid Brief" width="420">

### Home Assistant add-on repository

**"What do I bring to which map?" for Escape from Tarkov** — on your phone or
second monitor while you're in the stash picking a loadout.

[![Build add-on images](https://github.com/KarlisKocins/tarkov-raidbrief/actions/workflows/builder.yaml/badge.svg)](https://github.com/KarlisKocins/tarkov-raidbrief/actions/workflows/builder.yaml)
[![GitHub release](https://img.shields.io/github/v/release/KarlisKocins/tarkov-raidbrief?include_prereleases&sort=semver)](https://github.com/KarlisKocins/tarkov-raidbrief/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Supports aarch64](https://img.shields.io/badge/aarch64-yes-green.svg)
![Supports amd64](https://img.shields.io/badge/amd64-yes-green.svg)

[![Add repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FKarlisKocins%2Ftarkov-raidbrief)

[Install](#install) · [Options](#options) · [How it works](#how-it-works) ·
[Documentation](tarkov_raidbrief/DOCS.md) · [Changelog](CHANGELOG.md)

</div>

---

## Overview

This repository contains one Home Assistant add-on:

| Add-on | Version | Description |
|---|---|---|
| [**Tarkov Raid Brief**](tarkov_raidbrief) | ![version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FKarlisKocins%2Ftarkov-raidbrief%2Fmain%2Ftarkov_raidbrief%2Fconfig.yaml&query=%24.version&label=%20&color=41bdf5) | Per-map raid brief driven by your live task progress. |

It joins your live task progress from **TarkovTracker** (fed automatically by
TarkovMonitor) with task data from **tarkov.dev**, and gives you a per-map
brief: what to **carry in**, which **keys** you need, what to **bring out**, and
what to actually **do**.

- **Per-map packing lists** — CARRY IN, KEYS, BRING OUT and DO, built only from
  the tasks you can actually take right now, and only from the parts of them
  you have **not already done** — a counted objective reads "Bandage x3 (2/5
  done)", and a finished one takes its key off the list with it.
- **Tickable checklist** — ticks are saved per map in your browser and survive
  reloads.
- **"Run next" ranking** — a deterministic score (finishable-task XP, discounted
  partial XP, a Kappa bonus, a per-key penalty), with the breakdown on screen.
- **Extracts, per map** — every exit a PMC can use, switch-gated ones marked
  and any exit a task names pulled to the front. Plus raid length, lobby size
  and boss spawn chances.
- **Trader standing estimated from your completed tasks** — the tasks you have
  handed in say how much reputation they paid, so the panel can suggest each
  trader's loyalty level instead of making you type ten of them. Offered
  behind a button, never applied on its own.
- **Availability that matches TarkovTracker**, including the community
  [data overlay](#the-data-overlay--why-raw-tarkovdev-is-not-enough) the tracker
  itself applies — so the list doesn't show quests you can't take. The one gate
  nobody can check is the 1.x
  [trader-progression requirement](#its-showing-tasks-i-cant-take); tasks
  carrying one are listed with a dot rather than silently vouched for.
- **Ingress-native** — appears in the HA sidebar and the companion app, no port
  to open.
- **Offline-tolerant** — task data and your last good progress snapshot are
  cached to disk and survive restarts; upstream failures become banners, not
  stack traces.
- **Optional AI route advice**, off by default and confined to a block that can
  never touch your packing lists.

Read-only and public-API only. No game memory reading, no injection, no overlay,
no writes back to TarkovTracker.

<details>
<summary><b>Contents</b></summary>

- [Install](#install)
  - [Getting a TarkovTracker token](#getting-a-tarkovtracker-token)
  - [Trader loyalty levels](#trader-loyalty-levels)
- [Options](#options)
  - ["It's showing tasks I can't take"](#its-showing-tasks-i-cant-take)
  - ["It's showing tasks I have already done"](#its-showing-tasks-i-have-already-done)
- [AI route advice (optional)](#ai-route-advice-optional)
- [How it works](#how-it-works)
  - [Data sources — read this if tasks won't load](#data-sources--read-this-if-tasks-wont-load)
  - [The data overlay](#the-data-overlay--why-raw-tarkovdev-is-not-enough)
  - [How Ingress is handled](#how-ingress-is-handled)
  - [Data handling](#data-handling)
  - [Schema fragility (the GraphQL fallback)](#schema-fragility-the-graphql-fallback)
- [Development](#development)
  - [Debugging via the direct port](#debugging-via-the-direct-port)
  - [Tests](#tests)
  - [Building the image yourself](#building-the-image-yourself)
  - [Releasing a new version](#releasing-a-new-version)
  - [Repository layout](#repository-layout)
- [Non-goals](#non-goals)
- [Support](#support)
- [Credits](#credits)
- [License](#license)

</details>

---

## Install

This is a Home Assistant **add-on repository**. Images are pre-built for
`aarch64` and `amd64` by GitHub Actions and published to GHCR, so Home Assistant
just downloads one — nothing is compiled on your HA Green.

1. **Settings → Add-ons → Add-on Store**
2. **⋮ (top right) → Repositories**
3. Add:

   ```
   https://github.com/KarlisKocins/tarkov-raidbrief
   ```

4. Close the dialog, then find **Tarkov Raid Brief** in the store and click
   **Install**.
5. Set `tarkovtracker_token` in the **Configuration** tab (see below), then
   **Start**.
6. Open it from the sidebar (**Raid Brief**) or the companion app.

> The GHCR package must be public for step 4 to work. After the first successful
> CI run, go to the package on GitHub → **Package settings** → **Change
> visibility** → **Public**. Do this once per architecture package.

### Getting a TarkovTracker token

1. Sign in at [tarkovtracker.org](https://tarkovtracker.org).
2. **Settings → API Tokens → Create.**
3. Give it the **`get progression`** permission (that's all this add-on needs —
   it never writes).
4. Copy the token into the add-on's `tarkovtracker_token` option.

Without a token the add-on still runs; it just shows every task as if for a
maxed character, with a banner saying so.

### Trader loyalty levels

The progress API does **not** expose trader loyalty levels, so you tell the
add-on yourself, in the **TRADER STANDING** panel at the top of the page. Click
a pip and the brief rebuilds; each trader shows how many otherwise-ready tasks
their standing alone is holding back, which is the number that tells you who to
level next. Your answers are kept in `/data/standing.json` and survive restarts
and updates; **Reset** goes back to the `trader_levels` in the Configuration
tab, which are now just the starting values.

Since 1.7.0 the panel **estimates the levels for you**. Tasks say how much
reputation they pay on hand-in, so the ones TarkovTracker records as complete
add up to a reputation figure, and each trader's own loyalty tiers turn that
into a level — shown beside each trader, with **Use estimate** to apply the
whole roster at once. It is a suggestion rather than an answer, for three
reasons worth knowing before you trust it:

- loyalty also needs **roubles spent** with the trader (`requiredCommerce`),
  which neither API reports, so the estimate can read one tier high;
- **EOD and Unheard** editions start above zero reputation, which it cannot see;
- **Fence is excluded** — their standing comes from scav karma, not tasks.

Applying it writes ordinary overrides, so you can correct any trader afterwards
by clicking a pip, and **Reset** still clears the lot.

**Set these to your real levels.** Since 1.4.0 the overlay supplies a loyalty
requirement for roughly half of all tasks, so these values genuinely change what
you see — leaving everything at the default `1` hides every task gated behind
LL2–4, and the add-on shows a banner when it notices. A trader you can't
configure (the BTR Driver has no loyalty levels) never hides anything.

Reputation gets its own field, for the traders a task actually compares
reputation against — Fence and Lightkeeper today. It stays blank and
unenforced until you fill it in, deliberately: several of those requirements
want your standing *below* a threshold (the "Compensation for Damage" chain
needs Fence to dislike you), so assuming 0.00 would hide tasks one way or the
other on a number you never gave.

---

## Options

| Option | Type | Default | Meaning |
|---|---|---|---|
| `tarkovtracker_token` | password | — | Token with `get progression`. |
| `game_mode` | `regular` \| `pve` | `regular` | Which mode's tasks and progress to show. |
| `refresh_minutes` | 5–1440 | `60` | How often to poll TarkovTracker in the background. |
| `kappa_only` | bool | `false` | Show only Kappa-required tasks. Also toggleable in the UI. Ignored while tarkov.dev's `kappaRequired` flag is degraded — the add-on says so on screen. |
| `trader_levels.*` | 1–4 | `1` | Starting loyalty level per trader. The TRADER STANDING panel takes over once used; these become what **Reset** restores. |
| `excluded_maps` | list | `[]` | Maps to hide entirely, e.g. `Icebreaker`. Useful for event maps or ones you have not unlocked. Hidden before ranking, so they can't win "Run next". |
| `gemini_api_key` | password | — | Optional. Enables AI route advice. Empty = no AI and no third-party calls. |
| `gemini_model` | list | `gemini-2.5-flash` | Which Gemini model to use. The flash models have a free tier. |

`game_mode` maps to `regular`/`pve` on tarkov.dev and `pvp`/`pve` on
TarkovTracker — the two APIs name the same thing differently, and the add-on
translates.

### "It's showing tasks I can't take"

Look for a **dot** beside the task name. The 1.x trader rework gates much of
the task tree behind per-trader progression, carried in the data as
`otherRequirements` — 173 of the 516 live tasks have one, more than have a
trader loyalty requirement. Nothing publishes how far along each trader you
are: TarkovTracker's progress API returns tasks, objectives, hideout, level,
edition and faction and no global variables, and the 27 variable ids appear
nowhere in the data overlay or in TarkovTracker's own feed. So the add-on
cannot check those gates. It lists the task and marks it, rather than hiding
something you might be able to take. A dotted task missing in game is that
gate.

### "It's showing tasks I have already done"

Almost always `game_mode`. It defaults to `regular`, which polls TarkovTracker
for your **PVP** character; if you play PVE, what comes back is an untouched
account — level 1, nothing completed — and the brief dutifully lists the whole
early task tree. It looks like a broken add-on rather than a wrong setting,
which is why the page now says so directly: a token that reads fine but
reports zero completed tasks raises a banner naming the mode it asked for.

Check the header chips first — `Lv` and `N done` are what TarkovTracker
actually returned. If they aren't your character, either the mode is wrong or
the token belongs to a different TarkovTracker account than the one you browse.

To see both modes side by side:

```bash
export TARKOVTRACKER_TOKEN='...'      # the same token the add-on uses
python3 tools/tracker-doctor.py
```

It prints level, faction and completed-task counts for `pvp` and `pve` and
names the `game_mode` to set. The token is read from the environment, never
printed, and the call is a plain read that cannot alter your account.

---

## AI route advice (optional)

Off by default. Set `gemini_api_key` (get one at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)) to add a
per-map route briefing and a one-line explanation of the "Run next" pick.

Two things are deliberate:

- **It only generates when you press the button.** Nothing runs on startup, on
  the poller, or on page load, so it cannot burn quota unattended. Answers are
  cached against your current tasks, so re-asking an unchanged map is free;
  *Regenerate* forces a fresh call.
- **It can never touch your packing lists.** The model is allowed to use its own
  Tarkov knowledge — that is what makes the advice useful, and it is also why it
  is sometimes wrong. It is confined to a labelled block *below* CARRY IN /
  KEYS / BRING OUT and cannot alter them. Those come from live game data only,
  so a hallucinated key can never end up on your checklist.

The **"Run next" recommendation itself is not AI.** It is a deterministic score
(finishable-task XP, discounted partial XP, a Kappa bonus, a per-key penalty)
computed in `app/recommend.py`, with the breakdown shown on screen. AI only
writes the sentence explaining it.

Enabling this sends your task progress and player level to Google, which is a
change from the add-on's otherwise strict "tarkov.dev and TarkovTracker only"
policy. Leave the key empty to keep that guarantee.

---

## How it works

### Data sources — read this if tasks won't load

Task data comes from **`json.tarkov.dev`**, not the GraphQL API. The GraphQL
endpoint (`api.tarkov.dev/graphql`) has been returning
`{"errors":["GraphQL server unavailable. Try again later."]}` continuously since
2026-07-21 — see [tarkov-api#474](https://github.com/the-hideout/tarkov-api/issues/474),
still open at the time of writing. A maintainer's answer on that issue:

> "The GraphQL API is down for the moment, but you have the Json API who alive
> (https://json.tarkov.dev/endpoints). Tarkov.dev is based on this Json API and
> not on the GraphQL."

So the add-on reads the JSON API first and falls back to GraphQL automatically
if it ever returns. Nothing to configure either way.

The JSON API is harder to consume — it is unresolved (every reference is a bare
id) and untranslated (a task's `name` is literally `"657315... name"`). The
add-on fetches items/maps/traders alongside tasks, joins the ids, and resolves
text via the sibling `<path>_en` files, using the same `lang[value] ?? value`
rule the tarkov.dev site uses.

### What comes from where

Both upstreams send more than the brief used to read, and 1.7.0 spends the
bytes that were already being downloaded:

| Feature | Source | Cost |
|---|---|---|
| Objectives already done, partial counts | `taskObjectivesProgress`, in the same `/progress` response as the task records | none — same request |
| Extracts, bosses, raid length, lobby size | the `maps` dataset, already fetched to resolve map names | none — same request |
| Trader standing estimate | `finishRewards.traderStanding` in the `tasks` dataset | none — same request |

Objective ids are shared between the two APIs — TarkovTracker records progress
against the same `objectives[].id` tarkov.dev publishes — which is what makes
the join a dictionary lookup rather than a heuristic. Extract names are matched
the same way: a task's `exitName` and a map's extract name are the same
translation key resolved by two different language files.

### The data overlay — why raw tarkov.dev is not enough

tarkov.dev's task data is wrong in ways that decide availability, and
TarkovTracker does not consume it raw: it pipes every response through
[`tarkov-data-overlay`](https://github.com/tarkovtracker-org/tarkov-data-overlay),
a community-maintained patch file. This add-on does the same, because the gap
is not marginal — json.tarkov.dev ships **17** trader loyalty requirements
across all 510 tasks, and the overlay adds **247** more. Without it, A Shooter
Born in Heaven looks like it needs nothing when it actually needs Mechanic LL4.

The overlay also retires the 32 quests BSG has removed from the game (Rite of
Passage, Farming - Part 2, Signal Parts 3 and 4, …) and corrects task names and
XP values. It is fetched hourly on its own clock, so a correction lands without
waiting out the 24-hour task cache, and is cached to `/data/overlay.json`. If
it cannot be fetched at all the add-on says so in a banner and falls back to
raw tarkov.dev data, which over-reports.

Two gates exist in neither source and are hardcoded, exactly as TarkovTracker
hardcodes them: traders that do not exist until a quest is done (BTR Driver
needs A Helping Hand, Lightkeeper needs Getting Acquainted), and A Helping
Hand's own level 20 / Saving the Mole requirement.

### How Ingress is handled

Ingress serves the add-on under a generated path prefix and passes it in the
`X-Ingress-Path` header. Emitting absolute URLs (`/api/brief`, `/static/app.css`)
would 404 inside HA while working fine on the direct port.

**This add-on uses relative URLs throughout the frontend, and nothing else.**
Every `href`, `src` and `fetch()` in the page is relative (`static/app.css`,
`fetch("api/refresh")`), so they resolve correctly under the ingress prefix
*and* on the direct port with no server-side rewriting.

It deliberately does **not** set Starlette's `root_path` from `X-Ingress-Path`,
which is the obvious-looking alternative and is actively broken here. HA strips
the prefix before proxying, so requests arrive as plain `/static/app.css`. If
you set `root_path`, `Mount` appends `/static` to it and then tries to strip
that combined prefix from a path that no longer has it — the strip fails and
**every static asset 404s**, while the HTML still renders. It fails as an
unstyled page rather than an obvious error, which makes it easy to ship. This
was reproduced and removed; don't add it back.

### Data handling

- The joined task dump is cached to `/data/tasks.json` with a **24h TTL** — it
  is several MB across four endpoints and only changes on patch day. It survives
  add-on restarts. If tarkov.dev is unreachable the cached copy is served with a
  staleness banner rather than erroring out.
- TarkovTracker is polled **no more than once a minute**, with the `ETag` stored
  and sent as `If-None-Match`; `304` responses are handled. Polling happens on a
  background task on your `refresh_minutes` schedule — never on a page load.
- The last good progress snapshot is persisted to `/data/progress.json`, so a
  restart shows your data immediately instead of a blank page.
- `401` (bad token) and `429` (rate limited) become clear banners in the UI, not
  stack traces.

### Schema fragility (the GraphQL fallback)

This applies to the GraphQL path, which is currently only the fallback — but it
is what will run if `api.tarkov.dev/graphql` comes back.

The schema moves between patches, so the query is assembled from named optional
blocks (`requiredKeys`, `zones`, `shootDetail`, `questItemLocations`). If the
full query is rejected, the add-on drops one block at a time and retries,
logging exactly which block went. Worst case you lose the KEYS section; you
never lose the app.

One trap worth recording: **`requiredKeys` lives on the concrete objective
types, not on the `TaskObjective` interface.** Requesting it at interface level
fails the entire query. It must go inside each inline fragment, and only on the
seven types that have it (`Basic`, `Extract`, `Item`, `Mark`, `QuestItem`,
`Shoot`, `UseItem` — not `BuildItem`). `TaskObjectiveBasic` matters most: it is
the catch-all that `visit` resolves to, and 28 `visit` objectives carry keys.

A schema introspection call runs on first fetch and logs which optional fields
are actually present, including whether `tasks()` accepts `gameMode`.

---

## Development

### Debugging via the direct port

Port `8099` is exposed as well as Ingress. Set it in the add-on's **Network**
tab (e.g. to `8099`), then:

```bash
curl -s http://homeassistant.local:8099/health | jq
curl -s http://homeassistant.local:8099/api/brief | jq '.player, .warnings'
curl -s 'http://homeassistant.local:8099/api/brief?map=customs' | jq '.maps[0].carry'
curl -s -X POST http://homeassistant.local:8099/api/refresh | jq
```

To check the Ingress path handling without HA:

```bash
curl -s http://homeassistant.local:8099/ -H 'X-Ingress-Path: /api/hassio_ingress/test' \
  | grep -oE '(href|src)="/[^"]*"'    # should print nothing
```

#### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | The page. Accepts `?map=` and `?kappa_only=`. |
| `GET /api/brief` | Full brief as JSON. Optional `?map=` and `?kappa_only=`. |
| `POST /api/refresh` | Force-refresh both upstreams and bust the task cache. |
| `POST /api/trader-standing` | Set standing. Body `{"levels": {...}}`, `{"reputations": {...}}`, `{"apply_derived": true}` to take the estimate, or `{"reset": true}`. |
| `GET /health` | Liveness. Makes no upstream calls. |

### Tests

Aimed at the ways this app can rot between patches, plus the arithmetic that
decides what you see:

```bash
pip install graphql-core

# Every rung of the query fallback ladder is a valid document, checked against
# the real published schema. Offline; uses a vendored copy of the SDL.
python3 tests/test_query_validates.py
python3 tests/test_query_validates.py --update    # refresh the vendored SDL

# Every objective type in the live task dump is explicitly classified as
# carry / loot / non-raid. Fails if a patch adds a type we'd silently mishandle.
python3 tests/test_objective_coverage.py

# TarkovTracker's availability rules: branches, "active" requirements,
# retired prerequisites, trader-unlock gates. Offline.
python3 tests/test_availability.py

# Objective-level progress, the extract panel and the standing estimate:
# what gets filtered, what gets counted, and what is deliberately excluded
# (scav exfils, Fence's reputation). Offline.
python3 tests/test_progress_and_standing.py
```

The objective-type one caught two real types (`dialogue`, `globalVariable`)
that would otherwise have shown up as fake "things to do" on every map.

### Building the image yourself

CI does this for you on every version bump, but to verify a build locally:

```bash
# aarch64 (what the HA Green runs). Needs QEMU on a non-ARM host:
docker run --privileged --rm tonistiigi/binfmt --install arm64

cd tarkov_raidbrief
docker build \
  --build-arg BUILD_FROM=ghcr.io/home-assistant/aarch64-base-python:3.12-alpine3.20 \
  --build-arg BUILD_ARCH=aarch64 \
  --build-arg BUILD_VERSION=1.0.0 \
  --build-arg BUILD_NAME="Tarkov Raid Brief" \
  --build-arg BUILD_DESCRIPTION="Per-map Tarkov raid brief" \
  --platform linux/arm64 \
  -t local/tarkov-raidbrief-aarch64:1.0.0 .
```

Run it outside Home Assistant (bashio needs the Supervisor, so pass env vars and
uvicorn directly):

```bash
docker run --rm -p 8099:8099 -v "$PWD/testdata:/data" \
  -e RAIDBRIEF_DATA_DIR=/data \
  -e RAIDBRIEF_TOKEN="your-token" \
  -e RAIDBRIEF_GAME_MODE=regular \
  --entrypoint python3 local/tarkov-raidbrief-aarch64:1.0.0 \
  -m uvicorn app.main:app --host 0.0.0.0 --port 8099 --app-dir /app
```

### Releasing a new version

CI publishes only when `tarkov_raidbrief/config.yaml`'s `version` changes, so an
ordinary code push can't silently overwrite a released tag.

1. Bump `version` in `tarkov_raidbrief/config.yaml`.
2. Add a `CHANGELOG.md` entry (both copies — the root one and the add-on's).
3. Push to `main`. The workflow builds both arches and pushes to GHCR.
4. In HA: **⋮ → Check for updates** in the Add-on Store.

### Repository layout

```
.
├── repository.yaml                 # marks this as an HA add-on repository
├── .github/workflows/builder.yaml  # builds + pushes both arches to GHCR
├── tests/                          # offline checks + one live schema probe
├── tools/tracker-doctor.py         # which game mode holds your progress
└── tarkov_raidbrief/               # the add-on itself
    ├── config.yaml  Dockerfile  build.yaml  run.sh  requirements.txt
    ├── DOCS.md                     # rendered as the add-on's Documentation tab
    ├── icon.png  logo.png          # shown in the HA Add-on Store
    ├── translations/en.yaml        # option labels in the Configuration tab
    └── app/
        ├── main.py       # FastAPI entrypoint, ingress handling, background poller
        ├── tarkovjson.py # JSON API client (primary): id joins + translations
        ├── tarkovdev.py  # GraphQL client (fallback), composable query, disk cache
        ├── tracker.py    # TarkovTracker client, ETag/304, rate limiting
        ├── overlay.py    # tarkov-data-overlay: the corrections tarkov.dev lacks
        ├── brief.py      # availability + carry/loot/do classification, extracts
        ├── standing.py   # trader levels: stored overrides + the task-derived estimate
        ├── models.py     # dataclasses + settings
        ├── recommend.py  # deterministic "Run next" scoring
        ├── gemini.py     # optional AI route advice
        ├── static/       # app.css, app.js  (no build step, no framework)
        └── templates/    # index.html
```

---

## Non-goals

No game memory reading, process injection, input automation, or overlay —
log-file and public-API data only. No writes to TarkovTracker. No accounts, no
telemetry, no external calls beyond tarkov.dev and TarkovTracker. No interactive
map; it links out to tarkov.dev instead.

## Support

Found a bug, or a task showing up that you can't actually take?
[Open an issue](https://github.com/KarlisKocins/tarkov-raidbrief/issues/new/choose)
— the add-on's log and your player level help a lot. Contributions are welcome;
see [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits

Task data from [tarkov.dev](https://tarkov.dev). Progress from
[TarkovTracker](https://tarkovtracker.org), fed by
[TarkovMonitor](https://github.com/the-hideout/TarkovMonitor). Availability
corrections from
[tarkov-data-overlay](https://github.com/tarkovtracker-org/tarkov-data-overlay).

## License

[MIT](LICENSE) © Kārlis Kociņš.

This project is a community tool and is not affiliated with or endorsed by
Battlestate Games, tarkov.dev, or TarkovTracker. Escape from Tarkov is a
trademark of Battlestate Games Limited.
