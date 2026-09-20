"""Heritage Core — a deliberately hostile stand-in for a legacy teller console.

No test IDs, nested tables, unlabeled inputs, iframe chrome, and real
business-exception states (not-found, closed, validation, interstitial,
session expiry, irreversible transfer).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from corebank.branding import get_brand
from corebank.data import MEMBERS, VALID_PASSWORD, VALID_USER, money

ROOT = Path(__file__).parent


def create_app(brand_id: str | None = None) -> FastAPI:
    brand = get_brand(brand_id or os.getenv("COREBANK_BRAND", "heritage"))
    app = FastAPI(title=f"{brand.product} Teller Console", docs_url=None, redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=os.getenv("COREBANK_SECRET", "dev-only"))
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    templates.env.globals["money"] = money
    templates.env.globals["brand"] = brand

    def logged_in(request: Request) -> bool:
        return bool(request.session.get("user"))

    def current_member(request: Request):
        mid = request.session.get("member_id")
        return MEMBERS.get(mid) if mid else None

    @app.get("/", response_class=HTMLResponse)
    def root(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(request, "shell.html", {})

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, error: str | None = None):
        return templates.TemplateResponse(request, "login.html", {"error": error})

    @app.post("/login")
    def login(request: Request, f1: str = Form(""), f2: str = Form("")):
        if f1 == VALID_USER and f2 == VALID_PASSWORD:
            request.session["user"] = f1
            request.session.pop("expired", None)
            return RedirectResponse("/", status_code=302)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid operator credentials."}, status_code=401
        )

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=302)

    @app.get("/nav", response_class=HTMLResponse)
    def nav(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(
            request, "nav.html", {"user": request.session.get("user")}
        )

    @app.get("/welcome", response_class=HTMLResponse)
    def welcome(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(request, "welcome.html", {})

    @app.get("/timeout", response_class=HTMLResponse)
    def timeout(request: Request):
        request.session.clear()
        request.session["expired"] = True
        return templates.TemplateResponse(request, "timeout.html", {})

    @app.get("/search", response_class=HTMLResponse)
    def search(
        request: Request,
        memid: str = "",
        ssn4: str = "",
        lname: str = "",
        inject: str | None = Query(default=None),
    ):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        if inject == "batch" or request.session.get("force_batch"):
            request.session["force_batch"] = True
            return templates.TemplateResponse(request, "batch.html", {})
        if inject == "timeout":
            return RedirectResponse("/timeout", status_code=302)

        error = None
        member = None
        if memid:
            member = MEMBERS.get(memid.strip())
            if member is None:
                error = "No matching member found."
            else:
                request.session["member_id"] = member.member_id
        return templates.TemplateResponse(
            request,
            "search.html",
            {"memid": memid, "error": error, "member": member},
        )

    @app.get("/member", response_class=HTMLResponse)
    def member_record(request: Request, id: str = ""):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        member = MEMBERS.get(id) or current_member(request)
        if not member:
            return RedirectResponse("/search", status_code=302)
        request.session["member_id"] = member.member_id
        return templates.TemplateResponse(request, "member.html", {"member": member})

    @app.get("/open", response_class=HTMLResponse)
    def open_form(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(
            request, "open.html", {"member": current_member(request), "error": None}
        )

    @app.post("/open", response_class=HTMLResponse)
    def open_submit(
        request: Request,
        prod: str = Form("Savings"),
        nick: str = Form(""),
        dep: str = Form(""),
    ):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        member = current_member(request)
        if not member:
            return templates.TemplateResponse(
                request, "open.html", {"member": None, "error": None}
            )
        try:
            amount = float(dep.replace("$", "").replace(",", "").strip())
            if amount < 0:
                raise ValueError("negative")
        except (TypeError, ValueError):
            return templates.TemplateResponse(
                request,
                "open.html",
                {
                    "member": member,
                    "error": "Opening deposit must be a non-negative amount.",
                },
            )
        confirmation = "CNF-" + secrets.token_hex(3).upper()
        number = f"SV-{secrets.randbelow(900000) + 100000}"
        return templates.TemplateResponse(
            request,
            "confirm.html",
            {
                "member": member,
                "product": prod,
                "number": number,
                "deposit": money(amount),
                "confirmation": confirmation,
                "nickname": nick,
            },
        )

    @app.get("/transfer", response_class=HTMLResponse)
    def transfer_form(request: Request):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(
            request, "transfer.html", {"member": current_member(request), "error": None}
        )

    @app.post("/transfer", response_class=HTMLResponse)
    def transfer_submit(
        request: Request,
        src: str = Form(""),
        dst: str = Form(""),
        amt: str = Form(""),
    ):
        if not logged_in(request):
            return RedirectResponse("/login", status_code=302)
        member = current_member(request)
        if not member:
            return templates.TemplateResponse(
                request, "transfer.html", {"member": None, "error": None}
            )
        try:
            amount = float(amt.replace("$", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return templates.TemplateResponse(
                request,
                "transfer.html",
                {"member": member, "error": "Please correct the highlighted fields. Amount is required."},
            )
        source = next((a for a in member.accounts if a.number == src), None)
        if source and amount > source.balance:
            return templates.TemplateResponse(
                request,
                "transfer.html",
                {"member": member, "error": "Insufficient funds."},
            )
        return HTMLResponse(
            "<html><body><p>Transfer posted.</p></body></html>"
        )

    @app.post("/dismiss-batch")
    def dismiss_batch(request: Request):
        request.session.pop("force_batch", None)
        return RedirectResponse("/search", status_code=302)

    @app.get("/health")
    def health():
        return {"ok": True, "app": "heritage_core", "brand": brand.id}

    return app


app = create_app()
