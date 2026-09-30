"""
Agents package — Phase 1.

Phase 1 active agents:
  - Orchestrator: top-level planning agent

Future phases add agents here when approved:
  - Phase 2: LeadResearchAgent
  - Phase 3: OutreachAgent
  - Phase 4: FollowUpAgent
  - Phase 5: ClientIntelligenceAgent
  - Phase 6: WebsiteBuilderAgent
  - Phase 7: QAAgent
  - Phase 8: DeploymentAgent
"""
from agents.base_agent import AIProvider, BaseAgent
from agents.orchestrator import Orchestrator
from agents.lead_research import LeadResearchAgent

__all__ = ["BaseAgent", "AIProvider", "Orchestrator", "LeadResearchAgent"]
