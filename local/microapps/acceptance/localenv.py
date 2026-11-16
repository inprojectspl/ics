"""Shared setup of the local acceptance scripts.

Everything points at the local profile only: the env file written by
`scripts/microapps-local.sh init`, the local CA exported by `up`, and a fresh
ICS-MCP credential profile per test user (own keyring service name, own
token file, no OS keyring, nothing imported from an existing profile).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import ssl
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / ".microapps-local"
ENV_FILE = ROOT / ".env.microapps.local"
MCP_CHECKOUT = Path(os.environ.get("ICS_MCP_CHECKOUT", ROOT.parent / "ics-mcp")).resolve()
BASE_URL = "https://ics.localhost:8443"
RESOURCE = f"{BASE_URL}/mcp"
# Apps live on a site of their own (not under ics.localhost), as in
# production: their code cannot set cookies for ICS.
APP_SUFFIX = "ics-apps.localhost:8443"
EXAMPLES = ROOT / "examples" / "microapps"
USERS = ("alice", "bob", "carol", "dave")
LOCAL_HOSTS = ("ics.localhost", "html.ics.localhost", "ics-apps.localhost", "mail.ics.localhost")


def env_values() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def password(user: str) -> str:
    values = env_values()
    return values["ICS_BOOTSTRAP_ADMIN_PASSWORD"] if user == "admin" else values["ICS_LOCAL_USER_PASSWORD"]


def email(user: str) -> str:
    return f"{user}@example.com"


def assert_local_target() -> None:
    """Refuse to run against anything but the local profile."""
    for url in (BASE_URL, RESOURCE):
        host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
        if not any(host == h or host.endswith("." + h) for h in LOCAL_HOSTS):
            sys.exit(f"refusing non-local target {url}")
    if not (STATE / "local-ca.crt").exists():
        sys.exit("local CA not exported: run scripts/microapps-local.sh up")


def ca_bundle() -> Path:
    """certifi roots plus the local CA, for Python clients (SSL_CERT_FILE)."""
    import certifi

    bundle = STATE / "ca-bundle.pem"
    bundle.write_text(Path(certifi.where()).read_text() + "\n" + (STATE / "local-ca.crt").read_text())
    return bundle


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(ca_bundle()))


def chain_spki() -> str:
    """SPKI hashes of the local CA chain (CA and server certificate), for
    Chromium's --ignore-certificate-errors-spki-list: it trusts exactly this
    local CA, not every certificate."""
    # The CA and the leaf nginx serves (both are in tls/server.crt).
    chain = (STATE / "tls" / "server.crt").read_text()
    pems = [b.encode() + b"-----END CERTIFICATE-----\n" for b in chain.split("-----END CERTIFICATE-----") if b.strip()]
    hashes = []
    for pem in pems:
        der = subprocess.run(["openssl", "x509", "-pubkey", "-noout"], input=pem, capture_output=True, check=True).stdout
        spki = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "der"], input=der, capture_output=True, check=True).stdout
        hashes.append(base64.b64encode(hashlib.sha256(spki).digest()).decode())
    return ",".join(hashes)


def _browser_wrapper() -> Path:
    """`webbrowser` takes BROWSER as one executable (a value with spaces falls
    back to the system browser), so point it at a generated wrapper."""
    wrapper = STATE / "login-browser.sh"
    wrapper.write_text(
        f"#!/bin/sh\nexec {sys.executable} {Path(__file__).with_name('login_browser.py')} \"$@\"\n"
    )
    wrapper.chmod(0o700)
    return wrapper


def mcp_env(user: str) -> dict[str, str]:
    STATE.mkdir(exist_ok=True)
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "ICS_BASE_URL": BASE_URL,
        "ICS_MCP_RESOURCE_URI": RESOURCE,
        "ICS_MCP_TRANSPORT": "stdio",
        # Fresh, separate credential profile per local test user.
        "ICS_MCP_KEYRING_SERVICE": f"ics-mcp-local-microapps-{user}",
        "ICS_MCP_TOKEN_FALLBACK_PATH": str(STATE / f"mcp-credentials-{user}.json"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
        "ICS_MCP_DEFAULT_CONFIRM": "interactive",
        "SSL_CERT_FILE": str(ca_bundle()),
        # The stdio OAuth login opens this "browser": a headless Chromium that
        # signs in with the local test password and grants consent.
        "BROWSER": str(_browser_wrapper()),
        "ICS_LOCAL_LOGIN_EMAIL": email(user),
        "ICS_LOCAL_LOGIN_PASSWORD": password(user),
        "ICS_LOCAL_SPKI": chain_spki(),
    }


@contextlib.asynccontextmanager
async def mcp_client(user: str) -> AsyncIterator[Any]:
    """A real MCP stdio session to the local ICS-MCP checkout."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command="uv",
        args=["run", "--quiet", "--project", str(MCP_CHECKOUT), "ics-mcp"],
        env=mcp_env(user),
        cwd=str(MCP_CHECKOUT),
    )
    async with Client(transport, timeout=180) as client:
        yield client


async def call(client: Any, tool: str, args: dict[str, Any] | None = None, *, expect_error: bool = False) -> Any:
    result = await client.call_tool(tool, args or {}, raise_on_error=False)
    text = "".join(getattr(c, "text", "") for c in result.content)
    if result.is_error:
        if expect_error:
            try:
                return json.loads(text)
            except ValueError:
                return {"error": text}
        raise RuntimeError(f"{tool} failed: {text[:2000]}")
    if expect_error:
        raise RuntimeError(f"{tool} unexpectedly succeeded: {text[:500]}")
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(text) if text else None


def package_files(name: str) -> list[dict[str, str]]:
    root = EXAMPLES / name if (EXAMPLES / name).is_dir() else Path(__file__).with_name(name)
    return [
        {"path": str(p.relative_to(root)), "content_path": str(p)}
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.name.startswith(".")
    ]
