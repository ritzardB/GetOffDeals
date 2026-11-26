import sys
from pathlib import Path

# Ensure the GetOffDeals project root is importable during pytest startup.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import app as app_module
from flask.sessions import SecureCookieSessionInterface


@pytest.fixture()
def client():
    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-secret",
    )

    original_session_interface = app_module.app.session_interface
    app_module.app.session_interface = SecureCookieSessionInterface()

    try:
        with app_module.app.test_client() as test_client:
            yield test_client
    finally:
        app_module.app.session_interface = original_session_interface
