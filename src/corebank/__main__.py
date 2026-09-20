from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("COREBANK_HOST", "127.0.0.1")
    port = int(os.getenv("COREBANK_PORT", "8787"))
    uvicorn.run("corebank.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
