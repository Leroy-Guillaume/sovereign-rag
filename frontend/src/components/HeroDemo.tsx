import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import type { HeroDemoCopy } from "../views/landingCopy";

/**
 * The landing hero's chat window, played as a looping product simulation:
 * the question types itself, the answer streams in with its citation chips,
 * a pointer glides to the Sources pill and clicks, the panel slides open.
 * Decorative only; the composer doubles as the real CTA into /chat. The
 * caller remounts it (key) on language change so the loop restarts clean.
 */

/** Scenario steps, in playback order; at(p) tests "phase p reached or passed". */
const PHASES = [
  "idle",
  "typing",
  "sent",
  "answering",
  "meta",
  "cursor",
  "click",
  "panel",
  "hold",
  "fade",
] as const;
type Phase = (typeof PHASES)[number];

function Chip({ n, active }: { n: string; active: boolean }) {
  return (
    <span
      className={`mx-[3px] inline-block -translate-y-[2px] rounded-md px-1.5 font-mono text-[11.5px] leading-[18px] font-medium transition-colors duration-300 ${
        active ? "bg-accent text-white" : "bg-chip text-chip-ink"
      }`}
    >
      {n}
    </span>
  );
}

export default function HeroDemo({ copy }: { copy: HeroDemoCopy }) {
  const question = copy.question;
  const answerTotal = useMemo(
    () => copy.answer.reduce((sum, seg) => sum + (seg.text?.length ?? 1), 0),
    [copy],
  );
  const reduced = useMemo(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );
  const [phase, setPhase] = useState<Phase>("idle");
  const [typedCount, setTypedCount] = useState(0);
  const [answerBudget, setAnswerBudget] = useState(0);
  const [cursorXY, setCursorXY] = useState<{ x: number; y: number } | null>(null);
  const [active, setActive] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pillRef = useRef<HTMLSpanElement | null>(null);

  const at = (p: Phase) => reduced || PHASES.indexOf(phase) >= PHASES.indexOf(p);
  const panelOpen = reduced || at("panel");
  const pressed = phase === "click";

  // Play only while the window is actually on screen.
  useEffect(() => {
    const element = containerRef.current;
    if (element === null || reduced) return;
    const observer = new IntersectionObserver(
      ([entry]) => setActive(entry.isIntersecting),
      { threshold: 0.3 },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [reduced]);

  // Character reveals (question, then answer).
  useEffect(() => {
    if (!active || reduced) return;
    if (phase === "typing") {
      const timer = window.setInterval(
        () => setTypedCount((count) => Math.min(count + 1, question.length)),
        26,
      );
      return () => window.clearInterval(timer);
    }
    if (phase === "answering") {
      const timer = window.setInterval(
        () => setAnswerBudget((budget) => Math.min(budget + 2, answerTotal)),
        12,
      );
      return () => window.clearInterval(timer);
    }
  }, [phase, active, reduced]);

  // Phase advancement: each step hands over to the next after its beat.
  useEffect(() => {
    if (!active || reduced) return;
    const next = (target: Phase, delay: number) =>
      window.setTimeout(() => setPhase(target), delay);
    let timer: number | undefined;
    switch (phase) {
      case "idle":
        timer = next("typing", 900);
        break;
      case "typing":
        if (typedCount >= question.length) timer = next("sent", 350);
        break;
      case "sent":
        timer = next("answering", 800);
        break;
      case "answering":
        if (answerBudget >= answerTotal) timer = next("meta", 300);
        break;
      case "meta":
        timer = next("cursor", 800);
        break;
      case "cursor":
        timer = next("click", 1050);
        break;
      case "click":
        timer = next("panel", 260);
        break;
      case "panel":
        timer = next("hold", 600);
        break;
      case "hold":
        timer = next("fade", 3600);
        break;
      case "fade":
        timer = window.setTimeout(() => {
          setTypedCount(0);
          setAnswerBudget(0);
          setCursorXY(null);
          setPhase("idle");
        }, 400);
        break;
    }
    return () => window.clearTimeout(timer);
  }, [phase, typedCount, answerBudget, active, reduced]);

  // Pointer flight: measured against the real pill position, never hardcoded.
  useEffect(() => {
    if (phase !== "cursor") return;
    const container = containerRef.current;
    const pill = pillRef.current;
    if (container === null || pill === null) return;
    const containerRect = container.getBoundingClientRect();
    const pillRect = pill.getBoundingClientRect();
    setCursorXY({ x: containerRect.width * 0.62, y: containerRect.height * 0.94 });
    const raf = requestAnimationFrame(() =>
      requestAnimationFrame(() =>
        setCursorXY({
          x: pillRect.left - containerRect.left + pillRect.width * 0.62,
          y: pillRect.top - containerRect.top + pillRect.height * 0.5,
        }),
      ),
    );
    return () => cancelAnimationFrame(raf);
  }, [phase]);

  function renderAnswer(): ReactNode[] {
    let remaining = reduced ? answerTotal : answerBudget;
    const parts: ReactNode[] = [];
    for (const [i, segment] of copy.answer.entries()) {
      if (remaining <= 0) break;
      if (segment.chip !== undefined) {
        parts.push(<Chip key={i} n={segment.chip} active={segment.chip === "1" && at("panel")} />);
        remaining -= 1;
      } else if (segment.text !== undefined) {
        parts.push(<span key={i}>{segment.text.slice(0, remaining)}</span>);
        remaining -= segment.text.length;
      }
    }
    return parts;
  }

  return (
    <div
      ref={containerRef}
      className="relative mx-auto mt-[82px] max-w-[1060px] overflow-hidden rounded-t-2xl bg-white text-left text-ink shadow-[0_-1px_0_rgba(255,255,255,0.14),0_50px_110px_rgba(0,0,0,0.55)]"
    >
      <div className="grid grid-cols-[1fr_auto_1fr] items-center border-b border-black/[0.06] bg-surface px-[15px] py-[11px]">
        <div className="flex gap-[7px]">
          <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
        </div>
        <div className="text-center text-[12px] font-medium text-ink-tertiary">
          {copy.windowTitle}
        </div>
        <div />
      </div>

      <div
        className={`flex transition-opacity duration-400 md:h-[430px] ${
          phase === "fade" ? "opacity-0" : "opacity-100"
        }`}
      >
        <div className="flex min-w-0 flex-1 flex-col px-11 py-8">
          <div className="flex min-h-[38px] justify-end">
            {at("sent") && (
              <span className="rounded-[18px] rounded-br-[6px] bg-accent px-[15px] py-[9px] text-[14.5px] leading-normal text-white">
                {question}
              </span>
            )}
          </div>
          <p className="mt-6 min-h-[116px] text-[16px] leading-[1.8] text-pretty">
            {renderAnswer()}
            {phase === "answering" && <span className="animate-pulse text-muted">▍</span>}
          </p>
          <div
            className={`flex items-center gap-3.5 transition-opacity duration-400 ${
              at("meta") ? "opacity-100" : "opacity-0"
            }`}
          >
            <span
              ref={pillRef}
              className={`inline-flex items-center gap-2 rounded-full bg-surface px-[15px] py-[7px] text-[12.5px] font-medium text-link transition-transform duration-150 ${
                pressed ? "scale-90 bg-[#e3e3e8]" : ""
              }`}
            >
              {copy.sourcesLabel}
              <span className="font-mono text-[11px] font-normal text-muted">8</span>
            </span>
            <span className="text-[11.5px] text-muted">{copy.meta}</span>
          </div>
          <Link
            to="/chat"
            aria-label={copy.composerAria}
            className="group mt-auto flex items-center gap-3 rounded-full bg-surface py-2 pr-2 pl-[18px] transition hover:bg-surface-hover"
          >
            <span className="flex-1 truncate text-left text-[14px] text-muted">
              {phase === "typing" ? (
                <span className="text-ink">
                  {question.slice(0, typedCount)}
                  <span className="animate-pulse">|</span>
                </span>
              ) : (
                copy.composer
              )}
            </span>
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-white transition group-hover:brightness-110">
              <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">
                <path
                  d="M6.5 11V2M2.5 6 6.5 2l4 4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          </Link>
        </div>

        <div
          className="hidden shrink-0 overflow-hidden border-l border-black/[0.06] bg-surface-raised transition-[width] duration-500 ease-out md:block"
          style={{ width: panelOpen ? 316 : 0 }}
        >
          <div className="w-[316px] px-[18px] py-5">
            <div className="px-1 pb-3 text-[11px] font-medium text-muted">{copy.panelHeading}</div>
            {copy.sources.map((source, i) => (
              <div
                key={source.filename}
                className={`rounded-[14px] bg-white px-4 py-3.5 transition-all duration-500 ${i > 0 ? "mt-2.5" : ""} ${
                  i === 0 && at("hold")
                    ? "shadow-[0_0_0_1.5px_var(--color-accent),0_6px_18px_rgba(0,113,227,0.13)]"
                    : "shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
                } ${panelOpen ? "translate-x-0 opacity-100" : "translate-x-4 opacity-0"}`}
                style={{ transitionDelay: panelOpen ? `${i * 120}ms` : "0ms" }}
              >
                <div className="flex items-baseline justify-between">
                  <span className="text-[12.5px] font-medium">{source.filename}</span>
                  <span className="font-mono text-[10.5px] text-muted">{source.score}</span>
                </div>
                <div className="mt-[3px] text-[11px] text-muted">{source.where}</div>
                <p className="mt-2.5 text-[12px] leading-[1.6] text-ink-secondary">
                  {source.excerpt}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* The simulated pointer (macOS-style), flown between measured waypoints. */}
      {!reduced && cursorXY !== null && (phase === "cursor" || phase === "click") && (
        <svg
          width="17"
          height="22"
          viewBox="0 0 17 22"
          aria-hidden="true"
          className="pointer-events-none absolute top-0 left-0 z-10 drop-shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
          style={{
            transform: `translate(${cursorXY.x}px, ${cursorXY.y}px) scale(${pressed ? 0.85 : 1})`,
            transition:
              "transform 1000ms cubic-bezier(0.35, 0.7, 0.25, 1)",
          }}
        >
          <path
            d="M1 1v16.5l4.2-3.6 2.6 6 2.6-1.1-2.6-5.9h5.9z"
            fill="#1d1d1f"
            stroke="#fff"
            strokeWidth="1.4"
          />
        </svg>
      )}
    </div>
  );
}
