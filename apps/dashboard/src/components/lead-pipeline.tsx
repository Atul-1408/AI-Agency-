"use client";

const columns = [
  { id: "discovered", label: "Discovered", color: "#64748B" },
  { id: "researched", label: "Researched", color: "#6366F1" },
  { id: "qualified", label: "Qualified", color: "#8B5CF6" },
  { id: "approved", label: "Approved ✓", color: "#22C55E" },
  { id: "outreach_sent", label: "Outreach Sent", color: "#3B82F6" },
  { id: "replied", label: "Replied 🎉", color: "#F59E0B" },
];

// Placeholder cards — will be fetched from API
const mockLeads: Record<string, { name: string; company: string }[]> = {
  discovered: [],
  researched: [],
  qualified: [],
  approved: [],
  outreach_sent: [],
  replied: [],
};

export function LeadPipeline() {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">Lead Pipeline</h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--color-muted)" }}>
            AI-managed progression — approval required at key stages
          </p>
        </div>
        <a
          href="/dashboard/leads"
          className="text-xs font-medium"
          style={{ color: "var(--color-accent)" }}
        >
          View all →
        </a>
      </div>

      <div className="grid grid-cols-6 gap-2">
        {columns.map((col) => {
          const leads = mockLeads[col.id] || [];
          return (
            <div key={col.id} className="flex flex-col gap-2">
              {/* Column header */}
              <div
                className="flex items-center justify-between px-2 py-1.5 rounded-lg"
                style={{ background: "var(--color-surface-2)" }}
              >
                <span className="text-xs font-medium" style={{ color: col.color }}>
                  {col.label}
                </span>
                <span
                  className="text-xs font-bold px-1.5 py-0.5 rounded"
                  style={{
                    background: "var(--color-border)",
                    color: "var(--color-muted)",
                  }}
                >
                  {leads.length}
                </span>
              </div>

              {/* Cards */}
              <div className="space-y-2 min-h-[120px]">
                {leads.length === 0 ? (
                  <div
                    className="h-16 rounded-lg border border-dashed flex items-center justify-center"
                    style={{ borderColor: "var(--color-border)" }}
                  >
                    <span className="text-xs" style={{ color: "var(--color-muted)" }}>
                      Empty
                    </span>
                  </div>
                ) : (
                  leads.map((lead, i) => (
                    <div
                      key={i}
                      className="p-2 rounded-lg"
                      style={{ background: "var(--color-surface-2)" }}
                    >
                      <p className="text-xs font-medium truncate">{lead.name}</p>
                      <p className="text-xs truncate" style={{ color: "var(--color-muted)" }}>
                        {lead.company}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
