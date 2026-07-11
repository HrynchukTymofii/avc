"""Catalog invariants and availability rules."""

from app.config import Settings
from app.models_catalog import CATALOG, default_engine, engines_for, get_engine, is_available
from app.schemas import JobKind


def test_every_kind_has_exactly_one_default() -> None:
    for kind in JobKind:
        defaults = [engine for engine in engines_for(kind) if engine.default]
        assert len(defaults) == 1, kind
        assert default_engine(kind) is defaults[0]


def test_engine_ids_unique_per_kind() -> None:
    for kind in JobKind:
        ids = [engine.id for engine in engines_for(kind)]
        assert len(ids) == len(set(ids)), kind


def test_defaults_are_standard_and_implemented() -> None:
    for kind in JobKind:
        engine = default_engine(kind)
        assert engine.tier == "standard"
        assert engine.implemented


def test_premium_engines_hidden_without_flag() -> None:
    settings = Settings()
    for engine in CATALOG:
        if engine.tier == "premium":
            assert not is_available(engine, settings), engine.id
        elif engine.implemented:
            assert is_available(engine, settings), engine.id


def test_premium_flag_only_enables_implemented_engines() -> None:
    settings = Settings(premium_enabled=True)
    for engine in CATALOG:
        assert is_available(engine, settings) == engine.implemented, engine.id


def test_lookup() -> None:
    assert get_engine(JobKind.IMAGE, "flux-schnell").pipeline == "flux"
    assert get_engine(JobKind.TALKING_HEAD, "musetalk-animate").pipeline == "musetalk"
    assert get_engine(JobKind.IMAGE, "no-such-model") is None
