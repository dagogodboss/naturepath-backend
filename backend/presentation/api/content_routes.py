"""
Blog + Vlog content API.

Owner/admin can create draft/publish posts. Public endpoints list published content.
Native media uses GCS signed uploads when GCS_BUCKET is configured; YouTube/Vimeo
embeds are supported via embed_url.
"""
from __future__ import annotations

import html
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Literal, Optional

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from core.config import settings
from core.rbac import Permission, SystemRole, has_permission
from infrastructure.database import get_database
from presentation.dependencies import get_current_active_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["Content"])

# Strip tags / scripts so stored content stays plain text (defense in depth;
# React text nodes already escape, but API consumers and future HTML renderers
# must not receive executable markup).
_TAG_RE = re.compile(r"<[^>]*>")


def _sanitize_plain_text(value: Optional[str], *, max_len: int | None = None) -> Optional[str]:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = _TAG_RE.sub("", text)
    text = text.replace("\x00", "").strip()
    if max_len is not None:
        text = text[:max_len]
    return text

ContentType = Literal["blog", "vlog"]
ContentStatus = Literal["draft", "published"]

_EMBED_ALLOWED_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
        "vimeo.com",
        "www.vimeo.com",
        "player.vimeo.com",
    }
)


def _validate_embed_url(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    parsed = urlparse(v.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _EMBED_ALLOWED_HOSTS:
        raise ValueError("embed_url must be a YouTube or Vimeo URL")
    return v.strip()


def _validate_http_url(v: Optional[str], *, field: str) -> Optional[str]:
    """Reject javascript:/data: and other non-http(s) schemes used in media fields."""
    if not v:
        return v
    parsed = urlparse(v.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an http(s) URL")
    return v.strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _slugify(title: str) -> str:
    raw = (title or "").strip().lower()
    out = []
    prev = False
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
            prev = False
        elif not prev:
            out.append("-")
            prev = True
    return "".join(out).strip("-") or f"post-{uuid.uuid4().hex[:8]}"


def _require_content_admin(user: dict) -> None:
    role = user.get("role")
    if role in {SystemRole.OWNER.value, SystemRole.ADMIN.value}:
        return
    if has_permission(user, Permission.USER_ROLE_MANAGE):
        return
    raise HTTPException(status_code=403, detail="Owner or admin access required")


def _public_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out.pop("_id", None)
    return out


class ContentIn(BaseModel):
    type: ContentType
    title: str = Field(min_length=2, max_length=160)
    body: Optional[str] = Field(default=None, max_length=20000)
    caption: Optional[str] = Field(default=None, max_length=2200)
    cover_url: Optional[str] = None
    media_url: Optional[str] = None
    media_object_name: Optional[str] = Field(default=None, max_length=500)
    embed_url: Optional[str] = None
    status: ContentStatus = "draft"
    aspect_ratio: Optional[Literal["4:5", "3:4"]] = "4:5"

    @field_validator("title")
    @classmethod
    def _plain_title(cls, v: str) -> str:
        cleaned = _sanitize_plain_text(v, max_len=160) or ""
        if len(cleaned) < 2:
            raise ValueError("Title must be at least 2 characters")
        return cleaned

    @field_validator("body", "caption")
    @classmethod
    def _plain_text_fields(cls, v: Optional[str]) -> Optional[str]:
        return _sanitize_plain_text(v)

    @field_validator("embed_url")
    @classmethod
    def _validate_embed(cls, v: Optional[str]) -> Optional[str]:
        return _validate_embed_url(v)

    @field_validator("cover_url")
    @classmethod
    def _validate_cover(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v, field="cover_url")

    @field_validator("media_url")
    @classmethod
    def _validate_media(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v, field="media_url")


class ContentUpdateIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=160)
    body: Optional[str] = Field(default=None, max_length=20000)
    caption: Optional[str] = Field(default=None, max_length=2200)
    cover_url: Optional[str] = None
    media_url: Optional[str] = None
    media_object_name: Optional[str] = Field(default=None, max_length=500)
    embed_url: Optional[str] = None
    status: Optional[ContentStatus] = None
    aspect_ratio: Optional[Literal["4:5", "3:4"]] = None

    @field_validator("title")
    @classmethod
    def _plain_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = _sanitize_plain_text(v, max_len=160) or ""
        if len(cleaned) < 2:
            raise ValueError("Title must be at least 2 characters")
        return cleaned

    @field_validator("body", "caption")
    @classmethod
    def _plain_text_fields(cls, v: Optional[str]) -> Optional[str]:
        return _sanitize_plain_text(v)

    @field_validator("embed_url")
    @classmethod
    def _validate_embed(cls, v: Optional[str]) -> Optional[str]:
        return _validate_embed_url(v)

    @field_validator("cover_url")
    @classmethod
    def _validate_cover(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v, field="cover_url")

    @field_validator("media_url")
    @classmethod
    def _validate_media(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v, field="media_url")


class SignedUploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(min_length=3, max_length=120)
    kind: Literal["image", "video"] = "video"


def _gcs_enabled() -> bool:
    return bool(getattr(settings, "gcs_bucket", None))


def _signed_get_url(object_name: str, *, ttl_minutes: int = 60 * 24 * 7) -> Optional[str]:
    """V4 signed GET for private objects (PAP buckets cannot use anonymous URLs)."""
    if not _gcs_enabled():
        return None
    try:
        from infrastructure.gcs_signing import generate_signed_url

        return generate_signed_url(
            bucket_name=settings.gcs_bucket,
            object_name=object_name,
            method="GET",
            expiration=timedelta(minutes=ttl_minutes),
        )
    except Exception:
        logger.warning("Could not create signed GET URL for %s", object_name, exc_info=True)
        return None


def _cdn_url(object_name: str) -> Optional[str]:
    """
    Public media URL for a GCS object.

    Prefer CDN_BASE_URL when set to a real front door (not storage.googleapis.com).
    Otherwise return a signed GET URL. Never emit anonymous storage.googleapis.com
    URLs — PAP buckets return 403 for those.
    """
    base = (getattr(settings, "cdn_base_url", None) or "").rstrip("/")
    if base and "storage.googleapis.com" not in base.lower():
        return f"{base}/{object_name}"
    if base and "storage.googleapis.com" in base.lower():
        logger.warning(
            "CDN_BASE_URL points at storage.googleapis.com (unusable under PAP); "
            "falling back to signed GET"
        )
    return _signed_get_url(object_name)


async def _cache_get(key: str) -> Optional[str]:
    try:
        from infrastructure.cache import get_cache_service

        cache = await get_cache_service()
        if not cache:
            return None
        return await cache.get(key)
    except Exception:
        return None


async def _cache_set(key: str, value: str, ttl: int = 120) -> None:
    try:
        from infrastructure.cache import get_cache_service

        cache = await get_cache_service()
        if not cache:
            return
        await cache.set(key, value, expire=ttl)
    except Exception:
        return


async def _cache_delete_prefix(prefixes: tuple[str, ...]) -> None:
    """Best-effort bust of known content feed keys."""
    try:
        from infrastructure.cache import get_cache_service

        cache = await get_cache_service()
        if not cache:
            return
        # Fixed key set used by list_public_posts (type × common limits).
        types = ("all", "blog", "vlog")
        limits = (5, 10, 20, 50)
        for prefix in prefixes:
            for t in types:
                for lim in limits:
                    try:
                        await cache.delete(f"{prefix}:{t}:{lim}")
                    except Exception:
                        pass
    except Exception:
        return


async def _bust_content_caches() -> None:
    await _cache_delete_prefix(("content:feed",))


def _maybe_enqueue_preview_clip(doc: Dict[str, Any]) -> None:
    """Enqueue Phase G preview when a published vlog has native media."""
    if not doc:
        return
    if doc.get("type") != "vlog" or doc.get("status") != "published":
        return
    if not (doc.get("media_url") or doc.get("media_object_name")):
        return
    if doc.get("embed_url") and not doc.get("media_url") and not doc.get("media_object_name"):
        return
    try:
        from workers.media_preview_worker import enqueue_preview_clip

        enqueue_preview_clip(doc["post_id"])
    except Exception:
        logger.warning(
            "preview enqueue skipped for %s", doc.get("post_id"), exc_info=True
        )


@router.get("/posts")
async def list_public_posts(
    type: Optional[ContentType] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    db=Depends(get_database),
):
    query: Dict[str, Any] = {"status": "published"}
    if type:
        query["type"] = type
    cache_key = f"content:feed:{type or 'all'}:{limit}"
    cached = await _cache_get(cache_key)
    if cached:
        import json

        return json.loads(cached)
    rows = (
        await db.content_posts.find(query, {"_id": 0})
        .sort("published_at", -1)
        .to_list(length=limit)
    )
    payload = {"items": rows}
    import json

    await _cache_set(cache_key, json.dumps(payload, default=str), ttl=90)
    return payload


@router.get("/posts/latest")
async def latest_posts_for_landing(
    limit: int = Query(default=5, ge=1, le=10),
    db=Depends(get_database),
):
    """Top N published posts (blog + vlog mixed) for landing strip."""
    rows = (
        await db.content_posts.find({"status": "published"}, {"_id": 0})
        .sort("published_at", -1)
        .to_list(length=limit)
    )
    return {"items": rows}


@router.get("/posts/id/{post_id}")
async def get_public_post_by_id(post_id: str, db=Depends(get_database)):
    """Fetch a single published post by post_id (deep links beyond latest-N feed)."""
    doc = await db.content_posts.find_one(
        {"post_id": post_id, "status": "published"}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Post not found")
    return doc


@router.get("/posts/{slug}")
async def get_public_post(slug: str, db=Depends(get_database)):
    doc = await db.content_posts.find_one(
        {"slug": slug, "status": "published"}, {"_id": 0}
    )
    if not doc:
        # Allow /posts/{post_id} style deep links when slug route is used.
        doc = await db.content_posts.find_one(
            {"post_id": slug, "status": "published"}, {"_id": 0}
        )
    if not doc:
        raise HTTPException(status_code=404, detail="Post not found")
    return doc


@router.get("/admin/posts")
async def admin_list_posts(
    type: Optional[ContentType] = Query(default=None),
    status_filter: Optional[ContentStatus] = Query(default=None, alias="status"),
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    _require_content_admin(current_user)
    query: Dict[str, Any] = {}
    if type:
        query["type"] = type
    if status_filter:
        query["status"] = status_filter
    rows = (
        await db.content_posts.find(query, {"_id": 0})
        .sort("updated_at", -1)
        .to_list(length=200)
    )
    return {"items": rows}


@router.post("/admin/posts", status_code=status.HTTP_201_CREATED)
async def admin_create_post(
    body: ContentIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    _require_content_admin(current_user)
    now = _utc_now()
    base_slug = _slugify(body.title)
    slug = base_slug
    n = 1
    while await db.content_posts.find_one({"slug": slug}):
        n += 1
        slug = f"{base_slug}-{n}"
    doc = {
        "post_id": _id("post"),
        "type": body.type,
        "title": body.title.strip(),
        "slug": slug,
        "body": body.body,
        "caption": body.caption,
        "cover_url": body.cover_url,
        "media_url": body.media_url,
        "media_object_name": body.media_object_name,
        "embed_url": body.embed_url,
        "aspect_ratio": body.aspect_ratio or "4:5",
        "status": body.status,
        "author_user_id": current_user["user_id"],
        "author_name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
        or current_user.get("email"),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "published_at": now.isoformat() if body.status == "published" else None,
        "preview_clip_url": None,
    }
    await db.content_posts.insert_one(doc)
    await _bust_content_caches()
    _maybe_enqueue_preview_clip(doc)
    return _public_doc(doc)


@router.patch("/admin/posts/{post_id}")
async def admin_update_post(
    post_id: str,
    body: ContentUpdateIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    _require_content_admin(current_user)
    existing = await db.content_posts.find_one({"post_id": post_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Post not found")
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return _public_doc(existing)
    updates["updated_at"] = _utc_now().isoformat()
    if updates.get("status") == "published" and not existing.get("published_at"):
        updates["published_at"] = _utc_now().isoformat()
    await db.content_posts.update_one({"post_id": post_id}, {"$set": updates})
    await _bust_content_caches()
    doc = await db.content_posts.find_one({"post_id": post_id}, {"_id": 0})
    media_touched = any(
        k in updates for k in ("media_url", "media_object_name", "status", "type")
    )
    if media_touched:
        _maybe_enqueue_preview_clip(doc or {})
    return doc


@router.delete("/admin/posts/{post_id}")
async def admin_delete_post(
    post_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    _require_content_admin(current_user)
    res = await db.content_posts.delete_one({"post_id": post_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Post not found")
    await _bust_content_caches()
    return {"success": True}


@router.post("/admin/uploads/sign")
async def admin_sign_upload(
    body: SignedUploadIn,
    current_user: dict = Depends(get_current_active_user),
):
    """Return a GCS signed PUT URL when configured; otherwise instruct embed/media_url use."""
    _require_content_admin(current_user)
    if not _gcs_enabled():
        return {
            "enabled": False,
            "detail": "GCS not configured. Set GCS_BUCKET (and optional CDN_BASE_URL). Use embed_url for YouTube/Vimeo meanwhile.",
        }
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", body.filename)[:120]
    object_name = f"content/{body.kind}/{uuid.uuid4().hex}_{safe_name}"
    try:
        from infrastructure.gcs_signing import generate_signed_url

        url = generate_signed_url(
            bucket_name=settings.gcs_bucket,
            object_name=object_name,
            method="PUT",
            expiration=timedelta(minutes=30),
            content_type=body.content_type,
        )
        return {
            "enabled": True,
            "upload_url": url,
            "object_name": object_name,
            "public_url": _cdn_url(object_name),
            "content_type": body.content_type,
            "expires_in_seconds": 1800,
        }
    except Exception as exc:
        logger.exception("GCS signed URL failed")
        raise HTTPException(status_code=502, detail=f"Could not create upload URL: {exc}") from exc


@router.post("/admin/posts/{post_id}/preview-clip")
async def admin_trigger_preview_clip(
    post_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """Enqueue (or eagerly run) Phase G ffmpeg preview generation for a vlog."""
    _require_content_admin(current_user)
    post = await db.content_posts.find_one({"post_id": post_id}, {"_id": 0})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.get("type") != "vlog":
        raise HTTPException(status_code=400, detail="Preview clips are only for vlogs")
    if not (post.get("media_url") or post.get("media_object_name")):
        raise HTTPException(status_code=400, detail="Post has no native media")
    if not _gcs_enabled():
        raise HTTPException(status_code=503, detail="GCS_BUCKET not configured")
    from workers.media_preview_worker import enqueue_preview_clip

    task_id = enqueue_preview_clip(post_id)
    # Eager local: task may have already written preview_clip_url.
    refreshed = await db.content_posts.find_one({"post_id": post_id}, {"_id": 0})
    return {
        "success": True,
        "post_id": post_id,
        "task_id": task_id,
        "preview_clip_url": (refreshed or {}).get("preview_clip_url"),
        "eager": bool(getattr(settings, "celery_task_always_eager", False)),
    }


# ==================== Reels / social (authenticated customers) ====================


class ReelCommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _plain_comment(cls, v: str) -> str:
        cleaned = _sanitize_plain_text(v, max_len=2000) or ""
        if not cleaned:
            raise ValueError("Comment body is required")
        return cleaned


@router.get("/reels")
async def list_reels_feed(
    limit: int = Query(default=30, ge=1, le=50),
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    """
    Authenticated Reels feed: published vlogs, newest unseen first, then seen.
    """
    user_id = current_user["user_id"]
    seen_ids = set(
        await db.content_views.distinct(
            "post_id", {"user_id": user_id, "content_type": "vlog"}
        )
    )
    rows = (
        await db.content_posts.find(
            {"status": "published", "type": "vlog"}, {"_id": 0}
        )
        .sort("published_at", -1)
        .to_list(length=limit * 2)
    )
    unseen = [r for r in rows if r.get("post_id") not in seen_ids]
    seen = [r for r in rows if r.get("post_id") in seen_ids]
    ordered = (unseen + seen)[:limit]

    post_ids = [r["post_id"] for r in ordered]
    like_counts: Dict[str, int] = {}
    comment_counts: Dict[str, int] = {}
    liked_by_me: set = set()
    if post_ids:
        async for doc in db.content_likes.aggregate(
            [
                {"$match": {"post_id": {"$in": post_ids}}},
                {"$group": {"_id": "$post_id", "n": {"$sum": 1}}},
            ]
        ):
            like_counts[doc["_id"]] = doc["n"]
        async for doc in db.content_comments.aggregate(
            [
                {"$match": {"post_id": {"$in": post_ids}}},
                {"$group": {"_id": "$post_id", "n": {"$sum": 1}}},
            ]
        ):
            comment_counts[doc["_id"]] = doc["n"]
        liked_by_me = set(
            await db.content_likes.distinct(
                "post_id", {"user_id": user_id, "post_id": {"$in": post_ids}}
            )
        )

    items = []
    for row in ordered:
        pid = row["post_id"]
        items.append(
            {
                **row,
                "seen": pid in seen_ids,
                "like_count": like_counts.get(pid, 0),
                "comment_count": comment_counts.get(pid, 0),
                "liked_by_me": pid in liked_by_me,
                # Interim preview hint (client applies #t=0,60 when no GCS clip).
                "preview_seconds": 60,
            }
        )
    return {"items": items}


@router.post("/reels/{post_id}/seen")
async def mark_reel_seen(
    post_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    post = await db.content_posts.find_one(
        {"post_id": post_id, "status": "published", "type": "vlog"}
    )
    if not post:
        raise HTTPException(status_code=404, detail="Reel not found")
    now = _utc_now().isoformat()
    await db.content_views.update_one(
        {"user_id": current_user["user_id"], "post_id": post_id},
        {
            "$set": {
                "user_id": current_user["user_id"],
                "post_id": post_id,
                "content_type": "vlog",
                "seen_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return {"success": True, "post_id": post_id}


@router.post("/reels/{post_id}/like")
async def like_reel(
    post_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    post = await db.content_posts.find_one(
        {"post_id": post_id, "status": "published", "type": "vlog"}
    )
    if not post:
        raise HTTPException(status_code=404, detail="Reel not found")
    now = _utc_now().isoformat()
    await db.content_likes.update_one(
        {"user_id": current_user["user_id"], "post_id": post_id},
        {
            "$set": {
                "user_id": current_user["user_id"],
                "post_id": post_id,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now, "like_id": _id("like")},
        },
        upsert=True,
    )
    count = await db.content_likes.count_documents({"post_id": post_id})
    return {"success": True, "liked": True, "like_count": count}


@router.delete("/reels/{post_id}/like")
async def unlike_reel(
    post_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    await db.content_likes.delete_one(
        {"user_id": current_user["user_id"], "post_id": post_id}
    )
    count = await db.content_likes.count_documents({"post_id": post_id})
    return {"success": True, "liked": False, "like_count": count}


@router.get("/reels/{post_id}/comments")
async def list_reel_comments(
    post_id: str,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    post = await db.content_posts.find_one({"post_id": post_id, "status": "published"})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    rows = (
        await db.content_comments.find({"post_id": post_id}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(length=100)
    )
    return {"items": rows}


@router.post("/reels/{post_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_reel_comment(
    post_id: str,
    body: ReelCommentIn,
    current_user: dict = Depends(get_current_active_user),
    db=Depends(get_database),
):
    post = await db.content_posts.find_one(
        {"post_id": post_id, "status": "published", "type": "vlog"}
    )
    if not post:
        raise HTTPException(status_code=404, detail="Reel not found")
    now = _utc_now().isoformat()
    doc = {
        "comment_id": _id("cmt"),
        "post_id": post_id,
        "user_id": current_user["user_id"],
        "author_name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
        or current_user.get("email"),
        "body": body.body.strip(),
        "created_at": now,
        "updated_at": now,
    }
    await db.content_comments.insert_one(doc)
    return _public_doc(doc)
