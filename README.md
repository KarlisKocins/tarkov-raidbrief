# Tarkov Raid Brief — Home Assistant add-on repository

"What do I bring to which map?" for Escape from Tarkov, on your phone or second
monitor while you're in the stash picking a loadout.

It joins your live task progress from **TarkovTracker** (fed automatically by
TarkovMonitor) with task data from **tarkov.dev**, and gives you a per-map
brief: what to **carry in**, which **keys** you need, what to **bring out**, and
what to actually **do**.

Read-only and public-API only. No game memory reading, no injection, no overlay,
no writes back to TarkovTracker.

## Data sources — read this if tasks won't load

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

The progress API does **not** expose trader loyalty levels, so set them yourself
under `trader_levels` in the add-on Configuration tab. They're used to hide tasks
you can't unlock yet. Defaults are all `1`; wrong values only mean tasks appear
slightly early or late.

---

## Options

| Option | Type | Default | Meaning |
|---|---|---|---|
| `tarkovtracker_token` | password | — | Token with `get progression`. |
| `game_mode` | `regular` \| `pve` | `regular` | Which mode's tasks and progress to show. |
| `refresh_minutes` | 5–1440 | `60` | How often to poll TarkovTracker in the background. |
| `kappa_only` | bool | `false` | Show only Kappa-required tasks. Also toggleable in the UI. |
| `trader_levels.*` | 1–4 | `1` | Your loyalty level per trader. |

`game_mode` maps to `regular`/`pve` on tarkov.dev and `pvp`/`pve` on
TarkovTracker — the two APIs name the same thing differently, and the add-on
translates.

---

## How Ingress is handled

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

---

## Debugging via the direct port

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

### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | The page. Accepts `?map=` and `?kappa_only=`. |
| `GET /api/brief` | Full brief as JSON. Optional `?map=` and `?kappa_only=`. |
| `POST /api/refresh` | Force-refresh both upstreams and bust the task cache. |
| `GET /health` | Liveness. Makes no upstream calls. |

---

## Data handling

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

## Schema fragility (the GraphQL fallback)

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

## Tests

Two checks, both aimed at the ways this app can rot between patches:

```bash
pip install graphql-core

# Every rung of the query fallback ladder is a valid document, checked against
# the real published schema. Offline; uses a vendored copy of the SDL.
python3 tests/test_query_validates.py
python3 tests/test_query_validates.py --update    # refresh the vendored SDL

# Every objective type in the live task dump is explicitly classified as
# carry / loot / non-raid. Fails if a patch adds a type we'd silently mishandle.
python3 tests/test_objective_coverage.py
```

The second one caught two real types (`dialogue`, `globalVariable`) that would
otherwise have shown up as fake "things to do" on every map.

---

## Building the image yourself

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

## Releasing a new version

CI publishes only when `tarkov_raidbrief/config.yaml`'s `version` changes, so an
ordinary code push can't silently overwrite a released tag.

1. Bump `version` in `tarkov_raidbrief/config.yaml`.
2. Add a `CHANGELOG.md` entry.
3. Push to `main`. The workflow builds both arches and pushes to GHCR.
4. In HA: **⋮ → Check for updates** in the Add-on Store.

---

## Repository layout

```
.
├── repository.yaml                 # marks this as an HA add-on repository
├── .github/workflows/builder.yaml  # builds + pushes both arches to GHCR
├── tests/test_query_validates.py   # offline GraphQL query validation
└── tarkov_raidbrief/               # the add-on itself
    ├── config.yaml  Dockerfile  build.yaml  run.sh  requirements.txt
    └── app/
        ├── main.py       # FastAPI entrypoint, ingress handling, background poller
        ├── tarkovjson.py # JSON API client (primary): id joins + translations
        ├── tarkovdev.py  # GraphQL client (fallback), composable query, disk cache
        ├── tracker.py    # TarkovTracker client, ETag/304, rate limiting
        ├── brief.py      # availability + carry/loot/do classification
        ├── models.py     # dataclasses + settings
        ├── static/       # app.css, app.js  (no build step, no framework)
        └── templates/    # index.html
```

## Non-goals

No game memory reading, process injection, input automation, or overlay —
log-file and public-API data only. No writes to TarkovTracker. No accounts, no
telemetry, no external calls beyond tarkov.dev and TarkovTracker. No interactive
map; it links out to tarkov.dev instead.

## Credits

Task data from [tarkov.dev](https://tarkov.dev). Progress from
[TarkovTracker](https://tarkovtracker.org), fed by
[TarkovMonitor](https://github.com/the-hideout/TarkovMonitor).
