"""Единый резолвер IP клиента для rate-limit'ов.

Цепочка на проде: Cloudflare → nginx (real_ip_header CF-Connecting-IP только из
диапазонов CF) → docker-proxy 127.0.0.1:8081 → контейнер. Внутри контейнера
request.client.host — адрес docker-шлюза, одинаковый для всех клиентов, поэтому
по нему лимиты становились глобальными (security review 11.2026, F4).

nginx ПЕРЕЗАПИСЫВАЕТ X-Real-IP значением $remote_addr (snippets/botkin-backend.conf),
так что заголовку можно верить — но только если соединение пришло от прокси на
приватном/loopback-адресе. Прямой клиент с публичного адреса подставить себе
X-Real-IP не сможет: для него берём адрес соединения.
"""

import ipaddress

from fastapi import Request


def _is_trusted_proxy(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    if peer and _is_trusted_proxy(peer):
        real = (request.headers.get("x-real-ip") or "").strip()
        if real:
            try:
                return str(ipaddress.ip_address(real))
            except ValueError:
                pass
    return peer or "unknown"
