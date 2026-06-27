# Session Link Account Workbench Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the account-based session link workbench that imports ChatGPT registered accounts, runs selected accounts asynchronously, records per-account state/logs, tracks collision count, and writes generated payment links back to ChatGPT registered results.

**Architecture:** Keep `registered` as the source of credentials and result display, and add a separate `session_link_accounts` task table keyed by email plus `session_link_logs`. `webui/session_link.py` becomes an account-task controller backed by SQLite, with a fixed `ThreadPoolExecutor(max_workers=10)` and phase callbacks from `session_link_gen/core.py`.

**Tech Stack:** Python 3.13, SQLite, FastAPI/Pydantic, vanilla HTML/CSS/JS, `unittest`, existing `webui.proxy_pool` helpers.

---

### Task 1: Database Schema And Helpers

**Files:**
- Modify: `webui/db.py`
- Create/Modify: `tests/test_session_link_accounts.py`

**Step 1: Write failing DB tests**

Add tests for:

```python
def test_import_session_link_accounts_uses_email_as_unique_id(self):
    db.save_registered({"email": "a@example.com", "access_token": "token-a"})

    first = db.import_session_link_accounts(["A@example.com"])
    second = db.import_session_link_accounts(["a@example.com"])
    rows = db.list_session_link_accounts()

    self.assertEqual(first["imported"], 1)
    self.assertEqual(second["updated"], 1)
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["email"], "a@example.com")
```

```python
def test_import_marks_missing_token(self):
    db.save_registered({"email": "no-token@example.com", "access_token": ""})

    result = db.import_session_link_accounts(["no-token@example.com"])
    row = db.get_session_link_account("no-token@example.com")

    self.assertEqual(result["missing_token"], 1)
    self.assertEqual(row["status"], "missing_token")
```

```python
def test_payment_link_is_written_back_to_registered(self):
    db.save_registered({"email": "a@example.com", "access_token": "token-a"})

    db.set_registered_payment_link("a@example.com", "https://pay.example/link")
    row = db.list_registered()[0]

    self.assertEqual(row["payment_link"], "https://pay.example/link")
```

Also test log append/list, reset, delete, and `collision_count` persistence.

**Step 2: Verify red**

Run:

```powershell
python -m unittest tests.test_session_link_accounts
```

Expected: fails because helpers/tables do not exist.

**Step 3: Implement minimal DB layer**

In `init_db()`:

- Create `session_link_accounts`.
- Create `session_link_logs`.
- Add migration for `registered.payment_link`.
- Add indexes for account status and log email/time.

Add helpers:

- `import_session_link_accounts(emails: list[str]) -> dict`
- `list_session_link_accounts(status: str = "", limit: int = 500) -> list[dict]`
- `get_session_link_account(email: str) -> Optional[dict]`
- `update_session_link_account(email: str, **fields) -> bool`
- `append_session_link_log(email: str, kind: str, stage: str, message: str) -> None`
- `list_session_link_logs(email: str, limit: int = 300) -> list[dict]`
- `reset_session_link_accounts(emails: list[str]) -> int`
- `delete_session_link_accounts(emails: list[str]) -> int`
- `set_registered_payment_link(email: str, link: str) -> bool`

Keep tokens out of the session-link tables.

**Step 4: Verify green**

Run:

```powershell
python -m unittest tests.test_session_link_accounts
```

Expected: OK.

**Step 5: Commit**

```powershell
git add webui/db.py tests/test_session_link_accounts.py
git commit -m "feat(session-link): add account task storage"
```

---

### Task 2: Phase Callbacks In Payment Link Core

**Files:**
- Modify: `session_link_gen/core.py`
- Modify: `tests/test_session_link.py`

**Step 1: Write failing phase tests**

Add a test that patches low-level functions and asserts callback order:

```python
def test_paypal_generation_emits_stage_callbacks(self):
    stages = []

    with patch("session_link_gen.core.opll_create_checkout", return_value={...}), \
         patch("session_link_gen.core.opll_stripe_init", return_value={...}), \
         patch("session_link_gen.core.opll_stripe_create_paypal_method", return_value="pm_1"), \
         patch("session_link_gen.core.opll_stripe_confirm", return_value={...}), \
         patch("session_link_gen.core.opll_redirect_url_after_confirm", return_value="https://www.paypal.com/agreements/approve?ba_token=BA-1"):
        result = core.generate_payment_link(
            "token",
            "PayPal 长链接 US/USD",
            stage_callback=lambda stage, message="": stages.append(stage),
        )

    self.assertEqual(stages, ["create_checkout", "stripe_init", "paypal_approve"])
    self.assertIn("paypal.com/agreements/approve", result["long_url"])
```

Add a hosted-link test that expects only `["create_checkout", "stripe_init"]`.

**Step 2: Verify red**

Run:

```powershell
python -m unittest tests.test_session_link
```

Expected: fails because `generate_payment_link()` does not accept `stage_callback`.

**Step 3: Add callback support**

Add optional `stage_callback=None` to:

- `generate_payment_link`
- `generate_opll_paypal_long_link`
- `generate_opll_hosted_long_link`

Use a tiny helper:

```python
def _emit_stage(callback, stage: str, message: str = "") -> None:
    if callback:
        callback(stage, message)
```

Emit before each stage begins.

**Step 4: Verify green**

Run:

```powershell
python -m unittest tests.test_session_link
```

Expected: OK.

**Step 5: Commit**

```powershell
git add session_link_gen/core.py tests/test_session_link.py
git commit -m "feat(session-link): expose payment generation stages"
```

---

### Task 3: Account Controller

**Files:**
- Rewrite/Modify: `webui/session_link.py`
- Modify: `tests/test_session_link.py`

**Step 1: Write failing controller tests**

Cover these behaviors:

- Import calls DB helper and does not expose tokens.
- `run_selected()` starts background work and returns quickly.
- Missing access token sets `missing_token`.
- Proxy pool all unavailable enters `retry_wait` without increasing `collision_count`.
- Entering `create_checkout` increments `collision_count`.
- `stop_after=2` marks account `failed` after two failed collisions.
- Success writes `long_url` to both session-link account and `registered.payment_link`.
- `stop()` prevents another retry after the current step finishes.

Use patched dependencies:

```python
with patch("webui.session_link.pick_random_usable_proxy", return_value="http://proxy:8080"), \
     patch("webui.session_link.generate_payment_link", side_effect=fake_generate):
    controller.run_selected({...})
```

**Step 2: Verify red**

Run:

```powershell
python -m unittest tests.test_session_link
```

Expected: controller tests fail because account-level methods do not exist.

**Step 3: Implement account controller**

Keep `payment_modes()` and compatibility where easy, but add account methods:

- `import_registered(emails)`
- `accounts(status="", limit=500)`
- `run_selected(payload)`
- `stop()`
- `reset(emails)`
- `delete(emails)`
- `logs(email)`

Controller rules:

- One active batch at a time.
- Use `ThreadPoolExecutor(max_workers=int(os.getenv("SESSION_LINK_MAX_WORKERS", "10")))`.
- Per account loop:
  - Increment `attempts` when a cycle starts.
  - Set `check_proxy`.
  - If proxy pool has entries, call `pick_random_usable_proxy`; if none usable, log and sleep `delay_seconds`, then retry.
  - If no proxy pool entries, proceed direct.
  - Increment `collision_count` immediately before calling `generate_payment_link`.
  - Stage callback updates `create_checkout`, `stripe_init`, `paypal_approve`.
  - On success, set `done` and write back payment link.
  - On failure, if `stop_after > 0 and collision_count >= stop_after`, set `failed`; otherwise set `retry_wait`.
- Logs are appended for import, proxy selection, stage changes, retry, success, failure, stop.

**Step 4: Verify green**

Run:

```powershell
python -m unittest tests.test_session_link tests.test_session_link_accounts
```

Expected: OK.

**Step 5: Commit**

```powershell
git add webui/session_link.py tests/test_session_link.py tests/test_session_link_accounts.py
git commit -m "feat(session-link): run account-based link jobs"
```

---

### Task 4: FastAPI Account Endpoints

**Files:**
- Modify: `webui/app.py`
- Modify: `tests/test_session_link.py`

**Step 1: Write failing API tests**

Patch `web_app.session_link.CONTROLLER` and assert routes call the correct methods:

- `api_session_link_import_registered()`
- `api_session_link_accounts()`
- `api_session_link_run_selected()`
- `api_session_link_stop()`
- `api_session_link_reset()`
- `api_session_link_delete()`
- `api_session_link_logs()`

**Step 2: Verify red**

Run:

```powershell
python -m unittest tests.test_session_link
```

Expected: fails because route functions/models are missing.

**Step 3: Implement models and routes**

Add Pydantic models:

- `SessionLinkImportRegisteredReq`
- `SessionLinkRunSelectedReq`
- `SessionLinkEmailListReq`

Routes:

- `POST /api/session-link/accounts/import-registered`
- `GET /api/session-link/accounts`
- `POST /api/session-link/accounts/run-selected`
- `POST /api/session-link/accounts/stop`
- `POST /api/session-link/accounts/reset`
- `POST /api/session-link/accounts/delete`
- `GET /api/session-link/accounts/{email}/logs`

Keep existing `/api/session-link/payment-modes`. Existing `run-once/start/status` may stay for backward compatibility, but the new UI should use account routes.

**Step 4: Verify green**

Run:

```powershell
python -m unittest tests.test_session_link
python -m py_compile webui/app.py webui/session_link.py webui/db.py
```

Expected: OK.

**Step 5: Commit**

```powershell
git add webui/app.py tests/test_session_link.py
git commit -m "feat(session-link): add account workbench api"
```

---

### Task 5: ChatGPT Registered Table Integration

**Files:**
- Modify: `webui/static/index.html`
- Modify: `webui/static/app.js`
- Modify: `webui/static/style.css`
- Modify: `tests/test_static_custom_sms_ui.py`

**Step 1: Write failing static UI tests**

Assert:

- `btnImportToSessionLink` exists in the ChatGPT registered toolbar.
- `regTable` has a `支付链接` column.
- `refreshRegistered()` renders `r.payment_link`.
- Import button calls `/api/session-link/accounts/import-registered`.
- Import success does not call `activateTab("sessionlink")`.

**Step 2: Verify red**

Run:

```powershell
python -m unittest tests.test_static_custom_sms_ui
```

Expected: fails because button/column/API binding are missing.

**Step 3: Implement registered-table changes**

HTML:

- Add `导入到链接生成` button near export/delete buttons.
- Add `支付链接` header before time or operation.

JS:

- Add click handler using `_selectedRegEmails()`.
- POST `{ emails }` to import route.
- Update `#exportResult`.
- Do not navigate to sessionlink.
- Render payment link with copy/open buttons.

CSS:

- Reuse compact table button styles; add `.payment-link-cell` if needed.

**Step 4: Verify green**

Run:

```powershell
python -m unittest tests.test_static_custom_sms_ui
node --check webui/static/app.js
```

Expected: OK.

**Step 5: Commit**

```powershell
git add webui/static/index.html webui/static/app.js webui/static/style.css tests/test_static_custom_sms_ui.py
git commit -m "feat(session-link): import registered accounts"
```

---

### Task 6: Session Link Workbench UI

**Files:**
- Modify: `webui/static/index.html`
- Modify: `webui/static/app.js`
- Modify: `webui/static/style.css`
- Modify: `tests/test_static_custom_sms_ui.py`

**Step 1: Write failing static UI tests**

Assert:

- `sessionLinkThreadCount` is removed.
- New `sessionLinkStopAfter` exists.
- New table IDs exist: `sessionLinkAccountTable`, `sessionLinkSelectAll`.
- Top row contains payment mode, target amount, delay seconds, stop count, refresh, execute selected, stop, reset selected, delete selected.
- JS calls account routes: `/accounts`, `/run-selected`, `/stop`, `/reset`, `/delete`, `/logs`.
- Old bottom action layout is gone.

**Step 2: Verify red**

Run:

```powershell
python -m unittest tests.test_static_custom_sms_ui
```

Expected: fails because workbench UI does not exist.

**Step 3: Implement workbench HTML/JS/CSS**

HTML:

- Replace text input/results card with top toolbar and account table.
- Keep existing `sessionLinkMode`, `sessionLinkTargetAmount`, `sessionLinkDelaySeconds` IDs.
- Add `sessionLinkStopAfter`.
- Remove `sessionLinkThreadCount` from UI.

JS:

- `loadSessionLinkAccounts()`
- `_selectedSessionLinkEmails()`
- `renderSessionLinkAccounts(items)`
- `execute selected` posts mode/amount/delay/stop_after/proxy pool from `autoProxyPool`.
- Poll while any row is active.
- Log button loads per-account logs into modal or lightweight dialog.
- Stop calls account stop route.

CSS:

- Make `#tab-sessionlink` full-height.
- Table panel scrolls internally.
- Keep mobile horizontal overflow inside table panel.

**Step 4: Verify green**

Run:

```powershell
python -m unittest tests.test_static_custom_sms_ui
node --check webui/static/app.js
```

Expected: OK.

**Step 5: Commit**

```powershell
git add webui/static/index.html webui/static/app.js webui/static/style.css tests/test_static_custom_sms_ui.py
git commit -m "feat(session-link): add account workbench ui"
```

---

### Task 7: End-To-End Verification

**Files:**
- Potentially modify: `tests/test_session_link.py`, `tests/test_session_link_accounts.py`, `tests/test_static_custom_sms_ui.py`

**Step 1: Full automated verification**

Run:

```powershell
python -m unittest discover -s tests
python -m py_compile session_link_gen/core.py webui/session_link.py webui/app.py webui/db.py start_webui.py
node --check webui/static/app.js
git diff --check -- session_link_gen webui tests docs
```

Expected: all pass. `git diff --check` may only emit known CRLF warnings; fix actual whitespace errors.

**Step 2: Encoding check**

Run:

```powershell
@'
from pathlib import Path
paths = [
    "webui/db.py", "webui/session_link.py", "webui/app.py",
    "webui/static/index.html", "webui/static/app.js", "webui/static/style.css",
    "session_link_gen/core.py",
]
bad = []
for p in paths:
    b = Path(p).read_bytes()
    if b.startswith(b"\xef\xbb\xbf"):
        bad.append(p)
print("NO_BOM" if not bad else "BOM " + ", ".join(bad))
'@ | python -
```

Expected: `NO_BOM`.

**Step 3: Browser verification**

Start server:

```powershell
python start_webui.py
```

Use Playwright or the existing browser workflow to verify:

- ChatGPT registered toolbar shows import button.
- Importing selected registered accounts does not switch tabs.
- Link generation tab shows top toolbar and account table.
- Desktop and mobile have zero console errors.
- Table scroll is internal and no horizontal page overflow occurs.

**Step 4: Final commit**

If final verification required small fixes, commit them:

```powershell
git add <changed-files>
git commit -m "test(session-link): verify account workbench"
```

---

## Notes For Execution

- Follow TDD: write each test, run it and confirm it fails, then implement.
- Do not expose full access tokens or proxy passwords in API responses or logs.
- Keep `registered` as the credential source. Do not duplicate tokens into `session_link_accounts`.
- Reuse `webui.proxy_pool.pick_random_usable_proxy`; it already shuffles and checks all candidates.
- Use Chinese comments only when needed; logs remain English-compatible where practical.
