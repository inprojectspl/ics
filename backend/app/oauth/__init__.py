"""OAuth in ICS: `google` is the Google OIDC SSO client; the other submodules
form the OAuth 2.1 Authorization Server for MCP clients (MCP spec 2025-11-25:
PKCE S256, RFC 8707 resource indicators, refresh rotation with reuse
detection, RS256 JWTs verifiable via `/jwks.json`).
"""

from app.oauth.google import get_oauth

__all__ = ["get_oauth"]
