import pytest

from mcpharness.config import HarnessSettings, load_harness_settings


@pytest.fixture(scope="session")
def harness_settings() -> HarnessSettings:
    return load_harness_settings()
