"""
Base Agent — abstract foundation for all AI agents.

Every agent in this system:
1. Extends BaseAgent
2. Implements execute()
3. Gets its run lifecycle managed here (PENDING → RUNNING → COMPLETED/FAILED)
4. Has all activity recorded in the AgentRun table

Phase 1: BaseAgent defines the interface.
         AI (Nemotron) is an injectable abstraction — no live calls unless
         NEMOTRON_ENABLED=true in .env.
         The AI layer is isolated in AIProvider so it can be swapped or mocked.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from models import AgentRun, AgentRunStatus, ApprovalRequest, ApprovalStatus


class AIProvider:
    """
    Abstraction layer over the Nemotron / OpenAI-compatible AI endpoint.

    Phase 1: AI calls are disabled by default (NEMOTRON_ENABLED=false).
             Agents that call this in Phase 1 receive a NotImplementedError
             so it's clear the capability is not yet active.

    Phase 9: NEMOTRON_ENABLED=true enables real inference calls.
    """

    def __init__(self, enabled: bool, api_key: str, base_url: str, model: str):
        self._enabled = enabled
        self._model = model
        self._client = None

        if enabled:
            if not api_key:
                raise ValueError(
                    "NEMOTRON_ENABLED=true but NEMOTRON_API_KEY is not set."
                )
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> tuple[str, int]:
        """
        Send a chat completion request.
        Returns (response_text, tokens_used).

        Raises NotImplementedError if NEMOTRON_ENABLED=false.
        Never fabricates a response.
        """
        if not self._enabled or self._client is None:
            raise NotImplementedError(
                "AI calls are disabled. Set NEMOTRON_ENABLED=true and provide "
                "NEMOTRON_API_KEY to enable Nemotron inference."
            )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return text, tokens


class BaseAgent(ABC):
    """
    Abstract base class for all agents in the AI Web Agency system.

    Subclasses must implement:
      - name (class attribute): str — unique agent identifier
      - execute() — the core agent logic

    The run() method manages the full AgentRun lifecycle and must not
    be overridden.
    """

    name: str = "base"   # Override in subclasses

    def __init__(self):
        from core.config import settings
        self.log = structlog.get_logger(self.__class__.__name__)
        self.ai = AIProvider(
            enabled=settings.NEMOTRON_ENABLED,
            api_key=settings.NEMOTRON_API_KEY,
            base_url=settings.NEMOTRON_BASE_URL,
            model=settings.NEMOTRON_MODEL,
        )

    async def run(self, run_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Entry point called by the ARQ worker.
        Manages the AgentRun lifecycle — do NOT override.
        """
        async with AsyncSessionLocal() as db:
            run = await db.get(AgentRun, uuid.UUID(run_id))
            if run is None:
                raise ValueError(f"AgentRun {run_id!r} not found in database")

            run.status = AgentRunStatus.RUNNING
            run.started_at = datetime.now(timezone.utc)
            await db.commit()

            self.log.info("Agent started", agent=self.name, run_id=run_id)

            try:
                result = await self.execute(db=db, run=run, input_data=input_data)
                run.status = AgentRunStatus.COMPLETED
                run.output_data = result
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                self.log.info("Agent completed", agent=self.name, run_id=run_id)
                return result

            except Exception as exc:
                run.status = AgentRunStatus.FAILED
                run.error_message = str(exc)[:2000]
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                self.log.error(
                    "Agent failed",
                    agent=self.name,
                    run_id=run_id,
                    error=str(exc),
                    exc_info=True,
                )
                raise

    @abstractmethod
    async def execute(
        self,
        db: AsyncSession,
        run: AgentRun,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Core agent logic. Must be implemented by each agent subclass.

        Args:
            db:         Active database session (already in a transaction).
            run:        The AgentRun record for this execution.
            input_data: Arbitrary input passed when triggering the agent.

        Returns:
            A dict that will be stored as output_data on the AgentRun.
        """

    async def record_tokens(
        self, db: AsyncSession, run: AgentRun, count: int
    ) -> None:
        """Add to the token usage counter for this run."""
        run.tokens_used = (run.tokens_used or 0) + count
        await db.flush()

    async def request_approval(
        self,
        db: AsyncSession,
        run: AgentRun,
        action_type: str,
        payload: Dict[str, Any],
    ) -> ApprovalRequest:
        """
        Create a human approval request and pause.
        The agent should check approval.status in a loop or on resume.

        This is the primary mechanism enforcing human control.
        """
        approval = ApprovalRequest(
            action_type=action_type,
            payload=payload,
            status=ApprovalStatus.PENDING,
            agent_run_id=run.id,
        )
        db.add(approval)
        await db.flush()
        self.log.info(
            "Approval requested — waiting for owner decision",
            action=action_type,
            approval_id=str(approval.id),
            run_id=str(run.id),
        )
        return approval
