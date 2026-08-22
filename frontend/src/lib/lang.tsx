import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// One language choice for the whole product (landing and app), persisted
// locally. English is the default; the value survives navigation between
// the public landing and the authenticated screens.

export type Lang = "en" | "fr" | "de";

export const LANGS: Lang[] = ["en", "fr", "de"];

export const LANG_STORAGE = "sovereign-rag.lang";

/** BCP 47 locale for number/date formatting per language (Swiss variants). */
export function localeOf(lang: Lang): string {
  return lang === "en" ? "en-GB" : lang === "fr" ? "fr-CH" : "de-CH";
}

export function storedLang(): Lang {
  const stored = localStorage.getItem(LANG_STORAGE);
  return LANGS.includes(stored as Lang) ? (stored as Lang) : "en";
}

interface LangState {
  lang: Lang;
  setLang: (lang: Lang) => void;
}

const LangContext = createContext<LangState | null>(null);

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(storedLang);

  useEffect(() => {
    localStorage.setItem(LANG_STORAGE, lang);
    document.documentElement.lang = lang;
  }, [lang]);

  const value = useMemo(
    () => ({
      lang,
      // Synchronous persist: formatters read storedLang() at render time and
      // must see the new value on the very next render, before the effect.
      setLang: (next: Lang) => {
        localStorage.setItem(LANG_STORAGE, next);
        setLang(next);
      },
    }),
    [lang],
  );
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang(): LangState {
  const state = useContext(LangContext);
  if (state === null) throw new Error("useLang requires a LangProvider ancestor");
  return state;
}

/** The compact EN / FR / DE toggle used in the app chrome. */
export function LangSwitcher({ className = "" }: { className?: string }) {
  const { lang, setLang } = useLang();
  return (
    <div className={`flex items-center gap-1.5 text-[11px] ${className}`}>
      {LANGS.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => setLang(option)}
          aria-pressed={lang === option}
          className={
            lang === option
              ? "font-semibold text-ink"
              : "text-muted transition-colors hover:text-ink-secondary"
          }
        >
          {option.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
