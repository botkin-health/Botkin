#!/usr/bin/env python3
"""HTTP-клиент Botkin для MCP-коннектора Claude Desktop (#228).

Без зависимости от `mcp` — чистый requests-клиент, поэтому полностью юнит-тестируем.
Держит durable PAT, обменивает его на короткоживущий JWT через
POST /api/agent/exchange_pat_for_jwt и кэширует JWT до истечения. На 401 (JWT
протух или PAT отозван) — один переобмен и повтор; на 403 — понятная ошибка про ro.

Запускается на МАШИНЕ ПОЛЬЗОВАТЕЛЯ (внутри Claude Desktop), не на сервере Botkin.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

EXCHANGE_PATH = "/api/agent/exchange_pat_for_jwt"
DEFAULT_TIMEOUT = 30
EXCHANGE_TIMEOUT = 15
# Обновляем JWT чуть раньше истечения, чтобы не словить 401 на границе.
TTL_BUFFER_S = 30


class BotkinAuthError(Exception):
    """PAT недействителен/отозван или у токена не хватает прав (ro на write)."""


class BotkinAPIError(Exception):
    """Сервер вернул 4xx/5xx. Сообщение несёт `detail` сервера (напр. «days must be
    between 1 and 90»), чтобы Claude пользователя видел причину, а не голый «400»."""

    def __init__(self, status_code: int, detail: str, method: str = "", path: str = ""):
        self.status_code = status_code
        self.detail = detail
        where = f" ({method} {path})" if method or path else ""
        super().__init__(f"Botkin API {status_code}{where}: {detail}")


def _error_detail(resp: Any) -> str:
    """Достаёт FastAPI `detail` из тела ошибки; иначе — кусок текста ответа."""
    try:
        body = resp.json()
    except Exception:
        body = None
    if isinstance(body, dict) and "detail" in body:
        d = body["detail"]
        if isinstance(d, list):  # 422 от pydantic: [{"loc": [...], "msg": "..."}]
            parts = []
            for e in d:
                if isinstance(e, dict):
                    loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("query", "body"))
                    parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
                else:
                    parts.append(str(e))
            return "; ".join(parts)
        return str(d)
    text = (getattr(resp, "text", "") or "").strip()
    return text[:300] or "без описания"


class BotkinClient:
    def __init__(
        self,
        base_url: str,
        pat: str,
        *,
        session: Optional[requests.Session] = None,
        ttl_buffer_s: int = TTL_BUFFER_S,
    ):
        if not base_url:
            raise ValueError("base_url is required")
        if not pat:
            raise ValueError("PAT is required (env BOTKIN_PAT)")
        self.base_url = base_url.rstrip("/")
        self.pat = pat
        self._session = session or requests.Session()
        self._ttl_buffer = ttl_buffer_s
        self._jwt: Optional[str] = None
        self._jwt_expires_at: float = 0.0

    # ── auth ──────────────────────────────────────────────────────────────────

    def _now(self) -> float:
        return time.time()

    def _needs_refresh(self) -> bool:
        return self._jwt is None or self._now() >= self._jwt_expires_at

    def _fetch_jwt(self) -> str:
        resp = self._session.post(f"{self.base_url}{EXCHANGE_PATH}", json={"pat": self.pat}, timeout=EXCHANGE_TIMEOUT)
        if resp.status_code == 401:
            raise BotkinAuthError("PAT недействителен или отозван — выпусти новый через /connect_mcp")
        resp.raise_for_status()
        data = resp.json()
        self._jwt = data["access_token"]
        self._jwt_expires_at = self._now() + max(0, int(data.get("expires_in", 3600)) - self._ttl_buffer)
        return self._jwt

    def _bearer(self) -> str:
        if self._needs_refresh():
            self._fetch_jwt()
        return self._jwt  # type: ignore[return-value]

    # ── requests ────────────────────────────────────────────────────────────────

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> Any:
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"

        def _do() -> requests.Response:
            return self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {self._bearer()}"},
                timeout=DEFAULT_TIMEOUT,
            )

        resp = _do()
        if resp.status_code == 401:
            # JWT протух/отозван между запросами — сбрасываем кэш и пробуем один раз ещё.
            self._jwt = None
            self._jwt_expires_at = 0.0
            resp = _do()
        if resp.status_code == 403:
            raise BotkinAuthError("Недостаточно прав: токен только для чтения (ro), запись запрещена")
        if resp.status_code >= 400:
            raise BotkinAPIError(resp.status_code, _error_detail(resp), method, path)
        return resp.json()

    def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return self.request("GET", path, params=clean or None)

    def post(self, path: str, payload: dict) -> Any:
        return self.request("POST", path, json_body=payload)
