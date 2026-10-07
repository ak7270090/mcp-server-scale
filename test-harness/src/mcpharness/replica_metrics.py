"""Counts which replica served each call and writes Markdown reports."""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


class ReplicaDistribution:
    """How many calls each serving unit (replica, or replica/process) handled."""

    def __init__(self) -> None:
        self._call_counts: Counter[str] = Counter()
        self.failed_call_count = 0

    def record(self, serving_unit: str) -> None:
        self._call_counts[serving_unit] += 1

    def record_failure(self) -> None:
        self.failed_call_count += 1

    @property
    def serving_unit_count(self) -> int:
        return len(self._call_counts)

    @property
    def total_call_count(self) -> int:
        return sum(self._call_counts.values())

    def shares(self) -> dict[str, float]:
        total = self.total_call_count
        return {unit: count / total for unit, count in sorted(self._call_counts.items())}

    def max_share_deviation(self, expected_unit_count: int) -> float:
        """Largest gap between a unit's share and the even share ``1 / expected_unit_count``."""
        even_share = 1 / expected_unit_count
        return max((abs(share - even_share) for share in self.shares().values()), default=1.0)

    def to_markdown_table(self) -> str:
        rows = ["| Serving unit | Calls | Share |", "|---|---|---|"]
        for unit, share in self.shares().items():
            rows.append(f"| `{unit}` | {self._call_counts[unit]} | {share:.1%} |")
        rows.append(f"| failed calls | {self.failed_call_count} | |")
        return "\n".join(rows)


def write_markdown_report(report_path: Path, title: str, body: str) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_path.write_text(f"# {title}\n\nGenerated {generated_at}\n\n{body}\n", encoding="utf-8")
    return report_path
