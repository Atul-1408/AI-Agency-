"use client";

import { Activity } from "lucide-react";

interface AgentEvent {
  time: string;
  agent: string;
  message: string;
  status: "ok" | "warning" | "error";
}

const mockEvents: AgentEvent[] = [
  // Will be streamed from API via SSE or polled
];

export function AgentActivityLog() {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity size={16} style={{ color: "var(--color-accent)" }} />
          <h3 className="text-sm font-semibold">Real-time Agent Activity</h3>
          <span
            className="w-2 h-2 rounded-full animate-pulse-dot"
            style={{ background: "var(--color-success)" }}
          />
        </div>
        <a
          href="/dashboard/runs"
          className="text-xs font-medium"
          style={{ color: "var(--color-accent)" }}
        >
          Full audit log →
        </a>
      </div>

      {mockEvents.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center py-10 rounded-lg border border-dashed"
          style={{ borderColor: "var(--color-border)" }}
        >
          <Activity
            size={28}
            className="mb-2"
            style={{ color: "var(--color-muted)", opacity: 0.4 }}
          />
          <p className="text-sm" style={{ color: "var(--color-muted)" }}>
            No agent activity yet
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--color-muted)", opacity: 0.6 }}>
            Trigger an agent run to see live activity here
          </p>
        </div>
      ) : (
        <div className="space-y-1 font-mono text-xs">
          {mockEvents.map((event, i) => (
            <div
              key={i}
              className="flex items-center gap-3 px-3 py-2 rounded"
              style={{ background: "var(--color-surface-2)" }}
            >
              <span style={{ color: "var(--color-muted)" }}>{event.time}</span>
              <span style={{ color: "var(--color-accent)" }}>{event.agent}</span>
              <span className="flex-1">{event.message}</span>
              <span
                className={`badge badge-${event.status === "ok" ? "success" : "warning"}`}
              >
                {event.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
