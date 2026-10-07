import pytest

from mcpharness.config import load_harness_settings
from mcpharness.constants import ALL_SUITES


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Apply the phase's expectations: skip suites that don't apply, mark expected failures."""
    settings = load_harness_settings()
    for item in items:
        item_suites = {marker.name for marker in item.iter_markers()} & ALL_SUITES
        if item_suites & settings.skipped_suites:
            item.add_marker(pytest.mark.skip(reason="suite does not apply to this phase"))
        elif item_suites & settings.expected_failures:
            item.add_marker(
                pytest.mark.xfail(strict=True, reason="expected to fail for this phase")
            )
