# Design write-up

## 1. Architecture

Two execution paths share one surface and one artifact:

1. **Discovery.** An LLM (or a test-only scripted adapter) runs observe → decide → act against a live UI. It never invents selectors. Each observation is an inventory of numbered controls (`e0`, `e1`, …) with role, adjacent label, frame, and pre-ranked locators. The model picks a `ref`; the runtime stores the locators, not the ref.
2. **Replay.** A capability is a typed JSON contract. Replay substitutes parameters, walks the step list, and never calls a model. This is the production path an upstream agent invokes.

The **surface adapter** is the seam between “how we perceive/act” and “the recorded flow.” Today that adapter is Playwright over a web page, but the capability schema talks in actions + ranked locators + frames, not in CSS. A desktop adapter would implement the same protocol against an OS accessibility tree.

I implemented against a local stand-in (**Heritage Core**) rather than a public demo site: it lets me own the exception states the brief cares about (not-found, closed, validation, interstitial, timeout, irreversible transfer) without fighting a third party’s terms, and the DOM is intentionally hostile (iframes, nested tables, no test IDs, unlabeled inputs). That is closer to a core-banking screen than a clean React app.

Single-process CLI over services: one operator, one browser, one policy file. Queues and multi-tenant plumbing would pretend at scale we do not have.

## 2. Artifact schema

A capability is an agent-invocable tool, not a transcript.

- **Identity:** `id`, `version`, `status` (`draft` → `approved`), `goal_template`.
- **Binding:** `app` (vendor + app_id + surface + entry URL) and `tenant` (`vendor_default` plus optional locator/URL overrides). The flow is recorded against the vendor product, not against “First National of X.”
- **Contract:** typed `parameters` and `outputs` so a calling agent knows what to pass and what it gets back.
- **Steps:** ordered actions with a **ranked locator list**, optional frame name, wait policy, and an input source (`from_parameter` | `literal` | `secret_env`). Secrets never become parameters.
- **Checkpoints:** assertions that we actually arrived (e.g. “Member Record” visible, declared outputs present).
- **Outcomes:** detectors that map UI text to a **business code** (`MEMBER_NOT_FOUND`) or a **recoverable** condition (`BATCH_INTERSTITIAL` → dismiss). These travel with the artifact so replay does not treat “no such member” as a crash.

Locator rank is deliberate: accessible role+name, then adjacent-cell text (the legacy-table case), then placeholder, then visible text, then CSS as a last resort with a low confidence and a written `why`. Replay tries them in order.

## 3. Determinism & error handling

Determinism comes from not letting the model back into the loop. Same capability + params → same steps, same locators, same waits. Values that belonged to the goal become parameters; operator credentials bind to env vars.

After every step replay re-reads the page and classifies:

| Class | Example | Caller sees |
| --- | --- | --- |
| **Business outcome** | “No matching member found” | `kind=business_outcome`, `business_code=MEMBER_NOT_FOUND` (`ok=true`) |
| **Recoverable** | Nightly batch overlay | Dismiss, continue |
| **Hard failure** | Locator miss, checkpoint miss, policy deny | `kind=failure` with step id, expected, observed, locators tried, screenshot |

UI drift is secondary here — these apps change slowly — but ranked locators are the hedge. If role+name breaks because a tenant relabelled a button, adjacent text or (last) CSS may still hit; if nothing hits and no known outcome matches, we stop with evidence rather than guessing.

## 4. Heterogeneity & multi-tenant

**Surfaces.** Perception/actuation live behind `SurfaceAdapter`. The artifact does not say “Playwright CSS.” A desktop adapter would resolve `role_name` / `adjacent_text` against AXUIElement / UI Automation the same way the web adapter resolves them against frames. Screenshot+XY would be a locator strategy of last resort, not the default, because it dies on DPI and layout.

**Tenants.** Hundreds of institutions run the same vendor product, branded and versioned differently. The artifact binds to `vendor` + `app_id` with `tenant.scope=vendor_default`. A tenant that moved a button records **overrides** (replace locator list for `s4_click`, rewrite a path prefix) rather than a new flow. Detection of drift is a replay failure plus a fingerprint of the observation; the recovery I would build next is a bounded, policy-checked single-step LLM heal that proposes an override, never a silent rewrite of the approved artifact.

I did not build a tenant registry or a desktop driver. The types are there so adding either does not require a new schema.

## 5. Escalation & handoff

Stuck is: repeated observation fingerprint, max steps, LLM/act exception, or policy blocking an irreversible action.

The **live session** is a control-transfer object around a single surface (the same Playwright page). `owner` is `automation | human | none`. Requesting an intervention flips owner to human, clears a resume event, and persists an `InterventionRequest` (goal, step, observation summary, screenshot). Automation awaits that event before the next step — it does not open a new browser.

The operator console is intentionally thin: take control, act through the same adapter (click/type/dismiss by ref), record what the human did, hand back. A headed window is also valid; the human is still on the same session. A real co-browsing product (CDP screencast, cursor sync, audit video) is the next layer on this seam, not a substitute for it.

## 6. Safety

Policy is data (`policies/default.yaml`), enforced on **both** paths:

- Host / URL prefix allowlist. Heritage Core is localhost only.
- Action allowlist; `eval_js`, raw CDP, downloads, uploads are denied.
- Irreversible name/path patterns (`Submit Transfer`, `/transfer`, “cannot be undone”). Unattended replay **escalates** rather than clicking. I chose escalate over “confirm in the artifact” because an approved capability should still not silently move money.
- Redaction: SSNs, PANs, account numbers (`SV-001122`), passwords, tokens are stripped from logs and never stored as parameter examples.

Limits: allowlists are static; there is no runtime DLP model. A determined model could type a secret into a non-password field; we redact by regex and key name, not by a classifier. Irreversible detection is pattern-based, so a tenant that labels the button “Post” without “transfer” would need a profile update.

## 7. Cuts

Left out on purpose: real co-browsing UI, desktop driver, tenant registry, queues, multi-run flakiness dashboards, open-ended LLM healing, generated Playwright tests.

What I would build next: (1) bounded one-step heal that writes a *proposed* tenant override, (2) approval + stability score before unattended replay, (3) a second branded variant of Heritage Core to prove vendor_default + override reuse.

What I kept thin but real: the operator console (ugly, but the control-transfer model is complete), the catalog HTTP surface (lists contracts and accepts invoke payloads; the CLI/library owns the browser).
