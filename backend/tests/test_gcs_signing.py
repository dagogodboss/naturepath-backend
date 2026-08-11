"""Unit tests for Cloud Run–safe GCS V4 signing helpers."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from infrastructure import gcs_signing


def test_iam_sign_kwargs_empty_for_service_account_key():
    creds = MagicMock(spec=gcs_signing.service_account.Credentials)
    with patch.object(gcs_signing, "isinstance", return_value=True):
        assert gcs_signing._iam_sign_kwargs(creds) == {}


def test_iam_sign_kwargs_refreshes_default_email():
    class TokenCreds:
        service_account_email = "default"
        valid = False
        token = None
        expired = True
        refresh_calls = 0

        def refresh(self, _request):
            self.refresh_calls += 1
            self.service_account_email = "runtime@project.iam.gserviceaccount.com"
            self.token = "ya29.test-token"
            self.valid = True
            self.expired = False

    creds = TokenCreds()
    kwargs = gcs_signing._iam_sign_kwargs(creds)
    assert creds.refresh_calls >= 1
    assert kwargs == {
        "service_account_email": "runtime@project.iam.gserviceaccount.com",
        "access_token": "ya29.test-token",
    }


def test_generate_signed_url_passes_iam_kwargs():
    class TokenCreds:
        service_account_email = "runtime@project.iam.gserviceaccount.com"
        valid = True
        token = "ya29.test-token"
        expired = False

        def refresh(self, _request):
            pass

    blob = MagicMock()
    blob.generate_signed_url.return_value = "https://signed.example/put"
    bucket = MagicMock()
    bucket.blob.return_value = blob
    client = MagicMock()
    client.bucket.return_value = bucket

    with patch.object(gcs_signing.google.auth, "default", return_value=(TokenCreds(), "proj")):
        url = gcs_signing.generate_signed_url(
            bucket_name="naturalpath-media",
            object_name="content/video/a.mp4",
            method="PUT",
            expiration=timedelta(minutes=30),
            content_type="video/mp4",
            client=client,
        )

    assert url == "https://signed.example/put"
    call_kwargs = blob.generate_signed_url.call_args.kwargs
    assert call_kwargs["service_account_email"] == "runtime@project.iam.gserviceaccount.com"
    assert call_kwargs["access_token"] == "ya29.test-token"
