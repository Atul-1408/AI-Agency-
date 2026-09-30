"use client";

import {
  Users,
  Mail,
  Clock,
  Zap,
  TrendingUp,
  TrendingDown,
} from "lucide-react";

const kpis = [
  {
    id: "total-leads",
    label: "Total Leads",
    value: "—",
    delta: null,
    icon: Users,
    iconColor: "#6366F1",
    iconBg: "rgba(99,102,241,0.12)",
  },
  {
    id: "emails-sent",
    label: "Emails Sent Today",
    value: "0 / 50",
    delta: "Daily limit: 50",
    icon: Mail,
    iconColor: "#22C55E",
    iconBg: "rgba(34,197,94,0.12)",
  },
  {
    id: "pending-approvals",
    label: "Pending Approvals",
    value: "—",
    delta: "Require action",
    icon: Clock,
    iconColor: "#F59E0B",
    iconBg: "rgba(245,158,11,0.12)",
  },
  {
    id: "active-jobs",
    label: "Active Agent Jobs",
    value: "0",
    delta: null,
    icon: Zap,
    iconColor: "#818CF8",
    iconBg: "rgba(129,140,248,0.12)",
  },
];

export function KpiCards() {
  return (
    <div className="grid grid-cols-4 gap-4">
      {kpis.map((kpi) => {
        const Icon = kpi.icon;
        return (
          <div key={kpi.id} className="card">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium" style={{ color: "var(--color-muted)" }}>
                  {kpi.label}
                </p>
                <p className="text-2xl font-bold mt-1">{kpi.value}</p>
                {kpi.delta && (
                  <p className="text-xs mt-1" style={{ color: "var(--color-muted)" }}>
                    {kpi.delta}
                  </p>
                )}
              </div>
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: kpi.iconBg }}
              >
                <Icon size={16} style={{ color: kpi.iconColor }} />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
