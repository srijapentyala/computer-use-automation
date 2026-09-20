from __future__ import annotations

import threading
import time

import httpx
import pytest
import uvicorn

from corebank.app import create_app


@pytest.fixture(scope="session")
def corebank_url():
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=8799, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = "http://127.0.0.1:8799/"
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            if httpx.get(url + "health", timeout=0.2).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("Heritage Core failed to start")
    yield url
    server.should_exit = True
