"""Session payment link generation runner for the WebUI."""

from __future__ import annotations

import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from urllib.parse import urlparse

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


class SessionLinkController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = self._initial_state()

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

    def payment_modes(self) -> dict:
        return {
            name: {
                "country": cfg.get("country", ""),
                "currency": cfg.get("currency", ""),
                "paypal": "PayPal" in name,
            }
            for name, cfg in PAYMENT_MODES.items()
        }

    def start(self, payload: dict) -> dict:
        tokens = parse_input_tokens(
            payload.get("session_text") or payload.get("session_json") or "",
            payload.get("access_tokens") or [],
        )
        if not tokens:
            return {"ok": False, "error": "缺少 Session JSON / Access Token"}

        with self._lock:
            if self._state.get("running"):
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
        with self._lock:
            if not self._state.get("running"):
                return {"ok": True, **deepcopy(self._state)}
            self._add_log_locked("warn", "stopping", "stop requested")
            return {"ok": True, **deepcopy(self._state)}

    def status(self) -> dict:
        with self._lock:
            return {"ok": True, **deepcopy(self._state)}

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
