import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { listConversations, maskedApiKey } from "../api";
import type { ConversationOut } from "../types";
import BrandHomeLink from "./BrandHomeLink";

const DAY_MS = 86_400_000;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Age in whole days, calendar-based (yesterday 23:59 is 1, not 0). */
function ageInDays(iso: string): number {
  return Math.floor((startOfDay(new Date()) - startOfDay(new Date(iso))) / DAY_MS);
}

function groupLabel(iso: string): string {
  const age = ageInDays(iso);
  if (age <= 0) return "Aujourd'hui";
  if (age === 1) return "Hier";
  if (age < 7) return "Cette semaine";
  return "Plus ancien";
}

/** Today: "09:41" - this week: "lun." - older: "12.08.2026". */
function timeLabel(iso: string): string {
  const date = new Date(iso);
  const age = ageInDays(iso);
  if (age <= 0) return date.toLocaleTimeString("fr-CH", { hour: "2-digit", minute: "2-digit" });
  if (age < 7) return date.toLocaleDateString("fr-CH", { weekday: "short" });
  return date.toLocaleDateString("fr-CH");
}

const GROUP_ORDER = ["Aujourd'hui", "Hier", "Cette semaine", "Plus ancien"];

export default function ConversationSidebar() {
  const [conversations, setConversations] = useState<ConversationOut[]>([]);
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const activeId = searchParams.get("c");
  const masked = maskedApiKey();

  useEffect(() => {
    let cancelled = false;
    listConversations()
      .then((items) => {
        if (!cancelled) setConversations(items);
      })
      .catch(() => {
        // No key yet, or backend unreachable: an empty list is the right
        // fallback: the key modal / view-level errors handle the rest.
      });
    return () => {
      cancelled = true;
    };
  }, [location.key]);

  const groups = GROUP_ORDER.map((label) => ({
    label,
    items: conversations.filter((conversation) => groupLabel(conversation.created_at) === label),
  })).filter((group) => group.items.length > 0);

  return (
    <aside className="flex w-[262px] shrink-0 flex-col border-r border-black/[0.07] bg-surface">
      <div className="flex h-[52px] shrink-0 items-center border-b border-black/[0.06] px-[18px]">
        <BrandHomeLink />
      </div>

      <div className="px-3 pt-3.5 pb-2">
        <Link
          to="/chat"
          className="flex items-center justify-between rounded-[10px] bg-white px-3 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.08)] hover:shadow-[0_1px_4px_rgba(0,0,0,0.12)]"
        >
          <span className="text-[13px] font-medium text-link">Nouvelle conversation</span>
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-2">
        {groups.map((group) => (
          <div key={group.label}>
            <div className="px-2 pt-2.5 pb-1.5 text-[11px] font-medium text-muted">
              {group.label}
            </div>
            <ul>
              {group.items.map((conversation) => {
                const active = conversation.id === activeId;
                return (
                  <li key={conversation.id}>
                    <Link
                      to={`/chat?c=${conversation.id}`}
                      className={`block rounded-[10px] px-3 py-2.5 ${
                        active
                          ? "bg-white shadow-[0_1px_3px_rgba(0,0,0,0.09)]"
                          : "hover:bg-black/[0.04]"
                      }`}
                    >
                      <div
                        className={`truncate text-[13px] ${
                          active ? "font-medium text-ink" : "text-ink-secondary"
                        }`}
                      >
                        {conversation.title}
                      </div>
                      <div className="mt-0.5 text-[11px] text-muted">
                        {timeLabel(conversation.created_at)}
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="flex items-center justify-between border-t border-black/[0.06] px-[18px] py-3">
        <span className="font-mono text-[11px] text-muted">{masked ?? "hors ligne"}</span>
        <Link to="/admin" className="text-xs font-medium text-link hover:underline">
          Administration
        </Link>
      </div>
    </aside>
  );
}
