"""FastAPI entrypoint for the Tarkov Raid Brief add-on.

Ingress note - this is the part that bites.

Home Assistant serves the add-on under a generated prefix and announces it in
the `X-Ingress-Path` header, but it *strips that prefix before proxying*, so
requests arrive here as plain `/`, `/static/app.css`, `/api/brief`.

This app therefore solves ingress purely with **relative URLs** in the frontend
(`static/app.css`, `fetch("api/brief")` - no leading slashes anywhere), which
resolve correctly under the ingress prefix and on the direct port alike.

It deliberately does NOT set Starlette's `root_path` from that header, which is
the obvious-looking alternative and is actively broken here: `Mount` appends
`/static` to `root_path` and then strips the combined prefix from the request
path. Since HA already stripped it, the path is just `/static/app.css`, the
strip does not match, and every static asset 404s - while the HTML itself still
renders, so it fails as an unstyled page rather than an obvious error. Verified
by reproducing it. Set `root_path` only if you also stop stripping.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .brief import build_brief, filter_brief, locked_by_trader
from .gemini import Gemini
from .models import (
    TRADERS, Brief, PlayerInfo, Recommendation, Settings, TraderInfo, TraderLevelInfo,
    Warning_,
)
from .recommend import score_maps
from .standing import Standing
from .tarkovdev import CACHE_TTL, TarkovDev, TarkovDevError
from .tarkovjson import TarkovJson, TarkovJsonError
from .tracker import Tracker, TrackerAuthError, TrackerRateLimited, TrackerUnavailable

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("raidbrief")

HERE = Path(__file__).parent


class State:
    """Everything the request handlers read. Mutated only by the poller."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # JSON API is primary: the GraphQL endpoint has been down since
        # 2026-07-21 and the maintainers point integrators at json.tarkov.dev.
        # GraphQL stays as a fallback in case it comes back.
        self.tarkovjson = TarkovJson(settings.data_dir / "tasks.json", settings.game_mode)
        self.tarkovdev = TarkovDev(settings.data_dir / "tasks-graphql.json", settings.game_mode)
        self.source = "json"
        self.tracker = Tracker(
            settings.token,
            settings.tracker_game_mode,
            settings.data_dir / "progress.json",
        )
        self.gemini = Gemini(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.data_dir / "ai_cache.json",
        )
        # Loyalty levels start at whatever the add-on options say and are then
        # owned by the standing panel. See standing.py.
        self.standing = Standing(
            settings.trader_levels, settings.data_dir / "standing.json"
        )
        self.tasks: list[dict] = []
        self.tasks_fetched: float | None = None
        self.tracker_warning: Warning_ | None = None
        self.tasks_warning: Warning_ | None = None
        self.lock = asyncio.Lock()

    # -- upstream refresh --------------------------------------------------

    async def refresh_tasks(self, force: bool = False) -> None:
        """Load tasks from the JSON API, falling back to GraphQL if it fails."""
        try:
            self.tasks, self.tasks_fetched, _ = await self.tarkovjson.get_tasks(force=force)
            self.source = "json"
            self.tasks_warning = None
            return
        except TarkovJsonError as json_exc:
            log.warning("json.tarkov.dev failed (%s); trying the GraphQL API", json_exc)

        try:
            self.tasks, self.tasks_fetched, _ = await self.tarkovdev.get_tasks(force=force)
            self.source = "graphql"
            self.tasks_warning = None
            log.info("Loaded tasks from the GraphQL API fallback")
        except TarkovDevError as gql_exc:
            log.error("Could not load tasks from either source: %s", gql_exc)
            self.tasks_warning = Warning_(
                "upstream",
                "Could not reach tarkov.dev on either the JSON or GraphQL API, and "
                "there is no cached task data yet. Check the add-on's network access "
                "and hit Refresh.",
            )

    async def refresh_progress(self) -> None:
        if not self.settings.token:
            return
        try:
            await self.tracker.fetch()
            self.tracker_warning = None
        except TrackerAuthError as exc:
            log.error("%s", exc)
            self.tracker_warning = Warning_("auth", str(exc))
        except TrackerRateLimited as exc:
            log.warning("%s", exc)
            self.tracker_warning = Warning_("ratelimit", str(exc))
        except TrackerUnavailable as exc:
            log.warning("TarkovTracker unavailable: %s", exc)
            self.tracker_warning = Warning_(
                "upstream", f"TarkovTracker is unreachable: {exc}"
            )

    @property
    def player_level(self) -> int:
        return self.tracker.player_level if self.settings.token else 99

    @property
    def player_faction(self) -> str:
        return self.tracker.faction if self.settings.token else "USEC"

    async def refresh_all(self, force: bool = False) -> None:
        async with self.lock:
            await self.refresh_tasks(force=force)
            await self.refresh_progress()

    @property
    def active_source(self):
        """Whichever client actually supplied the tasks we are serving."""
        return self.tarkovjson if self.source == "json" else self.tarkovdev

    # -- traders -----------------------------------------------------------

    def _gating_traders(self) -> dict[str, str]:
        """The traders some task's availability turns on, and how: by loyalty
        level or by reputation.

        Read off the task data rather than hardcoded, so a patch that starts
        gating on a trader the add-on options never listed shows up in the
        panel without a code change. A trader no task requires is left out
        entirely: setting their level would not move a single line of the
        brief, and the panel is long enough already.
        """
        kinds: dict[str, str] = {}
        for task in self.tasks:
            for req in task.get("traderRequirements") or []:
                name = (req.get("trader") or {}).get("normalizedName") or ""
                kind = (req.get("requirementType") or "level").lower()
                if not name or kind not in ("level", "reputation"):
                    continue
                # Reputation wins the label: a trader gated both ways needs the
                # rep field on screen, and the pips are drawn either way.
                if kind == "reputation" or name not in kinds:
                    kinds[name] = kind
        return kinds

    def trader_roster(self, statuses: dict[str, str], level: int,
                      faction: str) -> list[TraderInfo]:
        gating = self._gating_traders()
        if not gating:
            return []

        blocked = locked_by_trader(
            self.tasks, statuses, level, faction, self.standing.levels,
            self.settings.game_mode, self.standing.reputations,
        )

        # Portraits and loyalty thresholds come from the traders dataset. The
        # GraphQL fallback does not fetch it, so a trader missing there is
        # rebuilt from the identity stamped on any task they hand out - which
        # costs the thresholds, not the panel.
        known = {t["normalizedName"]: t for t in self.active_source.traders}
        from_tasks: dict[str, dict] = {}
        for task in self.tasks:
            trader = task.get("trader") or {}
            name = trader.get("normalizedName")
            if name and name not in from_tasks:
                from_tasks[name] = trader

        roster = [
            self._trader_info(name, kind, known.get(name) or from_tasks.get(name) or {},
                              blocked.get(name, 0))
            for name, kind in gating.items()
        ]
        # The game's own trader order, which players already navigate by. Not
        # sorted by how much each one is blocking, tempting as that is: the
        # counts change on every click, and a trader that jumped to the far end
        # of the panel the moment you levelled them is disorienting when you
        # are setting eight of them in a row. The accent-coloured "N locked"
        # badge carries that signal instead, without moving anything.
        order = {name: i for i, name in enumerate(TRADERS)}
        roster.sort(key=lambda t: (order.get(t.normalized_name, len(order)), t.name))
        return roster

    def _trader_info(self, name: str, kind: str, entry: dict, gated: int) -> TraderInfo:
        return TraderInfo(
            id=entry.get("id") or name,
            name=entry.get("name") or name.replace("-", " ").title(),
            normalized_name=name,
            image=entry.get("imageLink") or "",
            level=self.standing.level(name),
            reputation=self.standing.reputation(name),
            levels=[
                TraderLevelInfo(
                    level=lvl["level"],
                    player_level=lvl.get("player_level") or 0,
                    reputation=lvl.get("reputation") or 0.0,
                )
                for lvl in entry.get("levels") or []
            ],
            gated_tasks=gated,
            tracks_reputation=kind == "reputation",
            reputation_known=name in self.standing.reputations,
        )

    # -- brief -------------------------------------------------------------

    def current_brief(self, kappa_only: bool | None = None) -> Brief:
        settings = self.settings
        kappa = settings.kappa_only if kappa_only is None else kappa_only
        statuses = self.tracker.statuses()
        has_token = bool(settings.token)
        level = self.tracker.player_level if has_token else 99
        faction = self.tracker.faction if has_token else "USEC"

        maps = build_brief(
            self.tasks,
            statuses,
            level,
            faction,
            self.standing.levels,
            kappa_only=kappa,
            game_mode=settings.game_mode,
            trader_reps=self.standing.reputations,
        )

        # Hidden maps are dropped before scoring, so an event map you cannot
        # enter never wins the recommendation. A task that also appears on a
        # visible map still shows up there.
        hidden_maps: list[str] = []
        if settings.excluded_maps:
            kept = []
            for m in maps:
                if settings.is_excluded(m.name, m.normalized_name):
                    hidden_maps.append(m.name)
                else:
                    kept.append(m)
            maps = kept

        warnings: list[Warning_] = []
        if self.tasks_warning:
            warnings.append(self.tasks_warning)
        if self.tracker_warning:
            warnings.append(self.tracker_warning)
        if not has_token:
            warnings.append(Warning_(
                "auth",
                "No TarkovTracker token configured - showing every task as if for a "
                "fresh level 99 character. Add a token in the add-on Configuration tab.",
            ))
        if self.active_source.serving_stale or (
            self.tasks_fetched and (time.time() - self.tasks_fetched) > CACHE_TTL
        ):
            age = _age(time.time() - self.tasks_fetched) if self.tasks_fetched else "unknown age"
            warnings.append(Warning_(
                "stale",
                f"tarkov.dev could not be reached, so this is cached task data from "
                f"{age}. Everything still works; it just will not pick up a new patch "
                f"until the API is back.",
            ))
        # Without the overlay, tarkov.dev ships almost no trader loyalty gates,
        # so the brief silently over-reports. Worth a banner rather than a log line.
        overlay = self.active_source.overlay
        if overlay.status == "missing":
            warnings.append(Warning_(
                "degraded",
                "The tarkov-data-overlay could not be fetched, so tasks are being "
                "judged on raw tarkov.dev data. Trader loyalty requirements and "
                "retired tasks are missing from that data, so this list will show "
                "some tasks you cannot actually take."
                + (f" ({overlay.error})" if overlay.error else ""),
            ))

        # Loyalty gates only bite if the levels are real, and they default to 1.
        if has_token and all(v <= 1 for v in settings.trader_levels.values()):
            warnings.append(Warning_(
                "degraded",
                "Every trader is configured at loyalty level 1. Tasks gated behind "
                "LL2-4 are being hidden - set your real levels under the add-on "
                "Configuration tab to see them.",
            ))

        if self.active_source.dropped_blocks:
            dropped = ", ".join(self.active_source.dropped_blocks)
            detail = (" The KEYS section may be incomplete."
                      if "requiredKeys" in self.active_source.dropped_blocks else "")
            warnings.append(Warning_(
                "degraded",
                f"tarkov.dev rejected part of the query, so some detail is "
                f"missing: {dropped}.{detail}",
            ))

        # Ranking is computed, never generated. The model only narrates it.
        scores = score_maps(maps)
        best = next((s for s in scores if s.tasks and s.score > 0), None)
        recommendation = None
        if best:
            recommendation = Recommendation(
                name=best.name,
                normalized_name=best.normalized_name,
                reasons=best.reasons,
                completable=best.completable,
                completable_xp=best.completable_xp,
                tasks=best.tasks,
                kappa=best.kappa,
                keys=best.keys,
            )

        if self.gemini.enabled:
            for map_brief in maps:
                cached = self.gemini.for_map(map_brief, level, faction)
                if cached:
                    map_brief.ai_text = cached.text
                    map_brief.ai_generated_at = cached.generated_at
            if recommendation:
                rec_text = self.gemini.for_recommendation(scores)
                if rec_text:
                    recommendation.ai_text = rec_text.text
            if self.gemini.last_error:
                warnings.append(Warning_(
                    "ai", f"Gemini could not generate advice: {self.gemini.last_error}"
                ))

        now = time.time()
        return Brief(
            maps=maps,
            hidden_maps=hidden_maps,
            recommendation=recommendation,
            ai_enabled=self.gemini.enabled,
            player=PlayerInfo(
                name=self.tracker.display_name if has_token else "no token",
                level=self.tracker.player_level if has_token else 0,
                faction=self.tracker.faction if has_token else "-",
                tasks_complete=sum(1 for s in statuses.values() if s == "complete"),
                has_token=has_token,
            ),
            traders=self.trader_roster(statuses, level, faction),
            warnings=warnings,
            tasks_age_seconds=(now - self.tasks_fetched) if self.tasks_fetched else None,
            progress_age_seconds=(
                (now - self.tracker.fetched_at) if self.tracker.fetched_at else None
            ),
            game_mode=settings.game_mode,
            kappa_only=kappa,
            dropped_blocks=list(self.active_source.dropped_blocks),
            generated_at=now,
        )


async def poller(state: State) -> None:
    """Background refresh loop. Nothing is ever fetched on a page load."""
    interval = max(60, state.settings.refresh_minutes * 60)
    while True:
        try:
            await asyncio.sleep(interval)
            log.debug("Background refresh")
            await state.refresh_all()
        except asyncio.CancelledError:
            raise
        except Exception:  # a poller that dies takes the whole app stale with it
            log.exception("Background refresh failed; continuing")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    log.info(
        "Settings: mode=%s refresh=%dm kappa_only=%s token=%s",
        settings.game_mode, settings.refresh_minutes, settings.kappa_only,
        "set" if settings.token else "MISSING",
    )
    log.info("Trader levels: %s",
             ", ".join(f"{k} {v}" for k, v in settings.trader_levels.items()))

    state = State(settings)
    app.state.brief_state = state

    await state.refresh_all()
    task = asyncio.create_task(poller(state))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Tarkov Raid Brief",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
)

app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))


def _static_version() -> str:
    """Content hash of the static assets, used as a ?v= cache-buster.

    Browsers heuristically cache /static responses (there is no Cache-Control
    header), and the HA webview held on to 1.1.0's app.js across an add-on
    update - new HTML, old JS, so new buttons had no handlers and did nothing.
    A hash tied to the file contents changes exactly when the files do.
    """
    h = hashlib.md5()
    for name in ("app.css", "app.js"):
        h.update((HERE / "static" / name).read_bytes())
    return h.hexdigest()[:8]


STATIC_V = _static_version()


def _age(seconds: float | None) -> str:
    """Render a data age compactly enough for the header strip."""
    if seconds is None:
        return "never"
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


templates.env.filters["age"] = _age


def _state(request: Request) -> State:
    return request.app.state.brief_state


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Liveness only - deliberately makes no upstream calls."""
    state = _state(request)
    return JSONResponse({
        "status": "ok",
        "tasks_loaded": len(state.tasks),
        "tasks_age_seconds": (
            round(time.time() - state.tasks_fetched) if state.tasks_fetched else None
        ),
        "progress_age_seconds": (
            round(time.time() - state.tracker.fetched_at)
            if state.tracker.fetched_at else None
        ),
        "has_token": bool(state.settings.token),
        "game_mode": state.settings.game_mode,
    })


@app.get("/api/brief")
async def api_brief(
    request: Request,
    map: str | None = Query(None, description="Filter to one map, e.g. customs"),
    kappa_only: bool | None = Query(None),
) -> JSONResponse:
    brief = _state(request).current_brief(kappa_only=kappa_only)
    return JSONResponse(asdict(filter_brief(brief, map)))


@app.post("/api/refresh")
async def api_refresh(request: Request) -> JSONResponse:
    """Force-refresh both upstreams and bust the task cache."""
    state = _state(request)
    await state.refresh_all(force=True)
    brief = state.current_brief()
    return JSONResponse({
        "status": "ok",
        "tasks_loaded": len(state.tasks),
        "warnings": [asdict(w) for w in brief.warnings],
    })


@app.post("/api/trader-standing")
async def api_trader_standing(request: Request) -> JSONResponse:
    """Set loyalty levels and reputation from the standing panel.

    Body is `{"levels": {"prapor": 3}, "reputations": {"fence": -2.5}}`, both
    optional and both partial - the panel sends only what changed. `{"reset":
    true}` throws the overrides away and hands control back to the add-on
    options.

    Every value here changes which tasks are available, so this reports the
    recomputed totals and the page reloads rather than trying to patch the
    lists in place.
    """
    state = _state(request)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body must be a JSON object."}, status_code=400)

    if body.get("reset"):
        state.standing.reset()
    else:
        levels = body.get("levels") if isinstance(body.get("levels"), dict) else None
        reputations = (
            body.get("reputations") if isinstance(body.get("reputations"), dict) else None
        )
        if levels is None and reputations is None:
            return JSONResponse(
                {"error": "Send 'levels' and/or 'reputations' objects, or 'reset': true."},
                status_code=400,
            )
        state.standing.update(levels, reputations)

    brief = state.current_brief()
    return JSONResponse({
        "status": "ok",
        "customised": state.standing.customised,
        "levels": state.standing.levels,
        "reputations": state.standing.reputations,
        "tasks_available": sum(m.task_count for m in brief.maps),
    })


@app.post("/api/ai/map")
async def api_ai_map(
    request: Request,
    map: str = Query(..., description="Map name or normalizedName"),
    force: bool = Query(False, description="Regenerate even if cached"),
) -> JSONResponse:
    """Generate one map's route advice. Explicit user action - costs an API call."""
    state = _state(request)
    if not state.gemini.enabled:
        return JSONResponse({"error": "No Gemini API key configured."}, status_code=400)

    needle = map.strip().lower()
    target = next(
        (m for m in state.current_brief().maps
         if m.name.lower() == needle or m.normalized_name.lower() == needle),
        None,
    )
    if target is None:
        return JSONResponse({"error": f"Unknown map: {map}"}, status_code=404)

    try:
        result = await state.gemini.generate_for_map(
            target, state.player_level, state.player_faction, force=force
        )
    except Exception as exc:  # noqa: BLE001 - surface upstream text to the UI
        log.warning("AI generation failed for %s: %s", target.name, exc)
        state.gemini.last_error = str(exc)[:200]
        return JSONResponse({"error": str(exc)[:200]}, status_code=502)

    return JSONResponse({"text": result.text, "generated_at": result.generated_at,
                         "model": result.model})


@app.post("/api/ai/recommendation")
async def api_ai_recommendation(
    request: Request,
    force: bool = Query(False),
) -> JSONResponse:
    state = _state(request)
    if not state.gemini.enabled:
        return JSONResponse({"error": "No Gemini API key configured."}, status_code=400)
    try:
        result = await state.gemini.generate_for_recommendation(
            score_maps(state.current_brief().maps), force=force
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("AI recommendation failed: %s", exc)
        state.gemini.last_error = str(exc)[:200]
        return JSONResponse({"error": str(exc)[:200]}, status_code=502)
    return JSONResponse({"text": result.text, "generated_at": result.generated_at,
                         "model": result.model})


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    kappa_only: bool | None = Query(None),
    map: str | None = Query(None),
) -> HTMLResponse:
    """The whole page, server-rendered. Never touches an upstream."""
    brief = filter_brief(_state(request).current_brief(kappa_only=kappa_only), map)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"brief": brief, "static_v": STATIC_V},
    )
