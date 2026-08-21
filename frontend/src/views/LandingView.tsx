import { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import HeroDemo from "../components/HeroDemo";
import { staticLanding } from "../lib/env";
import { LANDING_COPY, LANGS, LANG_STORAGE, type Lang } from "./landingCopy";

const REPO_URL = "https://github.com/Leroy-Guillaume/sovereign-rag";
const COMPLIANCE_URL = REPO_URL + "/blob/main/COMPLIANCE.md";
const README_URL = REPO_URL + "/blob/main/README.md";

function storedLang(): Lang {
  const stored = localStorage.getItem(LANG_STORAGE);
  return LANGS.includes(stored as Lang) ? (stored as Lang) : "en";
}

export default function LandingView() {
  const [searchParams] = useSearchParams();
  const [lang, setLang] = useState<Lang>(storedLang);
  const t = LANDING_COPY[lang];

  useEffect(() => {
    localStorage.setItem(LANG_STORAGE, lang);
    document.documentElement.lang = lang;
  }, [lang]);

  // The chat used to live at "/" with conversations addressed as /?c=<id>.
  // Redirect so old bookmarks keep working.
  const legacyConversationId = searchParams.get("c");
  if (legacyConversationId !== null) {
    return <Navigate to={"/chat?c=" + encodeURIComponent(legacyConversationId)} replace />;
  }

  return (
    <div className="bg-white font-sans text-ink">
      <nav className="sticky top-0 z-50 flex justify-center bg-black/80 backdrop-blur">
        <div className="flex h-11 w-full max-w-[1024px] items-center justify-between px-4 text-[#f5f5f7]">
          <span className="text-[13px] font-semibold tracking-[-0.01em]">sovereign-rag</span>
          <div className="hidden gap-[30px] md:flex">
            {t.navLinks.map(({ label, href }) => (
              <a
                key={href}
                href={href}
                className="text-[12px] opacity-85 transition-opacity hover:opacity-100"
              >
                {label}
              </a>
            ))}
          </div>
          <div className="flex items-center gap-[18px]">
            <div className="flex items-center gap-1.5 text-[12px]">
              {LANGS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setLang(option)}
                  aria-pressed={lang === option}
                  className={
                    lang === option
                      ? "font-semibold opacity-100"
                      : "opacity-55 transition-opacity hover:opacity-85"
                  }
                >
                  {option.toUpperCase()}
                </button>
              ))}
            </div>
            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer"
              className="text-[12px] opacity-85 transition-opacity hover:opacity-100"
            >
              GitHub
            </a>
            {staticLanding ? (
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="rounded-full bg-accent px-3.5 py-1.5 text-[12px] font-medium text-white transition hover:brightness-110"
              >
                {t.openApp}
              </a>
            ) : (
              <Link
                to="/chat"
                className="rounded-full bg-accent px-3.5 py-1.5 text-[12px] font-medium text-white transition hover:brightness-110"
              >
                {t.openApp}
              </Link>
            )}
          </div>
        </div>
      </nav>

      <main>
        {/* Hero */}
        <section className="bg-black pt-24 text-center text-[#f5f5f7]">
          <div className="px-4">
            <h1 className="mx-auto text-[clamp(56px,7.5vw,104px)] font-semibold text-balance leading-[1.03] tracking-[-0.035em]">
              {t.hero.title[0]}
              <br />
              {t.hero.title[1]}
            </h1>
            <p className="mx-auto mt-8 max-w-[700px] text-[22px] text-balance leading-[1.45] text-[#a1a1a6]">
              {t.hero.sub}
            </p>
            <div className="mt-[38px] flex items-center justify-center gap-[30px]">
              <a
                href="#deploiement"
                className="rounded-full bg-accent px-[23px] py-[11px] text-[16px] text-white transition hover:brightness-110"
              >
                {t.hero.deploy}
              </a>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="text-[16px] text-accent-sky hover:underline"
              >
                {t.hero.repo}
              </a>
            </div>
          </div>

          {/* The hero demo window: a looping simulation of the product
              (question typed, answer streamed, sources panel opened). */}
          <div id="citations" className="scroll-mt-16 px-4">
            <HeroDemo key={lang} copy={t.demo} />
          </div>
        </section>

        {/* Sovereignty */}
        <section id="souverainete" className="scroll-mt-16 bg-white py-[124px]">
          <div className="mx-auto max-w-[1024px] px-6">
            <div className="text-center">
              <p className="text-[19px] font-semibold text-accent">{t.sovereignty.eyebrow}</p>
              <h2 className="mt-3 text-[clamp(40px,5.5vw,72px)] font-semibold text-balance leading-[1.06] tracking-[-0.032em]">
                {t.sovereignty.title[0]}
                <br />
                {t.sovereignty.title[1]}
              </h2>
              <p className="mx-auto mt-[26px] max-w-[640px] text-[20px] text-balance leading-[1.5] text-ink-tertiary">
                {t.sovereignty.sub}
              </p>
            </div>
            <div className="mt-16 grid gap-5 md:grid-cols-[1.35fr_1fr]">
              <div className="rounded-[26px] bg-surface px-10 pt-9 pb-[30px]">
                <p className="text-[14.5px] font-medium text-ink-tertiary">
                  {t.sovereignty.residencyTitle}
                </p>
                {t.sovereignty.rows.map((row, index) => (
                  <div
                    key={row.name}
                    className={`grid grid-cols-[1fr_auto] items-center gap-[18px] ${
                      index === 0
                        ? "border-b border-black/[0.09] pt-5 pb-4"
                        : index === 1
                          ? "border-b border-black/[0.09] py-4"
                          : "pt-4"
                    }`}
                  >
                    <div>
                      <p className="text-[18px] font-medium">
                        {row.name}
                        {row.tag !== "" && (
                          <span className="ml-1.5 text-[12.5px] font-normal text-muted">
                            {row.tag}
                          </span>
                        )}
                      </p>
                      <p className="mt-[3px] text-[13px] text-muted">{row.detail}</p>
                    </div>
                    <p
                      className={`text-[14.5px] font-medium ${row.ok ? "text-ok" : "text-warn"}`}
                    >
                      {row.verdict}
                    </p>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-5">
                <div className="flex flex-1 flex-col justify-center rounded-[26px] bg-surface px-9 py-[34px]">
                  <p className="text-[88px] font-semibold leading-none tracking-[-0.045em]">0</p>
                  <p className="mt-3 text-[15.5px] leading-[1.45] text-ink-tertiary">
                    {t.sovereignty.zeroCaption}
                  </p>
                </div>
                <div className="rounded-[26px] bg-black px-9 py-8 text-[#f5f5f7]">
                  <p className="font-mono text-[16px] text-accent-sky">docker compose up</p>
                  <p className="mt-3 text-[15px] leading-[1.45] text-[#98989d]">
                    {t.sovereignty.composeCaption}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Verifiability */}
        <section className="bg-black py-[124px] text-[#f5f5f7]">
          <div className="mx-auto max-w-[1024px] px-6 text-center">
            <p className="text-[19px] font-semibold text-accent-sky">{t.verifiability.eyebrow}</p>
            <h2 className="mt-3 text-[clamp(40px,5.5vw,72px)] font-semibold text-balance leading-[1.06] tracking-[-0.032em]">
              {t.verifiability.title[0]}
              <br />
              {t.verifiability.title[1]}
            </h2>
            <p className="mx-auto mt-[26px] max-w-[620px] text-[20px] text-balance leading-[1.5] text-[#98989d]">
              {t.verifiability.sub}
            </p>
            <div className="mt-14 grid items-center gap-[46px] rounded-[26px] bg-white px-12 py-[46px] text-left text-ink md:grid-cols-[1fr_330px]">
              <div>
                <p className="text-[26px] text-pretty leading-[1.6]">
                  {t.verifiability.quoteBefore}
                  <span className="mx-[5px] inline-block -translate-y-1 rounded-lg bg-accent px-2 font-mono text-[15px] font-medium leading-[25px] text-white">
                    1
                  </span>
                  {t.verifiability.quoteAfter}
                </p>
                <div className="mt-7 flex items-center gap-3 text-[13.5px] text-muted">
                  <svg width="44" height="10" viewBox="0 0 44 10" aria-hidden="true">
                    <path
                      d="M0 5h38M34 1l4 4-4 4"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.2"
                    />
                  </svg>
                  <span>{t.verifiability.arrowCaption}</span>
                </div>
                <div className="mt-[34px] flex gap-[34px] border-t border-black/[0.09] pt-[22px]">
                  {t.verifiability.stats.map((stat) => (
                    <div key={stat.value}>
                      <p className="text-[25px] font-semibold">{stat.value}</p>
                      <p className="mt-1 text-[12.5px] text-muted">{stat.caption}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-[18px] bg-surface px-6 py-[22px]">
                <div className="flex items-baseline justify-between">
                  <span className="text-[13.5px] font-medium">{t.verifiability.card.filename}</span>
                  <span className="font-mono text-[11px] text-muted">
                    {t.verifiability.card.score}
                  </span>
                </div>
                <p className="mt-1 text-[12px] text-muted">{t.verifiability.card.where}</p>
                <p className="mt-3 text-[13.5px] leading-[1.65] text-ink-secondary">
                  {t.verifiability.card.excerpt}
                </p>
                <div className="mt-[18px] flex items-center gap-2.5">
                  <span className="relative h-1 flex-1 rounded-[2px] bg-black/10">
                    <span
                      className="absolute inset-0 rounded-[2px] bg-accent"
                      style={{ width: "83%" }}
                    />
                  </span>
                  <span className="font-mono text-[11px] text-muted">
                    {t.verifiability.card.ranks}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Measured */}
        <section id="mesures" className="scroll-mt-16 bg-white py-[118px]">
          <div className="mx-auto max-w-[1024px] px-6">
            <h2 className="text-center text-[clamp(36px,4.7vw,60px)] font-semibold leading-[1.08] tracking-[-0.03em]">
              {t.measures.title}
            </h2>
            <p className="mx-auto mt-5 max-w-[580px] text-center text-[19px] text-balance leading-[1.5] text-ink-tertiary">
              {t.measures.sub}
            </p>
            <div className="mt-[70px] grid grid-cols-1 gap-10 lg:grid-cols-4 lg:gap-0">
              {t.measures.stats.map((stat, index) => (
                <div
                  key={stat.caption}
                  className={
                    index === 0
                      ? "lg:border-r lg:border-black/[0.09] lg:pr-7"
                      : index === 3
                        ? "lg:pl-7"
                        : "lg:border-r lg:border-black/[0.09] lg:px-7"
                  }
                >
                  <p className="text-[66px] font-semibold leading-none tracking-[-0.04em]">
                    {stat.value}
                    {stat.unit !== undefined && <span className="text-[34px]">{stat.unit}</span>}
                  </p>
                  <p className="mt-3.5 text-[14.5px] leading-[1.45] text-ink-tertiary">
                    {stat.caption}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Compliance */}
        <section id="conformite" className="scroll-mt-16 bg-surface py-[110px]">
          <div className="mx-auto grid max-w-[1024px] items-center gap-14 px-6 md:grid-cols-2">
            <div>
              <p className="text-[19px] font-semibold text-accent">{t.compliance.eyebrow}</p>
              <h2 className="mt-3 text-[clamp(34px,4vw,52px)] font-semibold leading-[1.08] tracking-[-0.03em]">
                {t.compliance.title[0]}
                <br />
                {t.compliance.title[1]}
              </h2>
              <p className="mt-[22px] text-[18px] text-pretty leading-[1.55] text-ink-tertiary">
                {t.compliance.body}
              </p>
              <a
                href={COMPLIANCE_URL}
                target="_blank"
                rel="noreferrer"
                className="mt-7 inline-block text-[15.5px] text-link hover:underline"
              >
                {t.compliance.cta}
              </a>
            </div>
            <div className="rounded-[22px] bg-white px-8 py-[30px] shadow-[0_12px_40px_rgba(0,0,0,0.09)]">
              <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-[18px] gap-y-3.5">
                {t.compliance.rows.map((row) => (
                  <div key={row.ref} className="contents">
                    <dt className="font-mono text-[12px] font-medium text-link">{row.ref}</dt>
                    <dd className="text-[14px] leading-[1.45]">{row.text}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-6 border-t border-black/[0.09] pt-4 text-[12px] text-muted">
                {t.compliance.footer}
              </p>
            </div>
          </div>
        </section>

        {/* Deploy */}
        <section
          id="deploiement"
          className="scroll-mt-16 bg-black px-4 pt-[112px] pb-[120px] text-center text-[#f5f5f7]"
        >
          <p className="text-[19px] font-semibold text-accent-sky">{t.deploy.eyebrow}</p>
          <h2 className="mt-3.5 font-mono text-[clamp(28px,4.4vw,56px)] font-semibold leading-[1.1] tracking-[-0.035em]">
            <span className="text-ink-tertiary">$</span> docker compose up
          </h2>
          <p className="mx-auto mt-[22px] max-w-[520px] text-[18px] leading-[1.55] text-[#98989d]">
            {t.deploy.sub}
          </p>
          <div className="mx-auto mt-[46px] max-w-[620px] overflow-hidden rounded-2xl bg-[#161617] text-left">
            <div className="flex gap-[7px] border-b border-[#2c2c2e] px-4 py-[13px]">
              <span className="h-2.5 w-2.5 rounded-full bg-[#3a3a3c]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#3a3a3c]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#3a3a3c]" />
            </div>
            <div className="overflow-x-auto px-6 py-5 font-mono text-[13px] leading-[2.05] text-[#d8d8dc]">
              <p>
                <span className="text-ink-tertiary">$</span> git clone
                github.com/Leroy-Guillaume/sovereign-rag
              </p>
              <p>
                <span className="text-ink-tertiary">$</span> cp .env.example .env
              </p>
              <p>
                <span className="text-ink-tertiary">$</span> docker compose up --build
              </p>
              <p className="text-ink-tertiary">{t.deploy.comment}</p>
            </div>
          </div>
          <a
            href={README_URL}
            target="_blank"
            rel="noreferrer"
            className="mt-8 inline-block text-[15.5px] text-accent-sky hover:underline"
          >
            {t.deploy.cta}
          </a>
        </section>
      </main>

      <footer className="flex justify-center bg-white px-6 pt-[34px] pb-10">
        <div className="w-full max-w-[1024px]">
          <p className="border-b border-black/[0.09] pb-3.5 text-[11px] leading-[1.75] text-muted">
            {t.footer.finePrint}
          </p>
          <div className="flex flex-wrap justify-between gap-2 pt-3.5 text-[12px] text-ink-tertiary">
            <span>{t.footer.left}</span>
            <span>
              <a href={REPO_URL} target="_blank" rel="noreferrer" className="hover:underline">
                GitHub
              </a>
              {" · "}
              <a href="#conformite" className="hover:underline">
                {t.footer.conformity}
              </a>
              {t.footer.tail}
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
