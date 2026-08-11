"""Dataclasses and runtime settings for the raid brief.

Everything the UI renders is a plain dataclass here; `asdict()` on a Brief
produces exactly the `/api/brief` JSON payload, so the HTML template and the
API can never drift apart.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Order matters: this is the order the trader config is displayed/logged in.
TRADERS = (
    "prapor", "therapist", "fence", "skier", "peacekeeper",
    "mechanic", "ragman", "jaeger", "ref", "lightkeeper",
)

ANY_MAP = "Any map"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.environ.get(name, "").strip())))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Resolved add-on options. Built once at startup from run.sh's env vars."""

    token: str = ""
    game_mode: str = "regular"
    refresh_minutes: int = 60
    kappa_only: bool = False
    data_dir: Path = Path("/data")
    trader_levels: dict[str, int] = field(default_factory=lambda: {t: 1 for t in TRADERS})
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    # Maps to hide entirely - event maps, or ones you have not unlocked.
    # Matched case-insensitively against both name and normalizedName.
    excluded_maps: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls) -> "Settings":
        mode = (os.environ.get("RAIDBRIEF_GAME_MODE") or "regular").strip().lower()
        if mode not in ("regular", "pve"):
            mode = "regular"
        return cls(
            token=(os.environ.get("RAIDBRIEF_TOKEN") or "").strip(),
            game_mode=mode,
            refresh_minutes=_env_int("RAIDBRIEF_REFRESH_MINUTES", 60, 5, 1440),
            kappa_only=_env_bool("RAIDBRIEF_KAPPA_ONLY"),
            data_dir=Path(os.environ.get("RAIDBRIEF_DATA_DIR") or "/data"),
            trader_levels={
                t: _env_int(f"RAIDBRIEF_TRADER_{t.upper()}", 1, 1, 4) for t in TRADERS
            },
            gemini_api_key=(os.environ.get("RAIDBRIEF_GEMINI_KEY") or "").strip(),
            gemini_model=(os.environ.get("RAIDBRIEF_GEMINI_MODEL")
                          or "gemini-2.5-flash").strip(),
            excluded_maps=frozenset(
                part.strip().lower()
                for part in (os.environ.get("RAIDBRIEF_EXCLUDED_MAPS") or "").split(",")
                if part.strip()
            ),
        )

    def is_excluded(self, name: str, normalized_name: str = "") -> bool:
        if not self.excluded_maps:
            return False
        return (name or "").lower() in self.excluded_maps or (
            bool(normalized_name) and normalized_name.lower() in self.excluded_maps
        )

    @property
    def tracker_game_mode(self) -> str:
        """TarkovTracker calls it 'pvp'; tarkov.dev calls the same thing 'regular'."""
        return "pve" if self.game_mode == "pve" else "pvp"


@dataclass
class TaskBrief:
    """One task, as it appears on one specific map."""

    id: str
    name: str
    trader: str
    min_level: int
    xp: int
    kappa: bool
    wiki: str | None
    carry: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    loot: list[str] = field(default_factory=list)
    do: list[str] = field(default_factory=list)


@dataclass
class MapBrief:
    name: str
    normalized_name: str
    tasks: list[TaskBrief] = field(default_factory=list)
    carry: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    loot: list[str] = field(default_factory=list)
    # AI narration. Advisory only - it is never allowed to alter the three
    # lists above, which come from tarkov.dev data alone.
    ai_text: str | None = None
    ai_generated_at: float | None = None

    @property
    def task_count(self) -> int:
        return len(self.tasks)


@dataclass
class PlayerInfo:
    name: str = "player"
    level: int = 1
    faction: str = "USEC"
    tasks_complete: int = 0
    has_token: bool = False


@dataclass
class Warning_:
    """A non-fatal problem worth showing as a banner instead of a stack trace."""

    kind: str  # "auth" | "ratelimit" | "stale" | "degraded" | "upstream"
    message: str


@dataclass
class Recommendation:
    """The computed best map to run next, plus the arithmetic behind it."""

    name: str
    normalized_name: str
    reasons: list[str] = field(default_factory=list)
    completable: int = 0
    completable_xp: int = 0
    tasks: int = 0
    kappa: int = 0
    keys: int = 0
    ai_text: str | None = None


@dataclass
class Brief:
    maps: list[MapBrief] = field(default_factory=list)
    # Names dropped by `excluded_maps`, so the UI can say the setting is live.
    hidden_maps: list[str] = field(default_factory=list)
    recommendation: Recommendation | None = None
    ai_enabled: bool = False
    player: PlayerInfo = field(default_factory=PlayerInfo)
    warnings: list[Warning_] = field(default_factory=list)
    tasks_age_seconds: float | None = None
    progress_age_seconds: float | None = None
    game_mode: str = "regular"
    kappa_only: bool = False
    dropped_blocks: list[str] = field(default_factory=list)
    generated_at: float = 0.0
