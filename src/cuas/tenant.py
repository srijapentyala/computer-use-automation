"""Apply per-tenant overrides to a vendor-default capability."""

from __future__ import annotations

from cuas.models import Capability, LocatorStrategy


def apply_overrides(cap: Capability) -> Capability:
    """Return a copy with tenant locator names / entry URL applied.

    The recorded flow stays vendor_default. A tenant that relabelled a button
    records `locator_names` for those step ids instead of a new discovery run.
    """
    cap = cap.model_copy(deep=True)
    ov = cap.tenant.overrides or {}
    if not ov:
        return cap
    if ov.get("entry_url"):
        cap.app.entry_url = str(ov["entry_url"])
    names = ov.get("locator_names") or {}
    for step in cap.steps:
        new_name = names.get(step.id)
        if not new_name or not step.target:
            continue
        for loc in step.target.locators:
            if loc.strategy is LocatorStrategy.ROLE_NAME and loc.name:
                loc.name = str(new_name)
                loc.why = f"Tenant override: accessible name is {new_name!r}."
    texts = ov.get("checkpoint_text") or {}
    for cp in cap.checkpoints:
        if cp.id in texts:
            cp.text = str(texts[cp.id])
    return cap
