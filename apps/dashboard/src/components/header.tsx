"use client";

import { Bell, RefreshCw } from "lucide-react";

export function Header() {
  return (
    <header
      className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0"
      style={{
        background: "var(--color-surface)",
        borderColor: "var(--color-border)",
      }}
    >
      <div>
        <h1 className="text-base font-semibold">Owner Dashboard</h1>
        <p className="text-xs mt-0.5" style={{ color: "var(--color-muted)" }}>
          AI Web Agency Agent — You are in control
        </p>
      </div>

      <div className="flex items-center gap-3">
        {/* Live indicator */}
        <div className="flex items-center gap-2 text-xs" style={{ color: "var(--color-muted)" }}>
          <span
            className="w-2 h-2 rounded-full animate-pulse-dot"
            style={{ background: "var(--color-success)" }}
          />
          Live
        </div>

        {/* Refresh */}
        <button
          className="btn btn-secondary p-2"
          title="Refresh"
          onClick={() => window.location.reload()}
        >
          <RefreshCw size={14} />
        </button>

        {/* Notifications */}
        <button className="btn btn-secondary p-2 relative" title="Notifications">
          <Bell size={14} />
          <span
            className="absolute -top-1 -right-1 w-4 h-4 rounded-full text-xs flex items-center justify-center font-bold"
            style={{ background: "var(--color-danger)", fontSize: "10px" }}
          >
            3
          </span>
        </button>

        {/* Owner avatar */}
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold"
          style={{ background: "var(--color-accent)" }}
        >
          O
        </div>
      </div>
    </header>
  );
}
