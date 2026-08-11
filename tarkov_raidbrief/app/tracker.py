"""TarkovTracker API v2 client.

Read-only, by design: TarkovMonitor owns writes to the tracker, we only ever
GET /progress. Their docs ask integrators to poll no more than once a minute
and to send If-None-Match, so both are enforced here rather than left to the
caller's good behaviour.

Response shape is `{"success": bool, "data": Progress, "meta": {...}}`, where
Progress carries `playerLevel`, `pmcFaction`, `displayName` and an array of
`{id, complete, failed, invalid}`.

That array's key is a trap. The published OpenAPI spec calls it `taskProgress`;
the live API actually returns `tasksProgress`. Verified against the real
endpoint, which answered with `tasksProgress`. Both spellings are accepted
below so whichever way they settle it, this keeps working.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("raidbrief.tracker")

ENDPOINT = "https://api.tarkovtracker.org/api/v2/progress"
USER_AGENT = "tarkov-raidbrief/1.0 (Home Assistant add-on)"

# TarkovTracker explicitly asks integrators not to poll faster than this.
MIN_POLL_SECONDS = 60


def _task_entries(progress: dict) -> list[dict]:
    """The per-task progress array, under whichever key this deployment uses."""
    for key in ("tasksProgress", "taskProgress"):
        value = progress.get(key)
        if isinstance(value, list):
            return [e for e in value if isinstance(e, dict)]
    return []


class TrackerAuthError(RuntimeError):
    """401 - the token is wrong or lacks the 'get progression' permission."""


class TrackerRateLimited(RuntimeError):
    """429 - we asked too often."""


class TrackerUnavailable(RuntimeError):
    """Network trouble or a 5xx."""


class Tracker:
    def __init__(self, token: str, game_mode: str = "pvp", state_path: Path | None = None) -> None:
        self.token = token
        self.game_mode = game_mode
        self.state_path = state_path

        self.progress: dict | None = None
        self.fetched_at: float | None = None
        self.etag: str | None = None
        self._last_attempt: float = 0.0

        self._load_state()

    # -- polling -----------------------------------------------------------

    def _too_soon(self) -> bool:
        return (time.time() - self._last_attempt) < MIN_POLL_SECONDS

    async def fetch(self) -> dict | None:
        """Fetch progress, honouring the rate limit and the stored ETag.

        Returns the current progress dict (possibly the previously cached one
        on a 304 or a throttled skip), or None if we have never had any.
        Raises on 401 so the UI can say "your token is wrong" precisely.

        There is deliberately no `force`: see the 60s floor below.
        """
        if not self.token:
            return None

        # The 60s floor is absolute: `force` does not pierce it. A refresh button
        # the user can lean on must not be able to get them rate-limited. The
        # first call always passes, since _last_attempt starts at 0.
        if self._too_soon():
            log.debug("Skipping poll, %.0fs left on the %ds floor",
                      MIN_POLL_SECONDS - (time.time() - self._last_attempt), MIN_POLL_SECONDS)
            return self.progress

        self._last_attempt = time.time()

        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if self.etag:
            headers["If-None-Match"] = self.etag

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(
                    ENDPOINT,
                    params={"gameMode": self.game_mode},
                    headers=headers,
                    timeout=httpx.Timeout(30.0, connect=10.0),
                )
        except httpx.HTTPError as exc:
            raise TrackerUnavailable(str(exc)) from exc

        if resp.status_code == 304:
            log.debug("TarkovTracker: 304, progress unchanged")
            self.fetched_at = time.time()
            return self.progress

        if resp.status_code == 401:
            raise TrackerAuthError(
                "TarkovTracker rejected the token (401). Check it is copied whole and "
                "that it was created with the 'get progression' permission."
            )

        if resp.status_code == 429:
            raise TrackerRateLimited(
                "TarkovTracker rate-limited us (429). Backing off; data below may be stale."
            )

        if resp.status_code >= 400:
            raise TrackerUnavailable(f"TarkovTracker returned HTTP {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise TrackerUnavailable(f"TarkovTracker sent malformed JSON: {exc}") from exc

        data = payload.get("data")
        if not isinstance(data, dict):
            raise TrackerUnavailable("TarkovTracker response had no 'data' object")

        self.etag = resp.headers.get("ETag") or self.etag
        self.progress = data
        self.fetched_at = time.time()
        self._save_state()
        log.info("TarkovTracker: level %s %s, %d task records",
                 data.get("playerLevel"), data.get("pmcFaction"),
                 len(_task_entries(data)))
        return self.progress

    # -- derived views -----------------------------------------------------

    def statuses(self) -> dict[str, str]:
        """Map task id -> 'complete' | 'failed' | 'invalid'.

        Anything absent is simply not started. `invalid` means the task became
        unreachable (wrong faction, or a branch not taken) without being failed,
        so it is treated as unavailable too.
        """
        out: dict[str, str] = {}
        for entry in _task_entries(self.progress or {}):
            tid = entry.get("id")
            if not tid:
                continue
            if entry.get("failed"):
                out[tid] = "failed"
            elif entry.get("complete"):
                out[tid] = "complete"
            elif entry.get("invalid"):
                out[tid] = "invalid"
        return out

    @property
    def player_level(self) -> int:
        try:
            return int((self.progress or {}).get("playerLevel") or 1)
        except (TypeError, ValueError):
            return 1

    @property
    def faction(self) -> str:
        faction = ((self.progress or {}).get("pmcFaction") or "USEC").upper()
        return faction if faction in ("USEC", "BEAR") else "USEC"

    @property
    def display_name(self) -> str:
        return (self.progress or {}).get("displayName") or "player"

    # -- persistence -------------------------------------------------------

    def _load_state(self) -> None:
        if not self.state_path:
            return
        try:
            blob = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return
        if blob.get("game_mode") != self.game_mode:
            return
        if isinstance(blob.get("progress"), dict):
            self.progress = blob["progress"]
            self.fetched_at = blob.get("fetched")
            # Deliberately not restoring the ETag: we want one full-bodied
            # response after a restart rather than a 304 against no data.
            log.info("Restored TarkovTracker progress snapshot from disk")

    def _save_state(self) -> None:
        if not self.state_path:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "game_mode": self.game_mode,
                "fetched": self.fetched_at,
                "progress": self.progress,
            }))
            tmp.replace(self.state_path)
        except OSError as exc:
            log.warning("Could not persist progress snapshot: %s", exc)
