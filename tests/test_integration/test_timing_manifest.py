"""Integration tests for TimingManifest model logic."""

from __future__ import annotations

import pytest

from src.models import TimingManifest, TimingSegment


@pytest.mark.integration
class TestTimingManifest:
    def test_slot_durations_sum_correctly(self):
        segments = [
            TimingSegment(id=f"seg{i}", start_ms=i * 1000, end_ms=(i + 1) * 1000)
            for i in range(5)
        ]
        manifest = TimingManifest(total_duration_ms=5000, segments=segments)

        durations = [manifest.slot_duration_ms(i) for i in range(len(segments))]

        # First 4 slots span 1000ms each (gap between consecutive starts)
        for d in durations[:-1]:
            assert d == 1000
        # Last slot: end_ms - start_ms
        assert durations[-1] == segments[-1].end_ms - segments[-1].start_ms
        assert sum(durations) == 5000

    def test_manifest_json_roundtrip(self, tmp_path):
        segments = [
            TimingSegment(id=f"seg{i}", start_ms=i * 500, end_ms=(i + 1) * 500, text=f"Line {i}")
            for i in range(5)
        ]
        original = TimingManifest(total_duration_ms=2500, segments=segments)

        path = tmp_path / "manifest.json"
        path.write_text(original.model_dump_json(indent=2))

        loaded = TimingManifest.model_validate_json(path.read_text())

        assert loaded == original
        assert len(loaded.segments) == 5
