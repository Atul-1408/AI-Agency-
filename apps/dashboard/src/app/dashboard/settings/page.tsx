import type { Metadata } from "next";
import { Settings, AlertTriangle } from "lucide-react";

export const metadata: Metadata = { title: "Settings — AI Agency" };

const settingGroups = [
  {
    title: "Email Safeguards",
    items: [
      { key: "MAX_EMAILS_PER_DAY", label: "Max emails per day", value: "50" },
      { key: "MAX_EMAILS_PER_CAMPAIGN", label: "Max per campaign", value: "200" },
      { key: "EMAIL_COOLDOWN_HOURS", label: "Cooldown between touches (hours)", value: "72" },
    ],
  },
  {
    title: "AI Model",
    items: [
      { key: "NEMOTRON_MODEL", label: "Model", value: "nvidia/llama-3.1-nemotron-ultra-253b-v1" },
    ],
  },
  {
    title: "Integrations",
    items: [
      { key: "GMAIL", label: "Gmail OAuth", value: "Not connected" },
      { key: "GITHUB", label: "GitHub", value: "Not connected" },
      { key: "VERCEL", label: "Vercel", value: "Not connected" },
      { key: "GOOGLE_MAPS", label: "Google Maps API", value: "Not connected" },
    ],
  },
];

export default function SettingsPage() {
  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-xl font-semibold">Settings</h2>
        <p className="text-sm mt-1" style={{ color: "var(--color-muted)" }}>
          Configure safeguards, integrations, and agent policies
        </p>
      </div>

      {/* Warning */}
      <div
        className="card flex items-start gap-3"
        style={{
          background: "rgba(245,158,11,0.06)",
          borderColor: "rgba(245,158,11,0.2)",
        }}
      >
        <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" style={{ color: "var(--color-warning)" }} />
        <p className="text-xs" style={{ color: "var(--color-muted)" }}>
          All secrets (API keys, OAuth tokens) are stored as environment
          variables, never in the database. Edit your <code>.env</code> file and
          restart the API to apply changes.
        </p>
      </div>

      {settingGroups.map((group) => (
        <div key={group.title} className="card space-y-3">
          <h3 className="text-sm font-semibold">{group.title}</h3>
          {group.items.map((item) => (
            <div key={item.key} className="flex items-center justify-between py-2 border-t" style={{ borderColor: "var(--color-border)" }}>
              <div>
                <p className="text-xs font-medium">{item.label}</p>
                <p className="text-xs font-mono mt-0.5" style={{ color: "var(--color-muted)" }}>
                  {item.key}
                </p>
              </div>
              <span
                className="text-xs px-2 py-1 rounded"
                style={{
                  background: "var(--color-surface-2)",
                  color: item.value.includes("Not") ? "var(--color-warning)" : "var(--color-text)",
                }}
              >
                {item.value}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
