"""Minimal operator console for live-session handoff.

A full co-browsing product is out of scope. This surface lets an operator:
see why we stopped, take control of the *same* session, perform actions
through the same SurfaceAdapter, and hand control back.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from cuas.handoff.session import LiveSession
from cuas.models import ActionType, Target
from cuas.surface.web import WebSurface

PAGE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Operator handoff</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 24px; max-width: 900px; }
    pre { background: #111; color: #d6ffd6; padding: 12px; overflow: auto; font-size: 12px; }
    .banner { padding: 10px 14px; background: #1e3a5f; color: #fff; margin-bottom: 16px; }
    button, input[type=submit] { padding: 6px 12px; margin-right: 8px; }
    .muted { color: #555; }
  </style>
</head>
<body>
  <div class="banner">Heritage Core — operator handoff (same live session)</div>
  <p class="muted">Owner: <b>{{ owner }}</b> · Session {{ session_id }}</p>
  {% if intervention %}
    <h2>Intervention {{ intervention.id }}</h2>
    <p><b>Why:</b> {{ intervention.reason }}</p>
    <p><b>Goal:</b> {{ intervention.goal }}</p>
    <p><b>Status:</b> {{ intervention.status }}</p>
    <pre>{{ intervention.observation_summary }}</pre>
    {% if intervention.screenshot_path %}
      <p><a href="/screenshot">Open last screenshot</a></p>
    {% endif %}
    <form method="post" action="/take"><input type="submit" value="Take control"></form>
    <form method="post" action="/act">
      <p>Act on the live session (ref from the observation, e.g. e3):</p>
      <input name="ref" placeholder="e3">
      <select name="action">
        <option>click</option>
        <option>type</option>
        <option>dismiss</option>
      </select>
      <input name="value" placeholder="value if typing">
      <input type="submit" value="Perform">
    </form>
    <form method="post" action="/resume"><input type="submit" value="Hand back / resume automation"></form>
    <form method="post" action="/abort"><input type="submit" value="Abort run"></form>
    <h3>Human actions recorded</h3>
    <pre>{{ human }}</pre>
  {% else %}
    <p>No open intervention. Automation is in control, or the session has ended.</p>
  {% endif %}
</body>
</html>
"""


def create_operator_app(session: LiveSession, surface: WebSurface | None = None) -> FastAPI:
    app = FastAPI(title="CUAS operator")
    app.state.session = session
    app.state.surface = surface
    app.state.last_obs = None

    @app.get("/", response_class=HTMLResponse)
    async def home():
        from jinja2 import Template

        html = Template(PAGE).render(
            owner=session.owner.value,
            session_id=session.session_id,
            intervention=session.intervention,
            human=session.human_actions,
        )
        return HTMLResponse(html)

    @app.get("/status")
    async def status():
        return {
            "session_id": session.session_id,
            "owner": session.owner.value,
            "intervention": session.intervention.model_dump() if session.intervention else None,
        }

    @app.post("/take")
    async def take():
        session.take_control("operator-ui")
        return RedirectResponse("/", status_code=302)

    @app.post("/act")
    async def act(ref: str = Form(""), action: str = Form("click"), value: str = Form("")):
        session.record_human({"type": action, "ref": ref, "value": value})
        surface = app.state.surface
        if surface is not None:
            obs = await surface.observe()
            app.state.last_obs = obs
            target: Target | None = None
            if ref:
                target = surface.locators_for_ref(obs, ref)
            await surface.act(ActionType(action), target=target, value=value or None)
        return RedirectResponse("/", status_code=302)

    @app.post("/resume")
    async def resume():
        session.hand_back("operator resumed automation")
        return RedirectResponse("/", status_code=302)

    @app.post("/abort")
    async def abort():
        session.abort("operator aborted")
        return RedirectResponse("/", status_code=302)

    @app.get("/screenshot")
    async def screenshot():
        path = session.intervention.screenshot_path if session.intervention else None
        if not path or not Path(path).exists():
            return JSONResponse({"error": "no screenshot"}, status_code=404)
        from fastapi.responses import FileResponse

        return FileResponse(path)

    return app
