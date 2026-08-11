"""
Phase G — native ~60s preview clips for vlog/reels media.

Downloads the source object from GCS, clips with ffmpeg, uploads a preview
object, and sets content_posts.preview_clip_url.

Uses sync pymongo so the task works under Celery eager mode inside FastAPI's
running event loop (no nested asyncio.run).
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import unquote, urlparse

from pymongo import MongoClient

from core.config import settings
from infrastructure.queue.celery_config import celery_app

logger = logging.getLogger(__name__)

PREVIEW_SECONDS = 60


def object_name_from_media_url(url: Optional[str], bucket: Optional[str]) -> Optional[str]:
    """Best-effort extract of GCS object path from signed GET or CDN URL."""
    if not url or not bucket:
        return None
    parsed = urlparse(url.strip())
    path = unquote(parsed.path.lstrip("/"))
    host = (parsed.hostname or "").lower()
    if host == "storage.googleapis.com":
        prefix = f"{bucket}/"
        if path.startswith(prefix):
            return path[len(prefix) :]
        return None
    if host == f"{bucket}.storage.googleapis.com":
        return path or None
    if path.startswith("content/"):
        return path
    return None


def _cdn_or_signed_url(object_name: str) -> Optional[str]:
    """Mirror content_routes._cdn_url without importing FastAPI routes."""
    base = (getattr(settings, "cdn_base_url", None) or "").rstrip("/")
    if base and "storage.googleapis.com" not in base.lower():
        return f"{base}/{object_name}"
    try:
        from infrastructure.gcs_signing import generate_signed_url

        return generate_signed_url(
            bucket_name=settings.gcs_bucket,
            object_name=object_name,
            method="GET",
            expiration=timedelta(days=7),
        )
    except Exception:
        logger.warning("Could not sign preview URL for %s", object_name, exc_info=True)
        return None


def _run_ffmpeg_clip(src_path: str, dst_path: str, seconds: int = PREVIEW_SECONDS) -> None:
    copy_cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "0",
        "-t",
        str(seconds),
        "-i",
        src_path,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        dst_path,
    ]
    result = subprocess.run(copy_cmd, capture_output=True, text=True, timeout=240)
    if result.returncode == 0 and os.path.getsize(dst_path) > 0:
        return
    logger.info("ffmpeg copy failed; re-encoding preview (%s)", (result.stderr or "")[-400:])
    encode_cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "0",
        "-t",
        str(seconds),
        "-i",
        src_path,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        dst_path,
    ]
    result = subprocess.run(encode_cmd, capture_output=True, text=True, timeout=240)
    if result.returncode != 0 or os.path.getsize(dst_path) == 0:
        raise RuntimeError(f"ffmpeg failed: {(result.stderr or result.stdout or '')[-800:]}")


def _generate_preview_for_post(post_id: str) -> dict:
    if not getattr(settings, "gcs_bucket", None):
        return {"ok": False, "detail": "GCS_BUCKET not configured"}

    client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=10000)
    try:
        db = client[settings.db_name]
        post = db.content_posts.find_one({"post_id": post_id}, {"_id": 0})
        if not post:
            return {"ok": False, "detail": "post not found"}
        if post.get("type") != "vlog":
            return {"ok": False, "detail": "not a vlog"}

        source_object = post.get("media_object_name") or object_name_from_media_url(
            post.get("media_url"), settings.gcs_bucket
        )
        if not source_object:
            return {"ok": False, "detail": "no media_object_name / parseable media_url"}

        from google.cloud import storage

        gcs = storage.Client()
        bucket = gcs.bucket(settings.gcs_bucket)
        src_blob = bucket.blob(source_object)
        if not src_blob.exists():
            return {"ok": False, "detail": f"source object missing: {source_object}"}

        preview_object = f"content/preview/{post_id}_t0-{PREVIEW_SECONDS}.mp4"
        with tempfile.TemporaryDirectory(prefix="np-preview-") as tmp:
            src_path = os.path.join(tmp, "source.mp4")
            dst_path = os.path.join(tmp, "preview.mp4")
            src_blob.download_to_filename(src_path)
            _run_ffmpeg_clip(src_path, dst_path)
            dst_blob = bucket.blob(preview_object)
            dst_blob.upload_from_filename(dst_path, content_type="video/mp4")

        preview_url = _cdn_or_signed_url(preview_object)
        now = datetime.now(timezone.utc).isoformat()
        db.content_posts.update_one(
            {"post_id": post_id},
            {
                "$set": {
                    "preview_clip_url": preview_url,
                    "preview_clip_object": preview_object,
                    "media_object_name": source_object,
                    "preview_clip_updated_at": now,
                    "updated_at": now,
                }
            },
        )
        logger.info("preview clip ready post_id=%s object=%s", post_id, preview_object)
        return {
            "ok": True,
            "post_id": post_id,
            "preview_clip_object": preview_object,
            "preview_clip_url": preview_url,
        }
    finally:
        client.close()


@celery_app.task(bind=True, max_retries=2, name="workers.media_preview_worker.generate_preview_clip")
def generate_preview_clip(self, post_id: str):
    """Celery entry: build ~60s preview for a content post."""
    try:
        return _generate_preview_for_post(post_id)
    except Exception as exc:
        logger.exception("generate_preview_clip failed post_id=%s", post_id)
        raise self.retry(exc=exc, countdown=30)


def enqueue_preview_clip(post_id: str) -> Optional[str]:
    """Fire-and-forget (or eager) enqueue. Returns AsyncResult id when available."""
    if not post_id or not getattr(settings, "gcs_bucket", None):
        return None
    try:
        result = generate_preview_clip.delay(post_id)
        return getattr(result, "id", None)
    except Exception:
        logger.warning("Could not enqueue preview clip for %s", post_id, exc_info=True)
        return None
