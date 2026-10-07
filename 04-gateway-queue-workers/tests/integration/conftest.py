from collections.abc import Iterator

import pytest

from tests.integration.stack_control import StackConfig, apply_stack_config


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def restore_default_stack() -> Iterator[None]:
    """Leave the stack as the harness expects it: 3 workers, continuation mode, no autoscaler."""
    yield
    apply_stack_config(StackConfig())
