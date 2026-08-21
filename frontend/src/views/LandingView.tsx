import { Link, Navigate, useSearchParams } from "react-router";
import HeroDemo from "../components/HeroDemo";

const REPO_URL = "https://github.com/Leroy-Guillaume/sovereign-rag";
const COMPLIANCE_URL = REPO_URL + "/blob/main/COMPLIANCE.md";
const README_URL = REPO_URL + "/blob/main/README.md";

const NAV_LINKS = [
  { label: "Souveraineté", href: "#souverainete" },
  { label: "Citations", href: "#citations" },
  { label: "Mesures", href: "#mesures" },
  { label: "Conformité", href: "#conformite" },
  { label: "Déploiement", href: "#deploiement" },
];

export default function LandingView() {
  const [searchParams] = useSearchParams();
  // The chat used to live at "/" with conversations addressed as /?c=<id>.
  // Redirect so old bookmarks keep working.
  const legacyConversationId = searchParams.get("c");
  if (legacyConversationId !== null) {
    return (
      <Navigate
        to={"/chat?c=" + encodeURIComponent(legacyConversationId)}
        replace
      />
    );
  }

  return (
    <div className="bg-white font-sans text-ink">
      <nav className="sticky top-0 z-50 flex justify-center bg-black/80 backdrop-blur">
        <div className="flex h-11 w-full max-w-[1024px] items-center justify-between px-4 text-[#f5f5f7]">
          <span className="text-[13px] font-semibold tracking-[-0.01em]">
            sovereign-rag
          </span>
          <div className="hidden gap-[30px] md:flex">
            {NAV_LINKS.map(({ label, href }) => (
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
            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer"
              className="text-[12px] opacity-85 transition-opacity hover:opacity-100"
            >
              GitHub
            </a>
            <Link
              to="/chat"
              className="rounded-full bg-accent px-3.5 py-1.5 text-[12px] font-medium text-white transition hover:brightness-110"
            >
              Ouvrir l'app
            </Link>
          </div>
        </div>
      </nav>

      <main>
        {/* Hero */}
        <section className="bg-black pt-24 text-center text-[#f5f5f7]">
          <div className="px-4">
            <h1 className="mx-auto text-balance text-[clamp(56px,7.5vw,104px)] font-semibold leading-[1.03] tracking-[-0.035em]">
              Vos documents<br />restent chez vous.
            </h1>
            <p className="mx-auto mt-8 max-w-[700px] text-balance text-[22px] leading-[1.45] text-[#a1a1a6]">
              Un assistant qui répond à partir de vos corpus réglementaires en
              citant chaque passage. Modèle local, embeddings locaux, PostgreSQL
              chez vous.
            </p>
            <div className="mt-[38px] flex items-center justify-center gap-[30px]">
              <a
                href="#deploiement"
                className="rounded-full bg-accent px-[23px] py-[11px] text-[16px] text-white transition hover:brightness-110"
              >
                Déployer en local
              </a>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="text-[16px] text-accent-sky hover:underline"
              >
                Voir le dépôt ›
              </a>
            </div>
          </div>

          {/* The hero demo window: a looping simulation of the product
              (question typed, answer streamed, sources panel opened). */}
          <div id="citations" className="scroll-mt-16 px-4">
            <HeroDemo />
          </div>
        </section>

        {/* Souveraineté */}
        <section id="souverainete" className="scroll-mt-16 bg-white py-[124px]">
          <div className="mx-auto max-w-[1024px] px-6">
            <div className="text-center">
              <p className="text-[19px] font-semibold text-accent">
                Souveraineté
              </p>
              <h2 className="mt-3 text-balance text-[clamp(40px,5.5vw,72px)] font-semibold leading-[1.06] tracking-[-0.032em]">
                Zéro appel sortant.<br />Par construction.
              </h2>
              <p className="mx-auto mt-[26px] max-w-[640px] text-balance text-[20px] leading-[1.5] text-ink-tertiary">
                Le profil local est le profil par défaut : aucune clé externe,
                aucun réseau sortant, des images qui fonctionnent hors ligne.
              </p>
            </div>
            <div className="mt-16 grid gap-5 md:grid-cols-[1.35fr_1fr]">
              <div className="rounded-[26px] bg-surface px-10 pb-[30px] pt-9">
                <p className="text-[14.5px] font-medium text-ink-tertiary">
                  Résidence des données
                </p>
                <div className="grid grid-cols-[1fr_auto] items-center gap-[18px] border-b border-black/[0.09] pb-4 pt-5">
                  <div>
                    <p className="text-[18px] font-medium">
                      Profil local
                      {" "}
                      <span className="text-[12.5px] font-normal text-muted">par défaut</span>
                    </p>
                    <p className="mt-[3px] text-[13px] text-muted">
                      Ollama qwen3:4b · embeddings e5 · PostgreSQL
                    </p>
                  </div>
                  <p className="text-[14.5px] font-medium text-ok">
                    Rien ne sort
                  </p>
                </div>
                <div className="grid grid-cols-[1fr_auto] items-center gap-[18px] border-b border-black/[0.09] py-4">
                  <div>
                    <p className="text-[18px] font-medium">
                      Profil hybride
                      {" "}
                      <span className="text-[12.5px] font-normal text-muted">désactivé</span>
                    </p>
                    <p className="mt-[3px] text-[13px] text-muted">
                      Embeddings locaux, génération déléguée
                    </p>
                  </div>
                  <p className="text-[14.5px] font-medium text-warn">
                    Prompt seul
                  </p>
                </div>
                <div className="grid grid-cols-[1fr_auto] items-center gap-[18px] pt-4">
                  <div>
                    <p className="text-[18px] font-medium">Télémétrie</p>
                    <p className="mt-[3px] text-[13px] text-muted">
                      Aucun collecteur, aucun compte distant
                    </p>
                  </div>
                  <p className="text-[14.5px] font-medium text-ok">Néant</p>
                </div>
              </div>
              <div className="flex flex-col gap-5">
                <div className="flex flex-1 flex-col justify-center rounded-[26px] bg-surface px-9 py-[34px]">
                  <p className="text-[88px] font-semibold leading-none tracking-[-0.045em]">
                    0
                  </p>
                  <p className="mt-3 text-[15.5px] leading-[1.45] text-ink-tertiary">
                    appel réseau sortant sur le profil local : modèles embarqués
                    dans l'image, hors ligne par construction.
                  </p>
                </div>
                <div className="rounded-[26px] bg-black px-9 py-8 text-[#f5f5f7]">
                  <p className="font-mono text-[16px] text-accent-sky">
                    docker compose up
                  </p>
                  <p className="mt-3 text-[15px] leading-[1.45] text-[#98989d]">
                    Images publiées sur GHCR à chaque merge sur main.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Vérifiabilité */}
        <section className="bg-black py-[124px] text-[#f5f5f7]">
          <div className="mx-auto max-w-[1024px] px-6 text-center">
            <p className="text-[19px] font-semibold text-accent-sky">
              Vérifiabilité
            </p>
            <h2 className="mt-3 text-balance text-[clamp(40px,5.5vw,72px)] font-semibold leading-[1.06] tracking-[-0.032em]">
              Chaque phrase ramène<br />à son passage.
            </h2>
            <p className="mx-auto mt-[26px] max-w-[620px] text-balance text-[20px] leading-[1.5] text-[#98989d]">
              Ouvrez un marqueur : l'extrait exact, sa section, son score, la
              jambe de recherche qui l'a trouvé.
            </p>
            <div className="mt-14 grid items-center gap-[46px] rounded-[26px] bg-white px-12 py-[46px] text-left text-ink md:grid-cols-[1fr_330px]">
              <div>
                <p className="text-pretty text-[26px] leading-[1.6]">
                  « …une sécurité adaptée au risque
                  <span className="mx-[5px] inline-block -translate-y-1 rounded-lg bg-accent px-2 font-mono text-[15px] font-medium leading-[25px] text-white">1</span> » (art. 8 al. 1 nLPD)
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
                  <span>le passage tel qu'il est indexé, jamais reformulé</span>
                </div>
                <div className="mt-[34px] flex gap-[34px] border-t border-black/[0.09] pt-[22px]">
                  <div>
                    <p className="text-[25px] font-semibold">16 / 16</p>
                    <p className="mt-1 text-[12.5px] text-muted">
                      questions pièges sans invention
                    </p>
                  </div>
                  <div>
                    <p className="text-[25px] font-semibold">№f3a1</p>
                    <p className="mt-1 text-[12.5px] text-muted">
                      audit conservé après suppression
                    </p>
                  </div>
                </div>
              </div>
              <div className="rounded-[18px] bg-surface px-6 py-[22px]">
                <div className="flex items-baseline justify-between">
                  <span className="text-[13.5px] font-medium">
                    nlpd-excerpt.fr.md
                  </span>
                  <span className="font-mono text-[11px] text-muted">
                    0,0332
                  </span>
                </div>
                <p className="mt-1 text-[12px] text-muted">
                  Art. 8 · Sécurité des données · FR
                </p>
                <p className="mt-3 text-[13.5px] leading-[1.65] text-ink-secondary">
                  « Le responsable du traitement et le sous-traitant doivent
                  assurer, par des mesures organisationnelles et techniques
                  appropriées, une sécurité adaptée au risque. »
                </p>
                <div className="mt-[18px] flex items-center gap-2.5">
                  <span className="relative h-1 flex-1 rounded-[2px] bg-black/10">
                    <span
                      className="absolute inset-0 rounded-[2px] bg-accent"
                      style={{ width: "83%" }}
                    />
                  </span>
                  <span className="font-mono text-[11px] text-muted">
                    vect 1 · txt 2
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Mesures */}
        <section id="mesures" className="scroll-mt-16 bg-white py-[118px]">
          <div className="mx-auto max-w-[1024px] px-6">
            <h2 className="text-center text-[clamp(36px,4.7vw,60px)] font-semibold leading-[1.08] tracking-[-0.03em]">
              Mesuré, pas promis.
            </h2>
            <p className="mx-auto mt-5 max-w-[580px] text-balance text-center text-[19px] leading-[1.5] text-ink-tertiary">
              Banc d'évaluation juridique multilingue rejoué à chaque version,
              protocole publié avec les résultats.
            </p>
            <div className="mt-[70px] grid grid-cols-1 gap-10 lg:grid-cols-4 lg:gap-0">
              <div className="lg:border-r lg:border-black/[0.09] lg:pr-7">
                <p className="text-[66px] font-semibold leading-none tracking-[-0.04em]">
                  96<span className="text-[34px]"> %</span>
                </p>
                <p className="mt-3.5 text-[14.5px] leading-[1.45] text-ink-tertiary">
                  de rappel à 8 sources sur 159 questions FR, DE, EN
                </p>
              </div>
              <div className="lg:border-r lg:border-black/[0.09] lg:px-7">
                <p className="text-[66px] font-semibold leading-none tracking-[-0.04em]">
                  0,775
                </p>
                <p className="mt-3.5 text-[14.5px] leading-[1.45] text-ink-tertiary">
                  MRR : la bonne source arrive en tête
                </p>
              </div>
              <div className="lg:border-r lg:border-black/[0.09] lg:px-7">
                <p className="text-[66px] font-semibold leading-none tracking-[-0.04em]">
                  2,4<span className="text-[34px]"> s</span>
                </p>
                <p className="mt-3.5 text-[14.5px] leading-[1.45] text-ink-tertiary">
                  de re-classement par réponse, sur CPU
                </p>
              </div>
              <div className="lg:pl-7">
                <p className="text-[66px] font-semibold leading-none tracking-[-0.04em]">
                  9 246
                </p>
                <p className="mt-3.5 text-[14.5px] leading-[1.45] text-ink-tertiary">
                  passages indexés : RGPD, AI Act, NIS2, DORA, eIDAS, LPD,
                  ISO 27001
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Conformité */}
        <section id="conformite" className="scroll-mt-16 bg-surface py-[110px]">
          <div className="mx-auto grid max-w-[1024px] items-center gap-14 px-6 md:grid-cols-2">
            <div>
              <p className="text-[19px] font-semibold text-accent">
                Conformité
              </p>
              <h2 className="mt-3 text-[clamp(34px,4vw,52px)] font-semibold leading-[1.08] tracking-[-0.03em]">
                Article par article,<br />dans un document public.
              </h2>
              <p className="mt-[22px] text-pretty text-[18px] leading-[1.55] text-ink-tertiary">
                Chaque exigence est mise en regard du mécanisme qui la
                satisfait, avec le fichier de code correspondant. Vos auditeurs
                lisent la même page que vos développeurs.
              </p>
              <a
                href={COMPLIANCE_URL}
                target="_blank"
                rel="noreferrer"
                className="mt-7 inline-block text-[15.5px] text-link hover:underline"
              >
                Lire COMPLIANCE.md ›
              </a>
            </div>
            <div className="rounded-[22px] bg-white px-8 py-[30px] shadow-[0_12px_40px_rgba(0,0,0,0.09)]">
              <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-[18px] gap-y-3.5">
                <dt className="font-mono text-[12px] font-medium text-link">
                  ISO A.5.15
                </dt>
                <dd className="text-[14px] leading-[1.45]">
                  Contrôle d'accès par liste, privé par défaut, révocable
                </dd>
                <dt className="font-mono text-[12px] font-medium text-link">
                  ISO A.5.28
                </dt>
                <dd className="text-[14px] leading-[1.45]">
                  Instantané d'audit de chaque réponse, conservé après
                  suppression du document
                </dd>
                <dt className="font-mono text-[12px] font-medium text-link">
                  ISO A.8.12
                </dt>
                <dd className="text-[14px] leading-[1.45]">
                  Fuite de données : aucun chemin sortant sur le profil local
                </dd>
                <dt className="font-mono text-[12px] font-medium text-link">
                  nLPD art. 7
                </dt>
                <dd className="text-[14px] leading-[1.45]">
                  Protection dès la conception : profil local par défaut
                </dd>
                <dt className="font-mono text-[12px] font-medium text-link">
                  nLPD art. 8
                </dt>
                <dd className="text-[14px] leading-[1.45]">
                  Comparaison de clés en temps constant, conteneurs non root,
                  scan CVE en CI
                </dd>
                <dt className="font-mono text-[12px] font-medium text-link">
                  LIPAD
                </dt>
                <dd className="text-[14px] leading-[1.45]">
                  Reconstituer ce qui a été montré, d'après quel document, et
                  quand
                </dd>
              </dl>
              <p className="mt-6 border-t border-black/[0.09] pt-4 text-[12px] text-muted">
                Statuts honnêtes, implémenté ou feuille de route · dernière
                revue 21.08.2026
              </p>
            </div>
          </div>
        </section>

        {/* Déploiement */}
        <section
          id="deploiement"
          className="scroll-mt-16 bg-black px-4 pb-[120px] pt-[112px] text-center text-[#f5f5f7]"
        >
          <p className="text-[19px] font-semibold text-accent-sky">
            Pour les évaluateurs
          </p>
          <h2 className="mt-3.5 font-mono text-[clamp(28px,4.4vw,56px)] font-semibold leading-[1.1] tracking-[-0.035em]">
            <span className="text-ink-tertiary">$</span> docker compose up
          </h2>
          <p className="mx-auto mt-[22px] max-w-[520px] text-[18px] leading-[1.55] text-[#98989d]">
            Le dépôt est public. Trois conteneurs, un fichier compose, une clé
            de démonstration : la stack tourne en quelques minutes.
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
                <span className="text-ink-tertiary">$</span> cp .env.example
                .env
              </p>
              <p>
                <span className="text-ink-tertiary">$</span> docker compose up
                --build
              </p>
              <p className="text-ink-tertiary">
                # clé de démonstration sk-demo · premier lancement ~2,6 GB
              </p>
            </div>
          </div>
          <a
            href={README_URL}
            target="_blank"
            rel="noreferrer"
            className="mt-8 inline-block text-[15.5px] text-accent-sky hover:underline"
          >
            Lire le guide de déploiement ›
          </a>
        </section>
      </main>

      <footer className="flex justify-center bg-white px-6 pb-10 pt-[34px]">
        <div className="w-full max-w-[1024px]">
          <p className="border-b border-black/[0.09] pb-3.5 text-[11px] leading-[1.75] text-muted">
            Les chiffres proviennent du banc d'évaluation public (175 questions
            juridiques FR, DE, EN) exécuté sur le profil local : Ollama,
            embeddings multilingues, reranker sur CPU, PostgreSQL 16 avec
            pgvector. La correspondance article par article avec ISO 27001, la
            nLPD et la LIPAD est documentée dans COMPLIANCE.md. Le produit ne
            remplace pas l'analyse juridique : il retrouve et cite les passages
            applicables.
          </p>
          <div className="flex flex-wrap justify-between gap-2 pt-3.5 text-[12px] text-ink-tertiary">
            <span>sovereign-rag · RAG souverain pour organisations régulées</span>
            <span>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="hover:underline"
              >
                GitHub
              </a>
              {" · "}
              <a href="#conformite" className="hover:underline">
                Conformité
              </a>
              {" · Apache-2.0 · FR / DE / EN"}
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
