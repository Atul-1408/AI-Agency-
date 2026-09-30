"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  Mail,
  CheckCircle,
  Activity,
  Settings,
  Zap,
  Bot,
} from "lucide-react";

const navItems = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard/leads", label: "Leads", icon: Users },
  { href: "/dashboard/outreach", label: "Outreach", icon: Mail },
  { href: "/dashboard/approvals", label: "Approvals", icon: CheckCircle },
  { href: "/dashboard/runs", label: "Agent Runs", icon: Activity },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="w-60 flex-shrink-0 flex flex-col border-r"
      style={{
        background: "var(--color-surface)",
        borderColor: "var(--color-border)",
      }}
    >
      {/* Logo */}
      <div
        className="flex items-center gap-3 px-5 py-5 border-b"
        style={{ borderColor: "var(--color-border)" }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: "var(--color-accent)" }}
        >
          <Bot size={16} className="text-white" />
        </div>
        <div>
          <p className="text-sm font-semibold leading-none">AI Agency</p>
          <p className="text-xs mt-0.5" style={{ color: "var(--color-muted)" }}>
            Owner Dashboard
          </p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-0.5">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/dashboard"
              ? pathname === "/dashboard"
              : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150"
              style={{
                color: active ? "white" : "var(--color-muted)",
                background: active
                  ? "rgba(99, 102, 241, 0.15)"
                  : "transparent",
                borderLeft: active
                  ? "2px solid var(--color-accent)"
                  : "2px solid transparent",
              }}
            >
              <Icon size={16} />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Phase indicator */}
      <div
        className="m-3 p-3 rounded-lg"
        style={{ background: "var(--color-surface-2)" }}
      >
        <div className="flex items-center gap-2 mb-1">
          <Zap size={12} style={{ color: "var(--color-accent)" }} />
          <span className="text-xs font-semibold" style={{ color: "var(--color-accent)" }}>
            Phase 1 — Foundation
          </span>
        </div>
        <p className="text-xs" style={{ color: "var(--color-muted)" }}>
          10 phases to full autonomy
        </p>
        <div
          className="mt-2 h-1.5 rounded-full overflow-hidden"
          style={{ background: "var(--color-border)" }}
        >
          <div
            className="h-full rounded-full"
            style={{ width: "10%", background: "var(--color-accent)" }}
          />
        </div>
      </div>
    </aside>
  );
}
