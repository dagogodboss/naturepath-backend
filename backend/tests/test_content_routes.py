"""Unit tests for content helpers."""
from presentation.api.content_routes import (
    _slugify,
    ContentIn,
    LandingSettingsIn,
    _cdn_url,
    _landing_settings_doc,
)
import pytest
from unittest.mock import patch


def test_slugify_basic():
    assert _slugify("Hello World!") == "hello-world"
    assert _slugify("  Mesh Soap  ") == "mesh-soap"


def test_embed_url_rejects_unknown_host():
    with pytest.raises(ValueError):
        ContentIn(type="blog", title="T", embed_url="https://evil.example/watch")


def test_embed_url_allows_youtube():
    body = ContentIn(type="vlog", title="Clip", embed_url="https://www.youtube.com/watch?v=abc123")
    assert "youtube.com" in body.embed_url


def test_embed_url_allows_facebook():
    body = ContentIn(
        type="vlog",
        title="Clip",
        embed_url="https://www.facebook.com/Thenaturalpathla/videos/1234567890",
    )
    assert "facebook.com" in body.embed_url


def test_youtube_poster_when_cover_empty():
    from presentation.api.content_routes import provider_poster_url

    poster = provider_poster_url("https://www.youtube.com/watch?v=abc123")
    assert poster == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
    assert provider_poster_url("https://www.facebook.com/watch/?v=1") is None


def test_cover_url_rejects_javascript_scheme():
    with pytest.raises(ValueError):
        ContentIn(type="blog", title="Post", cover_url="javascript:alert(1)")


def test_media_url_rejects_data_scheme():
    with pytest.raises(ValueError):
        ContentIn(type="vlog", title="Clip", media_url="data:text/html,<script>alert(1)</script>")


def test_cover_url_allows_https():
    body = ContentIn(type="blog", title="Post", cover_url="https://cdn.example.com/cover.jpg")
    assert body.cover_url.startswith("https://")


def test_cdn_url_prefers_real_cdn_base():
    with patch("presentation.api.content_routes.settings") as settings:
        settings.cdn_base_url = "https://media.example.com"
        settings.gcs_bucket = "naturalpath-media"
        assert _cdn_url("content/video/a.mp4") == "https://media.example.com/content/video/a.mp4"


def test_cdn_url_rejects_storage_googleapis_as_cdn():
    with patch("presentation.api.content_routes.settings") as settings:
        settings.cdn_base_url = "https://storage.googleapis.com/naturalpath-media"
        settings.gcs_bucket = "naturalpath-media"
        with patch(
            "presentation.api.content_routes._signed_get_url",
            return_value="https://signed.example/obj",
        ) as signed:
            assert _cdn_url("content/video/a.mp4") == "https://signed.example/obj"
            signed.assert_called_once()


def test_cdn_url_no_anonymous_storage_fallback():
    with patch("presentation.api.content_routes.settings") as settings:
        settings.cdn_base_url = None
        settings.gcs_bucket = "naturalpath-media"
        with patch(
            "presentation.api.content_routes._signed_get_url",
            return_value=None,
        ):
            url = _cdn_url("content/video/a.mp4")
            assert url is None or "storage.googleapis.com" not in url


def test_landing_settings_prefers_fresh_signed_object_url():
    with patch(
        "presentation.api.content_routes._cdn_url",
        return_value="https://signed.example/hero.jpg",
    ):
        payload = _landing_settings_doc(
            {
                "hero_image_url": "https://old.example/hero.jpg",
                "hero_image_object_name": "content/image/hero.jpg",
                "hero_image_alt": "Wellness shelves",
            }
        )
    assert payload["hero_image_url"] == "https://signed.example/hero.jpg"
    assert payload["configured"] is True


def test_landing_settings_sanitizes_alt_text():
    settings = LandingSettingsIn(
        hero_image_url="https://example.com/hero.jpg",
        hero_image_alt="<script>alert(1)</script>Wellness shop",
    )
    assert settings.hero_image_alt == "alert(1)Wellness shop"


def test_object_name_from_signed_and_cdn_urls():
    from workers.media_preview_worker import object_name_from_media_url

    bucket = "naturalpath-media"
    signed = (
        f"https://storage.googleapis.com/{bucket}/content/video/abc_clip.mp4"
        "?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=x"
    )
    assert object_name_from_media_url(signed, bucket) == "content/video/abc_clip.mp4"
    assert (
        object_name_from_media_url("https://media.example.com/content/video/z.mp4", bucket)
        == "content/video/z.mp4"
    )
    assert object_name_from_media_url("https://evil.example/other.mp4", bucket) is None
