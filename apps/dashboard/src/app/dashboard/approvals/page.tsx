import type { Metadata } from "next";
import { CheckCircle, XCircle, Shield } from "lucide-react";

export const metadata: Metadata = { title: "Approvals — AI Agency" };

export default function ApprovalsPage() {
  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <div>
        <h2 className="text-xl font-semibold">Approval Queue</h2>
        <p className="text-sm mt-1" style={{ color: "var(--color-muted)" }}>
          Every agent action that requires your explicit sign-off appears here
        </p>
      </div>

      {/* Safety policy banner */}
      <div
        className="card flex items-start gap-4"
        style={{
          background: "rgba(99,102,241,0.06)",
          borderColor: "rgba(99,102,241,0.2)",
        }}
      >
        <div
          className="w-10 h-10 rounded-lg flex-shrink-0 flex items-center justify-center"
          style={{ background: "rgba(99,102,241,0.15)" }}
        >
          <Shield size={18} style={{ color: "var(--color-accent)" }} />
        </div>
        <div>
          <p className="text-sm font-semibold">Human-in-the-loop policy</p>
          <p className="text-xs mt-1" style={{ color: "var(--color-muted)" }}>
            The following actions always require your approval before execution:
            outbound email sending, website deployments, lead qualification
            changes, and any external API writes. The agent will never bypass
            this gate.
          </p>
        </div>
      </div>

      {/* Queue */}
      <div className="card">
        <div
          className="flex flex-col items-center justify-center py-20"
          style={{ color: "var(--color-muted)" }}
        >
          <CheckCircle
            size={36}
            className="mb-3"
            style={{ color: "var(--color-success)", opacity: 0.5 }}
          />
          <p className="text-sm font-medium">No pending approvals</p>
          <p className="text-xs mt-1">
            The agent will notify you here when action is required
          </p>
        </div>
      </div>
    </div>
  );
}
