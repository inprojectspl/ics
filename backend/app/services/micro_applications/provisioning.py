"""Trusted provisioning in the `ics_apps` database (worker only).

Takes identifiers from the platform binding and DDL from `ddl.py`; it never
receives SQL or shell input from a package. Every step can run again after a
crash: it checks what exists instead of creating blindly.

Per asset and environment: schema `a_<hex>`, NOLOGIN owner role (DDL through
`SET LOCAL ROLE`) and a LOGIN runtime role that holds DML on the app's
tables only and is not a member of the owner or of any other role.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import asyncpg

from app.config import Settings
from app.services.micro_applications import ddl

RUNTIME_SETTINGS = {
    "statement_timeout": "2s",
    "lock_timeout": "500ms",
    "idle_in_transaction_session_timeout": "5s",
}
RUNTIME_CONNECTION_LIMIT = 2


@dataclass(frozen=True)
class Names:
    database: str
    schema: str
    owner: str
    runtime: str

    @classmethod
    def for_asset(cls, asset_hex: str, environment: str, database: str = "ics_apps") -> Names:
        if len(asset_hex) != 32 or any(c not in "0123456789abcdef" for c in asset_hex):
            raise ValueError("asset_hex")
        suffix = "" if environment == "prod" else "_pv"
        return cls(
            database=database,
            schema=f"a_{asset_hex}{suffix}",
            owner=f"ma_{asset_hex}{suffix}_owner",
            runtime=f"ma_{asset_hex}{suffix}_run",
        )


def apps_database(settings: Settings) -> str:
    """Name of the apps database the provisioner URL points at."""
    from urllib.parse import urlparse

    return urlparse(settings.microapps_apps_database_url).path.lstrip("/") or "ics_apps"


def new_password() -> str:
    return secrets.token_urlsafe(32)


def scram_verifier(password: str, iterations: int = 4096) -> str:
    """PostgreSQL's stored SCRAM-SHA-256 form (RFC 5802 / 7677)."""
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = base64.b64encode
    return (
        f"SCRAM-SHA-256${iterations}:{b64(salt).decode()}"
        f"${b64(stored_key).decode()}:{b64(server_key).decode()}"
    )


@asynccontextmanager
async def provisioner(settings: Settings, dsn: str | None = None):
    url = dsn or settings.microapps_apps_database_url
    if not url:
        raise RuntimeError("ICS_MICROAPPS_APPS_DATABASE_URL is not configured")
    conn = await asyncpg.connect(url, timeout=10)
    try:
        yield conn
    finally:
        await conn.close()


def _q(name: str) -> str:
    return ddl.ident(name)


async def ensure_roles_and_schema(conn: asyncpg.Connection, n: Names, password: str) -> None:
    """Idempotent: roles, schema, ACL defaults and runtime session settings."""
    me = await conn.fetchval("SELECT current_user")
    async with conn.transaction():
        owner_exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", n.owner)
        if not owner_exists:
            await conn.execute(
                f"CREATE ROLE {_q(n.owner)} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            )
        run_exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", n.runtime)
        if not run_exists:
            await conn.execute(
                f"CREATE ROLE {_q(n.runtime)} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                f"NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT {RUNTIME_CONNECTION_LIMIT}"
            )
        # Only a SCRAM verifier reaches the server, never the password itself,
        # so it cannot surface in statement logs or pg_stat_activity.
        await conn.execute(f"ALTER ROLE {_q(n.runtime)} PASSWORD {_lit(scram_verifier(password))}")
        # The provisioner needs to act as the owner to create objects it owns.
        await conn.execute(f"GRANT {_q(n.owner)} TO {_q(me)} WITH SET TRUE, INHERIT FALSE")
        schema_exists = await conn.fetchval(
            "SELECT 1 FROM pg_namespace WHERE nspname = $1", n.schema
        )
        if not schema_exists:
            await conn.execute(f"CREATE SCHEMA {_q(n.schema)} AUTHORIZATION {_q(n.owner)}")
        await conn.execute(f"GRANT CONNECT ON DATABASE {_q(n.database)} TO {_q(n.runtime)}")
        # Schema ACL is the owner's to change.
        await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
        await conn.execute(f"REVOKE ALL ON SCHEMA {_q(n.schema)} FROM PUBLIC")
        await conn.execute(f"GRANT USAGE ON SCHEMA {_q(n.schema)} TO {_q(n.runtime)}")
        # Defaults for objects the owner creates, set as the owner itself.
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {_q(n.owner)} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
        )
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {_q(n.owner)} REVOKE USAGE ON TYPES FROM PUBLIC"
        )
        await conn.execute("RESET ROLE")
        await conn.execute(
            f"ALTER ROLE {_q(n.runtime)} IN DATABASE {_q(n.database)} "
            f"SET search_path = pg_catalog, {_q(n.schema)}, pg_temp"
        )
        for key, value in RUNTIME_SETTINGS.items():
            await conn.execute(
                f"ALTER ROLE {_q(n.runtime)} IN DATABASE {_q(n.database)} SET {key} = {_lit(value)}"
            )
        has_system = await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname = $1 AND tablename = '_ics_audit'", n.schema
        )
        if not has_system:
            await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
            for stmt in ddl.SYSTEM_TABLES:
                await conn.execute(stmt.format(s=_q(n.schema)))
            await conn.execute("RESET ROLE")
        await _grant_system(conn, n)


def _lit(value: str) -> str:
    if "\x00" in value:
        raise ValueError("NUL")
    return "'" + value.replace("'", "''") + "'"


async def _grant_system(conn: asyncpg.Connection, n: Names) -> None:
    s, r = _q(n.schema), _q(n.runtime)
    await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
    await conn.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {s}."_ics_idempotency" TO {r}')
    await conn.execute(f'GRANT INSERT ON {s}."_ics_audit" TO {r}')
    await conn.execute(f'REVOKE ALL ON {s}."_ics_schema_migrations" FROM {r}')
    await conn.execute("RESET ROLE")


async def applied_versions(conn: asyncpg.Connection, n: Names) -> dict[int, str]:
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
        rows = await conn.fetch(
            f'SELECT version, checksum FROM {_q(n.schema)}."_ics_schema_migrations"'
        )
    return {r["version"]: r["checksum"] for r in rows}


async def migrate(
    conn: asyncpg.Connection,
    n: Names,
    *,
    version: int,
    statements: list[str],
    collections: list[str],
    operation_id: str,
    seed_statements: Sequence[str],
) -> str:
    """Apply one schema version in one transaction, as the owner role, and
    the seed rows of the collections it creates.

    Returns `applied` or `already_applied` (same version and checksum after a
    retry). A different checksum under the same version is a hard error. The
    log keeps the DDL and a digest of the seed rows, not the data."""
    logged = list(statements)
    if seed_statements:
        logged.append(f"-- seed rows: {ddl.checksum(list(seed_statements))}")
    checksum = ddl.checksum(logged)
    done = await applied_versions(conn, n)
    if version in done:
        if done[version] != checksum:
            raise RuntimeError("schema version already applied with different statements")
        await grant_collections(conn, n, collections)
        return "already_applied"
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
        await conn.execute("SET LOCAL lock_timeout = '3s'")
        for stmt in (*statements, *seed_statements):
            await conn.execute(stmt)
        await conn.execute(
            f'INSERT INTO {_q(n.schema)}."_ics_schema_migrations" '
            "(version, checksum, operation_id, statements) VALUES ($1, $2, $3, $4)",
            version,
            checksum,
            operation_id,
            json.dumps(logged),
        )
        for coll in collections:
            await conn.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_q(n.schema)}.{_q(coll)} TO {_q(n.runtime)}"
            )
        await conn.execute("RESET ROLE")
    return "applied"


async def grant_collections(conn: asyncpg.Connection, n: Names, collections: list[str]) -> None:
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
        for coll in collections:
            await conn.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_q(n.schema)}.{_q(coll)} TO {_q(n.runtime)}"
            )
        await conn.execute("RESET ROLE")


async def grant_reader(conn: asyncpg.Connection, n: Names, reader: str) -> bool:
    """Lets `reader` read every table of the app, including tables later
    migrations add. False (nothing granted) when the role does not exist:
    it is created by the database administrator, not by ICS."""
    if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", reader):
        return False
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
        await conn.execute(f"GRANT USAGE ON SCHEMA {_q(n.schema)} TO {_q(reader)}")
        await conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {_q(n.schema)} TO {_q(reader)}")
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {_q(n.owner)} IN SCHEMA {_q(n.schema)} "
            f"GRANT SELECT ON TABLES TO {_q(reader)}"
        )
        await conn.execute("RESET ROLE")
    return True


async def verify(
    conn: asyncpg.Connection, n: Names, collections: list[str], reader: str = ""
) -> list[str]:
    """Problems with ownership and ACL after a migration; empty means OK.
    Runs as the owner: resolving names in the schema needs its USAGE."""
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
        problems = await _verify(conn, n, collections)
        if reader and await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", reader):
            problems += await _verify_reader(conn, n, collections, reader)
        return problems


async def _verify_reader(
    conn: asyncpg.Connection, n: Names, collections: list[str], reader: str
) -> list[str]:
    """The reader reads and nothing more."""
    problems: list[str] = []
    if await conn.fetchval("SELECT has_schema_privilege($1, $2, 'CREATE')", reader, n.schema):
        problems.append("reader role may CREATE in the schema")
    for coll in collections:
        qualified = f"{_q(n.schema)}.{_q(coll)}"
        for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "REFERENCES"):
            if await conn.fetchval(
                "SELECT has_table_privilege($1, $2, $3)", reader, qualified, priv
            ):
                problems.append(f"reader role has {priv} on {coll}")
    return problems


async def _verify(conn: asyncpg.Connection, n: Names, collections: list[str]) -> list[str]:
    problems: list[str] = []
    role = await conn.fetchrow(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolinherit, rolcanlogin "
        "FROM pg_roles WHERE rolname = $1",
        n.runtime,
    )
    if role is None:
        return ["runtime role missing"]
    for attr in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls"):
        if role[attr]:
            problems.append(f"runtime role has {attr}")
    memberships = await conn.fetch(
        "SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
        "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = $1",
        n.runtime,
    )
    if memberships:
        problems.append(f"runtime role is a member of {[m['rolname'] for m in memberships]}")
    if await conn.fetchval("SELECT has_schema_privilege($1, $2, 'CREATE')", n.runtime, n.schema):
        problems.append("runtime role may CREATE in its schema")
    owner = await conn.fetchval(
        "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = $1", n.schema
    )
    if owner != n.owner:
        problems.append(f"schema owned by {owner}")
    if await conn.fetchval("SELECT has_schema_privilege('public', $1, 'USAGE')", n.schema):
        problems.append("PUBLIC has USAGE on the schema")
    tables = await conn.fetch(
        "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = $1", n.schema
    )
    names = {t["tablename"] for t in tables}
    for t in tables:
        if t["tableowner"] != n.owner:
            problems.append(f"table {t['tablename']} owned by {t['tableowner']}")
    for coll in collections:
        if coll not in names:
            problems.append(f"table {coll} missing")
            continue
        qualified = f"{_q(n.schema)}.{_q(coll)}"
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            if not await conn.fetchval(
                "SELECT has_table_privilege($1, $2, $3)", n.runtime, qualified, priv
            ):
                problems.append(f"runtime lacks {priv} on {coll}")
        for priv in ("TRUNCATE", "TRIGGER", "REFERENCES"):
            if await conn.fetchval(
                "SELECT has_table_privilege($1, $2, $3)", n.runtime, qualified, priv
            ):
                problems.append(f"runtime has {priv} on {coll}")
    if await conn.fetchval(
        "SELECT has_table_privilege($1, $2, 'SELECT')",
        n.runtime,
        f'{_q(n.schema)}."_ics_schema_migrations"',
    ):
        problems.append("runtime can read migration history")
    return problems


async def measure(conn: asyncpg.Connection, schemas: list[str]) -> dict[str, dict[str, Any]]:
    """Size and approximate row count per schema, user tables only (`_ics_`
    tables excluded). Reads catalog statistics; never opens a runtime pool."""
    rows = await conn.fetch(
        "SELECT n.nspname AS schema, count(c.oid)::int AS tables, "
        "coalesce(sum(pg_total_relation_size(c.oid)), 0)::bigint AS bytes, "
        "coalesce(sum(greatest(s.n_live_tup, 0)), 0)::bigint AS rows "
        "FROM pg_namespace n "
        "LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relkind = 'r' "
        "AND c.relname NOT LIKE '\\_ics\\_%' "
        "LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid "
        "WHERE n.nspname = ANY($1::text[]) GROUP BY n.nspname",
        schemas,
    )
    return {
        r["schema"]: {"tables": r["tables"], "bytes": r["bytes"], "rows": r["rows"]} for r in rows
    }


async def drop(conn: asyncpg.Connection, n: Names) -> None:
    """Cleanup after deletion: schema with its data, then both roles."""
    me = await conn.fetchval("SELECT current_user")
    try:
        # Open runtime sessions would block DROP ROLE; needs pg_signal_backend.
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = $1", n.runtime
        )
    except asyncpg.InsufficientPrivilegeError:
        pass
    async with conn.transaction():
        if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", n.owner):
            await conn.execute(f"GRANT {_q(n.owner)} TO {_q(me)} WITH SET TRUE, INHERIT FALSE")
            # As the owner itself: its schema, objects and default ACL entries.
            await conn.execute(f"SET LOCAL ROLE {_q(n.owner)}")
            await conn.execute(f"DROP SCHEMA IF EXISTS {_q(n.schema)} CASCADE")
            await conn.execute(f"DROP OWNED BY {_q(n.owner)}")
            await conn.execute("RESET ROLE")
        if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", n.runtime):
            await conn.execute(f"REVOKE ALL ON DATABASE {_q(n.database)} FROM {_q(n.runtime)}")
            await conn.execute(f"DROP ROLE {_q(n.runtime)}")
        if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", n.owner):
            await conn.execute(f"DROP ROLE {_q(n.owner)}")
