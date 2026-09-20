from __future__ import annotations

import os

import uvicorn

from corebank.app import create_app


def main() -> None:
    host = os.getenv("COREBANK_HOST", "127.0.0.1")
    port = int(os.getenv("COREBANK_PORT", "8787"))
    brand = os.getenv("COREBANK_BRAND", "heritage")
    uvicorn.run(create_app(brand), host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
