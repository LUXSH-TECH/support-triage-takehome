"""Everything a request needs, created once at startup and shared by the routes."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .database import AuditRepository, PolicyRepository
from .services.erp_service import ErpAdapter
from .services.llm_service import ModelProvider


@dataclass
class AppContext:
    settings: Settings
    policies: PolicyRepository  # policy table
    audit: AuditRepository  # triage_log table
    erp: ErpAdapter  # legacy ERP adapter
    model: ModelProvider  # fake or real LLM
