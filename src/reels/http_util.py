"""HTTPS client helpers that trust the OS certificate store.

httpx defaults to certifi's CA bundle. On Windows, antivirus HTTPS scanning
(Avast/AVG/etc.) inserts a local MITM CA into the system store — browsers trust
it, certifi does not → CERTIFICATE_VERIFY_FAILED. Using truststore fixes that.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ssl_context: ssl.SSLContext | bool | None = None
_using_system_store = False


def _build_verify() -> ssl.SSLContext | bool:
    global _using_system_store
    try:
        import truststore

        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        _using_system_store = True
        return ctx
    except Exception as exc:
        logger.warning("truststore unavailable (%s); falling back to certifi CA bundle", exc)
        _using_system_store = False
        return True


def ssl_verify() -> ssl.SSLContext | bool:
    """Return verify= argument for httpx (system store when possible)."""
    global _ssl_context
    if _ssl_context is None:
        _ssl_context = _build_verify()
    return _ssl_context


def uses_system_trust_store() -> bool:
    ssl_verify()
    return _using_system_store


def http_client(**kwargs: Any) -> httpx.Client:
    """httpx.Client that verifies TLS via the OS trust store when available."""
    kwargs.setdefault("verify", ssl_verify())
    return httpx.Client(**kwargs)


def format_ssl_error(exc: BaseException) -> str:
    msg = str(exc)
    if "CERTIFICATE_VERIFY_FAILED" in msg or "certificate verify failed" in msg.lower():
        return (
            f"{msg} — Often caused by antivirus HTTPS scanning (e.g. Avast). "
            "The app prefers the Windows certificate store; if this persists, "
            "disable HTTPS/SSL scanning for Python or add the AV root CA to Trusted Root."
        )
    return msg
