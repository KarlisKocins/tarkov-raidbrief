# Changelog

## 1.7.0

Three features, all built from data the add-on was already downloading and
throwing away — no new upstream, no extra requests.

- **The brief now knows which objectives you have already done.** The
  TarkovTracker response carried `taskObjectivesProgress` all along and the
  add-on read only the task-level records out of it. It now reads both, so a
  task you are part-way through contributes only what is *left* of it: no keys
  you have finished with, no items already in the stash, and no map placement
  earned by an objective you closed out last raid. Counted objectives show
  what remains rather than what the quest asked for — "Bandage x3 (2/5 done)"
  — and each task card carries its own "4/7 done".
- **…which also fixes the RUN NEXT ranking.** A map's score turns on how many
  tasks are *finishable there in one raid*, and that was judged on every
  objective a task had ever had. A task whose remaining work is all on Customs
  now counts as finishable on Customs, which is what you would have said
  yourself looking at the same list.
- **EXTRACTS panel per map.** Every exit a PMC can use, with switch-gated ones
  marked and any exit a task specifically names pulled to the front in the
  accent colour. Scav-only exfils are filtered out. The map header also gains
  raid length and lobby size, and the panel lists boss spawn chances. All of
  it comes from the `maps` dataset the add-on already fetched for map names.
- **Trader standing is now estimated for you.** 366 of the 516 live tasks say
  exactly how much reputation they pay, so the completed ones add up to a
  reputation figure, and each trader's loyalty tiers turn that into a level.
  The panel shows the estimate beside each trader and a **Use estimate**
  button fills the whole roster in at once. It is *offered, never applied on
  its own*: the figure cannot see roubles spent (`requiredCommerce`) or your
  edition's starting bonus, so it is an upper bound you confirm — and Fence is
  excluded outright, since their standing comes from scav karma rather than
  tasks. Applied levels are ordinary overrides you can then correct pip by pip.
- Fixed: the GraphQL fallback had no trader roster attribute at all, so if the
  JSON API had failed while GraphQL was up, the trader panel would have taken
  the page down with it. Both side tables now exist on either client, empty on
  the fallback.
- The task cache format is now `json-v4`, carrying per-map extracts and the
  per-task reward standing. The first start after updating refetches rather
  than serving a cache with half the new fields missing.

## 1.6.0

Trader standing moves into the page, and the packing lists get item icons.

- **TRADER STANDING panel.** Loyalty level is the one input nothing upstream
  can supply — tarkov.dev knows what a task demands, TarkovTracker knows what
  you have finished, neither knows what Prapor thinks of you — so it used to
  come from the Configuration tab alone, which meant restarting the add-on
  after every level-up. It is now a panel at the top of the page: click a pip,
  the brief rebuilds. Each trader shows a portrait, the loyalty tiers with
  their real player-level and reputation thresholds on hover, and **how many
  otherwise-ready tasks that trader alone is holding back** — the number that
  tells you which trader is worth levelling next. The panel is collapsed by
  default and remembers whether you left it open.
- The `trader_levels` options become the starting point rather than the whole
  story: the panel outranks them once used, **Reset** hands control back, and
  your answers persist in `/data/standing.json` across restarts and updates.
- **Trader reputation is now enforced — but only when you supply it.** Twelve
  tasks compare against reputation rather than loyalty, all of them Fence or
  Lightkeeper, and several want your standing *below* a threshold (the
  "Compensation for Damage" chain needs Fence to dislike you). 1.5.0 skipped
  the check entirely because the value was unknowable. The panel makes it
  knowable, so a reputation you have entered is now applied; one you have not
  is still left alone rather than assumed to be 0.00.
- **Item icons on every packing line.** CARRY IN, KEYS and BRING OUT rows now
  carry the item's tarkov.dev icon, and each task shows the portrait of the
  trader who hands it out. Lines naming several interchangeable items
  ("Aquamari / EWR / Superwater") stay iconless, since no one picture stands
  for them. Icons are lazy-loaded from tarkov.dev's own asset host and any
  that fail — a few quest items have no art, and the add-on may be running
  with no route out — are dropped silently, leaving the row's text alone.
- The task cache format is now `json-v3`, carrying the trader roster. The
  first start after updating refetches from tarkov.dev rather than serving a
  cache with half a panel in it.

## 1.5.0

A visual pass on the whole page, plus one layout bug that had been hiding in
the wide-screen view since the two-column grid was added.

- **New look: "field issue".** Squared corners, hairline rules, uppercase
  letterspaced labels and monospace type on near-black olive — a printed
  briefing sheet rather than a web app. Section colour is now semantic and
  consistent: khaki is CARRY IN, steel blue is KEYS, olive green is BRING OUT,
  lilac is AI. That split is the fastest way to tell the authoritative packing
  lists apart from generated advice, so it is load-bearing, not decoration.
- **Every map rendered at once on wide screens.** `.map { display: grid }`
  overrides the browser's own rule for the `hidden` attribute, which is what
  the page and the map switcher use to show one map at a time. Above 820px
  that meant all your maps stacked down the page instead of just the selected
  one. The grid now restates `display: none` for hidden maps.
- No web fonts are loaded. The intended faces (IBM Plex Mono, Saira
  Condensed) are named first in the font stack and fall back to system faces,
  so the page still makes no request outside tarkov.dev and TarkovTracker and
  still renders with no network at all.
- The three packing columns now sit side by side in the order you pack them,
  and reflow to fill the row on maps with no keys or nothing to loot. Tasks
  read in two columns with trader, level and XP pulled right onto the title.
  Phone layout is unchanged apart from the styling — still single column, still
  40px tick targets.
- **The add-on now has an icon and a logo** in the Add-on Store instead of a
  grey placeholder, and every option in the Configuration tab has a real label
  and description instead of a raw key name like `excluded_maps`.
- The Documentation tab was missing `excluded_maps`, `gemini_api_key` and
  `gemini_model` entirely; all three are documented now, with defaults.

## 1.4.0

Fixes the add-on listing tasks you cannot actually take. On a level 15
account it was showing 39 tasks, 15 of them locked in game — A Shooter Born
in Heaven (needs Mechanic LL4), both BTR Driver quests (needs a trader you
have not met), and Shipping Delay Parts 1 and 2.

The root cause is that tarkov.dev's raw data is missing most of the
information availability depends on, and TarkovTracker does not use it raw.

- **The data overlay is now applied.** TarkovTracker pipes every tarkov.dev
  response through `tarkovtracker-org/tarkov-data-overlay`, a community patch
  file. Working without it means working from data the reference
  implementation considers broken: json.tarkov.dev ships 17 trader loyalty
  requirements across all 510 tasks, the overlay adds 247 more. It also
  retires 32 tasks BSG removed from the game (Rite of Passage, Farming -
  Part 2, Signal Parts 3 and 4, …) and corrects names and XP values. The
  overlay refreshes hourly, independently of the daily task refresh.
- **Traders you have not unlocked.** The BTR Driver does not exist until A
  Helping Hand is done, and the Lightkeeper until Getting Acquainted is.
  There is no field for this in tarkov.dev's data — TarkovTracker hardcodes
  it, and now so does this. Without it, BTR quests showed from level 1.
- **"Active" prerequisites are re-checked properly.** 1.3.0 approximated
  TarkovTracker's `isUnlockable` by copying the required quest's
  prerequisites, which silently discarded its level, faction, loyalty and
  trader-unlock gates. A prerequisite with no prerequisites of its own
  therefore unlocked its children unconditionally. This is now the same
  recursive, memoised evaluation TarkovTracker performs.
- **A Helping Hand** is level 20 and needs Saving the Mole. Neither
  tarkov.dev nor the overlay records this, and it matters more than most
  because the whole BTR chain hangs off it, so it is corrected locally —
  only where the overlay is silent, so the fix retires itself.
- **Prestige-only tasks are hidden.** The progress API reports no prestige
  level, so the prestige variants of New Beginning can never be reachable.
- A prerequisite that no longer exists no longer locks its successor
  forever. Painkiller, Broadcast - Part 1 and Bad Habit all hang off quests
  BSG retired, and were unreachable as a result.
- Two new banners: one when the overlay cannot be fetched (the brief will
  over-report without it), and one when every trader is still configured at
  loyalty level 1, which hides everything gated behind LL2-4. **Set your
  real loyalty levels under Configuration** — they now change what you see.

The task cache is rebuilt once on update, so the corrections apply
immediately rather than on the next daily refresh.

## 1.3.0

Task availability now matches TarkovTracker. Previously the add-on could list
quests the tracker (and the game) still had locked — most visibly the
mutually exclusive Chemical - Part 3 endings: Big Customer showed up for any
level 11 character, even with the Chemical questline untouched or already
resolved the other way.

- **Prerequisite graph, TarkovTracker-style.** A requirement of status
  "active" (Big Customer needs Chemical - Part 4 *accepted*, not completed —
  you hand the flash drive to Prapor instead of Skier) used to be ignored.
  The task now inherits the required quest's own prerequisites, so it
  unlocks at the same moment that quest does, exactly as on the tracker.
- **Mutually exclusive branches.** `failConditions` are now fetched, and a
  task disappears once any quest that would fail it is completed — even if
  the tracker never recorded the fail, which it can't when progress is
  written by other integrations.
- **Failed-prerequisite requirements.** Quests that require another quest to
  have been *failed* are now hidden until it actually was.
- A failed prerequisite counts as finished (TarkovTracker records fails as
  completions too), so quests downstream of a branch stay reachable
  whichever ending you picked.

The prerequisite gating applies to already-cached task data immediately; the
branch (`failConditions`) data arrives with the next task refresh — hit
Refresh once after updating if you don't want to wait for the daily one.

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
