"""
Admin RBAC: policy overrides and reload (requires user:role:manage).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.rbac import Permission, load_policy_overrides_from_db
from presentation.dependencies import get_current_admin
from infrastructure.database import get_database

router = APIRouter()


BASELINE_ROLE_HINTS: dict[str, list[str]] = {
    "customer": ["profile:read", "profile:write", "booking:create", "booking:read:own", "service:read"],
    "staff": ["profile:read", "profile:write", "booking:read:all", "booking:manage", "service:read"],
    "manager": [
        "profile:read",
        "profile:write",
        "booking:read:all",
        "booking:manage",
        "service:read",
        "service:create",
        "service:update",
        "admin:dashboard:read",
    ],
    "practitioner": [
        "profile:read",
        "profile:write",
        "service:read",
        "service:create",
        "service:update",
        "practitioner:profile:manage",
        "practitioner:slot:manage",
        "booking:complete",
    ],
    "admin": [p.value for p in Permission],
    "owner": ["(inherits admin via grouping g, owner, admin)"],
}


class RbacOverrideCreate(BaseModel):
    ptype: Literal["p", "g"] = Field(description='Policy type: "p" permission or "g" role inheritance')
    v0: str = Field(min_length=1, description='Subject: role name, user_id, or child role for g')
    v1: str = Field(min_length=1, description='Permission key (for p) or parent role (for g)')
    v2: str | None = Field(
        default="use",
        description='Action, usually "use" for p rules; ignored for g',
    )


def _serialize_override(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    out["_id"] = str(out.pop("_id"))
    return out


@router.get("/baseline")
async def rbac_baseline(_admin: dict = Depends(get_current_admin)):
    """Static hints for UI: all permission keys and typical role bundles."""
    return {
        "permissions": sorted(p.value for p in Permission),
        "role_hints": BASELINE_ROLE_HINTS,
        "override_help": {
            "p": "Adds p,subject,permission,action — e.g. v0=practitioner v1=user:role:manage v2=use",
            "g": "Adds g,child,parent — e.g. v0=manager v1=admin",
            "user_grant": 'For a specific user, use ptype=p and v0=<user_id> and v1=<permission>',
        },
    }


@router.get("/overrides")
async def list_rbac_overrides(
    _admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    cursor = db.rbac_policy_overrides.find({}).sort("created_at", -1)
    docs = await cursor.to_list(length=500)
    return [_serialize_override(d) for d in docs]


@router.post("/overrides", status_code=status.HTTP_201_CREATED)
async def create_rbac_override(
    body: RbacOverrideCreate,
    _admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    doc: dict[str, Any] = {
        "ptype": body.ptype,
        "v0": body.v0.strip(),
        "v1": body.v1.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.ptype == "p":
        doc["v2"] = (body.v2 or "use").strip()
    inserted = await db.rbac_policy_overrides.insert_one(doc)
    doc["_id"] = inserted.inserted_id
    await load_policy_overrides_from_db(db)
    return _serialize_override(doc)


@router.delete("/overrides/{doc_id}")
async def delete_rbac_override(
    doc_id: str,
    _admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    try:
        oid = ObjectId(doc_id)
    except InvalidId as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid id") from e
    result = await db.rbac_policy_overrides.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override not found")
    await load_policy_overrides_from_db(db)
    return {"deleted": True}


@router.post("/reload")
async def reload_rbac_policies(
    _admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    await load_policy_overrides_from_db(db)
    return {"reloaded": True}
