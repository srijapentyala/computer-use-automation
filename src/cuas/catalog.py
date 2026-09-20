"""File-backed catalog of capabilities — the agent-facing invoke surface."""

from __future__ import annotations

import json
import os
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
        if path.exists():
            return Capability.model_validate_json(path.read_text())
        for candidate in sorted(self.root.glob("*.json")):
            try:
                cap = Capability.model_validate_json(candidate.read_text())
            except Exception:  # noqa: BLE001
                continue
            if cap.id == cap_id:
                return cap
        raise FileNotFoundError(cap_id)

    def list(self) -> list[Capability]:
        caps = []
        seen = set()
        for path in sorted(self.root.glob("*.json")):
            try:
                cap = Capability.model_validate_json(path.read_text())
            except Exception:  # noqa: BLE001
                continue
            key = (cap.id, cap.tenant.tenant_id)
            if key in seen:
                continue
            seen.add(key)
            caps.append(cap)
        return caps


class InvokeRequest(BaseModel):
    params: dict[str, str] = Field(default_factory=dict)
    tenant_id: str | None = None


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
                "tenant": c.tenant.model_dump(),
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
        try:
            cap = catalog.get(cap_id)
        except FileNotFoundError:
            raise HTTPException(404, "unknown capability") from None
        if body.tenant_id:
            for candidate in catalog.list():
                if candidate.id == cap_id and candidate.tenant.tenant_id == body.tenant_id:
                    cap = candidate
                    break
        os.environ.setdefault("COREBANK_USER", "teller")
        os.environ.setdefault("COREBANK_PASSWORD", "teller")
        from cuas.config import Policy
        from cuas.evidence import EvidenceLog
        from cuas.replay import ReplayEngine
        from cuas.surface.web import WebSurface

        policy = Policy.load(Path(__file__).resolve().parents[2] / "policies" / "default.yaml")
        surface, browser, context = await WebSurface.launch(headless=True)
        try:
            engine = ReplayEngine(
                surface, policy, evidence=EvidenceLog(Path("runs"), f"catalog-{cap_id}")
            )
            result = await engine.run(cap, body.params)
            return json.loads(result.model_dump_json())
        finally:
            await context.close()
            await browser.close()

    return app
