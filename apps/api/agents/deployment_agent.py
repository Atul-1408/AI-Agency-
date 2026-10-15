"""
Phase 8 — Production Deployment & Hosting Agent.
Coordinates pre-deployment eligibility validation, Gate 5 owner approval,
repository publishing, and production deployment execution.
"""
from __future__ import annotations

from typing import Any, Dict
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from agents.base_agent import BaseAgent
from models import AgentRun
from models.website_deployment import DeploymentEnvironment
from schemas.website_deployment import (
    WebsiteDeploymentCreateRequest,
    WebsiteDeploymentExecuteRequest,
)
from services.website_deployment_service import WebsiteDeploymentService

log = structlog.get_logger(__name__)


class DeploymentAgent(BaseAgent):
    """
    Production Deployment & Hosting Agent.
    Coordinates deployment requests, Gate 5 owner approval integration,
    and verified release publishing.
    """
    name: str = "deployment"

    async def execute(
        self,
        db: AsyncSession,
        run: AgentRun,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        action = input_data.get("action", "execute")
        owner_id = input_data.get("owner_id", "owner@agency.com")

        if action == "check_eligibility":
            project_id_raw = input_data.get("project_id")
            if not project_id_raw:
                raise ValueError("project_id is required to check deployment eligibility.")
            project_id = uuid.UUID(str(project_id_raw))
            target_version = input_data.get("target_version")
            res = await WebsiteDeploymentService.check_eligibility(
                db=db,
                project_id=project_id,
                owner_id=owner_id,
                target_version=target_version,
            )
            return res.model_dump(mode="json")

        elif action == "request":
            project_id_raw = input_data.get("project_id")
            if not project_id_raw:
                raise ValueError("project_id is required to request a deployment.")
            project_id = uuid.UUID(str(project_id_raw))
            env_str = input_data.get("environment", "production")
            env = DeploymentEnvironment.PRODUCTION if env_str == "production" else DeploymentEnvironment.PREVIEW

            create_req = WebsiteDeploymentCreateRequest(
                environment=env,
                target_version=input_data.get("target_version"),
                custom_domain=input_data.get("custom_domain"),
                force_mock=input_data.get("force_mock", False),
            )
            dep = await WebsiteDeploymentService.request_deployment(
                db=db,
                project_id=project_id,
                owner_id=owner_id,
                request_payload=create_req,
            )
            return {
                "deployment_id": str(dep.id),
                "project_id": str(dep.project_id),
                "environment": dep.environment.value,
                "status": dep.status.value,
                "approval_request_id": str(dep.approval_request_id) if dep.approval_request_id else None,
            }

        elif action == "execute":
            deployment_id_raw = input_data.get("deployment_id")
            if not deployment_id_raw:
                raise ValueError("deployment_id is required to execute a deployment.")
            deployment_id = uuid.UUID(str(deployment_id_raw))
            force_mock = input_data.get("force_mock", False)

            dep = await WebsiteDeploymentService.execute_deployment(
                db=db,
                deployment_id=deployment_id,
                owner_id=owner_id,
                force_mock=force_mock,
            )
            return {
                "deployment_id": str(dep.id),
                "project_id": str(dep.project_id),
                "environment": dep.environment.value,
                "status": dep.status.value,
                "deployment_url": dep.deployment_url,
                "production_url": dep.production_url,
                "github_repo_url": dep.github_repo_url,
                "github_commit_sha": dep.github_commit_sha,
                "error_message": dep.error_message,
            }

        else:
            raise ValueError(f"Unknown deployment agent action: '{action}'")
