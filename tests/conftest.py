import pytest

from local_data_mcp.seed import seed
from local_data_mcp.server import create_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    return seed(tmp_path_factory.mktemp("data") / "store.db")


@pytest.fixture
def server(db_path):
    return create_server(str(db_path))
