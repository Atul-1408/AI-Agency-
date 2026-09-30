"""
Orchestrator Agent — Phase 1.

The orchestrator is the top-level coordination agent.
In Phase 1, it:
  - Accepts a goal string as input
  - Returns a structured plan describing which agents should run
  - Does NOT call AI (NEMOTRON_ENABLED=false by default)
  - Does NOT execute sub-agents directly
  - Documents what a real orchestrator will do in Phase 9

Phase 9 will extend this to actually invoke sub-agents,
monitor their progress, and adapt the plan dynamically.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from models import AgentRun


class Orchestrator(BaseAgent):
    """
    Top-level planning agent.

    Phase 1 behaviour:
      If AI is disabled (default): returns a static plan structure
      showing what the orchestrator will do when fully implemented.

      If AI is enabled (NEMOTRON_ENABLED=true): sends the goal to
      Nemotron and returns its plan as structured JSON.

    This agent is the only Phase 1 active agent.
    """

    name = "orchestrator"

    # The prompt that will be sent to Nemotron when NEMOTRON_ENABLED=true.
    # Defined here in Phase 1 so the interface is clear before the model is active.
    SYSTEM_PROMPT = """
You are an AI orchestrator for a web design agency.
Your job is to plan and coordinate a team of specialized agents.

Available agents and their phases:
- lead_research (Phase 2): Finds and qualifies business prospects
- outreach (Phase 3): Manages email outreach campaigns
- follow_up (Phase 4): Manages follow-up sequences
- client_intelligence (Phase 5): Extracts client requirements
- website_builder (Phase 6): Generates production-ready Next.js websites
- qa (Phase 7): Tests generated websites
- deployment (Phase 8): Deploys approved websites

Rules:
- Always escalate consequential actions to the human owner via approval requests.
- Never send emails without owner approval.
- Never deploy without owner approval.
- Respect all configured sending limits.

Respond with valid JSON only:
{
  "plan": [{"step": 1, "agent": "<name>", "task": "<description>", "requires_approval": <bool>}],
  "reasoning": "<why this plan>",
  "estimated_steps": <int>
}
""".strip()

    async def execute(
        self,
        db: AsyncSession,
        run: AgentRun,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Phase 1 orchestrator execution.

        Input:
          {"goal": "<natural language goal>"}

        Output (AI disabled):
          Static structure showing the intended plan format.

        Output (AI enabled):
          Nemotron-generated plan as structured JSON.
        """
        goal = input_data.get("goal", "No goal provided")
        self.log.info("Orchestrator executing", goal=goal)

        if not self.ai.enabled:
            # AI is disabled — return a clearly-labelled Phase 1 placeholder.
            # This is NOT a fake AI response. It is an explicit stub.
            return {
                "phase": 1,
                "ai_enabled": False,
                "goal": goal,
                "note": (
                    "AI planning is disabled (NEMOTRON_ENABLED=false). "
                    "This response shows the intended output format. "
                    "Set NEMOTRON_ENABLED=true and provide NEMOTRON_API_KEY "
                    "to enable real orchestration."
                ),
                "plan_format_example": {
                    "plan": [
                        {
                            "step": 1,
                            "agent": "lead_research",
                            "task": "Find 20 local restaurant businesses in London with poor websites",
                            "requires_approval": True,
                        }
                    ],
                    "reasoning": "Starting with lead research to build the prospect pipeline.",
                    "estimated_steps": 1,
                },
            }

        # AI is enabled — call Nemotron
        import json
        try:
            raw_response, tokens = await self.ai.chat(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=f"Create a plan for this goal: {goal}",
                temperature=0.3,
                max_tokens=1024,
            )
            await self.record_tokens(db, run, tokens)

            # Parse JSON response
            cleaned = raw_response.strip().strip("```json").strip("```").strip()
            plan = json.loads(cleaned)
            return {"ai_enabled": True, "goal": goal, "plan": plan, "tokens_used": tokens}

        except json.JSONDecodeError as exc:
            # AI returned non-JSON — record the raw response, don't fabricate
            return {
                "ai_enabled": True,
                "goal": goal,
                "error": "AI returned non-JSON response",
                "raw_response": raw_response[:500],
            }
