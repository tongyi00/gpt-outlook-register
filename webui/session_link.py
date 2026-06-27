"""Session payment link generation runner for the WebUI."""

from __future__ import annotations

import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from urllib.parse import urlparse

from . import db
from .proxy_pool import pick_random_usable_proxy

from session_link_gen.core import (
    PAYMENT_MODES,
    ProxyChainServer,
    generate_payment_link,
    mask_proxy_url,
    normalize_proxy_url,
    parse_session_tokens,
    randomize_proxy_sid,
)

DEFAULT_MODE = "PayPal 长链接 US/USD"
ACCOUNT_TERMINAL_STATUSES = {"done", "failed", "missing_token", "stopped"}
ACCOUNT_STAGE_STATUSES = {"create_checkout", "stripe_init", "paypal_approve"}


def _pool_from_text(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _pick_proxy(pool: list[str]) -> str:
    return normalize_proxy_url(random.choice(pool)) if pool else ""


def _positive_int(value, default: int, minimum: int = 1, maximum: int = 50) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _non_negative_int(value, default: int, maximum: int = 86400) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, min(maximum, number))


def _build_effective_proxy(local: str, proxy: str, payment_proxy: str) -> tuple[str, str]:
    local = normalize_proxy_url(local)
    proxy = normalize_proxy_url(proxy)
    payment_proxy = normalize_proxy_url(payment_proxy)
    if proxy:
        proxy = randomize_proxy_sid(proxy)
    if payment_proxy:
        payment_proxy = randomize_proxy_sid(payment_proxy)

    if payment_proxy:
        return payment_proxy, mask_proxy_url(payment_proxy)

    effective = proxy or local
    if not effective:
        return "", "直连"
    try:
        with ProxyChainServer(local, proxy or "", lambda _: None) as chain:
            return chain.url or effective, mask_proxy_url(effective)
    except Exception:
        return effective, mask_proxy_url(effective)


def is_paypal_ba_approve_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    return (
        bool(parsed.netloc)
        and re.search(r"(^|\.)paypal\.com$", parsed.hostname or "", re.I)
        and parsed.path.rstrip("/").lower() == "/agreements/approve"
        and "ba_token=" in parsed.query
    )


def result_error(item: dict, payment_mode: str) -> str:
    if not item.get("ok"):
        return str(item.get("error") or "生成失败")
    long_url = str(item.get("long_url") or "").strip()
    if not long_url:
        return "未返回付款链接"
    if item.get("amount_matched") is False:
        return (
            "金额不匹配: amount="
            f"{item.get('stripe_amount') or ''}, target={item.get('target_amount') or ''}, "
            f"source={item.get('stripe_amount_source') or ''}"
        )
    if str(payment_mode or "").startswith("PayPal 长链接") and not is_paypal_ba_approve_url(long_url):
        return f"未提取到 PayPal BA approve 链: {long_url}"
    return ""


def _token_preview(token: str) -> str:
    token = str(token or "").strip()
    if len(token) <= 18:
        return token
    return f"{token[:8]}...{token[-6:]}"


def parse_input_tokens(session_text: str = "", access_tokens: list[str] | None = None) -> list[str]:
    tokens: list[str] = []
    for token in access_tokens or []:
        token = str(token or "").strip()
        if token:
            tokens.append(token)
    tokens.extend(parse_session_tokens(session_text or ""))
    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _email_list(value) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\s,;]+", value)
    else:
        raw_items = value or []
    emails: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        email = str(item or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        emails.append(email)
    return emails


def _env_account_workers() -> int:
    try:
        value = int(os.getenv("SESSION_LINK_MAX_WORKERS", "10"))
    except (TypeError, ValueError):
        value = 10
    return max(1, value)


def _public_account(row: dict) -> dict:
    public = dict(row or {})
    public.pop("access_token", None)
    if public.get("proxy_url"):
        public["proxy_url"] = mask_proxy_url(str(public["proxy_url"]))
    if public.get("error"):
        public["error"] = _mask_sensitive_text(public["error"])
    return public


def _mask_sensitive_text(value) -> str:
    text = str(value or "")
    return re.sub(
        r"\b((?:(?:https?|socks5?|socks4)://)?[^/\s:@]+):([^@\s/]+)@",
        r"\1:***@",
        text,
        flags=re.I,
    )


def _public_log(row: dict) -> dict:
    public = dict(row or {})
    if public.get("message"):
        public["message"] = _mask_sensitive_text(public["message"])
    return public


class SessionLinkController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._account_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._account_stop = threading.Event()
        self._state = self._initial_state()
        self._account_state = self._initial_account_state()

    def _initial_state(self) -> dict:
        return {
            "running": False,
            "status": "idle",
            "attempt": 0,
            "started_at": None,
            "finished_at": None,
            "payment_mode": DEFAULT_MODE,
            "target_amount": "0",
            "thread_count": 1,
            "delay_seconds": 2,
            "total": 0,
            "success_count": 0,
            "failure_count": 0,
            "pending_count": 0,
            "results": [],
            "last_error": "",
            "logs": [],
        }

    def _initial_account_state(self) -> dict:
        return {
            "running": False,
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "total": 0,
            "emails": [],
            "payment_mode": DEFAULT_MODE,
            "target_amount": "0",
            "delay_seconds": 2,
            "stop_after": 0,
            "last_error": "",
        }

    def payment_modes(self) -> dict:
        return {
            name: {
                "country": cfg.get("country", ""),
                "currency": cfg.get("currency", ""),
                "paypal": "PayPal" in name,
            }
            for name, cfg in PAYMENT_MODES.items()
        }

    def import_registered(self, emails) -> dict:
        selected = _email_list(emails)
        result = db.import_session_link_accounts(selected)
        for email in selected:
            self._append_account_log(email, "info", "import", "Imported registered account")
        return {"ok": True, **result}

    def accounts(self, status: str = "", limit: int = 500) -> dict:
        items = [_public_account(row) for row in db.list_session_link_accounts(status=status, limit=limit)]
        return {"ok": True, "items": items}

    def run_selected(self, payload: dict) -> dict:
        payload = payload or {}
        emails = _email_list(payload.get("emails") or payload.get("selected") or payload.get("selected_emails"))
        if not emails:
            return {"ok": False, "error": "请选择账号"}

        with self._lock:
            if self._state.get("running") or self._account_state.get("running"):
                return {"ok": False, "error": "链接生成循环正在运行"}
            missing_accounts = [
                email for email in emails
                if not db.get_session_link_account(email)
            ]
            if missing_accounts:
                return {
                    "ok": False,
                    "error": "账号未导入链接生成: " + ", ".join(missing_accounts[:5]),
                    "missing": missing_accounts,
                }
            self._account_stop = threading.Event()
            config = self._build_account_config(payload, emails)
            self._account_state = self._initial_account_state()
            self._account_state.update({
                "running": True,
                "status": "running",
                "started_at": time.time(),
                "finished_at": None,
                "total": len(emails),
                "emails": emails,
                "payment_mode": config["payment_mode"],
                "target_amount": config["target_amount"],
                "delay_seconds": config["delay_seconds"],
                "stop_after": config["stop_after"],
            })
            self._account_thread = threading.Thread(
                target=self._run_account_batch,
                args=(config,),
                daemon=True,
            )
            self._account_thread.start()
            return {"ok": True, **deepcopy(self._account_state)}

    def reset(self, emails) -> dict:
        selected = _email_list(emails)
        with self._lock:
            if self._account_state.get("running"):
                return {"ok": False, "error": "账号链接任务正在运行，无法重置"}
            count = db.reset_session_link_accounts(selected)
        for email in selected:
            self._append_account_log(email, "info", "reset", "Account reset")
        return {"ok": True, "reset": count}

    def delete(self, emails) -> dict:
        selected = _email_list(emails)
        with self._lock:
            if self._account_state.get("running"):
                return {"ok": False, "error": "账号链接任务正在运行，无法删除"}
            count = db.delete_session_link_accounts(selected)
        return {"ok": True, "deleted": count}

    def logs(self, email: str) -> dict:
        return {"ok": True, "items": [_public_log(row) for row in db.list_session_link_logs(email)]}

    def start(self, payload: dict) -> dict:
        tokens = parse_input_tokens(
            payload.get("session_text") or payload.get("session_json") or "",
            payload.get("access_tokens") or [],
        )
        if not tokens:
            return {"ok": False, "error": "缺少 Session JSON / Access Token"}

        with self._lock:
            if self._state.get("running") or self._account_state.get("running"):
                return {"ok": False, "error": "链接生成循环正在运行"}
            self._stop = threading.Event()
            config = self._build_config(payload, tokens)
            self._state = self._initial_state()
            self._state.update({
                "running": True,
                "status": "running",
                "started_at": time.time(),
                "payment_mode": config["payment_mode"],
                "target_amount": config["target_amount"],
                "thread_count": config["thread_count"],
                "delay_seconds": config["delay_seconds"],
                "total": len(tokens),
                "pending_count": len(tokens),
            })
            self._add_log_locked("info", "started", f"tokens={len(tokens)} mode={config['payment_mode']}")
            self._thread = threading.Thread(target=self._run_loop, args=(config,), daemon=True)
            self._thread.start()
            return {"ok": True, **deepcopy(self._state)}

    def stop(self) -> dict:
        self._stop.set()
        self._account_stop.set()
        with self._lock:
            legacy_running = bool(self._state.get("running"))
            account_running = bool(self._account_state.get("running"))
            if legacy_running:
                self._add_log_locked("warn", "stopping", "stop requested")
            if account_running:
                self._account_state["status"] = "stopping"
                for email in self._account_state.get("emails") or []:
                    self._append_account_log(email, "warn", "stop", "Stop requested")
            state = deepcopy(self._state)
            state["running"] = legacy_running or account_running
            if account_running and not legacy_running:
                state["status"] = "stopping"
            return {"ok": True, **state}

    def status(self) -> dict:
        with self._lock:
            state = deepcopy(self._state)
            account_state = self._account_state
            account_started = account_state.get("started_at")
            legacy_started = state.get("started_at")
            if account_started and (
                account_state.get("running")
                or not legacy_started
                or account_started >= legacy_started
            ):
                state.update({
                    "running": bool(account_state.get("running")),
                    "status": account_state.get("status") or "running",
                    "started_at": account_state.get("started_at"),
                    "finished_at": account_state.get("finished_at"),
                    "payment_mode": account_state.get("payment_mode", DEFAULT_MODE),
                    "target_amount": account_state.get("target_amount", "0"),
                    "delay_seconds": account_state.get("delay_seconds", 2),
                    "total": account_state.get("total", 0),
                    "last_error": account_state.get("last_error", ""),
                })
            return {"ok": True, **state}

    def generate_once(self, payload: dict) -> dict:
        tokens = parse_input_tokens(
            payload.get("session_text") or payload.get("session_json") or "",
            payload.get("access_tokens") or [],
        )
        if not tokens:
            return {"ok": False, "error": "缺少 Session JSON / Access Token"}
        config = self._build_config(payload, tokens)
        pending = [{"index": index, "access_token": token} for index, token in enumerate(tokens)]
        batch = self._run_batch(config, pending)
        success_count = sum(1 for item in batch if not result_error(item, config["payment_mode"]))
        return {
            "ok": True,
            "total": len(batch),
            "success_count": success_count,
            "failure_count": len(batch) - success_count,
            "thread_count": min(config["thread_count"], len(batch)),
            "payment_mode": config["payment_mode"],
            "results": [self._public_item(item, config["payment_mode"]) for item in batch],
        }

    def _build_config(self, payload: dict, tokens: list[str]) -> dict:
        payment_mode = str(payload.get("payment_mode") or DEFAULT_MODE).strip()
        if payment_mode not in PAYMENT_MODES:
            payment_mode = DEFAULT_MODE
        return {
            "tokens": tokens,
            "payment_mode": payment_mode,
            "target_amount": str(payload.get("target_amount") or "0").strip() or "0",
            "local_proxy": str(payload.get("local_proxy") or ""),
            "proxy": str(payload.get("proxy") or ""),
            "payment_proxy": str(payload.get("payment_proxy") or ""),
            "proxy_pool": _pool_from_text(str(payload.get("proxy_pool") or "")),
            "payment_proxy_pool": _pool_from_text(str(payload.get("payment_proxy_pool") or "")),
            "thread_count": _positive_int(payload.get("thread_count"), 1),
            "delay_seconds": _non_negative_int(payload.get("delay_seconds"), 2),
        }

    def _build_account_config(self, payload: dict, emails: list[str]) -> dict:
        payment_mode = str(payload.get("payment_mode") or DEFAULT_MODE).strip()
        if payment_mode not in PAYMENT_MODES:
            payment_mode = DEFAULT_MODE
        return {
            "emails": emails,
            "payment_mode": payment_mode,
            "target_amount": str(payload.get("target_amount") or "0").strip() or "0",
            "proxy_pool": _pool_from_text(str(payload.get("proxy_pool") or "")),
            "delay_seconds": _non_negative_int(payload.get("delay_seconds"), 2),
            "stop_after": _non_negative_int(payload.get("stop_after"), 0, maximum=1000000),
        }

    def _run_account_batch(self, config: dict) -> None:
        failed = False
        try:
            with ThreadPoolExecutor(max_workers=_env_account_workers()) as executor:
                futures = [executor.submit(self._run_account_loop, email, config) for email in config["emails"]]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:
                        failed = True
                        with self._lock:
                            self._account_state["last_error"] = _mask_sensitive_text(str(exc))
        finally:
            with self._lock:
                self._account_state["running"] = False
                self._account_state["finished_at"] = time.time()
                if self._account_stop.is_set():
                    self._account_state["status"] = "stopped"
                elif failed:
                    self._account_state["status"] = "failed"
                else:
                    self._account_state["status"] = "done"

    def _run_account_loop(self, email: str, config: dict) -> None:
        access_token = ""
        started_at = None
        proxy_url = ""
        proxy_label = "直连"

        while not self._account_stop.is_set():
            row = db.get_session_link_account(email) or {}
            attempts = int(row.get("attempts") or 0) + 1
            started_at = row.get("started_at") or started_at or time.time()
            db.update_session_link_account(
                email,
                attempts=attempts,
                status="check_proxy",
                error=None,
                long_url=None,
                payment_mode=config["payment_mode"],
                target_amount=config["target_amount"],
                started_at=started_at,
                finished_at=None,
            )
            self._append_account_log(email, "info", "check_proxy", f"Attempt {attempts}")

            registered = db.get_registered(email) or {}
            access_token = str(registered.get("access_token") or "").strip()
            if not access_token:
                self._append_account_log(email, "error", "missing_token", "Missing access token")
                db.update_session_link_account(
                    email,
                    status="missing_token",
                    error="missing access token",
                    finished_at=time.time(),
                )
                return

            proxy_url = self._account_proxy(config, email)
            if self._account_stop.is_set():
                break

            if config["proxy_pool"] and not proxy_url:
                db.update_session_link_account(
                    email,
                    status="retry_wait",
                    error="代理池无可用代理",
                    proxy_url="",
                )
                self._append_account_log(email, "warn", "proxy_unavailable", "No usable proxy")
                if not self._wait_account_delay(config["delay_seconds"]):
                    break
                continue

            proxy_label = mask_proxy_url(proxy_url) if proxy_url else "直连"
            db.update_session_link_account(email, proxy_url=proxy_label)
            break

        if self._account_stop.is_set():
            self._mark_account_stopped(email)
            return

        first_collision = True
        while not self._account_stop.is_set():
            row = db.get_session_link_account(email) or {}
            if not first_collision:
                attempts = int(row.get("attempts") or 0) + 1
                db.update_session_link_account(
                    email,
                    attempts=attempts,
                    error=None,
                    long_url=None,
                    payment_mode=config["payment_mode"],
                    target_amount=config["target_amount"],
                    started_at=started_at,
                    finished_at=None,
                )
                self._append_account_log(email, "info", "retry", f"Attempt {attempts}")
                row = db.get_session_link_account(email) or {}
            first_collision = False

            collision_count = int(row.get("collision_count") or 0) + 1
            db.update_session_link_account(
                email,
                status="create_checkout",
                collision_count=collision_count,
                error=None,
                proxy_url=proxy_label,
            )
            self._append_account_log(email, "info", "create_checkout", f"Collision {collision_count}")

            try:
                result = generate_payment_link(
                    access_token,
                    config["payment_mode"],
                    proxy_url,
                    config["target_amount"],
                    stage_callback=self._account_stage_callback(email),
                )
                item = {
                    "ok": bool(result.get("success", True)),
                    "long_url": result.get("long_url") or "",
                    "stripe_amount": result.get("stripe_amount", ""),
                    "stripe_amount_source": result.get("stripe_amount_source", ""),
                    "target_amount": result.get("target_amount", config["target_amount"]),
                    "amount_matched": result.get("amount_matched", None),
                }
                err = result_error(item, config["payment_mode"])
                if err:
                    raise RuntimeError(err)
                long_url = item["long_url"]
                db.set_registered_payment_link(email, long_url)
                self._append_account_log(email, "ok", "success", "Payment link generated")
                db.update_session_link_account(
                    email,
                    status="done",
                    long_url=long_url,
                    error=None,
                    payment_mode=config["payment_mode"],
                    target_amount=config["target_amount"],
                    proxy_url=proxy_label,
                    finished_at=time.time(),
                )
                return
            except Exception as exc:
                message = _mask_sensitive_text(str(exc) or "生成失败")
                if self._account_stop.is_set():
                    self._mark_account_stopped(email)
                    return
                latest = db.get_session_link_account(email) or {}
                collision_count = int(latest.get("collision_count") or collision_count)
                if config["stop_after"] > 0 and collision_count >= config["stop_after"]:
                    self._append_account_log(email, "error", "failure", f"达到停止次数: {message}")
                    db.update_session_link_account(
                        email,
                        status="failed",
                        error=f"达到停止次数: {message}",
                        finished_at=time.time(),
                    )
                    return
                db.update_session_link_account(email, status="retry_wait", error=message)
                self._append_account_log(email, "warn", "retry", message)
                if not self._wait_account_delay(config["delay_seconds"]):
                    break

        self._mark_account_stopped(email)

    def _run_loop(self, config: dict) -> None:
        pending = [
            {"index": index, "access_token": token}
            for index, token in enumerate(config["tokens"])
        ]
        successes: dict[int, dict] = {}
        latest_failures: dict[int, dict] = {}

        try:
            while pending and not self._stop.is_set():
                with self._lock:
                    self._state["attempt"] += 1
                    attempt = self._state["attempt"]
                    self._state["pending_count"] = len(pending)
                    self._add_log_locked("info", f"attempt {attempt}", f"pending={len(pending)}")

                batch = self._run_batch(config, pending)
                next_pending: list[dict] = []
                latest_failures = {}
                for item in batch:
                    err = result_error(item, config["payment_mode"])
                    index = int(item.get("index") or 0)
                    if err:
                        item["error"] = err
                        latest_failures[index] = item
                        token = str(item.get("_access_token") or "")
                        if token:
                            next_pending.append({"index": index, "access_token": token})
                    else:
                        successes[index] = item

                with self._lock:
                    results = [*successes.values(), *latest_failures.values()]
                    results.sort(key=lambda x: int(x.get("index") or 0))
                    self._state["results"] = [
                        self._public_item(item, config["payment_mode"])
                        for item in results
                    ]
                    self._state["success_count"] = len(successes)
                    self._state["failure_count"] = len(latest_failures)
                    self._state["pending_count"] = len(next_pending)
                    if latest_failures:
                        self._state["last_error"] = next(iter(latest_failures.values())).get("error", "")
                    self._add_log_locked(
                        "ok" if not next_pending else "warn",
                        f"attempt {attempt} done",
                        f"success={len(successes)} pending={len(next_pending)}",
                    )

                pending = next_pending
                if pending and config["delay_seconds"] > 0:
                    self._stop.wait(config["delay_seconds"])

            with self._lock:
                self._state["running"] = False
                self._state["finished_at"] = time.time()
                if self._stop.is_set() and pending:
                    self._state["status"] = "stopped"
                    self._add_log_locked("warn", "stopped", f"pending={len(pending)}")
                else:
                    self._state["status"] = "done"
                    self._state["last_error"] = ""
                    self._add_log_locked("ok", "completed", f"success={len(successes)}")
        except Exception as exc:
            with self._lock:
                self._state["running"] = False
                self._state["status"] = "failed"
                self._state["finished_at"] = time.time()
                self._state["last_error"] = str(exc)
                self._add_log_locked("error", "failed", str(exc))

    def _account_proxy(self, config: dict, email: str) -> str:
        if not config["proxy_pool"]:
            self._append_account_log(email, "info", "proxy", "Direct connection")
            return ""
        selected = pick_random_usable_proxy(config["proxy_pool"])
        if not selected:
            return ""
        proxy_url = randomize_proxy_sid(normalize_proxy_url(selected))
        self._append_account_log(email, "info", "proxy", f"Selected {mask_proxy_url(proxy_url)}")
        return proxy_url

    def _account_stage_callback(self, email: str):
        def callback(stage: str, message: str = "") -> None:
            clean_stage = str(stage or "").strip()
            if clean_stage not in ACCOUNT_STAGE_STATUSES:
                return
            db.update_session_link_account(email, status=clean_stage)
            self._append_account_log(email, "info", clean_stage, message or clean_stage)

        return callback

    def _wait_account_delay(self, delay_seconds: int) -> bool:
        return not self._account_stop.wait(delay_seconds)

    def _mark_account_stopped(self, email: str) -> None:
        row = db.get_session_link_account(email) or {}
        if row.get("status") in ACCOUNT_TERMINAL_STATUSES:
            return
        self._append_account_log(email, "warn", "stop", "Stopped")
        db.update_session_link_account(email, status="stopped", finished_at=time.time())

    def _append_account_log(self, email: str, kind: str, stage: str, message: str) -> None:
        db.append_session_link_log(email, kind, stage, _mask_sensitive_text(message))

    def _run_batch(self, config: dict, pending: list[dict]) -> list[dict]:
        if not pending:
            return []

        def run_one(item: dict) -> dict:
            index = int(item["index"])
            access_token = str(item["access_token"])
            selected_proxy = config["proxy"] or _pick_proxy(config["proxy_pool"])
            selected_payment_proxy = config["payment_proxy"] or _pick_proxy(config["payment_proxy_pool"])
            effective, label = _build_effective_proxy(
                config["local_proxy"],
                selected_proxy,
                selected_payment_proxy,
            )
            try:
                result = generate_payment_link(
                    access_token,
                    config["payment_mode"],
                    effective,
                    config["target_amount"],
                )
                return {
                    "ok": True,
                    "index": index,
                    "_access_token": access_token,
                    "token_preview": _token_preview(access_token),
                    "long_url": result.get("long_url") or "",
                    "payment_mode": config["payment_mode"],
                    "proxy_used": label,
                    "proxy_url": mask_proxy_url(effective) if effective else "",
                    "stripe_amount": result.get("stripe_amount", ""),
                    "stripe_amount_source": result.get("stripe_amount_source", ""),
                    "target_amount": result.get("target_amount", ""),
                    "amount_matched": result.get("amount_matched", None),
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "index": index,
                    "_access_token": access_token,
                    "token_preview": _token_preview(access_token),
                    "payment_mode": config["payment_mode"],
                    "proxy_used": label,
                    "proxy_url": mask_proxy_url(effective) if effective else "",
                    "error": str(exc),
                }

        workers = min(config["thread_count"], len(pending))
        results: list[dict | None] = [None] * len(pending)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(run_one, item): position
                for position, item in enumerate(pending)
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return [item for item in results if item is not None]

    def _public_item(self, item: dict, payment_mode: str) -> dict:
        public = {
            key: value
            for key, value in item.items()
            if key != "_access_token"
        }
        public["error"] = result_error(item, payment_mode)
        public["ok"] = not bool(public["error"])
        return public

    def _add_log_locked(self, kind: str, title: str, message: str) -> None:
        logs = self._state.setdefault("logs", [])
        logs.insert(0, {
            "time": time.time(),
            "kind": kind,
            "title": title,
            "message": message,
        })
        del logs[200:]


CONTROLLER = SessionLinkController()
