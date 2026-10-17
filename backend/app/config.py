from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Settings refuses this value outside debug.
_DEFAULT_SECRET_KEY = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ICS_", case_sensitive=False)

    database_url: str = "postgresql+asyncpg://ics:ics@host.docker.internal:5432/ics"
    redis_url: str = "redis://redis:6379/0"
    storage_url: str = "fs:///data/storage"

    base_url: str = "http://ics.localhost"
    # Single subdomain used for serving html_bundle assets in an isolated
    # origin. Owner/share landing on the main domain redirects here via a
    # short-lived signed grant URL.
    html_viewer_base: str = "http://html.ics.localhost"

    # CSV of allowed CORS origins for the API. In dev defaults to the
    # Vite dev server + local host; production must override with
    # ICS_CORS_ORIGINS=https://ics.example.com,...
    cors_origins: str = "http://localhost:5173,http://ics.localhost"

    # CSV of e-mail domains treated as the organisation (SSO login, invites,
    # org-only links). Empty by default: every deployment names its own.
    allowed_domains: str = ""

    secret_key: str = _DEFAULT_SECRET_KEY
    google_oidc_client_id: str = ""
    google_oidc_client_secret: str = ""

    dev_stub_sso: bool = False
    allow_self_register: bool = False
    debug: bool = False

    # Bootstrap admin: if both are set, startup creates or syncs this admin account.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    lockout_threshold: int = 10
    lockout_minutes: int = 15

    # Container image of the ics-sync CLI shown in the GitLab CI snippet of a
    # new binding. Empty means the UI asks the user to fill in their own.
    sync_image: str = ""

    max_asset_bytes: int = 100 * 1024 * 1024
    # Hard cap on any request body; leaves room for multipart framing around
    # a max-size asset upload.
    max_request_bytes: int = 110 * 1024 * 1024
    max_files_per_bundle: int = 500

    # PDF assets (ADR-0013). The cap is per file; text extraction runs in a
    # child process that is killed after the timeout.
    pdf_max_bytes: int = 50 * 1024 * 1024
    pdf_extract_timeout_seconds: float = 60.0
    pdf_extract_max_pages: int = 2000
    pdf_extract_max_chars: int = 5_000_000
    pdf_extract_memory_bytes: int = 2 * 1024 * 1024 * 1024

    # OCR of scanned PDF pages (ADR-0021). Runs in its own Arq queue, served
    # by the `ocr-worker` service, one child process per document.
    ocr_enabled: bool = True
    # Queue OCR on every upload or new version that has pages without text.
    ocr_auto: bool = True
    # Engine for automatic runs; a name from `services.ocr.providers`.
    ocr_provider: str = "local"
    # Engines a reader may pick on request. A cloud engine sends the document
    # to its operator and takes the reader's API key with the request.
    ocr_providers: list[str] = ["local", "mistral"]
    # Mistral OCR (`mistral` provider): model, endpoint, pages per request.
    ocr_mistral_model: str = "mistral-ocr-4-0"
    ocr_mistral_url: str = "https://api.mistral.ai/v1/ocr"
    ocr_mistral_chunk_pages: int = 20
    ocr_queue_name: str = "ics:ocr"
    # Documents recognized at once by one OCR worker (CPU bound).
    ocr_concurrency: int = 1
    # Whole-document budget, and the longest wait for the next page.
    ocr_timeout_seconds: int = 3600
    ocr_page_timeout_seconds: int = 120
    ocr_max_pages: int = 1000
    # Interrupted runs (worker restart, OOM kill) are queued again this often.
    ocr_max_attempts: int = 3
    # Local engine: render resolution, cap on the rendered page size, threads
    # of the ONNX runtime, and the child's address-space limit.
    ocr_dpi: int = 200
    ocr_max_page_pixels: int = 40_000_000
    ocr_threads: int = 2
    ocr_memory_bytes: int = 3 * 1024 * 1024 * 1024

    # Word/ODF documents (ADR-0014). `office_max_unzipped_bytes` caps what a
    # .docx/.odt may declare when unpacked (zip bomb guard).
    office_max_bytes: int = 50 * 1024 * 1024
    office_max_unzipped_bytes: int = 300 * 1024 * 1024
    office_convert_timeout_seconds: float = 60.0
    office_convert_max_chars: int = 5_000_000
    office_convert_memory_bytes: int = 2 * 1024 * 1024 * 1024

    # S3-compatible storage, used when `storage_url` is `s3://<bucket>`. Credentials
    # stay out of the URL, which leaks into logs and traces (examples in .env.example).
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "auto"

    # HTML bundle policy: `permissive` keeps only clearly dangerous patterns critical;
    # `strict` makes every external script and most active content critical.
    security_policy: str = "permissive"

    # Baseline trusted CDN hosts; admins extend it at runtime (`app.cdn_allowlist`).
    trusted_cdn_hosts: str = (
        "cdn.jsdelivr.net,cdnjs.cloudflare.com,unpkg.com,esm.sh,"
        "cdn.skypack.dev,fonts.googleapis.com,fonts.gstatic.com,"
        "ajax.googleapis.com,cdn.tailwindcss.com,d3js.org,cdn.plot.ly"
    )

    # OAuth 2.1 authorization and resource server for MCP. `mcp_resource_uri` is the
    # RFC 8707 audience clients must request. Key: `openssl genrsa 2048` as PEM.
    oauth_issuer: str = ""
    oauth_private_key_pem: str = ""
    oauth_private_key_pem_path: str = ""
    oauth_kid: str = "ics-2026-05"
    oauth_access_token_ttl: int = 3600
    oauth_refresh_token_ttl: int = 30 * 24 * 3600
    oauth_authcode_ttl: int = 600
    mcp_resource_uri: str = ""

    # Arq async job queue (reuses redis_url by default).
    arq_redis_url: str = ""
    arq_max_jobs: int = 10
    arq_job_timeout: int = 120

    # Optional SMTP relay (MailPit in dev); empty `smtp_host` keeps only the DB outbox.
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_from: str = "ICS <no-reply@ics.localhost>"
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False

    # Notifications (ADR-0023).
    notifications_inbox_max: int = 150
    notifications_retention_days: int = 30
    # Writes to one asset within this window collapse into one fan-out.
    notifications_update_debounce_seconds: int = 20
    notifications_email_batch_seconds: int = 600
    notifications_chat_batch_seconds: int = 60
    notifications_digest_hour: int = 8
    notifications_timezone: str = "Europe/Warsaw"
    # Web Push (VAPID, RFC 8292). Without the private key the channel is off.
    # Generate a pair with `python -m app.cli vapid-keygen`.
    vapid_private_key: str = ""
    vapid_subject: str = ""

    @property
    def allowed_domain_list(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_domains.split(",") if d.strip()]

    @property
    def html_viewer_origin(self) -> str:
        parts = urlsplit(self.html_viewer_base)
        return f"{parts.scheme}://{parts.netloc}".lower()

    @property
    def cors_origins_list(self) -> list[str]:
        """Configured CORS origins minus the HTML bundle viewer, whose same-site
        user pages would otherwise read the API as their viewer."""
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return [o for o in origins if o.rstrip("/").lower() != self.html_viewer_origin]

    @property
    def trusted_cdn_hosts_set(self) -> frozenset[str]:
        """Comma-separated env -> lowercase set."""
        return frozenset(h.strip().lower() for h in self.trusted_cdn_hosts.split(",") if h.strip())

    @model_validator(mode="after")
    def _refuse_default_secret_in_prod(self) -> "Settings":
        """Outside debug, the public default key would make sessions and grants forgeable."""
        if not self.debug and self.secret_key == _DEFAULT_SECRET_KEY:
            raise ValueError(
                "ICS_SECRET_KEY must be set to a unique value in production "
                "(debug=0). Generate one with: openssl rand -hex 32"
            )
        return self

    @model_validator(mode="after")
    def _refuse_stub_sso_in_prod(self) -> "Settings":
        """The dev SSO stub trusts the `x-dev-user` header, so outside debug
        mode it would let any caller sign in as any allowed user."""
        if self.dev_stub_sso and not self.debug:
            raise ValueError("ICS_DEV_STUB_SSO requires ICS_DEBUG=1; never enable it in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
