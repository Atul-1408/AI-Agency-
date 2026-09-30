"use client";

import { CheckCircle, XCircle, Clock } from "lucide-react";

const mockApprovals = [
  // Will be populated from API
];

export function PendingApprovals() {
  return (
    <div className="card h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">Pending Approvals</h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--color-muted)" }}>
            Actions waiting for your decision
          </p>
        </div>
        <a
          href="/dashboard/approvals"
          className="text-xs font-medium"
          style={{ color: "var(--color-accent)" }}
        >
          View all →
        </a>
      </div>

      <div className="flex-1 flex flex-col gap-2">
        {mockApprovals.length === 0 ? (
          <div
            className="flex-1 flex flex-col items-center justify-center py-12 rounded-lg border border-dashed"
            style={{ borderColor: "var(--color-border)" }}
          >
            <CheckCircle
              size={32}
              className="mb-3"
              style={{ color: "var(--color-success)", opacity: 0.5 }}
            />
            <p className="text-sm font-medium">All clear!</p>
            <p className="text-xs mt-1" style={{ color: "var(--color-muted)" }}>
              No pending approvals
            </p>
          </div>
        ) : null}
      </div>

      {/* Safety notice */}
      <div
        className="mt-3 p-3 rounded-lg text-xs"
        style={{
          background: "rgba(99,102,241,0.08)",
          color: "var(--color-muted)",
          border: "1px solid rgba(99,102,241,0.15)",
        }}
      >
        🔒 Emails, deployments, and key actions require your explicit approval
      </div>
    </div>
  );
}
