"""File-backed catalog of capabilities — the agent-facing invoke surface."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from cuas.models import Capability


class Catalog:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, cap_id: str) -> Path:
        safe = cap_id.replace("/", "_")
        return self.root / f"{safe}.json"

    def save(self, cap: Capability) -> Path:
        path = self._path(cap.id)
        path.write_text(cap.model_dump_json(indent=2), encoding="utf-8")
        return path

    def get(self, cap_id: str) -> Capability:
        path = self._path(cap_id)
        if not path.exists():
            raise FileNotFoundError(cap_id)
        return Capability.model_validate_json(path.read_text())

    def list(self) -> list[Capability]:
        caps = []
        for path in sorted(self.root.glob("*.json")):
            try:
                caps.append(Capability.model_validate_json(path.read_text()))
            except Exception:  # noqa: BLE001
                continue
        return caps


class InvokeRequest(BaseModel):
    params: dict[str, str] = Field(default_factory=dict)


def create_catalog_app(catalog: Catalog) -> FastAPI:
    """Tiny function-calling surface an upstream AI agent can discover and call."""

    app = FastAPI(title="CUAS capability catalog")

    @app.get("/capabilities")
    def list_caps():
        return [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "parameters": [p.model_dump() for p in c.parameters],
                "outputs": [o.model_dump() for o in c.outputs],
                "risk": c.risk,
                "status": c.status,
            }
            for c in catalog.list()
        ]

    @app.get("/capabilities/{cap_id}")
    def get_cap(cap_id: str):
        try:
            return json.loads(catalog.get(cap_id).model_dump_json())
        except FileNotFoundError:
            raise HTTPException(404, "unknown capability") from None

    @app.post("/capabilities/{cap_id}/invoke")
    async def invoke(cap_id: str, body: InvokeRequest):
        # The HTTP catalog is the contract. Actual replay is triggered by the
        # CLI / library so this process does not have to own a browser.
        try:
            cap = catalog.get(cap_id)
        except FileNotFoundError:
            raise HTTPException(404, "unknown capability") from None
        return {
            "accepted": True,
            "capability_id": cap.id,
            "params": body.params,
            "hint": "Run `cuas replay --artifact ... --param k=v` (or cuas.replay.ReplayEngine) to execute without an LLM.",
        }

    return app
