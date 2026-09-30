import type { Metadata } from "next";

export const metadata: Metadata = { title: "Leads — AI Agency" };

export default function LeadsPage() {
  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Leads</h2>
          <p className="text-sm mt-1" style={{ color: "var(--color-muted)" }}>
            All prospects discovered and researched by the Lead Agent
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button className="btn btn-secondary text-sm">Filter</button>
          <button className="btn btn-primary text-sm">
            ＋ Trigger Lead Research
          </button>
        </div>
      </div>

      {/* Placeholder table */}
      <div className="card">
        <div
          className="flex flex-col items-center justify-center py-20"
          style={{ color: "var(--color-muted)" }}
        >
          <p className="text-sm font-medium">No leads yet</p>
          <p className="text-xs mt-1">
            Trigger a Lead Research agent run to discover prospects
          </p>
          <p className="text-xs mt-4 font-mono px-3 py-2 rounded" style={{ background: "var(--color-surface-2)" }}>
            POST /api/v1/agents/trigger {"{ agent_name: 'lead_research' }"}
          </p>
        </div>
      </div>
    </div>
  );
}
