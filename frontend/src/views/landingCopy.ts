// All landing copy in both languages. The landing defaults to English and
// the choice persists locally; the app screens stay French for now.

export type Lang = "en" | "fr" | "de";

export const LANGS: Lang[] = ["en", "fr", "de"];

export const LANG_STORAGE = "sovereign-rag.lang";

export interface HeroDemoCopy {
  windowTitle: string;
  question: string;
  /** The streamed answer, split around its citation chips. */
  answer: { text?: string; chip?: string }[];
  sourcesLabel: string;
  meta: string;
  panelHeading: string;
  composer: string;
  composerAria: string;
  /** Source documents stay in their corpus language on purpose: asking in
      English against French and German law is the measured cross-lingual
      strength of the retrieval stack. */
  sources: { filename: string; score: string; where: string; excerpt: string }[];
}

interface ResidencyRow {
  name: string;
  tag: string;
  detail: string;
  verdict: string;
  ok: boolean;
}

export interface LandingCopy {
  navLinks: { label: string; href: string }[];
  openApp: string;
  hero: { title: [string, string]; sub: string; deploy: string; repo: string };
  demo: HeroDemoCopy;
  sovereignty: {
    eyebrow: string;
    title: [string, string];
    sub: string;
    residencyTitle: string;
    rows: ResidencyRow[];
    zeroCaption: string;
    composeCaption: string;
  };
  verifiability: {
    eyebrow: string;
    title: [string, string];
    sub: string;
    quoteBefore: string;
    quoteAfter: string;
    arrowCaption: string;
    stats: { value: string; caption: string }[];
    card: { filename: string; score: string; where: string; excerpt: string; ranks: string };
  };
  measures: {
    title: string;
    sub: string;
    stats: { value: string; unit?: string; caption: string }[];
  };
  compliance: {
    eyebrow: string;
    title: [string, string];
    body: string;
    cta: string;
    rows: { ref: string; text: string }[];
    footer: string;
  };
  deploy: {
    eyebrow: string;
    sub: string;
    comment: string;
    cta: string;
  };
  footer: { finePrint: string; left: string; conformity: string; tail: string };
}

const DEMO_SOURCES_FR = [
  {
    filename: "nlpd-excerpt.fr.md",
    score: "0,033",
    where: "Art. 8 · Sécurité des données",
    excerpt:
      "« …doivent assurer, par des mesures organisationnelles et techniques appropriées, une sécurité adaptée au risque… »",
  },
  {
    filename: "dsg-auszug.de.md",
    score: "0,030",
    where: "Art. 8 DSG · Datensicherheit",
    excerpt: "« Der Verantwortliche gewährleistet eine dem Risiko angemessene Datensicherheit… »",
  },
];

export const LANDING_COPY: Record<Lang, LandingCopy> = {
  en: {
    navLinks: [
      { label: "Sovereignty", href: "#souverainete" },
      { label: "Citations", href: "#citations" },
      { label: "Measured", href: "#mesures" },
      { label: "Compliance", href: "#conformite" },
      { label: "Deploy", href: "#deploiement" },
    ],
    openApp: "Open the app",
    hero: {
      title: ["Your documents", "never leave home."],
      sub: "An assistant that answers from your regulatory corpora and cites every passage. Local model, local embeddings, PostgreSQL on your side of the wall.",
      deploy: "Deploy locally",
      repo: "View the repository ›",
    },
    demo: {
      windowTitle: "Security obligations, Swiss nLPD",
      question: "What are the security obligations under the Swiss nLPD?",
      answer: [
        {
          text: "The controller and the processor must ensure, through appropriate organisational and technical measures, a level of data security appropriate to the risk",
        },
        { chip: "1" },
        { text: " (art. 8 para. 1 nLPD). These measures must prevent any breach of data security" },
        { chip: "2" },
        { text: "." },
      ],
      sourcesLabel: "Sources",
      meta: "2.4 s · asked in EN, sources in FR and DE · audit kept",
      panelHeading: "SOURCES",
      composer: "Ask about your own documents…",
      composerAria: "Open the chat",
      sources: DEMO_SOURCES_FR,
    },
    sovereignty: {
      eyebrow: "Sovereignty",
      title: ["Zero outbound calls.", "By construction."],
      sub: "The local profile is the default: no external key, no outbound network, images that run offline.",
      residencyTitle: "Data residency",
      rows: [
        {
          name: "Local profile",
          tag: "default",
          detail: "Ollama qwen3:4b · e5 embeddings · PostgreSQL",
          verdict: "Nothing leaves",
          ok: true,
        },
        {
          name: "Hybrid profile",
          tag: "disabled",
          detail: "Local embeddings, delegated generation",
          verdict: "Prompt only",
          ok: false,
        },
        {
          name: "Telemetry",
          tag: "",
          detail: "No collector, no remote account",
          verdict: "None",
          ok: true,
        },
      ],
      zeroCaption:
        "outbound network calls on the local profile: models baked into the image, offline by construction.",
      composeCaption: "Images published to GHCR on every merge to main.",
    },
    verifiability: {
      eyebrow: "Verifiability",
      title: ["Every sentence leads", "back to its passage."],
      sub: "Open a marker: the exact excerpt, its section, its score, and the search leg that found it.",
      quoteBefore: "« …a level of security appropriate to the risk",
      quoteAfter: " » (art. 8 para. 1 nLPD)",
      arrowCaption: "the passage as indexed, never rephrased",
      stats: [
        { value: "16 / 16", caption: "trap questions answered without invention" },
        { value: "№f3a1", caption: "audit kept after document deletion" },
      ],
      card: {
        filename: "nlpd-excerpt.fr.md",
        score: "0,0332",
        where: "Art. 8 · Sécurité des données · FR",
        excerpt:
          "« Le responsable du traitement et le sous-traitant doivent assurer, par des mesures organisationnelles et techniques appropriées, une sécurité adaptée au risque. »",
        ranks: "vect 1 · txt 2",
      },
    },
    measures: {
      title: "Measured, not promised.",
      sub: "A multilingual legal evaluation bench replayed on every version, protocol published with the results.",
      stats: [
        { value: "96", unit: " %", caption: "recall at 8 sources over 159 questions in FR, DE, EN" },
        { value: "0.775", caption: "MRR: the right source comes first" },
        { value: "2.4", unit: " s", caption: "of reranking per answer, on CPU" },
        {
          value: "9,246",
          caption: "indexed passages: GDPR, AI Act, NIS2, DORA, eIDAS, FADP, ISO 27001",
        },
      ],
    },
    compliance: {
      eyebrow: "Compliance",
      title: ["Article by article,", "in a public document."],
      body: "Every requirement sits next to the mechanism that satisfies it, with the code file that implements it. Your auditors read the same page as your developers.",
      cta: "Read COMPLIANCE.md ›",
      rows: [
        { ref: "ISO A.5.15", text: "List-based access control, private by default, revocable" },
        {
          ref: "ISO A.5.28",
          text: "Audit snapshot of every answer, kept after document deletion",
        },
        { ref: "ISO A.8.12", text: "Data leakage: no outbound path on the local profile" },
        { ref: "nLPD art. 7", text: "Privacy by design: local profile as the default" },
        {
          ref: "nLPD art. 8",
          text: "Constant-time key comparison, non-root containers, CVE scan in CI",
        },
        { ref: "LIPAD", text: "Reconstruct what was shown, from which document, and when" },
      ],
      footer: "Honest statuses, implemented or roadmap · last review 21.08.2026",
    },
    deploy: {
      eyebrow: "For evaluators",
      sub: "The repository is public. Three containers, one compose file, one demo key: the stack runs in minutes.",
      comment: "# demo key sk-demo · first launch ~2.6 GB",
      cta: "Read the deployment guide ›",
    },
    footer: {
      finePrint:
        "The numbers come from the public evaluation bench (175 legal questions in FR, DE, EN) run on the local profile: Ollama, multilingual embeddings, CPU reranker, PostgreSQL 16 with pgvector. The article-by-article mapping to ISO 27001, the Swiss nLPD and the Geneva LIPAD is documented in COMPLIANCE.md. The product does not replace legal analysis: it retrieves and cites the applicable passages.",
      left: "sovereign-rag · sovereign RAG for regulated organizations",
      conformity: "Compliance",
      tail: " · Apache-2.0 · FR / DE / EN",
    },
  },
  fr: {
    navLinks: [
      { label: "Souveraineté", href: "#souverainete" },
      { label: "Citations", href: "#citations" },
      { label: "Mesures", href: "#mesures" },
      { label: "Conformité", href: "#conformite" },
      { label: "Déploiement", href: "#deploiement" },
    ],
    openApp: "Ouvrir l'app",
    hero: {
      title: ["Vos documents", "restent chez vous."],
      sub: "Un assistant qui répond à partir de vos corpus réglementaires en citant chaque passage. Modèle local, embeddings locaux, PostgreSQL chez vous.",
      deploy: "Déployer en local",
      repo: "Voir le dépôt ›",
    },
    demo: {
      windowTitle: "Obligations de sécurité nLPD",
      question: "Quelles sont les obligations de sécurité selon la nLPD ?",
      answer: [
        {
          text: "Le responsable du traitement et le sous-traitant doivent assurer, par des mesures organisationnelles et techniques appropriées, une sécurité adaptée au risque",
        },
        { chip: "1" },
        {
          text: " (art. 8 al. 1 nLPD). Ces mesures doivent éviter toute violation de la sécurité des données",
        },
        { chip: "2" },
        { text: "." },
      ],
      sourcesLabel: "Sources",
      meta: "2,4 s · audit conservé",
      panelHeading: "SOURCES",
      composer: "Posez votre question sur vos propres documents…",
      composerAria: "Accéder au chat",
      sources: DEMO_SOURCES_FR,
    },
    sovereignty: {
      eyebrow: "Souveraineté",
      title: ["Zéro appel sortant.", "Par construction."],
      sub: "Le profil local est le profil par défaut : aucune clé externe, aucun réseau sortant, des images qui fonctionnent hors ligne.",
      residencyTitle: "Résidence des données",
      rows: [
        {
          name: "Profil local",
          tag: "par défaut",
          detail: "Ollama qwen3:4b · embeddings e5 · PostgreSQL",
          verdict: "Rien ne sort",
          ok: true,
        },
        {
          name: "Profil hybride",
          tag: "désactivé",
          detail: "Embeddings locaux, génération déléguée",
          verdict: "Prompt seul",
          ok: false,
        },
        {
          name: "Télémétrie",
          tag: "",
          detail: "Aucun collecteur, aucun compte distant",
          verdict: "Néant",
          ok: true,
        },
      ],
      zeroCaption:
        "appel réseau sortant sur le profil local : modèles embarqués dans l'image, hors ligne par construction.",
      composeCaption: "Images publiées sur GHCR à chaque merge sur main.",
    },
    verifiability: {
      eyebrow: "Vérifiabilité",
      title: ["Chaque phrase ramène", "à son passage."],
      sub: "Ouvrez un marqueur : l'extrait exact, sa section, son score, la jambe de recherche qui l'a trouvé.",
      quoteBefore: "« …une sécurité adaptée au risque",
      quoteAfter: " » (art. 8 al. 1 nLPD)",
      arrowCaption: "le passage tel qu'il est indexé, jamais reformulé",
      stats: [
        { value: "16 / 16", caption: "questions pièges sans invention" },
        { value: "№f3a1", caption: "audit conservé après suppression" },
      ],
      card: {
        filename: "nlpd-excerpt.fr.md",
        score: "0,0332",
        where: "Art. 8 · Sécurité des données · FR",
        excerpt:
          "« Le responsable du traitement et le sous-traitant doivent assurer, par des mesures organisationnelles et techniques appropriées, une sécurité adaptée au risque. »",
        ranks: "vect 1 · txt 2",
      },
    },
    measures: {
      title: "Mesuré, pas promis.",
      sub: "Banc d'évaluation juridique multilingue rejoué à chaque version, protocole publié avec les résultats.",
      stats: [
        { value: "96", unit: " %", caption: "de rappel à 8 sources sur 159 questions FR, DE, EN" },
        { value: "0,775", caption: "MRR : la bonne source arrive en tête" },
        { value: "2,4", unit: " s", caption: "de re-classement par réponse, sur CPU" },
        {
          value: "9 246",
          caption: "passages indexés : RGPD, AI Act, NIS2, DORA, eIDAS, LPD, ISO 27001",
        },
      ],
    },
    compliance: {
      eyebrow: "Conformité",
      title: ["Article par article,", "dans un document public."],
      body: "Chaque exigence est mise en regard du mécanisme qui la satisfait, avec le fichier de code correspondant. Vos auditeurs lisent la même page que vos développeurs.",
      cta: "Lire COMPLIANCE.md ›",
      rows: [
        { ref: "ISO A.5.15", text: "Contrôle d'accès par liste, privé par défaut, révocable" },
        {
          ref: "ISO A.5.28",
          text: "Instantané d'audit de chaque réponse, conservé après suppression du document",
        },
        { ref: "ISO A.8.12", text: "Fuite de données : aucun chemin sortant sur le profil local" },
        { ref: "nLPD art. 7", text: "Protection dès la conception : profil local par défaut" },
        {
          ref: "nLPD art. 8",
          text: "Comparaison de clés en temps constant, conteneurs non root, scan CVE en CI",
        },
        { ref: "LIPAD", text: "Reconstituer ce qui a été montré, d'après quel document, et quand" },
      ],
      footer: "Statuts honnêtes, implémenté ou feuille de route · dernière revue 21.08.2026",
    },
    deploy: {
      eyebrow: "Pour les évaluateurs",
      sub: "Le dépôt est public. Trois conteneurs, un fichier compose, une clé de démonstration : la stack tourne en quelques minutes.",
      comment: "# clé de démonstration sk-demo · premier lancement ~2,6 GB",
      cta: "Lire le guide de déploiement ›",
    },
    footer: {
      finePrint:
        "Les chiffres proviennent du banc d'évaluation public (175 questions juridiques FR, DE, EN) exécuté sur le profil local : Ollama, embeddings multilingues, reranker sur CPU, PostgreSQL 16 avec pgvector. La correspondance article par article avec ISO 27001, la nLPD et la LIPAD est documentée dans COMPLIANCE.md. Le produit ne remplace pas l'analyse juridique : il retrouve et cite les passages applicables.",
      left: "sovereign-rag · RAG souverain pour organisations régulées",
      conformity: "Conformité",
      tail: " · Apache-2.0 · FR / DE / EN",
    },
  },
  de: {
    navLinks: [
      { label: "Souveränität", href: "#souverainete" },
      { label: "Zitate", href: "#citations" },
      { label: "Gemessen", href: "#mesures" },
      { label: "Compliance", href: "#conformite" },
      { label: "Deployment", href: "#deploiement" },
    ],
    openApp: "App öffnen",
    hero: {
      title: ["Ihre Dokumente", "bleiben bei Ihnen."],
      sub: "Ein Assistent, der aus Ihren regulatorischen Korpora antwortet und jede Passage zitiert. Lokales Modell, lokale Embeddings, PostgreSQL bei Ihnen.",
      deploy: "Lokal deployen",
      repo: "Zum Repository ›",
    },
    demo: {
      windowTitle: "Sicherheitspflichten nach DSG",
      question: "Welche Sicherheitspflichten sieht das Schweizer DSG vor?",
      answer: [
        {
          text: "Der Verantwortliche und der Auftragsbearbeiter müssen durch geeignete organisatorische und technische Massnahmen eine dem Risiko angemessene Datensicherheit gewährleisten",
        },
        { chip: "1" },
        {
          text: " (Art. 8 Abs. 1 DSG). Diese Massnahmen müssen Verletzungen der Datensicherheit vermeiden",
        },
        { chip: "2" },
        { text: "." },
      ],
      sourcesLabel: "Quellen",
      meta: "2.4 s · Audit aufbewahrt",
      panelHeading: "QUELLEN",
      composer: "Stellen Sie Ihre Frage zu Ihren eigenen Dokumenten…",
      composerAria: "Zum Chat",
      sources: DEMO_SOURCES_FR,
    },
    sovereignty: {
      eyebrow: "Souveränität",
      title: ["Null ausgehende Aufrufe.", "Konstruktionsbedingt."],
      sub: "Das lokale Profil ist der Standard: kein externer Schlüssel, kein ausgehender Netzwerkverkehr, Images, die offline funktionieren.",
      residencyTitle: "Datenresidenz",
      rows: [
        {
          name: "Lokales Profil",
          tag: "Standard",
          detail: "Ollama qwen3:4b · e5-Embeddings · PostgreSQL",
          verdict: "Nichts geht raus",
          ok: true,
        },
        {
          name: "Hybridprofil",
          tag: "deaktiviert",
          detail: "Lokale Embeddings, delegierte Generierung",
          verdict: "Nur der Prompt",
          ok: false,
        },
        {
          name: "Telemetrie",
          tag: "",
          detail: "Kein Collector, kein Remote-Konto",
          verdict: "Keine",
          ok: true,
        },
      ],
      zeroCaption:
        "ausgehende Netzwerkaufrufe im lokalen Profil: Modelle im Image eingebettet, offline konstruktionsbedingt.",
      composeCaption: "Images bei jedem Merge auf main auf GHCR veröffentlicht.",
    },
    verifiability: {
      eyebrow: "Nachprüfbarkeit",
      title: ["Jeder Satz führt", "zu seiner Passage."],
      sub: "Öffnen Sie einen Marker: der exakte Auszug, sein Abschnitt, sein Score und der Suchzweig, der ihn gefunden hat.",
      quoteBefore: "« …eine dem Risiko angemessene Datensicherheit",
      quoteAfter: " » (Art. 8 Abs. 1 DSG)",
      arrowCaption: "die Passage wie indexiert, nie umformuliert",
      stats: [
        { value: "16 / 16", caption: "Fangfragen ohne Erfindung beantwortet" },
        { value: "№f3a1", caption: "Audit bleibt nach Löschung erhalten" },
      ],
      card: {
        filename: "dsg-auszug.de.md",
        score: "0,0301",
        where: "Art. 8 DSG · Datensicherheit · DE",
        excerpt:
          "« Der Verantwortliche und der Auftragsbearbeiter gewährleisten durch geeignete technische und organisatorische Massnahmen eine dem Risiko angemessene Datensicherheit. »",
        ranks: "vect 3 · txt 1",
      },
    },
    measures: {
      title: "Gemessen, nicht versprochen.",
      sub: "Ein mehrsprachiger juristischer Evaluationsbench, bei jeder Version neu ausgeführt, Protokoll mit den Resultaten veröffentlicht.",
      stats: [
        { value: "96", unit: " %", caption: "Recall bei 8 Quellen über 159 Fragen in FR, DE, EN" },
        { value: "0.775", caption: "MRR: die richtige Quelle kommt zuerst" },
        { value: "2.4", unit: " s", caption: "Reranking pro Antwort, auf CPU" },
        {
          value: "9'246",
          caption: "indexierte Passagen: DSGVO, AI Act, NIS2, DORA, eIDAS, DSG, ISO 27001",
        },
      ],
    },
    compliance: {
      eyebrow: "Compliance",
      title: ["Artikel für Artikel,", "in einem öffentlichen Dokument."],
      body: "Jede Anforderung steht neben dem Mechanismus, der sie erfüllt, mit der zugehörigen Code-Datei. Ihre Auditoren lesen dieselbe Seite wie Ihre Entwickler.",
      cta: "COMPLIANCE.md lesen ›",
      rows: [
        {
          ref: "ISO A.5.15",
          text: "Listenbasierte Zugriffskontrolle, standardmässig privat, widerrufbar",
        },
        {
          ref: "ISO A.5.28",
          text: "Audit-Snapshot jeder Antwort, bleibt nach Löschung des Dokuments erhalten",
        },
        { ref: "ISO A.8.12", text: "Datenabfluss: kein ausgehender Pfad im lokalen Profil" },
        { ref: "DSG Art. 7", text: "Datenschutz durch Technik: lokales Profil als Standard" },
        {
          ref: "DSG Art. 8",
          text: "Schlüsselvergleich in konstanter Zeit, Non-Root-Container, CVE-Scan in der CI",
        },
        { ref: "LIPAD", text: "Rekonstruieren, was gezeigt wurde, aus welchem Dokument und wann" },
      ],
      footer: "Ehrliche Status, implementiert oder Roadmap · letzte Überprüfung 21.08.2026",
    },
    deploy: {
      eyebrow: "Für Evaluatoren",
      sub: "Das Repository ist öffentlich. Drei Container, eine Compose-Datei, ein Demo-Schlüssel: der Stack läuft in Minuten.",
      comment: "# Demo-Schlüssel sk-demo · erster Start ~2.6 GB",
      cta: "Deployment-Leitfaden lesen ›",
    },
    footer: {
      finePrint:
        "Die Zahlen stammen aus dem öffentlichen Evaluationsbench (175 juristische Fragen in FR, DE, EN), ausgeführt im lokalen Profil: Ollama, mehrsprachige Embeddings, CPU-Reranker, PostgreSQL 16 mit pgvector. Die artikelweise Zuordnung zu ISO 27001, dem Schweizer DSG und dem Genfer LIPAD ist in COMPLIANCE.md dokumentiert. Das Produkt ersetzt keine juristische Analyse: es findet und zitiert die anwendbaren Passagen.",
      left: "sovereign-rag · souveränes RAG für regulierte Organisationen",
      conformity: "Compliance",
      tail: " · Apache-2.0 · FR / DE / EN",
    },
  },
};

