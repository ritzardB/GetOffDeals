import sys
from pathlib import Path

# Ensure the GetOffDeals project root is importable during pytest startup.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import app as app_module


@pytest.fixture()
def client():
    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-secret",
    )
    with app_module.app.test_client() as test_client:
        yield test_client
