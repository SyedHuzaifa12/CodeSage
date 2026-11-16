"""Turn a libpq-style PostgreSQL URL into what SQLAlchemy + asyncpg accept.

Hosted providers (Neon, Render) hand you one URL such as::

    postgresql://user:pass@ep-x-pooler.eu-central-1.aws.neon.tech/db?sslmode=require&channel_binding=require

asyncpg cannot use that as is: it does not understand ``sslmode`` (it wants an
``ssl`` argument) and rejects ``channel_binding`` outright, and a pooled
(PgBouncer, transaction-mode) endpoint needs prepared-statement caching turned
off. Doing the translation in one pure, tested function means a deploy is "paste
the URL", not "learn which query parameters crash the driver".
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.engine import make_url

_ASYNC_DRIVER = "postgresql+asyncpg"
_ACCEPTED_DRIVERS = {"postgres", "postgresql", "postgresql+asyncpg"}

# libpq sslmode -> the value asyncpg's ``ssl`` argument takes (it accepts the same names).
_SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
# Query parameters libpq has and asyncpg does not; dropped rather than passed through to crash the driver.
_UNSUPPORTED_PARAMS = {"channel_binding", "options", "gssencmode", "target_session_attrs", "sslrootcert"}


@dataclass(frozen=True)
class PreparedDsn:
    """A SQLAlchemy URL plus the driver arguments that go with it."""

    url: str  # contains the password: treat as a secret, never log it
    connect_args: dict[str, Any] = field(default_factory=dict)
    pooled: bool = False


def _is_pooler_host(host: Optional[str]) -> bool:
    # Neon's pooled endpoints have "-pooler" in the first label of the hostname.
    return bool(host) and "-pooler" in host.split(".")[0]


def prepare_asyncpg_dsn(raw: str, *, sslmode: Optional[str] = None, pooled: Optional[bool] = None) -> PreparedDsn:
    """Translate ``raw`` for SQLAlchemy's asyncpg dialect.

    Args:
        raw: A ``postgres://``, ``postgresql://`` or ``postgresql+asyncpg://`` URL.
        sslmode: Used when the URL has no ``sslmode`` of its own (discrete-setting configs).
        pooled: Force pooled-endpoint behaviour on or off; ``None`` detects Neon's ``-pooler`` hosts.

    Returns:
        The cleaned URL, driver arguments, and whether the endpoint is a transaction-mode pooler.

    Raises:
        ValueError: If ``raw`` is not a usable PostgreSQL URL. The message never includes the URL.
    """
    try:
        url = make_url(raw)
    except Exception as exc:  # noqa: BLE001 -- sqlalchemy's message would echo the URL, password included
        raise ValueError("The database URL is not a valid URL.") from exc
    if url.drivername not in _ACCEPTED_DRIVERS:
        raise ValueError(f"The database URL must be a PostgreSQL URL, not '{url.drivername}'.")
    if not url.host:
        raise ValueError("The database URL has no host.")

    query = dict(url.query)
    mode = query.pop("sslmode", None) or sslmode
    for name in _UNSUPPORTED_PARAMS:
        query.pop(name, None)

    connect_args: dict[str, Any] = {}
    if mode is not None:
        if mode not in _SSLMODES:
            raise ValueError(f"Unknown sslmode '{mode}'.")
        if mode != "disable":
            connect_args["ssl"] = mode
        else:
            connect_args["ssl"] = False

    is_pooled = _is_pooler_host(url.host) if pooled is None else pooled
    if is_pooled:
        # PgBouncer in transaction mode hands each statement to a different server connection, so asyncpg's
        # per-connection prepared statements and their cache would point at statements that are not there.
        connect_args.update(
            statement_cache_size=0,
            prepared_statement_cache_size=0,
            prepared_statement_name_func=lambda: f"__asyncpg_{uuid.uuid4()}__",
        )

    cleaned = url.set(drivername=_ASYNC_DRIVER, query=query)
    return PreparedDsn(url=cleaned.render_as_string(hide_password=False), connect_args=connect_args, pooled=is_pooled)
