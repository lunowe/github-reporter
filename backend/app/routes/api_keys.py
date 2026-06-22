# app/routes/api_keys.py
"""
Personal API key management.

Each activated user manages their own keys. A key authenticates calls to the
MCP server (`/mcp`) and impersonates its owner — running with the owner's GitHub
token and repo permissions. The plaintext key is returned exactly once, at
creation time.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_activated_user
from app.models.api import ApiKeyCreate
from app.services import api_key_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


@router.post("")
async def create_api_key(
    body: ApiKeyCreate,
    user: dict = Depends(get_activated_user),
):
    """Create a new API key. Returns the plaintext key once — store it now."""
    doc, plaintext = await api_key_service.generate_api_key(
        user_id=str(user["_id"]),
        name=body.name,
    )
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "prefix": doc["prefix"],
        "key": plaintext,  # shown only here, never again
        "created_at": doc["created_at"],
    }


@router.get("")
async def list_api_keys(
    user: dict = Depends(get_activated_user),
):
    """List the current user's API keys (masked — no plaintext)."""
    return await api_key_service.list_keys(str(user["_id"]))


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: dict = Depends(get_activated_user),
):
    """Revoke one of the current user's API keys."""
    revoked = await api_key_service.revoke_key(str(user["_id"]), key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API-Schlüssel nicht gefunden.")
    return {"status": "revoked"}
