import { KpiCards } from "@/components/kpi-cards";
import { LeadPipeline } from "@/components/lead-pipeline";
import { AgentActivityLog } from "@/components/agent-activity-log";
import { PendingApprovals } from "@/components/pending-approvals";

export default function DashboardPage() {
  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <div>
        <h2 className="text-xl font-semibold">Overview</h2>
        <p className="text-sm mt-1" style={{ color: "var(--color-muted)" }}>
          Real-time snapshot of your AI agency pipeline
        </p>
      </div>

      {/* KPI Row */}
      <KpiCards />

      {/* Main Grid */}
      <div className="grid grid-cols-3 gap-6">
        {/* Lead Pipeline — 2/3 width */}
        <div className="col-span-2">
          <LeadPipeline />
        </div>

        {/* Pending Approvals — 1/3 width */}
        <div>
          <PendingApprovals />
        </div>
      </div>

      {/* Activity Log */}
      <AgentActivityLog />
    </div>
  );
}
