import ipaddress
import socket
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import PoolManager

_STRICT = False


class BlockedAddressError(requests.exceptions.ConnectionError):
    pass


class RedirectBlockedError(requests.exceptions.RequestException):
    pass


def set_strict(value: bool) -> None:
    global _STRICT
    _STRICT = bool(value)


def is_strict() -> bool:
    return _STRICT


def is_blocked_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def host_is_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    return any(is_blocked_ip(info[4][0]) for info in infos)


def _check_socket(sock: Any) -> None:
    peer = sock.getpeername()[0]
    if is_blocked_ip(peer):
        sock.close()
        raise BlockedAddressError(f"connection to non public address {peer} refused")


class _GuardMixin:
    def _new_conn(self):
        sock = super()._new_conn()
        _check_socket(sock)
        return sock


class _SafeHTTPConnection(_GuardMixin, HTTPConnection):
    pass


class _SafeHTTPSConnection(_GuardMixin, HTTPSConnection):
    pass


class _SafeHTTPPool(HTTPConnectionPool):
    ConnectionCls = _SafeHTTPConnection


class _SafeHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _SafeHTTPSConnection


class _SafePoolManager(PoolManager):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = {"http": _SafeHTTPPool, "https": _SafeHTTPSPool}


class _SafeAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self._pool_connections = connections
        self._pool_maxsize = maxsize
        self._pool_block = block
        self.poolmanager = _SafePoolManager(num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)


class StrictSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.trust_env = False
        adapter = _SafeAdapter()
        self.mount("http://", adapter)
        self.mount("https://", adapter)

    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        resp = super().request(method, url, **kwargs)
        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("Location", "")
            resp.close()
            raise RedirectBlockedError(
                f"redirects are not followed in strict mode (got {resp.status_code} to {location!r})"
            )
        return resp


def new_session() -> requests.Session:
    return StrictSession() if _STRICT else requests.Session()
