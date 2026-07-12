"""Model catalog: the selectable engines per job kind, with tier and credit info.

Static data; availability is computed against settings at request time. Premium
engines ship as scaffolds until the H100 tier exists (SERVICE_ARCHITECTURE.md
section 2) — `implemented=False` marks entries that are listed in the UI but
whose pipeline integration has not run on real hardware yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.schemas import JobKind


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    kind: JobKind
    tier: str  # "standard" (L40S) | "premium" (H100)
    credits: str  # display-only cost hint, e.g. "8 / clip"
    pipeline: str  # ManagedPipeline name the processor acquires
    implemented: bool = True
    default: bool = False


CATALOG: tuple[Engine, ...] = (
    # ---- talking head ------------------------------------------------------------
    Engine(
        "musetalk", "Lip-sync (still photo)", JobKind.TALKING_HEAD,
        "standard", "2 / min", "musetalk", default=True,
    ),
    Engine(
        "musetalk-animate", "Animated head (motion + lip-sync)", JobKind.TALKING_HEAD,
        "standard", "4 / min + 10", "musetalk",
    ),
    Engine(
        "wan-s2v-14b", "Full motion (Wan2.2-S2V-14B)", JobKind.TALKING_HEAD,
        "premium", "40 / min", "wan-s2v", implemented=False,
    ),
    # ---- b-roll / video ----------------------------------------------------------
    Engine(
        "wan-5b", "Wan2.2 5B", JobKind.BROLL,
        "standard", "8 / clip", "wan", default=True,
    ),
    # implemented=True but premium-gated: selectable the day an H100 box runs
    # with PREMIUM_ENABLED=true. First run there is still a validation run.
    Engine(
        "wan-a14b", "Wan2.2 A14B — high quality", JobKind.BROLL,
        "premium", "30 / clip", "wan-a14b",
    ),
    Engine(
        "wan-animate-14b", "Character video (Wan2.2-Animate-14B)", JobKind.BROLL,
        "premium", "40 / clip", "wan-animate", implemented=False,
    ),
    # ---- full video ----------------------------------------------------------------
    # One engine: the assembler always narrates with S2, lip-syncs with MuseTalk
    # and generates b-roll/stills on the Wan pipeline (stills deliberately skip
    # FLUX — rendering them inside the same Wan residency avoids a ~34 GB swap).
    Engine(
        "full-video", "Full video (tagged script)", JobKind.FULL_VIDEO,
        "standard", "varies / script", "wan", default=True,
    ),
    # ---- image -------------------------------------------------------------------
    Engine(
        "wan-5b", "Wan2.2 5B (single frame)", JobKind.IMAGE,
        "standard", "1 / image", "wan", default=True,
    ),
    Engine(
        "flux-schnell", "FLUX.1 schnell", JobKind.IMAGE,
        "standard", "2 / image", "flux",
    ),
)


def engines_for(kind: JobKind) -> list[Engine]:
    return [engine for engine in CATALOG if engine.kind is kind]


def get_engine(kind: JobKind, engine_id: str) -> Engine | None:
    for engine in CATALOG:
        if engine.kind is kind and engine.id == engine_id:
            return engine
    return None


def default_engine(kind: JobKind) -> Engine:
    return next(engine for engine in engines_for(kind) if engine.default)


def is_available(engine: Engine, settings: Settings) -> bool:
    if not engine.implemented:
        return False
    return engine.tier == "standard" or settings.premium_enabled
