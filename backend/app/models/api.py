# app/models/api.py
"""
Pydantic request / response schemas for the API.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional


# ── Chat ────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"] = Field(...)
    content: str


class ChatRequest(BaseModel):
    query: str = Field(..., description="Die Frage des Nutzers")
    chat_history: list[ChatMessage] = Field(default_factory=list)
    chat_id: Optional[str] = Field(default=None, description="Bestehende Chat-ID zum Fortsetzen")
    repo: Optional[str] = Field(default=None, description="Repo-Vollname (owner/repo), überschreibt den Standard")
    model: Optional[str] = Field(default=None, description="LLM-Modellname, überschreibt den Standard")


# ── Repos ───────────────────────────────────────────────────────────────

class RepoConnection(BaseModel):
    repo_full_name: str = Field(..., description="z.B. 'lunowe/ChatforenVFL'")
    display_name: Optional[str] = Field(default=None)
    default_branch: str = Field(default="main")


class RepoConnectionOut(BaseModel):
    id: str
    repo_full_name: str
    display_name: str
    default_branch: str


# ── Access Codes ───────────────────────────────────────────────────────

class AccessCodeCreate(BaseModel):
    label: str = ""
    max_uses: int = Field(default=1, ge=0, description="0 = unbegrenzt")


class AccessCodeRedeem(BaseModel):
    code: str = Field(..., description="Der Zugangscode")


# ── Invites ────────────────────────────────────────────────────────────

class InviteCreate(BaseModel):
    email: str = Field(..., description="E-Mail des einzuladenden Nutzers")
    repo_ids: list[str] = Field(default_factory=list, description="Erlaubte Repository-IDs")


class InviteRedeem(BaseModel):
    token: str
    password: str = Field(..., min_length=8, description="Mindestens 8 Zeichen")
    display_name: str = ""


class EmailLogin(BaseModel):
    email: str
    password: str
