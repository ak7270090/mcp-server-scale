from pathlib import Path

import pytest

from mcpharness.replica_metrics import ReplicaDistribution, write_markdown_report


def build_distribution(call_counts: dict[str, int]) -> ReplicaDistribution:
    distribution = ReplicaDistribution()
    for serving_unit, call_count in call_counts.items():
        for _ in range(call_count):
            distribution.record(serving_unit)
    return distribution


def test_even_spread_has_no_deviation() -> None:
    distribution = build_distribution({"replica-1": 10, "replica-2": 10})

    assert distribution.serving_unit_count == 2
    assert distribution.max_share_deviation(expected_unit_count=2) == pytest.approx(0.0)


def test_uneven_spread_reports_largest_gap() -> None:
    distribution = build_distribution({"replica-1": 30, "replica-2": 10})

    assert distribution.max_share_deviation(expected_unit_count=2) == pytest.approx(0.25)


def test_empty_distribution_counts_as_fully_uneven() -> None:
    assert ReplicaDistribution().max_share_deviation(expected_unit_count=3) == 1.0


def test_report_lists_units_and_failures(tmp_path: Path) -> None:
    distribution = build_distribution({"replica-1": 3})
    distribution.record_failure()

    report_path = write_markdown_report(
        tmp_path / "nested" / "report.md", "Title", distribution.to_markdown_table()
    )

    report_text = report_path.read_text(encoding="utf-8")
    assert "| `replica-1` | 3 | 100.0% |" in report_text
    assert "| failed calls | 1 | |" in report_text
