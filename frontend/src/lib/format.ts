// Locale-aware formatting shared by the chat and admin screens. The locale
// follows the product language (lang.tsx); storedLang() is read per call so
// a language switch takes effect on the next render without an import cycle.

import type { AnswerMeta } from "../hooks/useChatStream";
import { localeOf, storedLang, type Lang } from "./lang";

function locale(): string {
  return localeOf(storedLang());
}

/** Grouped integer: 9246 -> "9 246" (fr), "9,246" (en), "9'246" (de-CH). */
export function formatInt(value: number): string {
  return new Intl.NumberFormat(locale()).format(value);
}

/** Fixed-precision decimal with the locale's separator. */
export function fmtDecimal(value: number, digits: number): string {
  return new Intl.NumberFormat(locale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Compact counter: 2 140 000 -> "2,14 M" / "2.14 M". */
export function formatCount(value: number): string {
  if (value >= 1_000_000) return `${fmtDecimal(value / 1_000_000, 2)} M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)} k`;
  return formatInt(value);
}

/** "2,4 s" above one second, "310 ms" below; "n/a" for missing samples. */
export function formatLatency(ms: number | null): string {
  if (ms === null) return "n/a";
  return ms >= 1000 ? `${fmtDecimal(ms / 1000, 1)} s` : `${ms} ms`;
}

export function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${fmtDecimal(bytes / (1024 * 1024), 1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${bytes} B`;
}

/** "21.08.2026", the Swiss short date, stable across languages. */
export function formatDate(iso: string): string {
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}`;
}

const RELATIVE: Record<Lang, { now: string; min: (n: number) => string; h: (n: number) => string; yesterday: string }> = {
  en: {
    now: "just now",
    min: (n) => `${n} minute${n > 1 ? "s" : ""} ago`,
    h: (n) => `${n} hour${n > 1 ? "s" : ""} ago`,
    yesterday: "yesterday",
  },
  fr: {
    now: "à l'instant",
    min: (n) => `il y a ${n} minute${n > 1 ? "s" : ""}`,
    h: (n) => `il y a ${n} heure${n > 1 ? "s" : ""}`,
    yesterday: "hier",
  },
  de: {
    now: "gerade eben",
    min: (n) => `vor ${n} Minute${n > 1 ? "n" : ""}`,
    h: (n) => `vor ${n} Stunde${n > 1 ? "n" : ""}`,
    yesterday: "gestern",
  },
};

/** Relative age in the product language, then the plain date. */
export function formatRelative(iso: string): string {
  const t = RELATIVE[storedLang()];
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return t.now;
  if (minutes < 60) return t.min(minutes);
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t.h(hours);
  if (hours < 48) return t.yesterday;
  return formatDate(iso);
}

/** RRF scores land around 0.03: four decimals keep them distinguishable. */
export function formatScore(score: number): string {
  return fmtDecimal(score, 4);
}

/** "№f3a1" style audit label: first 4 hex chars of the message UUID. */
export function auditLabel(meta: AnswerMeta | undefined): string | null {
  if (meta === undefined) return null;
  return meta.messageId.replaceAll("-", "").slice(0, 4);
}

/** Total answer latency as "18,9 s", when both stage timings are known. */
export function formatAnswerSeconds(meta: AnswerMeta): string | null {
  if (meta.retrievalMs === null || meta.generationMs === null) return null;
  return `${fmtDecimal((meta.retrievalMs + meta.generationMs) / 1000, 1)} s`;
}
