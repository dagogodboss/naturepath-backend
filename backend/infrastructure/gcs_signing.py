"""
GCS V4 signed URLs that work on Cloud Run ADC (no JSON key file).

Local SA key files already include a private key signer. On Cloud Run / GCE,
ADC is a token-only credential — generate_signed_url must use IAM Credentials
signBlob via service_account_email + access_token.
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.request
from datetime import timedelta
from typing import Any, Optional

import google.auth
from google.auth.transport import requests as google_auth_requests
from google.cloud import storage
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

_METADATA_SA_EMAIL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/email"
)


def gcs_client() -> storage.Client:
    credentials, project = google.auth.default()
    return storage.Client(credentials=credentials, project=project)


def _metadata_sa_email() -> Optional[str]:
    """Resolve runtime SA email from the GCE/Cloud Run metadata server."""
    try:
        req = urllib.request.Request(
            _METADATA_SA_EMAIL,
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            email = resp.read().decode().strip()
        if email and email not in ("default", "unknown"):
            return email
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("metadata SA email lookup failed: %s", exc)
    return None


def _resolve_sa_email(credentials: Any) -> Optional[str]:
    """Return a real service-account email (never 'default')."""
    email = getattr(credentials, "service_account_email", None)
    if email and email not in ("default", "unknown"):
        return email
    return _metadata_sa_email()


def _iam_sign_kwargs(credentials: Any) -> dict:
    """Return kwargs so generate_signed_url uses IAM signBlob when needed."""
    # JSON key / explicit SA credentials already sign locally.
    if isinstance(credentials, service_account.Credentials):
        return {}

    request = google_auth_requests.Request()
    # Cloud Run ADC often starts with service_account_email == "default" until refresh.
    if (
        not getattr(credentials, "valid", False)
        or not getattr(credentials, "token", None)
        or getattr(credentials, "service_account_email", None) in (None, "default", "unknown")
    ):
        credentials.refresh(request)

    sa_email = _resolve_sa_email(credentials)
    token = getattr(credentials, "token", None)
    if not token:
        credentials.refresh(request)
        token = credentials.token

    if not sa_email or not token:
        raise RuntimeError(
            "Cannot IAM-sign GCS URLs: missing service_account_email or access token "
            "(grant roles/iam.serviceAccountTokenCreator on the runtime SA to itself)"
        )

    return {
        "service_account_email": sa_email,
        "access_token": token,
    }


def generate_signed_url(
    *,
    bucket_name: str,
    object_name: str,
    method: str = "GET",
    expiration: timedelta,
    content_type: Optional[str] = None,
    client: Optional[storage.Client] = None,
) -> str:
    """Create a V4 signed URL; uses signBlob under Cloud Run ADC."""
    credentials, project = google.auth.default()
    storage_client = client or storage.Client(credentials=credentials, project=project)
    blob = storage_client.bucket(bucket_name).blob(object_name)
    kwargs: dict[str, Any] = {
        "version": "v4",
        "expiration": expiration,
        "method": method,
        **_iam_sign_kwargs(credentials),
    }
    if content_type is not None:
        kwargs["content_type"] = content_type
    return blob.generate_signed_url(**kwargs)
