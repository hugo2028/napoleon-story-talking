// Langues de l'interface et de la voix. Ajouter une langue = une entrée ici
// (+ son code dans LANGUES de pipeline/napoleon_api.py).
export const LANGS = {
  fr: {
    label: 'Français', locale: 'fr-FR', voice: 'fr-FR-AlainNeural',
    strings: {
      subtitle: 'Empereur des Français · 1769 – 1821',
      chatTitle: 'Dialogue impérial',
      chatIntro: 'Interrogez l\'Empereur sur sa vie, ses campagnes et son empire.',
      start: 'Commencer', end: 'Finir', reset: 'Reset', send: 'Envoyer', language: 'Langue',
      loadingAvatar: 'Chargement de l\'avatar…',
      avatarError: 'Erreur avatar — vérifiez avatar/avatar.glb',
      ttsUnavailable: 'TTS indisponible : ',
      ttsError: 'Erreur TTS : ',
      initializing: 'Initialisation…',
      started: 'Conversation commencée. Posez votre première question à l\'Empereur.',
      ended: 'Conversation terminée. Commencez une nouvelle conversation pour repartir à zéro.',
      endedStatus: 'Conversation terminée',
      endedHistory: 'Conversation terminée. L\'historique reste visible jusqu\'au prochain reset.',
      empty: 'Commencez une conversation pour parler avec Napoléon.',
      readyIdle: 'Prêt — commencez une conversation',
      askQuestion: 'Posez votre question…',
      thinking: 'Napoléon réfléchit…',
      speaking: 'L\'Empereur parle…',
      commsDown: 'Les communications sont interrompues.',
      placeholderActive: 'Posez votre question à l\'Empereur…',
      placeholderIdle: 'Commencez une conversation pour écrire…',
      letters: n => `${n} lettre${n > 1 ? 's' : ''}`,
      sources: 'sources', source: 'source', chapter: 'Chapitre',
      record: "● Enregistrer", stopRecording: "■ Arrêter",
      recordingOn: "Enregistrement en cours… Le fichier vidéo sera téléchargé à l'arrêt.",
      recordingNoAudio: "Enregistrement sans son : relancez-le et cochez « Partager aussi l'audio de l'onglet ».",
      recordingUnsupported: "Enregistrement vidéo non pris en charge par ce navigateur.",
      recordingSaved: "Vidéo enregistrée dans vos téléchargements.",
    },
  },
  en: {
    label: 'English', locale: 'en-GB', voice: 'en-GB-RyanNeural',
    strings: {
      subtitle: 'Emperor of the French · 1769 – 1821',
      chatTitle: 'Imperial dialogue',
      chatIntro: 'Ask the Emperor about his life, his campaigns and his empire.',
      start: 'Start', end: 'End', reset: 'Reset', send: 'Send', language: 'Language',
      loadingAvatar: 'Loading the avatar…',
      avatarError: 'Avatar error — check avatar/avatar.glb',
      ttsUnavailable: 'Speech unavailable: ',
      ttsError: 'Speech error: ',
      initializing: 'Initialising…',
      started: 'Conversation started. Ask the Emperor your first question.',
      ended: 'Conversation ended. Start a new conversation to begin again.',
      endedStatus: 'Conversation ended',
      endedHistory: 'Conversation ended. The history stays visible until the next reset.',
      empty: 'Start a conversation to talk with Napoleon.',
      readyIdle: 'Ready — start a conversation',
      askQuestion: 'Ask your question…',
      thinking: 'Napoleon is thinking…',
      speaking: 'The Emperor is speaking…',
      commsDown: 'Communications are cut off.',
      placeholderActive: 'Ask the Emperor your question…',
      placeholderIdle: 'Start a conversation to write…',
      letters: n => `${n} letter${n > 1 ? 's' : ''}`,
      sources: 'sources', source: 'source', chapter: 'Chapter',
      record: "● Record", stopRecording: "■ Stop",
      recordingOn: "Recording… The video file will download when you stop.",
      recordingNoAudio: "Recording without sound: restart it and tick “Also share tab audio”.",
      recordingUnsupported: "Video recording is not supported by this browser.",
      recordingSaved: "Video saved to your downloads.",
    },
  },
  es: {
    label: 'Español', locale: 'es-ES', voice: 'es-ES-AlvaroNeural',
    strings: {
      subtitle: 'Emperador de los franceses · 1769 – 1821',
      chatTitle: 'Diálogo imperial',
      chatIntro: 'Pregunte al Emperador por su vida, sus campañas y su imperio.',
      start: 'Empezar', end: 'Terminar', reset: 'Reiniciar', send: 'Enviar', language: 'Idioma',
      loadingAvatar: 'Cargando el avatar…',
      avatarError: 'Error del avatar — compruebe avatar/avatar.glb',
      ttsUnavailable: 'Voz no disponible: ',
      ttsError: 'Error de voz: ',
      initializing: 'Iniciando…',
      started: 'Conversación iniciada. Haga su primera pregunta al Emperador.',
      ended: 'Conversación terminada. Empiece una nueva conversación para volver a empezar.',
      endedStatus: 'Conversación terminada',
      endedHistory: 'Conversación terminada. El historial sigue visible hasta el próximo reinicio.',
      empty: 'Empiece una conversación para hablar con Napoleón.',
      readyIdle: 'Listo — empiece una conversación',
      askQuestion: 'Haga su pregunta…',
      thinking: 'Napoleón reflexiona…',
      speaking: 'El Emperador habla…',
      commsDown: 'Las comunicaciones están interrumpidas.',
      placeholderActive: 'Haga su pregunta al Emperador…',
      placeholderIdle: 'Empiece una conversación para escribir…',
      letters: n => `${n} carta${n > 1 ? 's' : ''}`,
      sources: 'fuentes', source: 'fuente', chapter: 'Capítulo',
      record: "● Grabar", stopRecording: "■ Detener",
      recordingOn: "Grabando… El archivo de vídeo se descargará al detener.",
      recordingNoAudio: "Grabación sin sonido: reiníciela y marque «Compartir también el audio de la pestaña».",
      recordingUnsupported: "Este navegador no permite grabar vídeo.",
      recordingSaved: "Vídeo guardado en sus descargas.",
    },
  },
  it: {
    label: 'Italiano', locale: 'it-IT', voice: 'it-IT-DiegoNeural',
    strings: {
      subtitle: 'Imperatore dei Francesi · 1769 – 1821',
      chatTitle: 'Dialogo imperiale',
      chatIntro: 'Interrogate l\'Imperatore sulla sua vita, le sue campagne e il suo impero.',
      start: 'Inizia', end: 'Termina', reset: 'Azzera', send: 'Invia', language: 'Lingua',
      loadingAvatar: 'Caricamento dell\'avatar…',
      avatarError: 'Errore avatar — verificate avatar/avatar.glb',
      ttsUnavailable: 'Voce non disponibile: ',
      ttsError: 'Errore voce: ',
      initializing: 'Inizializzazione…',
      started: 'Conversazione iniziata. Fate la vostra prima domanda all\'Imperatore.',
      ended: 'Conversazione terminata. Iniziate una nuova conversazione per ricominciare.',
      endedStatus: 'Conversazione terminata',
      endedHistory: 'Conversazione terminata. La cronologia resta visibile fino al prossimo azzeramento.',
      empty: 'Iniziate una conversazione per parlare con Napoleone.',
      readyIdle: 'Pronto — iniziate una conversazione',
      askQuestion: 'Fate la vostra domanda…',
      thinking: 'Napoleone riflette…',
      speaking: 'L\'Imperatore parla…',
      commsDown: 'Le comunicazioni sono interrotte.',
      placeholderActive: 'Fate la vostra domanda all\'Imperatore…',
      placeholderIdle: 'Iniziate una conversazione per scrivere…',
      letters: n => `${n} letter${n > 1 ? 'e' : 'a'}`,
      sources: 'fonti', source: 'fonte', chapter: 'Capitolo',
      record: "● Registra", stopRecording: "■ Ferma",
      recordingOn: "Registrazione in corso… Il video verrà scaricato all'arresto.",
      recordingNoAudio: "Registrazione senza audio: riavviatela e spuntate «Condividi anche l'audio della scheda».",
      recordingUnsupported: "Questo browser non supporta la registrazione video.",
      recordingSaved: "Video salvato nei download.",
    },
  },
  de: {
    label: 'Deutsch', locale: 'de-DE', voice: 'de-DE-ConradNeural',
    strings: {
      subtitle: 'Kaiser der Franzosen · 1769 – 1821',
      chatTitle: 'Kaiserlicher Dialog',
      chatIntro: 'Befragen Sie den Kaiser zu seinem Leben, seinen Feldzügen und seinem Reich.',
      start: 'Beginnen', end: 'Beenden', reset: 'Zurücksetzen', send: 'Senden', language: 'Sprache',
      loadingAvatar: 'Avatar wird geladen…',
      avatarError: 'Avatar-Fehler — avatar/avatar.glb prüfen',
      ttsUnavailable: 'Sprachausgabe nicht verfügbar: ',
      ttsError: 'Fehler der Sprachausgabe: ',
      initializing: 'Wird gestartet…',
      started: 'Gespräch begonnen. Stellen Sie dem Kaiser Ihre erste Frage.',
      ended: 'Gespräch beendet. Beginnen Sie ein neues Gespräch, um neu anzufangen.',
      endedStatus: 'Gespräch beendet',
      endedHistory: 'Gespräch beendet. Der Verlauf bleibt bis zum nächsten Zurücksetzen sichtbar.',
      empty: 'Beginnen Sie ein Gespräch, um mit Napoleon zu sprechen.',
      readyIdle: 'Bereit — beginnen Sie ein Gespräch',
      askQuestion: 'Stellen Sie Ihre Frage…',
      thinking: 'Napoleon denkt nach…',
      speaking: 'Der Kaiser spricht…',
      commsDown: 'Die Verbindungen sind unterbrochen.',
      placeholderActive: 'Stellen Sie dem Kaiser Ihre Frage…',
      placeholderIdle: 'Beginnen Sie ein Gespräch, um zu schreiben…',
      letters: n => `${n} Brief${n > 1 ? 'e' : ''}`,
      sources: 'Quellen', source: 'Quelle', chapter: 'Kapitel',
      record: "● Aufnehmen", stopRecording: "■ Stoppen",
      recordingOn: "Aufnahme läuft… Die Videodatei wird beim Stoppen heruntergeladen.",
      recordingNoAudio: "Aufnahme ohne Ton: neu starten und „Tab-Audio teilen“ aktivieren.",
      recordingUnsupported: "Videoaufnahme wird von diesem Browser nicht unterstützt.",
      recordingSaved: "Video in Ihren Downloads gespeichert.",
    },
  },
  pt: {
    label: 'Português', locale: 'pt-PT', voice: 'pt-PT-DuarteNeural',
    strings: {
      subtitle: 'Imperador dos Franceses · 1769 – 1821',
      chatTitle: 'Diálogo imperial',
      chatIntro: 'Interrogue o Imperador sobre a sua vida, as suas campanhas e o seu império.',
      start: 'Começar', end: 'Terminar', reset: 'Reiniciar', send: 'Enviar', language: 'Idioma',
      loadingAvatar: 'A carregar o avatar…',
      avatarError: 'Erro do avatar — verifique avatar/avatar.glb',
      ttsUnavailable: 'Voz indisponível: ',
      ttsError: 'Erro de voz: ',
      initializing: 'A iniciar…',
      started: 'Conversa iniciada. Faça a sua primeira pergunta ao Imperador.',
      ended: 'Conversa terminada. Comece uma nova conversa para recomeçar.',
      endedStatus: 'Conversa terminada',
      endedHistory: 'Conversa terminada. O histórico fica visível até ao próximo reinício.',
      empty: 'Comece uma conversa para falar com Napoleão.',
      readyIdle: 'Pronto — comece uma conversa',
      askQuestion: 'Faça a sua pergunta…',
      thinking: 'Napoleão reflete…',
      speaking: 'O Imperador fala…',
      commsDown: 'As comunicações estão interrompidas.',
      placeholderActive: 'Faça a sua pergunta ao Imperador…',
      placeholderIdle: 'Comece uma conversa para escrever…',
      letters: n => `${n} carta${n > 1 ? 's' : ''}`,
      sources: 'fontes', source: 'fonte', chapter: 'Capítulo',
      record: "● Gravar", stopRecording: "■ Parar",
      recordingOn: "A gravar… O ficheiro de vídeo será transferido ao parar.",
      recordingNoAudio: "Gravação sem som: reinicie e marque «Partilhar também o áudio do separador».",
      recordingUnsupported: "Este navegador não suporta gravação de vídeo.",
      recordingSaved: "Vídeo guardado nas suas transferências.",
    },
  },
}

// Drapeaux en SVG : les émojis drapeaux ne s'affichent pas sous Windows.
const stripes = (dir, colors) => {
  const n = colors.length
  return colors.map((c, i) => dir === 'v'
    ? `<rect x="${(i * 60) / n}" y="0" width="${60 / n + 0.5}" height="40" fill="${c}"/>`
    : `<rect x="0" y="${(i * 40) / n}" width="60" height="${40 / n + 0.5}" fill="${c}"/>`).join('')
}
const svg = (body, viewBox = '0 0 60 40') =>
  `<svg class="flag" viewBox="${viewBox}" preserveAspectRatio="none" aria-hidden="true">${body}</svg>`

const FLAGS = {
  fr: svg(stripes('v', ['#002654', '#ffffff', '#ce1126'])),
  it: svg(stripes('v', ['#009246', '#ffffff', '#ce2b37'])),
  de: svg(stripes('h', ['#000000', '#dd0000', '#ffce00'])),
  es: svg('<rect width="60" height="40" fill="#aa151b"/><rect y="10" width="60" height="20" fill="#f1bf00"/>'),
  pt: svg('<rect width="60" height="40" fill="#da291c"/><rect width="24" height="40" fill="#046a38"/>'
    + '<circle cx="24" cy="20" r="8" fill="#ffe900"/><circle cx="24" cy="20" r="5" fill="#da291c"/>'),
  en: svg('<rect width="60" height="30" fill="#012169"/>'
    + '<path d="M0,0L60,30M60,0L0,30" stroke="#fff" stroke-width="6"/>'
    + '<path d="M0,0L60,30M60,0L0,30" stroke="#c8102e" stroke-width="2"/>'
    + '<path d="M30,0v30M0,15h60" stroke="#fff" stroke-width="10"/>'
    + '<path d="M30,0v30M0,15h60" stroke="#c8102e" stroke-width="6"/>', '0 0 60 30'),
}
for (const [code, info] of Object.entries(LANGS)) info.flag = FLAGS[code] || ''

const LANG_KEY = 'napoleon.lang'

function initialLang() {
  try {
    const saved = localStorage.getItem(LANG_KEY)
    if (saved && LANGS[saved]) return saved
  } catch {}
  const nav = (navigator.language || 'fr').slice(0, 2).toLowerCase()
  return LANGS[nav] ? nav : 'fr'
}

let current = initialLang()

export function getLang() { return current }
export function getLangInfo() { return LANGS[current] }

export function setLang(code) {
  if (!LANGS[code]) return
  current = code
  try { localStorage.setItem(LANG_KEY, code) } catch {}
  document.documentElement.lang = code
}

/** Libellé traduit ; les entrées fonctions (pluriels) reçoivent les arguments. */
export function t(key, ...args) {
  const value = LANGS[current].strings[key] ?? LANGS.fr.strings[key] ?? key
  return typeof value === 'function' ? value(...args) : value
}

/** Textes fixes de la page : éléments marqués data-i18n / data-i18n-placeholder. */
export function applyStaticTexts(root = document) {
  document.documentElement.lang = current
  for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n)
  for (const el of root.querySelectorAll('[data-i18n-aria]')) el.setAttribute('aria-label', t(el.dataset.i18nAria))
}
