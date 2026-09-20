"""CLI: discover, replay, demo target, operator, catalog."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Optional
from uuid import uuid4

import typer
import uvicorn
from dotenv import load_dotenv
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

from cuas.agent.llm import build_llm
from cuas.agent.loop import DiscoveryRunner
from cuas.catalog import Catalog, create_catalog_app
from cuas.config import Policy, Settings
from cuas.evidence import EvidenceLog
from cuas.handoff.operator import create_operator_app
from cuas.handoff.session import LiveSession
from cuas.models import Capability
from cuas.replay import ReplayEngine
from cuas.surface.web import WebSurface

load_dotenv()

app = typer.Typer(help="Computer-use automation system (discover → artifact → replay).")
console = Console()
ROOT = Path(__file__).resolve().parents[2]


def _policy() -> Policy:
    return Policy.load(ROOT / "policies" / "default.yaml")


def _parse_params(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise typer.BadParameter(f"expected key=value, got {item}")
        k, v = item.split("=", 1)
        out[k] = v
    return out


def _print_result(result) -> None:
    console.print(Panel(JSON.from_data(json.loads(result.model_dump_json())), title="result"))


def _start_corebank(host: str, port: int) -> None:
    from corebank.app import app as core_app

    config = uvicorn.Config(core_app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()


@app.command()
def target(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8787),
):
    """Run the Heritage Core teller-console stand-in."""
    console.print(f"Heritage Core on http://{host}:{port}/  (teller / teller)")
    uvicorn.run("corebank.app:app", host=host, port=port, reload=False)


@app.command()
def discover(
    goal: str = typer.Option(..., "--goal", help="Natural-language goal"),
    url: str = typer.Option("http://127.0.0.1:8787/", help="Entry URL of the target app"),
    llm: str = typer.Option("openai", help="openai | anthropic | scripted"),
    headed: bool = typer.Option(False, help="Show the browser window"),
    out: Path = typer.Option(Path("artifacts"), help="Directory for the compiled capability"),
    evidence_dir: Path = typer.Option(Path("runs"), help="Evidence root"),
    start_target: bool = typer.Option(False, "--start-target", help="Boot Heritage Core in-process"),
):
    """LLM-driven observe→decide→act run; compile a reusable capability on success."""

    async def _run() -> None:
        if start_target:
            _start_corebank("127.0.0.1", 8787)
            await asyncio.sleep(0.4)
        settings = Settings()
        os.environ.setdefault("COREBANK_USER", "teller")
        os.environ.setdefault("COREBANK_PASSWORD", "teller")
        run_id = "discover-" + uuid4().hex[:8]
        evidence = EvidenceLog(evidence_dir, run_id)
        session = LiveSession()
        surface, browser, context = await WebSurface.launch(headless=not headed, start_url=None)
        try:
            runner = DiscoveryRunner(
                surface,
                build_llm(llm, settings),
                _policy(),
                session=session,
                evidence=evidence,
                start_url=url,
            )
            result, cap = await runner.run(goal)
            _print_result(result)
            if cap:
                out.mkdir(parents=True, exist_ok=True)
                path = Catalog(out).save(cap)
                console.print(f"[green]wrote capability[/green] {path}")
                evidence.dump_text("capability.json", cap.model_dump_json(indent=2))
            else:
                console.print("[yellow]no capability emitted (run did not complete successfully)[/yellow]")
            console.print(f"evidence: {evidence.dir}")
        finally:
            await context.close()
            await browser.close()

    asyncio.run(_run())


@app.command()
def replay(
    artifact: Path = typer.Option(..., exists=True, help="Capability JSON"),
    param: list[str] = typer.Option([], help="Repeatable key=value input"),
    headed: bool = typer.Option(False),
    evidence_dir: Path = typer.Option(Path("runs")),
    start_target: bool = typer.Option(False, "--start-target"),
    url: Optional[str] = typer.Option(None, help="Override artifact entry URL"),
):
    """Replay a saved capability with no LLM in the loop."""

    async def _run() -> None:
        if start_target:
            _start_corebank("127.0.0.1", 8787)
            await asyncio.sleep(0.4)
        os.environ.setdefault("COREBANK_USER", "teller")
        os.environ.setdefault("COREBANK_PASSWORD", "teller")
        cap = Capability.model_validate_json(artifact.read_text())
        if url:
            cap.app.entry_url = url
        run_id = "replay-" + uuid4().hex[:8]
        evidence = EvidenceLog(evidence_dir, run_id)
        surface, browser, context = await WebSurface.launch(headless=not headed)
        try:
            engine = ReplayEngine(surface, _policy(), evidence=evidence)
            result = await engine.run(cap, _parse_params(param))
            _print_result(result)
            evidence.dump_text("result.json", result.model_dump_json(indent=2))
            console.print(f"evidence: {evidence.dir}")
            if not result.ok:
                raise typer.Exit(2)
        finally:
            await context.close()
            await browser.close()

    asyncio.run(_run())


@app.command("operator")
def operator_cmd(
    port: int = typer.Option(8788),
):
    """Mock operator console. Pair with a live discover/replay session in another process
    by pointing both at the same runs/handoff directory — see REPORT.md.
    """
    session = LiveSession()
    app_ = create_operator_app(session, surface=None)
    console.print(f"Operator console on http://127.0.0.1:{port}/")
    uvicorn.run(app_, host="127.0.0.1", port=port, log_level="info")


@app.command("catalog")
def catalog_cmd(
    artifacts: Path = typer.Option(Path("artifacts")),
    port: int = typer.Option(8789),
):
    """Expose saved capabilities as an agent-invocable catalog."""
    api = create_catalog_app(Catalog(artifacts))
    console.print(f"Catalog on http://127.0.0.1:{port}/capabilities")
    uvicorn.run(api, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    app()
