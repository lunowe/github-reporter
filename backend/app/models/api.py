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
    chat_id: Optional[str] = Field(
        default=None,
        description="Chat-ID zum Fortsetzen, oder eine vom Client generierte ID für einen neuen Chat.",
    )
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


# ── API Keys (MCP) ─────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str = Field(default="", description="Bezeichnung des Schlüssels, z.B. 'Claude Desktop'")


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


# ── Admin ─────────────────────────────────────────────────────────────

class UserReposUpdate(BaseModel):
    allowed_repo_ids: list[str] = Field(..., description="Liste erlaubter Repository-IDs")


class UserLimitsUpdate(BaseModel):
    plan: str = Field(..., description="Plan-Schlüssel (z.B. 'free', 'pro', 'unlimited')")
    monthly_budget_usd: Optional[float] = Field(
        default=None, ge=0,
        description="Budget-Override in USD. Leer = Standardbudget des Tarifs verwenden.",
    )
    extra_usage_opt_in: bool = Field(
        default=False,
        description="Pay-per-token-Mehrverbrauch über das Budget hinaus erlauben.",
    )
    suspended: bool = Field(
        default=False, description="Konto sperren — blockiert neue Chat-Läufe.",
    )
    allowed_models: list[str] = Field(
        default_factory=list,
        description="Erlaubte LLM-Modelle. Leer = alle Modelle erlaubt.",
    )


class UsageAdjust(BaseModel):
    reset: bool = Field(
        default=False, description="Aktuellen Monatsverbrauch auf $0 zurücksetzen.",
    )
    credit_usd: Optional[float] = Field(
        default=None, ge=0,
        description="Gutschrift in USD (reduziert den abgerechneten Verbrauch).",
    )
    note: str = Field(default="", max_length=300, description="Notiz für das Audit-Log.")


# ── Automations ────────────────────────────────────────────────────────

class AutomationStepIn(BaseModel):
    name: str = Field(..., description="Kurzer Name für den Schritt")
    prompt: str = Field(..., description="Der Prompt für diesen Schritt. {{step1.output}} referenziert vorherige Schritte.")
    repo: str = Field(..., description="repo_full_name gegen den der Schritt läuft")
    model: Optional[str] = Field(default=None, description="LLM-Modell überschreiben (sonst Automation-Default)")


FinalOutputFormat = Literal["last_step", "merge", "template"]


class AutomationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    steps: list[AutomationStepIn] = Field(..., min_length=1, max_length=10)
    schedule_cron: Optional[str] = Field(
        default=None,
        description="5-Feld Cron-Ausdruck, z.B. '0 9 * * 1' (Mo 09:00). Leer = nur manuelle Ausführung.",
    )
    timezone: str = Field(default="Europe/Berlin", description="IANA Timezone")
    enabled: bool = Field(default=True)
    email_enabled: bool = Field(default=False)
    email_to: Optional[str] = Field(default=None, description="Empfänger — leer = eigene E-Mail")
    model: Optional[str] = Field(default=None, description="Default LLM-Modell für alle Schritte")
    final_output_format: FinalOutputFormat = Field(
        default="last_step",
        description=(
            "Wie das finale Ergebnis aus den Schritten zusammengesetzt wird: "
            "'last_step' = Output des letzten Schritts, "
            "'merge' = alle Schritt-Outputs mit Überschriften zusammenfügen, "
            "'template' = eigene Vorlage mit {{stepN.output}}-Platzhaltern."
        ),
    )
    final_output_template: Optional[str] = Field(
        default=None,
        max_length=8000,
        description="Vorlage (nur bei final_output_format='template'). Unterstützt {{stepN.output}}.",
    )


class AutomationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    steps: Optional[list[AutomationStepIn]] = Field(default=None, min_length=1, max_length=10)
    schedule_cron: Optional[str] = None
    timezone: Optional[str] = None
    enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    email_to: Optional[str] = None
    model: Optional[str] = None
    final_output_format: Optional[FinalOutputFormat] = None
    final_output_template: Optional[str] = Field(default=None, max_length=8000)


class AutomationToggle(BaseModel):
    enabled: bool


class AutomationStepOut(BaseModel):
    name: str
    prompt: str
    repo: str
    model: Optional[str] = None


class AutomationOut(BaseModel):
    id: str
    name: str
    description: str
    steps: list[AutomationStepOut]
    schedule_cron: Optional[str]
    timezone: str
    enabled: bool
    email_enabled: bool
    email_to: Optional[str]
    model: Optional[str]
    final_output_format: FinalOutputFormat = "last_step"
    final_output_template: Optional[str] = None
    last_run_at: Optional[str]
    next_run_at: Optional[str]
    created_at: str
    updated_at: str


class AutomationStepResult(BaseModel):
    order: int
    name: str
    prompt: str
    repo: str
    output: str = ""
    duration_ms: int = 0
    error: Optional[str] = None


class AutomationRunOut(BaseModel):
    id: str
    automation_id: str
    automation_name: str = ""
    status: Literal["queued", "running", "completed", "failed"]
    trigger: Literal["manual", "schedule"] = "manual"
    step_results: list[AutomationStepResult] = Field(default_factory=list)
    final_output: str = ""
    error: Optional[str] = None
    email_sent: bool = False
    started_at: str
    completed_at: Optional[str] = None
