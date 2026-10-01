"use client";

import Link from "next/link";
import {
  Workflow,
  Search,
  Mail,
  RotateCw,
  Users2,
  Layout,
  ShieldCheck,
  Cloud,
  Check,
  Lock,
  ArrowRight,
  Play,
} from "lucide-react";

interface AgentItem {
  phase: number;
  id: string;
  name: string;
  status: "active" | "implemented" | "upcoming";
  statusText: string;
  description: string;
  icon: typeof Workflow;
  iconColor: string;
  iconBg: string;
  features: string[];
  actionType: "gold-trigger" | "emerald-link" | "locked";
  actionLabel: string;
  actionHref?: string;
}

const AGENTS: AgentItem[] = [
  {
    phase: 1,
    id: "orchestrator",
    name: "Orchestrator",
    status: "active",
    statusText: "Active",
    description: "Multi-agent coordinator & human approval gatekeeper.",
    icon: Workflow,
    iconColor: "#E8B968",
    iconBg: "rgba(232, 185, 105, 0.12)",
    features: [
      "Coordinates all agents",
      "Manages workflows",
      "Requires human approval",
    ],
    actionType: "gold-trigger",
    actionLabel: "Trigger Orchestrator",
  },
  {
    phase: 2,
    id: "lead_research",
    name: "Lead Research",
    status: "implemented",
    statusText: "Implemented",
    description: "Prospect discovery, website audits & deterministic qualification.",
    icon: Search,
    iconColor: "#39C98A",
    iconBg: "rgba(57, 201, 138, 0.12)",
    features: [
      "Discover new prospects",
      "Audit websites (SSRF-safe)",
      "Find public contacts & MX",
    ],
    actionType: "emerald-link",
    actionLabel: "Open Lead Pipeline",
    actionHref: "/dashboard/leads",
  },
  {
    phase: 3,
    id: "outreach",
    name: "Outreach",
    status: "upcoming",
    statusText: "Upcoming",
    description: "Personalized email drafting and delivery with owner review.",
    icon: Mail,
    iconColor: "#8B6FB8",
    iconBg: "rgba(139, 111, 184, 0.12)",
    features: [
      "AI-powered personalization",
      "Human approval workflow",
      "Gmail integration",
    ],
    actionType: "locked",
    actionLabel: "Coming in Phase 3",
  },
  {
    phase: 4,
    id: "follow_up",
    name: "Follow-up",
    status: "upcoming",
    statusText: "Upcoming",
    description: "Multi-touch follow-up sequences with reply detection.",
    icon: RotateCw,
    iconColor: "#E5B85C",
    iconBg: "rgba(229, 184, 92, 0.12)",
    features: [
      "Smart delay tracking",
      "Thread continuation",
      "Opt-out auto-detection",
    ],
    actionType: "locked",
    actionLabel: "Coming in Phase 4",
  },
  {
    phase: 5,
    id: "client_intelligence",
    name: "Client Intelligence",
    status: "upcoming",
    statusText: "Upcoming",
    description: "Lead response parsing, sentiment analysis & onboarding.",
    icon: Users2,
    iconColor: "#8B6FB8",
    iconBg: "rgba(139, 111, 184, 0.12)",
    features: [
      "Lead reply analysis",
      "Intent classification",
      "Meeting booking coordination",
    ],
    actionType: "locked",
    actionLabel: "Coming in Phase 5",
  },
  {
    phase: 6,
    id: "website_builder",
    name: "Website Builder",
    status: "upcoming",
    statusText: "Upcoming",
    description: "Generates bespoke client websites via component assembly.",
    icon: Layout,
    iconColor: "#A98BD6",
    iconBg: "rgba(169, 139, 214, 0.12)",
    features: [
      "Next.js website generation",
      "Component assembly engine",
      "Mobile-first responsive styling",
    ],
    actionType: "locked",
    actionLabel: "Coming in Phase 6",
  },
  {
    phase: 7,
    id: "qa",
    name: "QA & Evaluator",
    status: "upcoming",
    statusText: "Upcoming",
    description: "Automated browser testing, accessibility & lighthouse checks.",
    icon: ShieldCheck,
    iconColor: "#8B6FB8",
    iconBg: "rgba(139, 111, 184, 0.12)",
    features: [
      "Automated visual validation",
      "Mobile viewport audit",
      "Lighthouse performance check",
    ],
    actionType: "locked",
    actionLabel: "Coming in Phase 7",
  },
  {
    phase: 8,
    id: "deployment",
    name: "Deployment",
    status: "upcoming",
    statusText: "Upcoming",
    description: "One-click deployment to Vercel with GitHub repo and custom domain.",
    icon: Cloud,
    iconColor: "#E8B968",
    iconBg: "rgba(232, 185, 105, 0.12)",
    features: [
      "GitHub repo auto-setup",
      "Vercel production preview",
      "Custom domain hook",
    ],
    actionType: "locked",
    actionLabel: "Coming in Phase 8",
  },
];

interface AgentCardsGridProps {
  onTrigger?: (agentId: string) => void;
}

export function AgentCardsGrid({ onTrigger }: AgentCardsGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-[20px]">
      {AGENTS.map((agent) => {
        const Icon = agent.icon;
        const isPhase1 = agent.phase === 1;
        const isPhase2 = agent.phase === 2;

        return (
          <div
            key={agent.id}
            className={`min-h-[290px] rounded-[14px] flex flex-col justify-between transition-all duration-200 ${
              isPhase1
                ? "agent-card-active-p1"
                : isPhase2
                ? "agent-card-active-p2"
                : "agent-card-locked"
            }`}
          >
            <div>
              {/* TOP: Phase Badge + Status Badge (Height 28px, padding 0 10px, radius 8px) */}
              <div className="flex items-center justify-between">
                <span
                  className={`h-[28px] px-3 rounded-[8px] text-[11px] font-semibold flex items-center justify-center whitespace-nowrap ${
                    isPhase1
                      ? "bg-[rgba(232,185,105,0.14)] text-[#F5CC7A] border border-[rgba(232,185,105,0.30)]"
                      : isPhase2
                      ? "bg-[rgba(57,201,138,0.14)] text-[#39C98A] border border-[rgba(57,201,138,0.30)]"
                      : "bg-[#1D1A1F] text-[#77717C] border border-[#302A30]"
                  }`}
                >
                  Phase {agent.phase}
                </span>

                <div className="flex items-center gap-1.5">
                  {isPhase1 ? (
                    <span className="flex items-center gap-1.5 text-[12px] font-semibold text-[#39C98A]">
                      <span className="w-2 h-2 rounded-full bg-[#39C98A] animate-pulse" />
                      {agent.statusText}
                    </span>
                  ) : isPhase2 ? (
                    <span className="flex items-center gap-1.5 text-[12px] font-semibold text-[#39C98A]">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A]" />
                      {agent.statusText}
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[11px] text-[#77717C]">
                      <Lock size={11} />
                      {agent.statusText}
                    </span>
                  )}
                </div>
              </div>

              {/* Spacing Badge → icon: 16px */}
              <div className="h-[16px]" />

              {/* Icon Container: 56px x 56px, radius 12px, icon size 22-24px */}
              <div
                className="w-[56px] h-[56px] rounded-[12px] flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: agent.iconBg }}
              >
                <Icon size={24} style={{ color: agent.iconColor }} />
              </div>

              {/* Spacing Icon → title: 14px */}
              <div className="h-[14px]" />

              {/* Title: 17-18px, Weight 600 */}
              <h3 className="text-[17px] font-semibold text-[#F5F1EA] tracking-tight">
                {agent.name}
              </h3>

              {/* Spacing Title → description: 8px */}
              <div className="h-[8px]" />

              {/* Description: 13-14px, line-height 1.5, #B7AFBA */}
              <p className="text-[13px] text-[#B7AFBA] leading-[1.5]">
                {agent.description}
              </p>

              {/* Spacing Description → checklist: 16px */}
              <div className="h-[16px]" />

              {/* Feature Checklist: 8px gap between rows */}
              <ul className="flex flex-col gap-[8px] text-[12px]">
                {agent.features.map((feature, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span
                      className={`w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0 ${
                        isPhase1
                          ? "bg-[rgba(232,185,105,0.15)] text-[#E8B968]"
                          : isPhase2
                          ? "bg-[rgba(57,201,138,0.15)] text-[#39C98A]"
                          : "bg-[#1D1A1F] text-[#77717C]"
                      }`}
                    >
                      <Check size={9} strokeWidth={3} />
                    </span>
                    <span
                      className={
                        isPhase1 || isPhase2
                          ? "text-[#F5F1EA]"
                          : "text-[#77717C]"
                      }
                    >
                      {feature}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Spacing Checklist → button: 20px */}
            <div className="pt-[20px]">
              {agent.actionType === "gold-trigger" ? (
                <button
                  type="button"
                  onClick={() => onTrigger && onTrigger(agent.id)}
                  className="btn-gold-primary"
                >
                  <Play size={14} fill="currentColor" />
                  <span>{agent.actionLabel}</span>
                </button>
              ) : agent.actionType === "emerald-link" ? (
                <Link
                  href={agent.actionHref || "/dashboard/leads"}
                  className="btn-emerald-secondary"
                >
                  <span>{agent.actionLabel}</span>
                  <ArrowRight size={14} />
                </Link>
              ) : (
                <button
                  type="button"
                  disabled
                  className="btn-locked"
                >
                  <Lock size={12} />
                  <span>{agent.actionLabel}</span>
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
