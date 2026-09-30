import type { Metadata } from "next";
import { Activity, Clock } from "lucide-react";

export const metadata: Metadata = { title: "Agent Runs — AI Agency" };

const AGENTS = [
  { id: "orchestrator", label: "Orchestrator", phase: 1 },
  { id: "lead_research", label: "Lead Research", phase: 2 },
  { id: "outreach", label: "Outreach", phase: 3 },
  { id: "client_intelligence", label: "Client Intelligence", phase: 5 },
  { id: "website_builder", label: "Website Builder", phase: 6 },
  { id: "qa", label: "QA Agent", phase: 7 },
  { id: "deployment", label: "Deployment", phase: 8 },
];

export default function RunsPage() {
  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Agent Runs</h2>
          <p className="text-sm mt-1" style={{ color: "var(--color-muted)" }}>
            Full audit log of every agent execution
          </p>
        </div>
      </div>

      {/* Agent cards */}
      <div className="grid grid-cols-4 gap-4">
        {AGENTS.map((agent) => (
          <div key={agent.id} className="card flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{agent.label}</span>
              <span
                className={`badge ${agent.phase === 1 ? "badge-success" : "badge-muted"}`}
              >
                Phase {agent.phase}
              </span>
            </div>
            <p className="text-xs" style={{ color: "var(--color-muted)" }}>
              {agent.phase === 1 ? "Active" : "Not yet implemented"}
            </p>
            {agent.phase === 1 && (
              <button className="btn btn-primary text-xs w-full justify-center">
                Trigger Run
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Runs table */}
      <div className="card">
        <div className="flex items-center gap-2 mb-4">
          <Activity size={16} style={{ color: "var(--color-accent)" }} />
          <h3 className="text-sm font-semibold">Run History</h3>
        </div>
        <div
          className="flex flex-col items-center justify-center py-16"
          style={{ color: "var(--color-muted)" }}
        >
          <Clock size={32} className="mb-3" style={{ opacity: 0.4 }} />
          <p className="text-sm font-medium">No runs yet</p>
          <p className="text-xs mt-1">
            Every agent action is logged here for full auditability
          </p>
        </div>
      </div>
    </div>
  );
}
