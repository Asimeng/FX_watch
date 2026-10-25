"""Signed, tamper-proof links. No tokens are stored in the database.

* Confirmation links expire (default 48h) and only activate one alert.
* Management links don't expire but embed the subscriber's token version; "rotate my
  link" bumps the version, which invalidates every previously issued link.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from urllib.parse import urlencode

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_CONFIRM_SALT = "fxwatch.confirm-alert.v1"
_MANAGE_SALT = "fxwatch.manage.v1"


class InvalidToken(Exception):
    def __init__(self, message: str, expired: bool = False) -> None:
        super().__init__(message)
        self.expired = expired


@dataclass(frozen=True)
class ManageClaims:
    subscriber_id: int
    version: int


class TokenService:
    def __init__(self, secret_key: str, base_url: str) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key)
        self._secret = secret_key.encode()
        self.base_url = base_url.rstrip("/")

    # -- confirmation -----------------------------------------------------------------------
    def confirm_token(self, alert_id: int) -> str:
        return self._serializer.dumps({"a": alert_id}, salt=_CONFIRM_SALT)

    def read_confirm_token(self, token: str, max_age_seconds: int) -> int:
        try:
            data = self._serializer.loads(token, salt=_CONFIRM_SALT, max_age=max_age_seconds)
            return int(data["a"])
        except SignatureExpired as exc:
            raise InvalidToken("This confirmation link has expired.", expired=True) from exc
        except (BadSignature, KeyError, TypeError, ValueError) as exc:
            raise InvalidToken("This confirmation link is invalid.") from exc

    # -- management -------------------------------------------------------------------------
    def manage_token(self, subscriber_id: int, version: int) -> str:
        return self._serializer.dumps({"s": subscriber_id, "v": version}, salt=_MANAGE_SALT)

    def read_manage_token(self, token: str) -> ManageClaims:
        try:
            data = self._serializer.loads(token, salt=_MANAGE_SALT)
            return ManageClaims(int(data["s"]), int(data["v"]))
        except (BadSignature, KeyError, TypeError, ValueError) as exc:
            raise InvalidToken("This management link is invalid or has been replaced.") from exc

    # -- URLs -------------------------------------------------------------------------------
    def url(self, page: str, **params: str | int) -> str:
        query = urlencode({k: v for k, v in params.items() if v is not None})
        return f"{self.base_url}/{page}" + (f"?{query}" if query else "")

    def confirm_url(self, alert_id: int) -> str:
        return self.url("confirm", token=self.confirm_token(alert_id))

    def manage_url(self, subscriber_id: int, version: int, **extra: str | int) -> str:
        return self.url("manage", token=self.manage_token(subscriber_id, version), **extra)

    # -- privacy-preserving keys ------------------------------------------------------------
    def fingerprint(self, value: str) -> str:
        """Keyed hash used for rate-limit keys, so raw IPs/emails aren't stored there."""
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()[:32]
