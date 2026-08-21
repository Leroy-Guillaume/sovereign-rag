// French-locale formatting shared by the chat and admin screens.

import type { AnswerMeta } from "../hooks/useChatStream";

const intFormat = new Intl.NumberFormat("fr-CH");

/** Grouped integer: 9246 -> "9 246". */
export function formatInt(value: number): string {
  return intFormat.format(value);
}

/** French decimal comma on a fixed-precision number. */
export function frDecimal(value: number, digits: number): string {
  return value.toFixed(digits).replace(".", ",");
}

/** Compact counter: 2 140 000 -> "2,14 M", 486 000 -> "486 k". */
export function formatCount(value: number): string {
  if (value >= 1_000_000) return `${frDecimal(value / 1_000_000, 2)} M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)} k`;
  return formatInt(value);
}

/** "2,4 s" above one second, "310 ms" below; "n/a" for missing samples. */
export function formatLatency(ms: number | null): string {
  if (ms === null) return "n/a";
  return ms >= 1000 ? `${frDecimal(ms / 1000, 1)} s` : `${ms} ms`;
}

export function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${frDecimal(bytes / (1024 * 1024), 1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${bytes} B`;
}

/** "21.08.2026", the Swiss short date. */
export function formatDate(iso: string): string {
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}`;
}

/** "il y a 4 minutes", "il y a 2 heures", "hier", then the plain date. */
export function formatRelative(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} minute${minutes > 1 ? "s" : ""}`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `il y a ${hours} heure${hours > 1 ? "s" : ""}`;
  if (hours < 48) return "hier";
  return formatDate(iso);
}

/** RRF scores land around 0.03: four decimals keep them distinguishable. */
export function formatScore(score: number): string {
  return frDecimal(score, 4);
}

/** "№f3a1" style audit label: first 4 hex chars of the message UUID. */
export function auditLabel(meta: AnswerMeta | undefined): string | null {
  if (meta === undefined) return null;
  return meta.messageId.replaceAll("-", "").slice(0, 4);
}

/** Total answer latency as "18,9 s", when both stage timings are known. */
export function formatAnswerSeconds(meta: AnswerMeta): string | null {
  if (meta.retrievalMs === null || meta.generationMs === null) return null;
  const seconds = (meta.retrievalMs + meta.generationMs) / 1000;
  return `${seconds.toLocaleString("fr-CH", { maximumFractionDigits: 1 })} s`;
}
