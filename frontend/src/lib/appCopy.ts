// All UI copy of the authenticated app (chat and admin) in the three product
// languages. The landing keeps its own dictionary (views/landingCopy.ts).

import type { Lang } from "./lang";

export interface AppCopy {
  modal: {
    title: string;
    bodyBefore: string;
    bodyAfter: string;
    save: string;
  };
  sidebar: {
    newConversation: string;
    today: string;
    yesterday: string;
    thisWeek: string;
    older: string;
    admin: string;
    offline: string;
  };
  brand: { backToSite: string };
  chat: {
    newConversation: string;
    emptyTitle: string;
    emptySub: string;
    searching: string;
    noAnswerTitle: string;
    noAnswerNote: (audit: string | null) => string;
    copy: string;
    copied: string;
    sources: string;
    hideSources: string;
    openSource: (n: number) => string;
    meta: (documents: number) => string;
    audit: string;
  };
  composer: {
    placeholder: string;
    hints: string;
    stop: string;
    send: string;
  };
  panel: {
    title: (answer: number) => string;
    subtitle: (passages: number, documents: number) => string;
    close: string;
    page: string;
    auditBefore: string;
    auditAfter: string;
    exportJson: string;
  };
  admin: {
    chatTab: string;
    adminTab: string;
    title: string;
    subtitle: (documents: number, passages: string) => string;
    lastAdded: string;
    day: string;
    upload: string;
    tiles: {
      answers: string;
      conversations: (n: string) => string;
      tokens: string;
      perAnswer: (n: string) => string;
      latency: string;
      retrieval: (p50: string, p95: string) => string;
      errors: string;
      errorPct: (pct: string) => string;
    };
    documents: string;
    refreshNote: string;
    dropHere: string;
    browse: string;
    dropNote: string;
    headers: { file: string; size: string; status: string; sharing: string; added: string };
    ready: string;
    passages: (n: string) => string;
    processing: string;
    failed: string;
    everyone: string;
    revoke: string;
    private: string;
    share: string;
    manage: string;
    remove: string;
    confirmDelete: (filename: string) => string;
    noShares: string;
    principalPlaceholder: string;
    add: string;
    shareAll: string;
    invalidPrincipal: string;
    empty: string;
    topCited: string;
    noCitations: string;
    unanswered: string;
    unansweredIntro: (n: string) => string;
    noUnanswered: string;
    checking: string;
    forbiddenTitle: string;
    forbiddenBefore: string;
    forbiddenAfter: string;
    errLoadMetrics: string;
    errLoadDocuments: string;
    errUpload: (name: string) => string;
    errDelete: string;
    errShare: string;
    errRevoke: string;
    errVerify: string;
  };
}

export const APP_COPY: Record<Lang, AppCopy> = {
  en: {
    modal: {
      title: "API key required",
      bodyBefore: "Paste one of the keys configured in ",
      bodyAfter:
        ". It stays in this browser's localStorage (demo authentication, OIDC lands in phase 2).",
      save: "Save the key",
    },
    sidebar: {
      newConversation: "New conversation",
      today: "Today",
      yesterday: "Yesterday",
      thisWeek: "This week",
      older: "Older",
      admin: "Administration",
      offline: "offline",
    },
    brand: { backToSite: "Back to the site" },
    chat: {
      newConversation: "New conversation",
      emptyTitle: "Ask a question.",
      emptySub: "Answers cite their passages, in FR, DE or EN.",
      searching: "Searching the document base…",
      noAnswerTitle: "The corpus cannot answer this.",
      noAnswerNote: (audit) =>
        "No relevant passage found. Rather than extrapolate, the system stops" +
        (audit !== null ? ` · the question stays on record (audit №${audit})` : "") +
        ".",
      copy: "Copy",
      copied: "Copied",
      sources: "Sources",
      hideSources: "Hide sources",
      openSource: (n) => `Open source ${n}`,
      meta: (d) => `${d} document${d > 1 ? "s" : ""} · RRF fusion`,
      audit: "audit",
    },
    composer: {
      placeholder: "Ask about the indexed documents…",
      hints: "⏎ send · ⇧⏎ new line · questions in FR, DE, EN",
      stop: "■ stop",
      send: "Send",
    },
    panel: {
      title: (n) => `Sources · answer ${n}`,
      subtitle: (p, d) =>
        `${p} passage${p > 1 ? "s" : ""} · ${d} document${d > 1 ? "s" : ""} · RRF fusion`,
      close: "Close the sources panel",
      page: "p.",
      auditBefore: "Audit snapshot",
      auditAfter: ": excerpts, scores and ranks are kept even if the document is deleted.",
      exportJson: "Export (json)",
    },
    admin: {
      chatTab: "Chat",
      adminTab: "Administration",
      title: "Documents and insight",
      subtitle: (docs, passages) =>
        `${docs} document${docs > 1 ? "s" : ""} · ${passages} indexed passages`,
      lastAdded: "last added",
      day: "d",
      upload: "Upload",
      tiles: {
        answers: "Answers",
        conversations: (n) => `${n} conversations`,
        tokens: "Prompt / completion tokens",
        perAnswer: (n) => `≈ ${n} tokens per answer`,
        latency: "Latency p50 / p95",
        retrieval: (p50, p95) => `retrieval ${p50} / ${p95}`,
        errors: "Errors",
        errorPct: (pct) => `${pct} % of answers`,
      },
      documents: "Documents",
      refreshNote: "statuses refresh every 2 s while processing",
      dropHere: "Drop your documents here, or ",
      browse: "browse",
      dropNote:
        "pdf · docx · md · txt · extracted, chunked and embedded on site, nothing is sent to a third party",
      headers: { file: "File", size: "Size", status: "Status", sharing: "Sharing", added: "Added" },
      ready: "ready",
      passages: (n) => `${n} passages`,
      processing: "processing",
      failed: "failed",
      everyone: "everyone (*)",
      revoke: "revoke",
      private: "private",
      share: "share",
      manage: "manage",
      remove: "delete",
      confirmDelete: (filename) =>
        `Delete ${filename}? Audit snapshots of past answers are kept.`,
      noShares: "No shares yet, this document is private.",
      principalPlaceholder: "user id, or * for everyone",
      add: "Add",
      shareAll: "Share with everyone (*)",
      invalidPrincipal: "Invalid id: no spaces or « / » (or * for everyone).",
      empty: "No documents. Upload one to make it searchable.",
      topCited: "Most cited documents",
      noCitations: "No citations over the period.",
      unanswered: "Unanswered questions",
      unansweredIntro: (n) =>
        `The corpus could not answer ${n} times over the period. Each case hints at a document worth indexing.`,
      noUnanswered: "No unanswered questions over the period.",
      checking: "Checking permissions…",
      forbiddenTitle: "Admin access required",
      forbiddenBefore:
        "Your API key is valid but does not carry the admin role. Ask an operator to add your id to ",
      forbiddenAfter: ", or switch to an admin key.",
      errLoadMetrics: "Failed to load the metrics",
      errLoadDocuments: "Failed to load the documents",
      errUpload: (name) => `upload of ${name} failed`,
      errDelete: "delete failed",
      errShare: "share failed",
      errRevoke: "revoke failed",
      errVerify: "Could not verify access rights",
    },
  },
  fr: {
    modal: {
      title: "Clé API requise",
      bodyBefore: "Collez une des clés configurées dans ",
      bodyAfter:
        ". Elle reste dans le localStorage de ce navigateur (authentification de démonstration, OIDC en phase 2).",
      save: "Enregistrer la clé",
    },
    sidebar: {
      newConversation: "Nouvelle conversation",
      today: "Aujourd'hui",
      yesterday: "Hier",
      thisWeek: "Cette semaine",
      older: "Plus ancien",
      admin: "Administration",
      offline: "hors ligne",
    },
    brand: { backToSite: "Retour au site" },
    chat: {
      newConversation: "Nouvelle conversation",
      emptyTitle: "Posez une question.",
      emptySub: "Les réponses citent leurs passages, en FR, DE ou EN.",
      searching: "Recherche dans la base documentaire…",
      noAnswerTitle: "Le corpus ne permet pas de répondre.",
      noAnswerNote: (audit) =>
        "Aucun passage pertinent trouvé. Plutôt que d'extrapoler, le système s'arrête" +
        (audit !== null ? ` · la question reste consignée (audit №${audit})` : "") +
        ".",
      copy: "Copier",
      copied: "Copié",
      sources: "Sources",
      hideSources: "Masquer les sources",
      openSource: (n) => `Ouvrir la source ${n}`,
      meta: (d) => `${d} document${d > 1 ? "s" : ""} · fusion RRF`,
      audit: "audit",
    },
    composer: {
      placeholder: "Posez une question sur les documents indexés…",
      hints: "⏎ envoyer · ⇧⏎ nouvelle ligne · questions en FR, DE, EN",
      stop: "■ arrêter",
      send: "Envoyer",
    },
    panel: {
      title: (n) => `Sources · réponse ${n}`,
      subtitle: (p, d) =>
        `${p} passage${p > 1 ? "s" : ""} · ${d} document${d > 1 ? "s" : ""} · fusion RRF`,
      close: "Fermer le panneau des sources",
      page: "p.",
      auditBefore: "Instantané d'audit",
      auditAfter: " : extraits, scores et rangs conservés même si le document est supprimé.",
      exportJson: "Exporter (json)",
    },
    admin: {
      chatTab: "Chat",
      adminTab: "Administration",
      title: "Documents et pilotage",
      subtitle: (docs, passages) =>
        `${docs} document${docs > 1 ? "s" : ""} · ${passages} passages indexés`,
      lastAdded: "dernier ajout",
      day: "j",
      upload: "Téléverser",
      tiles: {
        answers: "Réponses",
        conversations: (n) => `${n} conversations`,
        tokens: "Tokens prompt / complétion",
        perAnswer: (n) => `≈ ${n} tokens par réponse`,
        latency: "Latence p50 / p95",
        retrieval: (p50, p95) => `récupération ${p50} / ${p95}`,
        errors: "Erreurs",
        errorPct: (pct) => `${pct} % des réponses`,
      },
      documents: "Documents",
      refreshNote: "statuts rafraîchis toutes les 2 s pendant le traitement",
      dropHere: "Déposez vos documents ici, ou ",
      browse: "parcourir",
      dropNote:
        "pdf · docx · md · txt · extraits, découpés et vectorisés sur place, rien n'est envoyé à un tiers",
      headers: { file: "Fichier", size: "Taille", status: "Statut", sharing: "Partage", added: "Ajouté" },
      ready: "prêt",
      passages: (n) => `${n} passages`,
      processing: "traitement",
      failed: "échec",
      everyone: "tous (*)",
      revoke: "révoquer",
      private: "privé",
      share: "partager",
      manage: "gérer",
      remove: "supprimer",
      confirmDelete: (filename) =>
        `Supprimer ${filename} ? Les instantanés d'audit des réponses passées sont conservés.`,
      noShares: "Aucun partage pour l'instant, ce document est privé.",
      principalPlaceholder: "identifiant utilisateur, ou * pour tous",
      add: "Ajouter",
      shareAll: "Partager à tous (*)",
      invalidPrincipal: "Identifiant invalide : ni espace ni « / » (ou * pour tous).",
      empty: "Aucun document. Téléversez-en un pour le rendre interrogeable.",
      topCited: "Documents les plus cités",
      noCitations: "Aucune citation sur la période.",
      unanswered: "Questions sans réponse",
      unansweredIntro: (n) =>
        `Le corpus n'a pas permis de répondre ${n} fois sur la période. Chaque cas est une piste de document à indexer.`,
      noUnanswered: "Aucune question restée sans réponse sur la période.",
      checking: "Vérification des permissions…",
      forbiddenTitle: "Accès administrateur requis",
      forbiddenBefore:
        "Votre clé API est valide mais ne porte pas le rôle admin. Demandez à un opérateur d'ajouter votre identifiant à ",
      forbiddenAfter: ", ou passez sur une clé admin.",
      errLoadMetrics: "Échec du chargement des métriques",
      errLoadDocuments: "Échec du chargement des documents",
      errUpload: (name) => `échec du téléversement de ${name}`,
      errDelete: "échec de la suppression",
      errShare: "échec du partage",
      errRevoke: "échec de la révocation",
      errVerify: "Impossible de vérifier les droits",
    },
  },
  de: {
    modal: {
      title: "API-Schlüssel erforderlich",
      bodyBefore: "Fügen Sie einen der in ",
      bodyAfter:
        " konfigurierten Schlüssel ein. Er bleibt im localStorage dieses Browsers (Demo-Authentifizierung, OIDC in Phase 2).",
      save: "Schlüssel speichern",
    },
    sidebar: {
      newConversation: "Neue Unterhaltung",
      today: "Heute",
      yesterday: "Gestern",
      thisWeek: "Diese Woche",
      older: "Älter",
      admin: "Administration",
      offline: "offline",
    },
    brand: { backToSite: "Zur Website" },
    chat: {
      newConversation: "Neue Unterhaltung",
      emptyTitle: "Stellen Sie eine Frage.",
      emptySub: "Antworten zitieren ihre Passagen, auf FR, DE oder EN.",
      searching: "Suche in der Dokumentbasis…",
      noAnswerTitle: "Der Korpus kann das nicht beantworten.",
      noAnswerNote: (audit) =>
        "Keine relevante Passage gefunden. Statt zu extrapolieren, hält das System an" +
        (audit !== null ? ` · die Frage bleibt protokolliert (Audit №${audit})` : "") +
        ".",
      copy: "Kopieren",
      copied: "Kopiert",
      sources: "Quellen",
      hideSources: "Quellen ausblenden",
      openSource: (n) => `Quelle ${n} öffnen`,
      meta: (d) => `${d} Dokument${d > 1 ? "e" : ""} · RRF-Fusion`,
      audit: "Audit",
    },
    composer: {
      placeholder: "Stellen Sie eine Frage zu den indexierten Dokumenten…",
      hints: "⏎ senden · ⇧⏎ neue Zeile · Fragen auf FR, DE, EN",
      stop: "■ stoppen",
      send: "Senden",
    },
    panel: {
      title: (n) => `Quellen · Antwort ${n}`,
      subtitle: (p, d) =>
        `${p} Passage${p > 1 ? "n" : ""} · ${d} Dokument${d > 1 ? "e" : ""} · RRF-Fusion`,
      close: "Quellenpanel schliessen",
      page: "S.",
      auditBefore: "Audit-Snapshot",
      auditAfter:
        ": Auszüge, Scores und Ränge bleiben erhalten, auch wenn das Dokument gelöscht wird.",
      exportJson: "Exportieren (json)",
    },
    admin: {
      chatTab: "Chat",
      adminTab: "Administration",
      title: "Dokumente und Steuerung",
      subtitle: (docs, passages) =>
        `${docs} Dokument${docs > 1 ? "e" : ""} · ${passages} indexierte Passagen`,
      lastAdded: "zuletzt hinzugefügt",
      day: "T",
      upload: "Hochladen",
      tiles: {
        answers: "Antworten",
        conversations: (n) => `${n} Unterhaltungen`,
        tokens: "Prompt- / Completion-Tokens",
        perAnswer: (n) => `≈ ${n} Tokens pro Antwort`,
        latency: "Latenz p50 / p95",
        retrieval: (p50, p95) => `Retrieval ${p50} / ${p95}`,
        errors: "Fehler",
        errorPct: (pct) => `${pct} % der Antworten`,
      },
      documents: "Dokumente",
      refreshNote: "Status wird während der Verarbeitung alle 2 s aktualisiert",
      dropHere: "Dokumente hier ablegen, oder ",
      browse: "durchsuchen",
      dropNote:
        "pdf · docx · md · txt · vor Ort extrahiert, zerlegt und vektorisiert, nichts geht an Dritte",
      headers: { file: "Datei", size: "Grösse", status: "Status", sharing: "Freigabe", added: "Hinzugefügt" },
      ready: "bereit",
      passages: (n) => `${n} Passagen`,
      processing: "Verarbeitung",
      failed: "fehlgeschlagen",
      everyone: "alle (*)",
      revoke: "widerrufen",
      private: "privat",
      share: "freigeben",
      manage: "verwalten",
      remove: "löschen",
      confirmDelete: (filename) =>
        `${filename} löschen? Audit-Snapshots früherer Antworten bleiben erhalten.`,
      noShares: "Noch keine Freigaben, dieses Dokument ist privat.",
      principalPlaceholder: "Benutzer-ID, oder * für alle",
      add: "Hinzufügen",
      shareAll: "Für alle freigeben (*)",
      invalidPrincipal: "Ungültige ID: keine Leerzeichen oder « / » (oder * für alle).",
      empty: "Keine Dokumente. Laden Sie eines hoch, um es durchsuchbar zu machen.",
      topCited: "Meistzitierte Dokumente",
      noCitations: "Keine Zitate im Zeitraum.",
      unanswered: "Unbeantwortete Fragen",
      unansweredIntro: (n) =>
        `Der Korpus konnte ${n} Mal im Zeitraum nicht antworten. Jeder Fall ist ein Hinweis auf ein zu indexierendes Dokument.`,
      noUnanswered: "Keine unbeantworteten Fragen im Zeitraum.",
      checking: "Berechtigungen werden geprüft…",
      forbiddenTitle: "Administratorzugriff erforderlich",
      forbiddenBefore:
        "Ihr API-Schlüssel ist gültig, trägt aber nicht die Admin-Rolle. Bitten Sie einen Operator, Ihre ID zu ",
      forbiddenAfter: " hinzuzufügen, oder wechseln Sie zu einem Admin-Schlüssel.",
      errLoadMetrics: "Metriken konnten nicht geladen werden",
      errLoadDocuments: "Dokumente konnten nicht geladen werden",
      errUpload: (name) => `Hochladen von ${name} fehlgeschlagen`,
      errDelete: "Löschen fehlgeschlagen",
      errShare: "Freigabe fehlgeschlagen",
      errRevoke: "Widerruf fehlgeschlagen",
      errVerify: "Zugriffsrechte konnten nicht geprüft werden",
    },
  },
};
