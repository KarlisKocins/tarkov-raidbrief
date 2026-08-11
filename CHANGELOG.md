# Changelog

## 1.2.1

Fixes the 1.2.0 UI appearing broken after the update: browsers (and the HA
companion app's webview) had cached 1.1.0's `app.js`, which predates the AI
feature, so the new buttons rendered but had no click handlers — pressing
them did nothing, with no loading animation and no error. The ingress view
and the direct-port view could even disagree, since they cache separately.

- Static assets are now served with a content-hash `?v=` parameter, so every
  add-on update forces the browser to fetch fresh CSS/JS. This can't recur.
- If a map is hidden via `excluded_maps`, the page footer now says so
  ("Hidden by excluded_maps: Icebreaker"), so you can see the setting is
  live. Reminder: the setting itself lives in the add-on **Configuration**
  tab in Home Assistant, not in this web UI.

## 1.2.0

- **Map exclusion.** New `excluded_maps` option hides maps you cannot enter —
  event maps like Icebreaker, which otherwise topped the recommendation with
  tasks you have no way to reach. Excluded maps are dropped before scoring, so
  they can never win. Matched case-insensitively on name or normalized name.
- **"Run next" recommendation.** A deterministic ranking of which map is worth
  your next raid, weighted towards tasks you could actually *finish* there in
  one go, plus Kappa-required tasks, minus a penalty per key needed. This is
  plain arithmetic, not AI: it is instant, free, reproducible, and cannot
  invent a task. The score breakdown is shown so you can disagree with it.
- **Optional Gemini route advice.** Set `gemini_api_key` to enable a per-map
  briefing that orders your objectives into a route, plus a one-line
  explanation of the recommendation.
  - **Generated only when you press the button.** Nothing runs on startup, on
    the background poller, or on page load, so the add-on cannot spend your
    quota while you are not looking. Results are cached against the brief, so
    re-asking an unchanged map is free; "Regenerate" forces a new call.
  - The model is allowed to use its own map knowledge, which is what makes the
    text useful and also means it can be wrong. It is therefore confined to its
    own labelled block *below* the CARRY IN / KEYS / BRING OUT lists, and can
    never alter them — those come from live game data alone. A hallucinated key
    can never reach your packing checklist.
  - The prompt forbids telling you where to spawn, since you do not choose your
    spawn; spawn-dependent advice must be phrased conditionally.
  - Leaving the key empty keeps the add-on talking only to tarkov.dev and
    TarkovTracker. Enabling it sends your task progress and level to Google.

## 1.1.0

**Switched the task data source to the tarkov.dev JSON API.** 1.0.0 could not
load any tasks at all, because `api.tarkov.dev/graphql` has been returning
`{"errors":["GraphQL server unavailable. Try again later."]}` continuously
since 2026-07-21 (the-hideout/tarkov-api#474, still open). A maintainer on that
issue: *"The GraphQL API is down for the moment, but you have the Json API who
alive. Tarkov.dev is based on this Json API and not on the GraphQL."*

- New `app/tarkovjson.py` reads `json.tarkov.dev`, which serves unresolved and
  untranslated data: every reference is a bare id and every text field holds a
  translation key (a task's `name` is literally `"657315... name"`). It fetches
  items/maps/traders alongside tasks, joins the ids, and resolves text through
  the sibling `<path>_en` files using the same `lang[value] ?? value` rule the
  tarkov.dev site itself uses.
- Output is converted to the GraphQL shape, so all downstream classification is
  unchanged. Verified: 510 tasks, 5310 items, 17 maps, 16 traders.
- GraphQL is kept as an automatic fallback for when it returns.
- Fixed two conditions that were rendering as noise on real data: `distance`
  reads `>= 0` on 178 of 192 shoot objectives (meaning "no requirement") and
  `shotType` is `kill` on 198 of 200. Both are now suppressed, and `>=`/`<=`
  render as `≥`/`≤` — the JSON API uses those where GraphQL used
  `moreThan`/`lessThan`.
- Classified `dialogue` and `globalVariable`, two objective types that fall
  through to the catch-all and would otherwise appear as phantom map tasks.

## 1.0.0

First release.

- Per-map raid brief: **CARRY IN**, **KEYS**, **BRING OUT**, and a task list
  with objectives, trader, min level, XP and Kappa flag.
- Live progress from TarkovTracker, joined with task data from tarkov.dev.
- Mobile-first dark UI behind Home Assistant Ingress, with carry-in checkboxes
  that persist in `localStorage` per map.
- Multi-arch images (`aarch64`, `amd64`) pre-built in CI and published to GHCR,
  so Home Assistant downloads rather than compiles.

Notes on the two upstreams, both of which had surprises worth recording:

- **`requiredKeys` lives on the concrete objective types, not on the
  `TaskObjective` interface.** Requesting it at interface level fails the entire
  query, so it is requested inside each inline fragment — and only on the seven
  types that actually have it (`Basic`, `Extract`, `Item`, `Mark`, `QuestItem`,
  `Shoot`, `UseItem`). `Task.neededKeys` is deprecated.
- **`tasks()` does accept `gameMode`**, with values `regular` and `pve`.
- **TarkovTracker returns `tasksProgress`, not `taskProgress`** as its published
  OpenAPI spec claims. Both spellings are accepted.
- TarkovTracker's `gameMode` values are `pvp`/`pve` where tarkov.dev's are
  `regular`/`pve`; the add-on translates between them.
- `TaskObjectiveItem.item` is deprecated in favour of `items`; the query uses
  `items` and renders alternatives as `A / B / C`.
