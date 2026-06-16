"""重新拿 refresh_token：基于已注册号的 session_token + access_token 重走 Codex OAuth。

适用场景：
  - 注册时 Codex OAuth 失败（OpenAI 反欺诈对新号 100% 返 token_exchange_user_error）
  - 号"养"几天后重新点这个按钮，借助已存的 session_token 复活会话再换 RT
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config  # noqa: E402
from auth_flow import AuthFlow  # noqa: E402
from sms_provider import PhoneCallbackController  # noqa: E402

from . import db  # noqa: E402

logger = logging.getLogger("refetch_rt")


def _build_sms_callback() -> Optional[PhoneCallbackController]:
    """构造 SMS 接码 controller（重拿 RT 走 Codex OAuth 时同样会触发 add-phone）。"""
    cfg = db.get_sms_internal_config()
    if not cfg.get("sms_enabled"):
        return None
    if not (cfg.get("sms_api_key") or "").strip():
        return None
    try:
        return PhoneCallbackController(
            provider_key=cfg["sms_provider"],
            config=cfg,
            service=cfg.get("sms_service") or "openai",
            country=cfg.get("sms_country") or "52",
            log_fn=logger.info,
            auto_select_country=bool(cfg.get("sms_auto_country")),
        )
    except Exception as e:
        logger.warning(f"[sms] 创建接码 controller 失败: {e}")
        return None


def refetch_refresh_token(
    email: str,
    proxy: Optional[str] = None,
    allow_retry: bool = True,
    force: bool = False,
) -> dict:
    """用已存的凭证重新走 Codex OAuth 拿 refresh_token。

    Args:
        email:    DB 里已注册的邮箱
        proxy:    出口代理（沿用前端传的）
        force:    True = 即使已有 RT 也强制再拿一次（覆盖旧值）
                  False（默认）= 已有非空 RT 直接跳过

    返回 {ok, refresh_token_len, error, before_len, after_len, skipped}
    """
    row = db.get_registered(email)
    if not row:
        return {"ok": False, "error": f"DB 里没有 {email}"}

    access_token = (row.get("access_token") or "").strip()
    session_token = (row.get("session_token") or "").strip()
    if not access_token and not session_token:
        return {"ok": False, "error": "该号既无 access_token 也无 session_token，无法重试"}

    before_rt = (row.get("refresh_token") or "").strip()
    before_len = len(before_rt)

    # 短路：已有 RT 且不强制 → 直接返成功
    if before_rt and not force:
        return {
            "ok": True,
            "skipped": True,
            "refresh_token_len": before_len,
            "before_len": before_len,
            "after_len": before_len,
            "message": "已有 refresh_token，跳过重拿（如需强制覆盖请传 force=true）",
        }

    cfg = Config()
    cfg.proxy = (proxy or "").strip() or None

    # 强制允许 retry（避免 _codex_rt_attempted 拦截）
    saved_env = {
        "OAUTH_CODEX_RT_ALLOW_RETRY": os.environ.get("OAUTH_CODEX_RT_ALLOW_RETRY"),
        "OAUTH_CODEX_RT_EXCHANGE":    os.environ.get("OAUTH_CODEX_RT_EXCHANGE"),
    }
    os.environ["OAUTH_CODEX_RT_ALLOW_RETRY"] = "1"
    os.environ["OAUTH_CODEX_RT_EXCHANGE"] = "1"

    try:
        flow = AuthFlow(cfg, sms_callback=_build_sms_callback())
        # 把已有凭证灌进 result + cookie jar
        flow.from_existing_credentials(
            session_token=session_token,
            access_token=access_token,
            device_id=(row.get("device_id") or ""),
        )
        flow.result.email = email

        logger.info(f"[refetch] {email} 走 Codex OAuth 重试 (before_rt_len={before_len} force={force})")
        ok = flow.oauth_codex_rt_exchange(mail_provider=None)
        new_rt = (flow.result.refresh_token or "").strip()
        after_len = len(new_rt)

        if ok and new_rt:
            # 落库（保留原有 session_token / cookie_header；只更新 RT 相关字段）
            db.save_registered({
                "email": email,
                "password": row.get("password", ""),
                "access_token": (flow.result.access_token or row.get("access_token", "")),
                "session_token": row.get("session_token", ""),
                "refresh_token": new_rt,
                "id_token": (flow.result.id_token or row.get("id_token", "")),
                "device_id": row.get("device_id", ""),
                "csrf_token": row.get("csrf_token", ""),
                "cookie_header": row.get("cookie_header", ""),
            })
            return {
                "ok": True,
                "refresh_token_len": after_len,
                "before_len": before_len,
                "after_len": after_len,
                "skipped": False,
            }
        else:
            # 注意：不覆盖旧 RT
            return {
                "ok": False,
                "error": (
                    "Codex OAuth 失败"
                    + ("（号可能在 OpenAI 反欺诈观察期，建议 1-7 天后再试）"
                       if before_len == 0 else
                       "（无法获取新的 RT；旧的 refresh_token 仍然有效，已保留）")
                ),
                "before_len": before_len,
                "after_len": before_len,  # 旧的还在
                "skipped": False,
            }
    except Exception as e:
        logger.exception(f"refetch RT 异常: {e}")
        return {"ok": False, "error": str(e), "before_len": before_len}
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
