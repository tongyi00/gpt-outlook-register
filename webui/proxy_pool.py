"""代理池解析与可用代理选择。"""
from __future__ import annotations

import logging
import os
import random
from typing import Callable, Iterable

from http_client import create_http_session

logger = logging.getLogger("proxy_pool")


def parse_proxy_pool(text: str) -> list[str]:
    """把多行代理字符串拆成列表。空行 / # 开头注释跳过。"""
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def is_proxy_usable(proxy: str, timeout: float | None = None) -> bool:
    """快速探测代理是否可用。"""
    p = str(proxy or "").strip()
    if not p:
        return False
    try:
        t = float(timeout if timeout is not None else os.getenv("PROXY_CHECK_TIMEOUT", "6"))
    except Exception:
        t = 6.0
    session = None
    try:
        session = create_http_session(proxy=p)
        resp = session.get("https://cloudflare.com/cdn-cgi/trace", timeout=t)
        ok = getattr(resp, "status_code", 0) == 200
        if not ok:
            logger.info("[proxy] unusable status=%s proxy=%s", getattr(resp, "status_code", "N/A"), p)
        return ok
    except Exception as e:
        logger.info("[proxy] unusable error=%s proxy=%s", str(e)[:160], p)
        return False
    finally:
        try:
            if session is not None:
                session.close()
        except Exception:
            pass


def pick_random_usable_proxy(
    proxies: str | Iterable[str],
    *,
    tester: Callable[[str], bool] | None = None,
) -> str:
    """随机排序后逐个探测，返回第一个可用代理；全部不可用则返回空串。"""
    if isinstance(proxies, str):
        candidates = parse_proxy_pool(proxies)
    else:
        candidates = [str(p or "").strip() for p in proxies if str(p or "").strip()]
    if not candidates:
        return ""
    random.shuffle(candidates)
    check = tester or is_proxy_usable
    for proxy in candidates:
        if check(proxy):
            return proxy
    return ""
