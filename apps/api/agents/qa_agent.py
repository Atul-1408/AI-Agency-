"""
Phase 7 — Automated Website QA & Evaluator Agent.
Coordinates automated visual, accessibility, structural, security, and responsive audits.
"""
from __future__ import annotations

from typing import Any, Dict
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from agents.base_agent import BaseAgent
from models import AgentRun
from schemas.website_qa import WebsiteQARunCreateRequest
from services.website_qa_service import WebsiteQAService

log = structlog.get_logger(__name__)


class QAAgent(BaseAgent):
    """
    Automated Website QA & Evaluator Agent.
    Evaluates generated websites against build integrity, responsive breakpoints,
    accessibility standards, SEO fundamentals, and security constraints.
    """
    name: str = "qa"

    async def execute(
        self,
        db: AsyncSession,
        run: AgentRun,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        project_id_raw = input_data.get("project_id")
        if not project_id_raw:
            raise ValueError("project_id is required for QA agent execution.")

        project_id = uuid.UUID(str(project_id_raw))
        owner_id = input_data.get("owner_id", "owner@agency.com")
        target_version = input_data.get("target_version")
        code_gen_id_raw = input_data.get("code_generation_id")
        code_gen_id = uuid.UUID(str(code_gen_id_raw)) if code_gen_id_raw else None

        req = WebsiteQARunCreateRequest(
            target_version=target_version,
            code_generation_id=code_gen_id,
        )

        qa_run = await WebsiteQAService.create_and_execute_qa_run(
            db=db,
            project_id=project_id,
            owner_id=owner_id,
            request_payload=req,
            created_by=f"agent:{self.name}",
        )

        return {
            "qa_run_id": str(qa_run.id),
            "project_id": str(qa_run.project_id),
            "status": qa_run.status.value,
            "score": qa_run.score,
            "total_checks": qa_run.total_checks,
            "passed_checks": qa_run.passed_checks,
            "failed_checks": qa_run.failed_checks,
            "warning_checks": qa_run.warning_checks,
        }
