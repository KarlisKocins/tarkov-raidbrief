# Changelog

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
