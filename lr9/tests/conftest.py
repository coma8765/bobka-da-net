from dataclasses import replace
from uuid import uuid4

import pytest

from src.cache import StatisticsCache, redis_client
from src.config import ROOT, Config
from src.repository import Repository
from src.snapshot import exclusive_target, restore_snapshot


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", help="Run PostgreSQL/Redis tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Pass --integration for real services"))


@pytest.fixture
def database_config():
    config = replace(Config.from_env(), database="supply_lab_lr9_test")
    with exclusive_target(config):
        restore_snapshot(config, ROOT / "snapshots/baseline.dump")
        yield config


@pytest.fixture
def repository(database_config):
    with database_config.connect() as connection:
        yield Repository(connection)


@pytest.fixture
def cache():
    client = redis_client(Config.from_env().redis_url)
    client.ping()
    result = StatisticsCache(client, f"test-{uuid4().hex}")
    try:
        yield result
    finally:
        client.delete(result.key)
        client.close()
