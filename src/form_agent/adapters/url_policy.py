"""URL and network checks for user-selected web forms."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit


def validate_web_url(url: str, allowed_hosts: tuple[str, ...] = ()) -> SplitResult:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").encode("idna").decode().lower().rstrip(".")
        port = parsed.port
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or (port is not None and not 1 <= port <= 65535)
            or any(character.isspace() or ord(character) < 32 for character in url)
            or "\\" in url
        ):
            raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Informe uma URL HTTP ou HTTPS válida, sem usuário ou senha.") from exc
    trusted = {name.lower().rstrip(".") for name in allowed_hosts}
    if host not in trusted:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
                raise ValueError("Esse destino local não foi habilitado pelo servidor.") from None
        else:
            if not address.is_global:
                raise ValueError("Esse destino local não foi habilitado pelo servidor.")
    return parsed


async def validate_network_url(url: str, allowed_hosts: tuple[str, ...] = ()) -> None:
    parsed = validate_web_url(url, allowed_hosts)
    host = (parsed.hostname or "").encode("idna").decode().lower().rstrip(".")
    if host in {name.lower().rstrip(".") for name in allowed_hosts}:
        return
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        async with asyncio.timeout(5):
            addresses = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
    except (OSError, TimeoutError) as exc:
        raise ValueError("Não foi possível localizar o servidor do formulário.") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("O endereço do formulário aponta para uma rede não habilitada.")
