// Langues de l'interface et du récit.
//
// Ajouter une langue :
//   1. une entrée dans LANGS ci-dessous (nom, locale, voix, nom donné au narrateur) ;
//   2. ses libellés dans web/src/locales/<code>.json (scripts/translate_ui.py les génère) ;
//   3. éventuellement son drapeau dans FLAGS.
// L'API Python accepte toute langue envoyée par l'interface : rien d'autre à modifier.

// Libellés : un fichier JSON par langue. Les pluriels sont des objets { one, few, many, other }
// où {n} est remplacé par le nombre (catégories de Intl.PluralRules).
const LOCALES = Object.fromEntries(
  Object.entries(import.meta.glob('./locales/*.json', { eager: true, import: 'default' }))
    .map(([path, strings]) => [path.match(/([\w-]+)\.json$/)[1], strings]),
)

// label        : nom de la langue dans la langue elle-même
// locale       : langue de l'interface, des dates et des pluriels
// speechLocale : langue de la voix si elle diffère (langues sans voix de synthèse : voix d'une langue proche)
// voice        : voix Azure (utilisée seulement avec un avatar 3D)
// promptName   : nom de la langue dans la consigne donnée au narrateur
// dir          : 'rtl' pour les écritures de droite à gauche
export const LANGS = {
  fr: { label: 'Français', locale: 'fr-FR', voice: 'fr-FR-AlainNeural', promptName: 'français' },
  en: { label: 'English', locale: 'en-GB', voice: 'en-GB-RyanNeural', promptName: 'anglais' },
  es: { label: 'Español', locale: 'es-ES', voice: 'es-ES-AlvaroNeural', promptName: 'espagnol' },
  it: { label: 'Italiano', locale: 'it-IT', voice: 'it-IT-DiegoNeural', promptName: 'italien' },
  de: { label: 'Deutsch', locale: 'de-DE', voice: 'de-DE-ConradNeural', promptName: 'allemand' },
  pt: { label: 'Português', locale: 'pt-PT', voice: 'pt-PT-DuarteNeural', promptName: 'portugais' },
  // Langues liées à l'histoire napoléonienne
  ru: { label: 'Русский', locale: 'ru-RU', voice: 'ru-RU-DmitryNeural', promptName: 'russe' },
  pl: { label: 'Polski', locale: 'pl-PL', voice: 'pl-PL-MarekNeural', promptName: 'polonais' },
  nl: { label: 'Nederlands', locale: 'nl-NL', voice: 'nl-NL-MaartenNeural', promptName: 'néerlandais' },
  ar: { label: 'العربية', locale: 'ar-EG', voice: 'ar-EG-ShakirNeural', promptName: 'arabe (arabe standard moderne)', dir: 'rtl' },
  // Grand public mondial
  zh: { label: '中文', locale: 'zh-CN', voice: 'zh-CN-YunxiNeural', promptName: 'chinois (mandarin, caractères simplifiés)' },
  ja: { label: '日本語', locale: 'ja-JP', voice: 'ja-JP-KeitaNeural', promptName: 'japonais' },
  ko: { label: '한국어', locale: 'ko-KR', voice: 'ko-KR-InJoonNeural', promptName: 'coréen' },
  hi: { label: 'हिन्दी', locale: 'hi-IN', voice: 'hi-IN-MadhurNeural', promptName: 'hindi' },
  // Autres langues européennes
  sv: { label: 'Svenska', locale: 'sv-SE', voice: 'sv-SE-MattiasNeural', promptName: 'suédois' },
  da: { label: 'Dansk', locale: 'da-DK', voice: 'da-DK-JeppeNeural', promptName: 'danois' },
  cs: { label: 'Čeština', locale: 'cs-CZ', voice: 'cs-CZ-AntoninNeural', promptName: 'tchèque' },
  el: { label: 'Ελληνικά', locale: 'el-GR', voice: 'el-GR-NestorasNeural', promptName: 'grec moderne' },
  ro: { label: 'Română', locale: 'ro-RO', voice: 'ro-RO-EmilNeural', promptName: 'roumain' },
  tr: { label: 'Türkçe', locale: 'tr-TR', voice: 'tr-TR-AhmetNeural', promptName: 'turc' },
  uk: { label: 'Українська', locale: 'uk-UA', voice: 'uk-UA-OstapNeural', promptName: 'ukrainien' },
  // Langues régionales (corse, breton : pas de voix de synthèse, voix d'une langue proche)
  co: { label: 'Corsu', locale: 'co-FR', speechLocale: 'it-IT', voice: 'it-IT-DiegoNeural', promptName: 'corse' },
  ca: { label: 'Català', locale: 'ca-ES', voice: 'ca-ES-EnricNeural', promptName: 'catalan' },
  eu: { label: 'Euskara', locale: 'eu-ES', voice: 'eu-ES-AnderNeural', promptName: 'basque' },
  br: { label: 'Brezhoneg', locale: 'br-FR', speechLocale: 'fr-FR', voice: 'fr-FR-AlainNeural', promptName: 'breton' },
}

// ── Drapeaux en SVG (les émojis drapeaux ne s'affichent pas sous Windows) ─────
const stripes = (dir, colors) => {
  const n = colors.length
  return colors.map((c, i) => dir === 'v'
    ? `<rect x="${(i * 60) / n}" y="0" width="${60 / n + 0.5}" height="40" fill="${c}"/>`
    : `<rect x="0" y="${(i * 40) / n}" width="60" height="${40 / n + 0.5}" fill="${c}"/>`).join('')
}
const svg = (body, viewBox = '0 0 60 40') =>
  `<svg class="flag" viewBox="${viewBox}" preserveAspectRatio="none" aria-hidden="true">${body}</svg>`
const star = (cx, cy, r, fill, turn = 0) => {
  const pts = []
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + turn + (i * Math.PI) / 5
    const rr = i % 2 ? r * 0.4 : r
    pts.push(`${(cx + rr * Math.cos(a)).toFixed(2)},${(cy + rr * Math.sin(a)).toFixed(2)}`)
  }
  return `<polygon points="${pts.join(' ')}" fill="${fill}"/>`
}
const alternate = (a, b, n) => Array.from({ length: n }, (_, i) => (i % 2 ? b : a))

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
  ru: svg(stripes('h', ['#ffffff', '#0039a6', '#d52b1e'])),
  pl: svg(stripes('h', ['#ffffff', '#dc143c'])),
  nl: svg(stripes('h', ['#ae1c28', '#ffffff', '#21468b'])),
  // Arabe : drapeau égyptien simplifié (campagne d'Égypte)
  ar: svg(stripes('h', ['#ce1126', '#ffffff', '#000000']) + '<circle cx="30" cy="20" r="4" fill="#c09300"/>'),
  zh: svg('<rect width="60" height="40" fill="#de2910"/>' + star(10, 10, 6, '#ffde00')
    + star(20, 4, 2, '#ffde00', 0.4) + star(24, 8, 2, '#ffde00', 0.8)
    + star(24, 14, 2, '#ffde00', 0) + star(20, 18, 2, '#ffde00', 0.4)),
  ja: svg('<rect width="60" height="40" fill="#ffffff"/><circle cx="30" cy="20" r="12" fill="#bc002d"/>'),
  ko: svg('<rect width="60" height="40" fill="#ffffff"/>'
    + '<path d="M20,20a10,10 0 0 1 20,0z" fill="#cd2e3a"/><path d="M20,20a10,10 0 0 0 20,0z" fill="#0047a0"/>'
    + '<path d="M8,6l6,4M8,9l6,4M46,27l6,4M46,30l6,4M8,34l6,-4M8,31l6,-4M46,13l6,-4M46,10l6,-4" stroke="#000" stroke-width="1.6"/>'),
  hi: svg(stripes('h', ['#ff9933', '#ffffff', '#138808'])
    + '<circle cx="30" cy="20" r="5" fill="none" stroke="#000080" stroke-width="1.3"/>'),
  sv: svg('<rect width="60" height="40" fill="#006aa7"/><rect x="16" width="8" height="40" fill="#fecc00"/>'
    + '<rect y="16" width="60" height="8" fill="#fecc00"/>'),
  da: svg('<rect width="60" height="40" fill="#c8102e"/><rect x="17" width="6" height="40" fill="#ffffff"/>'
    + '<rect y="17" width="60" height="6" fill="#ffffff"/>'),
  cs: svg(stripes('h', ['#ffffff', '#d7141a']) + '<polygon points="0,0 30,20 0,40" fill="#11457e"/>'),
  el: svg(stripes('h', alternate('#0d5eaf', '#ffffff', 9))
    + '<rect width="22.2" height="22.2" fill="#0d5eaf"/><rect x="8.9" width="4.4" height="22.2" fill="#fff"/>'
    + '<rect y="8.9" width="22.2" height="4.4" fill="#fff"/>'),
  ro: svg(stripes('v', ['#002b7f', '#fcd116', '#ce1126'])),
  tr: svg('<rect width="60" height="40" fill="#e30a17"/><circle cx="23" cy="20" r="10" fill="#fff"/>'
    + '<circle cx="25.5" cy="20" r="8" fill="#e30a17"/>' + star(35, 20, 4, '#fff', -Math.PI / 2)),
  uk: svg(stripes('h', ['#0057b7', '#ffd700'])),
  // Corse : tête de Maure simplifiée
  co: svg('<rect width="60" height="40" fill="#ffffff"/><circle cx="30" cy="21" r="10" fill="#000"/>'
    + '<rect x="19" y="14" width="22" height="3.5" fill="#fff"/>'),
  ca: svg(stripes('h', alternate('#fcdd09', '#da121a', 9))),
  eu: svg('<rect width="60" height="40" fill="#d52b2b"/>'
    + '<path d="M0,0L60,40M60,0L0,40" stroke="#009b48" stroke-width="5"/>'
    + '<path d="M30,0v40M0,20h60" stroke="#ffffff" stroke-width="5"/>'),
  br: svg(stripes('h', alternate('#000000', '#ffffff', 9)) + '<rect width="26" height="22.2" fill="#ffffff"/>'
    + [6, 13, 20].flatMap(x => [5, 11, 17].map(y => `<circle cx="${x}" cy="${y}" r="1.6" fill="#000"/>`)).join('')),
}
for (const [code, info] of Object.entries(LANGS)) info.flag = FLAGS[code] || ''

// ── Langue courante ───────────────────────────────────────────────────────────
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

/** Langue et voix de synthèse (une langue sans voix utilise celle d'une langue proche). */
export function getSpeechInfo() {
  const info = LANGS[current]
  return { locale: info.speechLocale || info.locale, voice: info.voice }
}

export function setLang(code) {
  if (!LANGS[code]) return
  current = code
  try { localStorage.setItem(LANG_KEY, code) } catch {}
  document.documentElement.lang = code
}

/** Libellé traduit ; à défaut, l'anglais puis le français. Les pluriels reçoivent le nombre. */
export function t(key, ...args) {
  const value = LOCALES[current]?.[key] ?? LOCALES.en?.[key] ?? LOCALES.fr?.[key] ?? key
  if (value && typeof value === 'object') {
    const n = Number(args[0] ?? 0)
    let category = 'other'
    try { category = new Intl.PluralRules(LANGS[current].locale).select(n) } catch {}
    const template = value[category] ?? value.other ?? value.one ?? ''
    return template.replace('{n}', String(n))
  }
  return value
}

/** Textes fixes de la page (data-i18n / data-i18n-aria) et sens d'écriture des panneaux. */
export function applyStaticTexts(root = document) {
  document.documentElement.lang = current
  for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n)
  for (const el of root.querySelectorAll('[data-i18n-aria]')) el.setAttribute('aria-label', t(el.dataset.i18nAria))
  // Arabe : écriture de droite à gauche dans les panneaux de texte, sans retourner toute la page.
  const dir = LANGS[current].dir || 'ltr'
  for (const id of ['chat-panel', 'context-bubble', 'settings-dialog']) {
    root.getElementById?.(id)?.setAttribute('dir', dir)
  }
}
