from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings


class TokenInvalid(Exception):
    pass


class TokenExpired(TokenInvalid):
    pass


_SERIALIZER = URLSafeTimedSerializer(get_settings().secret_key)

# TTLs in seconds
TTL = {
    "invite": 7 * 24 * 3600,
    "project_invite": 7 * 24 * 3600,
    "reset": 1 * 3600,
    "verify": 24 * 3600,
    # Greylisting can delay a mail by hours, and people open it the next day.
    "magic_link": 24 * 3600,
    # Signed link from the app to the html subdomain grant.
    "html_grant": 10 * 60,
    # html subdomain cookie listing the asset IDs the visitor may read.
    "html_access_cookie": 60 * 60,
    # One-click opt-out link in notification e-mails (RFC 8058). Long, since
    # people unsubscribe from old messages too.
    "notify_unsubscribe": 180 * 24 * 3600,
}


def issue(purpose: str, payload: str) -> str:
    if purpose not in TTL:
        raise ValueError(f"unknown token purpose: {purpose}")
    return _SERIALIZER.dumps(payload, salt=purpose)


def verify(purpose: str, token: str) -> str:
    if purpose not in TTL:
        raise ValueError(f"unknown token purpose: {purpose}")
    try:
        return _SERIALIZER.loads(token, salt=purpose, max_age=TTL[purpose])
    except SignatureExpired as e:
        raise TokenExpired(str(e)) from e
    except BadSignature as e:
        raise TokenInvalid(str(e)) from e
