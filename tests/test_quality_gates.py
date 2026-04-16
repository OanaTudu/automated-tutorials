"""Tests for quality_gates.validate_script — pure logic, no mocking needed."""

from __future__ import annotations

from src.models import Section, Shot, TutorialScript
from src.quality_gates import validate_script

# ── Fixtures ─────────────────────────────────────────────────────────────


def _script(**overrides) -> TutorialScript:
    """Build a default-valid script, applying keyword overrides."""
    defaults = dict(
        topic="testing",
        audience="data scientists",
        total_target_seconds=240,
        estimated_words=500,
        hook=(
            "Welcome to this comprehensive tutorial where we will "
            "walk through the essential concepts step by step!"
        ),
        sections=[
            Section(
                id=f"s{i}",
                title=f"Section {i}",
                target_seconds=60,
                narration=(
                    f"In this section number {i} we will explore important concepts "
                    "that every data scientist needs to understand for their daily "
                    "workflow and practical analysis tasks in real projects."
                ),
                key_points=["key concept"],
                shots=[Shot(id=f"s{i}-shot1", start_sec=0, end_sec=10, visual="v", action="a")],
            )
            for i in range(1, 4)
        ],
        recap=(
            "We covered all the key topics in this tutorial including practical "
            "examples and real world applications for data scientists."
        ),
        cta="Subscribe for more!",
    )
    defaults.update(overrides)
    return TutorialScript(**defaults)


# ── Passing script ───────────────────────────────────────────────────────


def test_valid_script_passes_all_gates():
    errors = validate_script(_script(), max_seconds=300)
    assert errors == []


# ── Duration cap ─────────────────────────────────────────────────────────


def test_duration_over_cap():
    # Use model_construct to bypass Pydantic le=300 constraint for testing
    script = _script()
    script = script.model_copy(update={"total_target_seconds": 310})
    object.__setattr__(script, "total_target_seconds", 310)
    errors = validate_script(script, max_seconds=300)
    assert any("exceeds" in e for e in errors)


def test_duration_at_cap_passes():
    errors = validate_script(_script(total_target_seconds=300), max_seconds=300)
    assert not any("exceeds" in e for e in errors)


# ── Pacing range ─────────────────────────────────────────────────────────


def test_too_sparse():
    # Very few words for a long target → sparse
    errors = validate_script(_script(estimated_words=50, total_target_seconds=240))
    assert any("sparse" in e for e in errors)


def test_too_dense():
    # Many words for a short target → dense
    errors = validate_script(_script(estimated_words=2000, total_target_seconds=120))
    assert any("dense" in e for e in errors)


# ── Section count ────────────────────────────────────────────────────────


def test_too_few_sections():
    sections = [
        Section(
            id="s1",
            title="Only",
            target_seconds=60,
            narration="n",
            key_points=["a"],
            shots=[Shot(id="shot1", start_sec=0, end_sec=10, visual="v", action="a")],
        ),
    ]
    # Adjust total to match 1 section so model validator passes (tests section count gate)
    errors = validate_script(_script(sections=sections, total_target_seconds=70))
    assert any("3-5 sections" in e for e in errors)


def test_too_many_sections():
    sections = [
        Section(
            id=f"s{i}",
            title=f"S{i}",
            target_seconds=30,
            narration="n",
            key_points=["a"],
            shots=[Shot(id=f"shot{i}", start_sec=0, end_sec=10, visual="v", action="a")],
        )
        for i in range(7)
    ]
    errors = validate_script(_script(sections=sections))
    assert any("3-5 sections" in e for e in errors)


# ── Shot timing ──────────────────────────────────────────────────────────


def test_shot_invalid_timing():
    # Use model_construct to bypass Shot validator — quality gate is defense-in-depth
    bad_shot = Shot.model_construct(
        id="bad1", start_sec=10, end_sec=5, visual="v", action="a", on_screen_text=""
    )
    bad_sections = [
        Section.model_construct(
            id="s1",
            title="Broken Shot",
            target_seconds=60,
            narration="n",
            key_points=["a"],
            shots=[bad_shot],
        ),
        Section(
            id="s2",
            title="OK",
            target_seconds=60,
            narration="n",
            key_points=["a"],
            shots=[Shot(id="ok1", start_sec=0, end_sec=5, visual="v", action="a")],
        ),
        Section(
            id="s3",
            title="OK2",
            target_seconds=60,
            narration="n",
            key_points=["a"],
            shots=[Shot(id="ok2", start_sec=0, end_sec=5, visual="v", action="a")],
        ),
    ]
    errors = validate_script(_script(sections=bad_sections))
    assert any("bad1" in e and "invalid timing" in e for e in errors)


def test_shot_zero_length_is_invalid():
    # Use model_construct to bypass Shot validator for the zero-length shot
    zero_shot = Shot.model_construct(
        id="zero1", start_sec=5, end_sec=5, visual="v", action="a", on_screen_text=""
    )
    sections = [
        Section.model_construct(
            id="s1",
            title="S1",
            target_seconds=60,
            narration="n",
            key_points=["a"],
            shots=[zero_shot],
        ),
        Section(
            id="s2",
            title="S2",
            target_seconds=60,
            narration="n",
            key_points=["a"],
            shots=[Shot(id="ok2", start_sec=0, end_sec=10, visual="v", action="a")],
        ),
        Section(
            id="s3",
            title="S3",
            target_seconds=60,
            narration="n",
            key_points=["a"],
            shots=[Shot(id="ok3", start_sec=0, end_sec=10, visual="v", action="a")],
        ),
    ]
    errors = validate_script(_script(sections=sections))
    assert any("zero1" in e for e in errors)


# ── Content safety ───────────────────────────────────────────────────────


def test_unverified_claims_flagged():
    sections = [
        Section(
            id=f"s{i}",
            title=f"S{i}",
            target_seconds=60,
            narration="This claim needs_verification before publication."
            if i == 2
            else "Safe content.",
            key_points=["a"],
            shots=[Shot(id=f"shot{i}", start_sec=0, end_sec=10, visual="v", action="a")],
        )
        for i in range(1, 4)
    ]
    errors = validate_script(_script(sections=sections))
    assert any("unverified" in e.lower() for e in errors)


# ── Multiple errors ──────────────────────────────────────────────────────


def test_multiple_errors_reported():
    script = _script(estimated_words=50)
    object.__setattr__(script, "total_target_seconds", 310)
    errors = validate_script(script, max_seconds=300)
    assert len(errors) >= 2
