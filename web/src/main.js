import { AvatarPlayer, avatarModelAvailable } from './avatar.js'
import { PortraitAvatar } from './portraitAvatar.js'
import { SpeechSynth, stripPauses } from './speechSynth.js'
import { LANGS, t, getLang, getLangInfo, getSpeechInfo, setLang, applyStaticTexts } from './i18n.js'
import { DemoRecorder, recordingSupported } from './recorder.js'
import { BrowserSpeech } from './browserSpeech.js'
import { PROVIDERS, providerFromUrl } from './providers.js'
import { Subtitles } from './subtitles.js'
import { Ambience } from './ambience.js'
import { findPlaceMentions, addMapPlace } from './decorScene.js'
import { Memoire, TYPES as ENTITE_TYPES, decorerTexte, indexDesMentions, ouvrirFiche, ouvrirCarte as ouvrirCarteBrute,
  annoncer } from './memoire.js'
import './mobileViewport.js'

// ── DOM refs ──────────────────────────────────────────────────────────────────
const avatarCanvas = document.getElementById('avatar-canvas')
const chatForm     = document.getElementById('chat-form')
const chatInput    = document.getElementById('chat-input')
const sendBtn      = document.getElementById('send-btn')
const chatLog      = document.getElementById('chat-log')
const statusDot    = document.getElementById('status-dot')
const statusText   = document.getElementById('status-text')
const contextBubble = document.getElementById('context-bubble')
// Un clic déplie ou replie les notes (nombre de lettres et contexte de l'épisode)
contextBubble.addEventListener('click', () => {
  if (contextBubble.classList.contains('has-more')) contextBubble.classList.toggle('open')
})
const contextCount  = document.getElementById('context-count')
const contextText   = document.getElementById('context-text')
const contextEpisode  = document.getElementById('context-episode')
const contextPeriode  = document.getElementById('context-periode')
const contextChapitre = document.getElementById('context-chapitre')
const contextLettres  = document.getElementById('context-lettres')
const contextLacune   = document.getElementById('context-lacune')
const newBtn       = document.getElementById('new-conversation-btn')
const subtitles    = new Subtitles(document.getElementById('subtitles'))
const recordBtn    = document.getElementById('record-btn')
const settingsBtn      = document.getElementById('settings-btn')
const settingsDialog   = document.getElementById('settings-dialog')
const settingsForm     = document.getElementById('settings-form')
const settingsClose    = document.getElementById('settings-close')
const settingsSave     = document.getElementById('settings-save')
const settingsMessage  = document.getElementById('settings-message')
const langGrid         = document.getElementById('lang-grid')
const providerSelect     = document.getElementById('llm-provider')
const baseUrlInput       = document.getElementById('llm-base-url')
const llmUrlField        = document.getElementById('llm-url-field')
const llmKeyField        = document.getElementById('llm-key-field')
const llmKeyInput        = document.getElementById('llm-key')
const llmState           = document.getElementById('llm-state')
const llmKeyLink         = document.getElementById('llm-key-link')
const agentModelInput    = document.getElementById('agent-model')
const narratorModelInput = document.getElementById('narrator-model')
const loadModelsBtn      = document.getElementById('llm-load-models')
const embeddingField     = document.getElementById('embedding-field')
const embeddingKeyInput  = document.getElementById('embedding-key')
const embeddingState     = document.getElementById('embedding-state')
const azureKeyInput      = document.getElementById('azure-key')
const azureRegionInput   = document.getElementById('azure-region')
const azureState         = document.getElementById('azure-state')
const avatarNote         = document.getElementById('avatar-note')
const voiceSection       = document.getElementById('voice-section')
const agentSection       = document.getElementById('agent-section')
const avatarSection      = document.getElementById('avatar-section')
const settingsActions    = document.getElementById('settings-actions')

// ── State ─────────────────────────────────────────────────────────────────────
let avatar   = null
// Développement : l'avatar est inspectable depuis la console (window.__napoleon.avatar)
if (import.meta.env.DEV) window.__napoleon = { get avatar() { return avatar } }
let synth    = null
let speaking = false
let placeMentions = []   // lieux de la carte nommés dans la réponse en cours, par mot (findPlaceMentions)
let quoteSpans = []      // citations « … » de la réponse en cours, par mot : la musique ne joue que pendant elles
let entityMentions = []  // noms nouveaux de la réponse en cours, par mot (indexDesMentions) : bandeau et carte
let turnToken = 0        // change à chaque réponse : des noms arrivés trop tard pour une réponse s'ignorent
const memoire = new Memoire()
/** La mémoire ; une bulle verrouillée propose de demander à Napoléon (la question est préparée dans le chat). */
function ouvrirCarte(memoireArg = memoire, focus = null) {
  return ouvrirCarteBrute(memoireArg, focus, {
    onDemander: (n) => {
      chatInput.value = t('memAsk').replace('{0}', n.nom)
      chatInput.dispatchEvent(new Event('input'))
      chatInput.focus()
    },
  })
}
const entitesFond = document.getElementById('entites-fond')
document.getElementById('memory-btn')?.addEventListener('click', () => ouvrirCarte(memoire))

/** Un nom de la réponse a été cliqué : le récit se met en pause le temps de lire sa fiche. */
function onEntite(e) {
  if (e.type === 'lieu' && e.carte) avatar?.focusPlace?.(e.carte)
  const enPause = speaking && synth?.canPause && !synth.paused
  if (enPause) { synth.pause(); avatar?.stopTalking?.() }
  const reprendre = () => {
    if (enPause && synth?.paused) { synth.resume(); avatar?.startTalking?.() }
  }
  ouvrirFiche(memoire, e, {
    reprendre: enPause,
    onClose: (versCarte) => { if (!versCarte) reprendre() },
    onCarte: (id) => {
      ouvrirCarte(memoire, id)
      document.getElementById('memoire-dialog')?.addEventListener('close', reprendre, { once: true })
    },
  })
}

/** Le nom est prononcé : il rejoint le bandeau (en fond), et un lieu s'éclaire sur la carte. */
function montrerEntite(e) {
  if (e.type === 'lieu' && e.carte) avatar?.focusPlace?.(e.carte)
  if (!entitesFond || entitesFond.querySelector(`[data-id="${CSS.escape(e.id)}"]`)) return
  const b = document.createElement('button')
  b.type = 'button'
  b.className = 'entite-chip'
  b.dataset.id = e.id
  const nom = document.createElement('span')
  nom.textContent = `${ENTITE_TYPES[e.type]?.icone || ''} ${e.nom}`
  const notice = document.createElement('small')
  notice.textContent = e.notice || ''
  b.append(nom, notice)
  b.addEventListener('click', () => onEntite(e))
  entitesFond.appendChild(b)
  while (entitesFond.children.length > 8) entitesFond.firstElementChild.remove()
}

/**
 * Noms nouveaux de la réponse (demandés pendant que la voix démarre) : mis en mémoire, mis en évidence à leur
 * première apparition dans la bulle et les sous-titres, puis montrés au fil de la voix.
 */
async function chargerEntites(texte, bubble, item, annotation, avantTour = null, docsTour = []) {
  const token = turnToken
  let data
  try {
    const res = await fetch('/api/entites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texte, connus: memoire.connus(), lang: getLang(), langName: getLangInfo().promptName,
        contexte: [annotation?.episode, annotation?.periode_debut, annotation?.periode_fin].filter(Boolean).join(', ') })
    })
    data = await res.json()
  } catch (err) {
    console.warn('[Mémoire]', err)
    data = { entites: [], cites: [] }
  }
  const entites = (data.entites || []).filter((e) => !memoire.get(e.id))
  for (const e of entites) if (e.type === 'lieu') e.carte = addMapPlace(e.mention, e.lon, e.lat)
  memoire.ajouter({ entites }, annotation?.episode || '')
  // Le jeu : liens du corpus débloqués par cette réponse (noms rencontrés ensemble), épisodes de ses documents
  try {
    const tour = [...entites.map((e) => e.id), ...(data.cites || []), ...docsTour]
    const res = await fetch('/api/graphe/debloquer', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vus: memoire.refsVues(), tour }) })
    const d = await res.json()
    memoire.debloquerLiens(d.liens || [])
    memoire.debloquerEpisodes(d.episodes || [])
  } catch (err) { console.warn('[Mémoire]', err) }
  if (avantTour) annoncer(avantTour, memoire.compter())
  if (!entites.length) return
  item.entites = entites
  persistConversation()
  const body = bubble?.querySelector('.bubble-text')
  if (body) decorerTexte(body, entites, onEntite)
  if (token !== turnToken) return
  // Sous-titres : les mots de chaque nom deviennent cliquables ; la voix les a peut-être déjà dépassés
  const mentions = indexDesMentions(texte, entites)
  for (const m of mentions) {
    for (let k = m.index; k < m.index + m.mots; k++) {
      const span = subtitles.words[k]
      if (!span) continue
      span.classList.add('entite-mot')
      span.addEventListener('click', (ev) => { ev.stopPropagation(); onEntite(m.entite) })
    }
  }
  const dits = mentions.filter((m) => m.index <= subtitles.index || !synth)
  for (const m of dits) montrerEntite(m.entite)
  entityMentions = mentions.filter((m) => !dits.includes(m))
}

/** Citations de la réponse : [{ start, end }] en index de mots (sous-titres), du « ouvrant au » fermant. */
function findQuoteSpans(text) {
  const spans = []
  let start = null
  text.split(/\s+/).filter(Boolean).forEach((w, i) => {
    if (start === null && /[«“]/.test(w)) start = i
    if (start !== null && /[»”]/.test(w)) { spans.push({ start, end: i }); start = null }
  })
  return spans
}
// Plans du narrateur ([cam:…]) → modes de caméra de l'avatar (avatar.js, _setCameraTargets)
const CAMERA_SHOTS = {
  large: 'default', rapproche: 'closeup', visage: 'face',
  gauche: 'left', droite: 'right', plongee: 'high', travelling: 'travelling', tableau: 'board',
}

// Œuvre du tableau mural en grand, avec son cartel et son crédit
const paintingOverlay = document.getElementById('painting-overlay')
function showPaintingLarge(info) {
  if (!info?.url) return
  document.getElementById('painting-image').src = info.url
  document.getElementById('painting-image').alt = info.titre || ''
  const caption = document.getElementById('painting-caption')
  caption.replaceChildren()
  const title = document.createElement('strong')
  title.textContent = info.titre || ''
  const credit = document.createElement('small')
  credit.textContent = [info.peintre, info.date].filter(Boolean).join(', ') + ' — Wikimedia Commons, domaine public'
  caption.append(title, credit)
  paintingOverlay.hidden = false
}
paintingOverlay.addEventListener('click', () => { paintingOverlay.hidden = true })

// Lettre entière, dans une liseuse : date, destinataire, texte complet, lien Gallica
const letterOverlay = document.getElementById('letter-overlay')
// Une page de lettre tient environ LETTER_PAGE caractères ; on coupe entre deux paragraphes, sinon entre deux phrases
const LETTER_PAGE = 1300
function letterPages(text) {
  const pages = []
  let rest = (text || '').trim()
  while (rest.length > LETTER_PAGE * 1.25) {
    const chunk = rest.slice(0, LETTER_PAGE + 200)
    let cut = chunk.lastIndexOf('\n')
    if (cut < LETTER_PAGE * 0.6) {
      // fin de phrase la plus proche de la taille visée ; à défaut, la taille visée
      const ends = [...chunk.matchAll(/[.!?;»]\s/g)].map((x) => x.index + 1).filter((i) => i >= LETTER_PAGE * 0.6)
      cut = ends.length ? ends.reduce((a, b) => (Math.abs(b - LETTER_PAGE) < Math.abs(a - LETTER_PAGE) ? b : a)) : LETTER_PAGE
    }
    pages.push(rest.slice(0, cut).trim())
    rest = rest.slice(cut).trim()
  }
  if (rest) pages.push(rest)
  return pages.length ? pages : ['']
}

let letterState = null   // { source, pages, page }
function showLetterFull(source) {
  letterState = { source, pages: letterPages(source.text || source.snippet || ''), page: 0 }
  renderLetterPage()
  letterOverlay.hidden = false
}
function renderLetterPage() {
  const { source, pages, page } = letterState
  const sheet = document.getElementById('letter-sheet')
  sheet.replaceChildren()
  if (page === 0) {
    const h = document.createElement('h3')
    h.textContent = SOURCE_KIND[source.kind] || formatDate(source.date) || source.date || ''
    const to = document.createElement('p')
    to.className = 'letter-to'
    to.textContent = source.title || ''
    sheet.append(h, to)
  }
  const body = document.createElement('div')
  body.className = 'letter-body' + (page === 0 ? '' : ' continued')
  body.textContent = pages[page]
  sheet.appendChild(body)
  const foot = document.createElement('div')
  foot.className = 'letter-foot'
  if (pages.length > 1) {
    const nav = (label, delta, disabled) => {
      const b = document.createElement('button')
      b.type = 'button'
      b.className = 'letter-nav'
      b.textContent = label
      b.disabled = disabled
      b.addEventListener('click', () => { letterState.page += delta; renderLetterPage() })
      return b
    }
    const count = document.createElement('span')
    count.className = 'letter-count'
    count.textContent = `${page + 1} / ${pages.length}`
    foot.append(nav('‹', -1, page === 0), count, nav('›', 1, page === pages.length - 1))
  }
  if (source.url && page === pages.length - 1) {
    const a = document.createElement('a')
    a.className = 'letter-link'
    a.href = source.url
    a.target = '_blank'
    a.rel = 'noopener'
    a.textContent = 'Gallica ↗'
    foot.appendChild(a)
  }
  if (foot.childElementCount) sheet.appendChild(foot)
  sheet.scrollTop = 0
}
document.addEventListener('keydown', (e) => {
  if (letterOverlay.hidden || !letterState) return
  const last = letterState.pages.length - 1
  if (e.key === 'ArrowRight' && letterState.page < last) { letterState.page++; renderLetterPage() }
  if (e.key === 'ArrowLeft' && letterState.page > 0) { letterState.page--; renderLetterPage() }
})
letterOverlay.addEventListener('click', (e) => { if (e.target === letterOverlay) letterOverlay.hidden = true })

// Objet regardé de près : bouton pour revenir au récit ; au survol, le nom de l'objet près du curseur
const inspectBack = document.getElementById('inspect-back')
inspectBack.addEventListener('click', () => avatar?.endInspect?.())
const poiLabel = document.getElementById('poi-label')
function showPoiLabel(poi, e) {
  if (!poi || !e) { poiLabel.hidden = true; return }
  const panel = poiLabel.parentElement.getBoundingClientRect()
  const key = `poi_${poi.id}`
  poiLabel.textContent = poi.id !== 'tableau' && t(key) !== key ? t(key) : poi.label
  poiLabel.style.left = `${e.clientX - panel.left + 14}px`
  poiLabel.style.top = `${e.clientY - panel.top + 16}px`
  poiLabel.hidden = false
}
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return
  if (!paintingOverlay.hidden) paintingOverlay.hidden = true
  else if (!letterOverlay.hidden) letterOverlay.hidden = true
  else avatar?.endInspect?.()
})
let pending  = false
let ready    = false
let conversationActive = false
let conversationId = null
let history = []

const STORAGE_KEY = 'napoleon.conversation.v1'
const MAX_VISIBLE_MESSAGES = 80

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  initSettings()
  setStatus(t('loadingAvatar'), false)
  restoreConversation()
  renderHistory()
  updateControls()

  try {
    hasAvatarModel = await avatarModelAvailable()
    if (hasAvatarModel) {
      avatar = await AvatarPlayer.create(avatarCanvas)
    } else {
      // Pas de modèle 3D (optionnel) : médaillon 2D, tout le reste fonctionne pareil
      console.info('[Avatar] web/avatar/avatar.glb absent — portrait 2D de repli')
      avatar = await PortraitAvatar.create(avatarCanvas)
    }
  } catch (err) {
    console.error('[Avatar]', err)
    setStatus(t('avatarError'), false)
    return
  }

  updateNightfall()
  applyLighting()
  restoreScene()
  if (avatar) avatar.onLightning = () => ambience.thunder()
  if (avatar) avatar.onPaintingClick = showPaintingLarge
  if (avatar) avatar.onLetterClick = showLetterFull
  if (avatar) avatar.onMemoryClick = () => ouvrirCarte(memoire)
  if (avatar) avatar.onInspectChange = (on) => {
    inspectBack.hidden = !on
    poiLabel.hidden = true
    document.getElementById('avatar-panel').classList.toggle('inspecting', on)
  }
  if (avatar) avatar.onPoiHover = showPoiLabel
  if (import.meta.env.DEV) { window.__avatar = avatar; window.__ambience = ambience }   // essais dans la console (développement seulement)
  const status = await refreshConfigStatus()
  await initSpeech()
  ready = true
  if (!status.api) setStatus(t('apiUnreachable'), false)
  else if (!status.llm) {
    setStatus(t('missingKeys'), false)
    openSettings()
  } else setReady()
  updateControls()
}

/** Voix : Azure Speech si configurée (voix neuronale + lèvres synchronisées), sinon voix du navigateur. */
async function initSpeech() {
  synth?.stop()
  synth = null
  try {
    // Azure ne sert qu'à synchroniser les lèvres de l'avatar 3D : sans modèle, voix du navigateur.
    if (hasAvatarModel && configStatus.azure) synth = await SpeechSynth.create(getSpeechInfo())
  } catch (err) {
    console.warn('[Speech] Azure indisponible, voix du navigateur :', err)
  }
  if (!synth && BrowserSpeech.supported()) {
    try { synth = await BrowserSpeech.create(getSpeechInfo()) } catch (err) { console.warn('[Speech]', err) }
  }
  if (!synth) return false
  synth.onViseme = (id)    => avatar?.setViseme(id)
  synth.onFaceReset  = ()          => avatar?.resetFace?.()
  synth.onFaceFrames = (i, frames) => avatar?.addFaceFrames?.(i, frames)
  synth.onFaceClock  = (t0)        => avatar?.setFaceClock?.(t0)
  synth.onAction = (anim)  => {
    // « cam:<plan> » : plan de caméra choisi par le narrateur ; sinon un geste de l'avatar
    if (anim?.startsWith('cam:')) avatar?.setCameraMode?.(CAMERA_SHOTS[anim.slice(4)] || 'default')
    else avatar?.switchAnimation(anim)
  }
  synth.onWord   = (i) => {
    subtitles.reach(i)
    // La carte suit la voix : chaque lieu nommé s'éclaire au moment où il est prononcé
    while (placeMentions.length && placeMentions[0].index <= i) avatar?.focusPlace?.(placeMentions.shift().name)
    while (entityMentions.length && entityMentions[0].index <= i) montrerEntite(entityMentions.shift().entite)
    // Musique pendant les citations seulement, et un instant après (quelques mots)
    ambience.setMusicActive(quoteSpans.some((s) => i >= s.start && i <= s.end + 4))
  }
  synth.onStart  = () => { speaking = true;  avatar?.startTalking(); ambience.setSpeaking(true); updateControls() }
  synth.onEnd    = () => {
    speaking = false; avatar?.stopTalking(); ambience.setSpeaking(false); ambience.setMusicActive(false)
    subtitles.finish(); setReady()
    // Fin de la réponse : retour au plan large, pour que le visiteur voie la pièce et puisse cliquer les objets
    avatar?.setCameraMode?.('default')
  }
  return true
}

// ── Paramètres : langue, modèle de l'agent, voix, avatar ─────────────────────
let configStatus = { llm: false, azure: false, azureRegion: '', api: false, embeddings: false }
let hasAvatarModel = false

async function refreshConfigStatus() {
  try {
    configStatus = await (await fetch('/api/config-status')).json()
  } catch {
    configStatus = { llm: false, azure: false, azureRegion: '', api: false, embeddings: false }
  }
  renderSettingsFields(true)
  return configStatus
}

function initSettings() {
  for (const [code, info] of Object.entries(LANGS)) {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'lang-option'
    btn.dataset.lang = code
    btn.innerHTML = info.flag   // SVG statique défini dans i18n.js
    btn.append(document.createTextNode(info.label))
    btn.addEventListener('click', () => chooseLanguage(code))
    langGrid.appendChild(btn)
  }
  for (const [id, p] of Object.entries(PROVIDERS)) {
    const opt = document.createElement('option')
    opt.value = id
    opt.textContent = id === 'custom' ? t('customProvider') : p.label
    providerSelect.appendChild(opt)
  }
  renderLangGrid()
  applyStaticTexts()
  renderSettingsFields(true)
}

function renderLangGrid() {
  for (const btn of langGrid.querySelectorAll('button')) {
    btn.setAttribute('aria-pressed', String(btn.dataset.lang === getLang()))
  }
}

/** Remplit le formulaire depuis la configuration actuelle (jamais les clés : un champ vide les conserve). */
function renderSettingsFields(fromStatus = false) {
  if (fromStatus) {
    const id = configStatus.base_url ? providerFromUrl(configStatus.base_url) : 'openai'
    providerSelect.value = id
    baseUrlInput.value = configStatus.base_url || PROVIDERS[id].baseUrl
    if (!azureRegionInput.value) azureRegionInput.value = configStatus.azureRegion || ''
    fillModelSelects([], configStatus.llm ? configStatus.agent_model : '', configStatus.llm ? configStatus.model : '')
  }
  const p = PROVIDERS[providerSelect.value]
  const sameProvider = configStatus.llm && baseUrlInput.value.replace(/\/+$/, '') === configStatus.base_url
  llmUrlField.hidden = providerSelect.value !== 'custom' && providerSelect.value !== 'ollama'
  llmKeyField.hidden = Boolean(p.noKey)
  llmKeyInput.placeholder = sameProvider && configStatus.has_key ? t('keyConfigured') : t('apiKeyPlaceholder')
  llmState.textContent = sameProvider ? '✓' : ''
  llmKeyLink.hidden = !p.keyUrl
  llmKeyLink.href = p.keyUrl || '#'
  // Avec OpenAI, la même clé sert aux embeddings : pas de champ séparé.
  embeddingField.hidden = providerSelect.value === 'openai'
  embeddingKeyInput.placeholder = configStatus.embeddings ? t('keyConfigured') : 'sk-…'
  embeddingState.textContent = configStatus.embeddings ? '✓' : ''
  azureKeyInput.placeholder = configStatus.azure ? t('keyConfigured') : t('azureKeyPlaceholder')
  azureState.textContent = configStatus.azure ? '✓' : ''
  avatarNote.textContent = t(hasAvatarModel ? 'avatarFound' : 'avatarMissing')
  voiceSection.hidden = !hasAvatarModel
  // Version en ligne : configuration fixée sur le serveur, seule la langue reste au choix
  const readOnly = Boolean(configStatus.readOnly)
  agentSection.hidden = readOnly
  avatarSection.hidden = readOnly
  settingsActions.hidden = readOnly
  if (readOnly) voiceSection.hidden = true
}

/** Listes de modèles remplies depuis l'API du fournisseur ; le choix actuel reste sélectionné. */
function fillModelSelects(models, agentChoice = agentModelInput.value, narratorChoice = narratorModelInput.value) {
  for (const [select, choice] of [[agentModelInput, agentChoice], [narratorModelInput, narratorChoice]]) {
    const ids = [...models]
    if (choice && !ids.includes(choice)) ids.unshift(choice)
    select.replaceChildren(...(ids.length
      ? ids.map((m) => Object.assign(document.createElement('option'), { value: m, textContent: m }))
      : [Object.assign(document.createElement('option'), { value: '', textContent: t('modelsNeedKey') })]))
    select.value = choice || ids[0] || ''
  }
}

let modelsRequest = 0
async function loadModels(silent = false) {
  const request = ++modelsRequest
  if (!silent) showSettingsMessage(t('loadingModels'))
  try {
    const res = await fetch('/api/config/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ baseUrl: baseUrlInput.value.trim(), apiKey: llmKeyInput.value.trim() }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'invalid_llm')
    if (request !== modelsRequest) return
    fillModelSelects(data.models)
    if (!silent) showSettingsMessage(t('modelsLoaded', data.models.length), 'ok')
  } catch (err) {
    if (request !== modelsRequest) return
    if (!agentModelInput.value) fillModelSelects([])
    if (!silent) showSettingsMessage(t(err.message === 'api_unreachable' ? 'apiUnreachable' : 'invalidLlm'), 'error')
  }
}

providerSelect.addEventListener('change', () => {
  baseUrlInput.value = PROVIDERS[providerSelect.value].baseUrl
  llmKeyInput.value = ''
  fillModelSelects([], '', '')
  renderSettingsFields()
  loadModels(true)
})
baseUrlInput.addEventListener('input', () => renderSettingsFields())
baseUrlInput.addEventListener('change', () => loadModels(true))
llmKeyInput.addEventListener('change', () => loadModels(true))
loadModelsBtn.addEventListener('click', () => loadModels(false))

function showSettingsMessage(text, kind = '') {
  settingsMessage.className = 'settings-message' + (kind ? ` ${kind}` : '')
  settingsMessage.textContent = text
}

function openSettings() {
  showSettingsMessage('')
  renderSettingsFields(true)
  if (!settingsDialog.open) settingsDialog.showModal()
  if (!configStatus.readOnly) loadModels(true)
}

settingsBtn.addEventListener('click', openSettings)

settingsClose.addEventListener('click', () => settingsDialog.close())

settingsForm.addEventListener('submit', async (e) => {
  e.preventDefault()
  const baseUrl = baseUrlInput.value.trim().replace(/\/+$/, '')
  if (!agentModelInput.value || !narratorModelInput.value) {
    showSettingsMessage(t('chooseModels'), 'error')
    return
  }
  const agentChanged = !configStatus.llm || baseUrl !== configStatus.base_url
    || llmKeyInput.value.trim() || embeddingKeyInput.value.trim()
    || agentModelInput.value.trim() !== configStatus.agent_model
    || narratorModelInput.value.trim() !== configStatus.model
  const body = {
    azureKey: azureKeyInput.value.trim(),
    azureRegion: azureKeyInput.value.trim() || azureRegionInput.value.trim() !== (configStatus.azureRegion || '')
      ? azureRegionInput.value.trim() : '',
  }
  if (agentChanged) {
    body.agent = {
      baseUrl, apiKey: llmKeyInput.value.trim(),
      agentModel: agentModelInput.value.trim(), model: narratorModelInput.value.trim(),
      ...(embeddingKeyInput.value.trim() ? { embeddingKey: embeddingKeyInput.value.trim() } : {}),
    }
  }
  if (!body.agent && !body.azureKey && !body.azureRegion) {
    settingsDialog.close()
    return
  }
  settingsSave.disabled = true
  showSettingsMessage(t('saving'))
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'error')
    llmKeyInput.value = ''
    embeddingKeyInput.value = ''
    azureKeyInput.value = ''
    const status = await refreshConfigStatus()
    if (body.azureKey || body.azureRegion) await initSpeech()
    showSettingsMessage(t('saved'), 'ok')
    if (status.llm && synth) setReady()
  } catch (err) {
    const code = err.message
    showSettingsMessage(t(
      code === 'invalid_llm' ? 'invalidLlm'
        : code === 'invalid_embedding_key' ? 'invalidEmbedding'
          : code === 'invalid_azure' ? 'invalidAzure'
            : code === 'api_unreachable' ? 'apiUnreachable' : 'saveFailed'), 'error')
  } finally {
    settingsSave.disabled = false
  }
})

// La langue peut changer en cours de conversation : la réponse suivante et la voix suivent.
function chooseLanguage(code) {
  if (code === getLang()) return
  setLang(code)
  renderLangGrid()
  applyStaticTexts()
  renderSettingsFields()
  if (SHOW_RECORDER) renderRecordButton()
  synth?.setLanguage(getSpeechInfo())
  renderHistory()
  if (ready && !pending && !speaking && synth) setReady()
  else updateControls()
}

// ── Enregistrement de démo (activé par VITE_DEMO_RECORDER=true dans .env) ────
const SHOW_RECORDER = import.meta.env.VITE_DEMO_RECORDER === 'true'
const recorder = SHOW_RECORDER ? new DemoRecorder() : null

function renderRecordButton() {
  const on = recorder.recording
  recordBtn.dataset.i18n = on ? 'stopRecording' : 'record'
  recordBtn.textContent = t(recordBtn.dataset.i18n)
  recordBtn.classList.toggle('recording', on)
  recordBtn.setAttribute('aria-pressed', String(on))
}

if (SHOW_RECORDER) {
  recordBtn.hidden = false
  recorder.onStateChange = (on) => {
    renderRecordButton()
    if (!on) addBubble(t('recordingSaved'), 'system')
  }
  if (!recordingSupported()) {
    recordBtn.disabled = true
    recordBtn.title = t('recordingUnsupported')
  }
  recordBtn.addEventListener('click', async () => {
    if (recorder.recording) {
      recorder.stop()
      return
    }
    try {
      const { hasAudio } = await recorder.start()
      addBubble(t(hasAudio ? 'recordingOn' : 'recordingNoAudio'), 'system')
    } catch (err) {
      // Refus de partage par l'utilisateur : rien à signaler
      if (err?.name !== 'NotAllowedError') {
        console.error('[Enregistrement]', err)
        addBubble(t('recordingUnsupported'), 'system')
      }
      renderRecordButton()
    }
  })
}

// ── Chat ──────────────────────────────────────────────────────────────────────
// Pas de bouton « Commencer » : la première question ouvre la conversation. Une question posée
// pendant que Napoléon parle l'interrompt. « Nouvelle conversation » efface tout (deux clics).
const NEW_CONFIRM_MS = 4000
let newConfirmTimer = null

newBtn.addEventListener('click', () => {
  if (!newBtn.classList.contains('confirm')) {
    newBtn.classList.add('confirm')
    newBtn.textContent = t('confirmNew')
    clearTimeout(newConfirmTimer)
    newConfirmTimer = setTimeout(resetNewButton, NEW_CONFIRM_MS)
    return
  }
  resetNewButton()
  resetConversation()
})

// ── Ambiance : son de Longwood et soir qui tombe ─────────────────────────────
const ambience = new Ambience()
const NIGHT_AFTER_ANSWERS = 10   // la nuit est tombée après une dizaine de réponses

// Jeu de lumière choisi par l'archiviste à chaque tour (scène « lumiere »)
const LIGHTING_FROM_SCENE = { normale: 'normal', penombre: 'penombre', projecteur: 'projecteur' }
let agentLighting = 'normal'
function applyLighting() {
  avatar?.setLightingStyle?.(agentLighting)
}

// Le navigateur n'autorise le son qu'après un geste de l'utilisateur : premier clic ou première touche.
function unlockAmbience() {
  if (!ambience.enabled) ambience.start()
}
document.addEventListener('pointerdown', unlockAmbience, { capture: true })
document.addEventListener('keydown', unlockAmbience, { capture: true })

/** Mise en scène de l'archiviste : temps derrière la fenêtre (image et son), région éclairée sur la carte. */
function applyScene(scene) {
  if (!scene) return
  avatar?.applyScene?.(scene)
  if (scene.meteo) ambience.setWeather(scene.meteo)
  if (scene.musique) ambience.setMusic(scene.musique)
  if (scene.reset) ambience.setMusic(null)
  if (scene.reset) agentLighting = 'normal'
  if (LIGHTING_FROM_SCENE[scene.lumiere]) agentLighting = LIGHTING_FROM_SCENE[scene.lumiere]
  if (scene.reset || scene.lumiere) applyLighting()
}

/** Reprise d'une conversation enregistrée : la dernière mise en scène connue de chaque élément. */
function restoreScene() {
  const scene = {}
  for (const m of history) {
    if (m.role !== 'assistant' || !m.scene) continue
    if (m.scene.meteo) scene.meteo = m.scene.meteo
    if (m.scene.carte) scene.carte = m.scene.carte
    if (m.scene.lumiere) scene.lumiere = m.scene.lumiere
    if (m.scene.tableau) scene.tableau = m.scene.tableau
  }
  const last = [...history].reverse().find((m) => m.role === 'assistant')
  if (last?.sources) scene.lettres = last.sources
  applyScene(scene)
}

/** Au fil des réponses, le crépuscule laisse place à la nuit (ciel, lumière de la fenêtre, bougies). */
function updateNightfall() {
  const answers = history.filter((m) => m.role === 'assistant').length
  avatar?.setNightfall?.(Math.min(1, answers / NIGHT_AFTER_ANSWERS))
}

function resetNewButton() {
  clearTimeout(newConfirmTimer)
  newBtn.classList.remove('confirm')
  newBtn.textContent = t('newConversation')
}

chatInput.addEventListener('input', updateControls)

chatForm.addEventListener('submit', async (e) => {
  e.preventDefault()
  if (!ready || pending) return
  synth?.unlockAudio?.()   // geste de l'utilisateur : la voix pourra jouer ensuite (mobile)
  const text = chatInput.value.trim()
  if (speaking) stopSpeaking()
  if (!text) return
  chatInput.value = ''
  // Sur mobile, le clavier se ferme pour laisser voir Napoléon
  if (coarsePointer()) chatInput.blur()
  await respond(text, true)
})

/** Napoléon se tait (bouton ■ ou nouvelle question pendant qu'il parle). */
function stopSpeaking() {
  synth?.stop()
  avatar?.stopTalking()
  subtitles.finish()
  setReady()
}

function coarsePointer() {
  return window.matchMedia?.('(pointer: coarse)').matches
}

function ensureConversation() {
  if (conversationActive && conversationId) return
  conversationActive = true
  conversationId = crypto.randomUUID?.() || String(Date.now())
}

function resetConversation() {
  conversationActive = false
  pending = false
  speaking = false
  conversationId = null
  history = []
  updateNightfall()
  applyScene({ reset: true, meteo: 'clair' })
  synth?.stop()
  avatar?.stopTalking()
  subtitles.clear()
  localStorage.removeItem(STORAGE_KEY)
  clearNotes()
  renderHistory()
  if (ready) setReady()
  else updateControls()
}

async function respond(userText, showUser = true) {
  ensureConversation()
  if (showUser) addBubble(userText, 'user')
  chatLog.querySelector('.bubble-welcome')?.remove()
  subtitles.clear()

  setStatus(t('thinking'), false)
  avatar?.startThinking?.()
  pending = true
  updateControls()
  speaking = false  // reset au cas où

  history.push({ role: 'user', content: userText })
  persistConversation()

  let speech = ''
  let apiDocCount = null
  let apiPeriodCount = null
  let apiContext  = null
  let apiSources  = null
  let apiActions  = []
  let apiAnnotation = null
  let apiScene = null
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversationId, lang: getLang(), langName: getLangInfo().promptName, messages: history.map(({ role, content }) => ({ role, content })) })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'Erreur LLM')
    speech      = data.speech || ''
    apiDocCount = data.doc_count ?? null
    apiPeriodCount = data.period_count ?? null
    apiContext  = data.context ?? null
    apiSources  = data.sources ?? null
    apiActions  = data.actions ?? []
    apiAnnotation = data.annotation ?? null
    apiScene = data.scene ?? null
  } catch (err) {
    speech = err.message === 'missing_llm' ? t('missingKeys') : t('commsDown')
    if (err.message === 'missing_llm') openSettings()
    console.error('[Chat]', err)
  }

  avatar?.stopThinking?.()
  history.push({ role: 'assistant', content: speech, sources: apiSources, annotation: apiAnnotation, scene: apiScene })
  updateNightfall()
  // Au tableau mural, toutes les sources de la réponse : lettres, passages des Œuvres, faits de la fiche
  applyScene({ ...apiScene, lettres: apiSources || [] })
  trimHistory()
  persistConversation()
  addBubble(speech, 'napoleon', apiSources)
  // La mémoire garde aussi les documents de la réponse : lettres, passages des Œuvres, tableau épinglé
  const avantTour = memoire.compter()
  memoire.ajouterDocuments([
    ...(apiSources || []).filter((src) => src.ref).map((src) => ({
      ref: src.ref, genre: src.kind === 'oeuvres' ? 'oeuvre' : 'lettre', nom: src.title, date: src.date })),
    ...(apiScene?.tableau?.ref ? [{ ref: apiScene.tableau.ref, genre: 'tableau', nom: apiScene.tableau.titre,
      date: apiScene.tableau.date, image: `/decor/tableaux/${apiScene.tableau.id}.jpg` }] : []),
  ], apiAnnotation?.episode || '')
  const reponseBulle = chatLog.lastElementChild
  const reponseItem = history[history.length - 1]
  const docsTour = [...(apiSources || []).filter((src) => src.ref).map((src) => src.ref),
    ...(apiScene?.tableau?.ref ? [apiScene.tableau.ref] : [])]
  // Les notes suivent chaque réponse : nouvel épisode → nouveau contexte, sinon on garde
  // le contexte de l'épisode en cours mais chapitre et lettres sont ceux de CETTE réponse.
  if (apiAnnotation) {
    const episodeChanged = apiAnnotation.episode !== currentEpisode
    currentEpisode = apiAnnotation.episode
    if (episodeChanged) updateContextBubble(apiDocCount, apiContext, true, apiPeriodCount)
    else if (apiDocCount != null || apiContext) updateContextBubble(apiDocCount, apiContext, false, apiPeriodCount)
    updateAnnotation(apiAnnotation)
  } else if (apiDocCount != null || apiContext) {
    updateContextBubble(apiDocCount, apiContext, false, apiPeriodCount)
  }
  pending = false
  updateControls()

  if (synth && speech) {
    setStatus(t('speaking'), false)
    subtitles.show(stripPauses(speech))
    avatar?.focusPlace?.(null)
    avatar?.endInspect?.()          // nouvelle réponse : la caméra reprend le récit
    placeMentions = findPlaceMentions(stripPauses(speech))
    quoteSpans = findQuoteSpans(stripPauses(speech))
    turnToken++
    entityMentions = []
    entitesFond?.replaceChildren()
    chargerEntites(stripPauses(speech), reponseBulle, reponseItem, apiAnnotation, avantTour, docsTour)
    try {
      await synth.speak(speech, apiActions)
    } catch (err) {
      console.error('[Speech] Erreur TTS:', err)
      setStatus(t('ttsError') + (err.message || err), false)
      speaking = false
      avatar?.stopTalking()
      subtitles.finish()
      setReady()
    }
  } else {
    if (speech) chargerEntites(stripPauses(speech), reponseBulle, reponseItem, apiAnnotation, avantTour, docsTour)
    setReady()
  }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function addBubble(text, role, sources = null) {
  const div = document.createElement('div')
  div.className = `bubble bubble-${role}`
  // Le texte est dans son propre bloc : sur mobile, il est masqué et seules les lettres restent.
  const body = document.createElement('div')
  body.className = 'bubble-text'
  body.textContent = stripPauses(text)
  div.appendChild(body)

  if (role === 'napoleon' && sources && sources.length > 0) {
    div.classList.add('has-sources')
    chatLog.querySelector('.latest-sources')?.classList.remove('latest-sources')
    div.classList.add('latest-sources')
    const btn = document.createElement('button')
    btn.className = 'source-toggle'
    const nLettres = sources.filter((s) => !s.kind).length   // les écrits et les souvenirs ne sont pas des lettres
    btn.textContent = nLettres ? `📜 ${t('letters', nLettres)} · ${t('sources')}` : `📜 ${t('sources')}`
    btn.type = 'button'

    const panel = document.createElement('div')
    panel.className = 'source-panel'
    panel.hidden = true

    // Un clic déplie la liste ; chaque ligne (date, destinataire) ouvre la lettre entière, « Gallica ↗ » l'original.
    for (const s of sources) {
      const item = document.createElement('div')
      item.className = 'source-item'
      const open = document.createElement('button')
      open.type = 'button'
      open.className = 'source-open'
      const dateSpan = document.createElement('span')
      dateSpan.className = 'source-date'
      dateSpan.textContent = SOURCE_KIND[s.kind] || formatDate(s.date) || s.date || '?'
      const titleSpan = document.createElement('span')
      titleSpan.className = 'source-title'
      titleSpan.textContent = s.title || s.snippet || ''
      open.append(dateSpan, titleSpan)
      open.addEventListener('click', () => showLetterFull(s))
      item.appendChild(open)
      if (s.url) {
        const arrow = document.createElement('a')
        arrow.className = 'source-link'
        arrow.href = s.url
        arrow.target = '_blank'
        arrow.rel = 'noopener'
        arrow.textContent = 'Gallica ↗'
        item.appendChild(arrow)
      }
      panel.appendChild(item)
    }

    btn.setAttribute('aria-expanded', 'false')
    btn.addEventListener('click', () => {
      panel.hidden = !panel.hidden
      btn.setAttribute('aria-expanded', String(!panel.hidden))
    })
    div.appendChild(btn)
    div.appendChild(panel)
  }

  chatLog.appendChild(div)
  chatLog.scrollTop = chatLog.scrollHeight
}

let currentEpisode = null

/** Compteur de lettres + contexte historique de l'épisode. `replace` efface l'ancien épisode. */
/**
 * Notes de l'épisode. `docCount` : lettres retenues pour le récit ; `period` : toutes les lettres de la base
 * écrites pendant la période de l'épisode ({ total, debut, fin }), quel qu'en soit le sujet.
 */
function updateContextBubble(docCount, text, replace = false, period = null) {
  if (!replace && docCount == null && !text) return
  if (replace || docCount != null) {
    const parts = []
    if (docCount != null) parts.push(t('lettersChosen', docCount))
    if (period?.total) {
      parts.push(t('lettersWritten', period.total)
        .replace('{from}', formatDate(period.debut)).replace('{to}', formatDate(period.fin)))
    }
    contextCount.textContent = parts.join(' · ')
  }
  if (replace || text) contextText.textContent = text || ''
  refreshNotesVisibility()
}

function clearNotes() {
  currentEpisode = null
  for (const el of [contextEpisode, contextPeriode, contextChapitre, contextCount, contextText]) el.textContent = ''
  contextLettres.replaceChildren()
  contextBubble.hidden = true
}

/** Étiquette des sources qui ne sont pas des lettres datées. */
const SOURCE_KIND = { oeuvres: 'Ses écrits', fiche: 'Souvenir' }

function refreshNotesVisibility() {
  const empty = [contextEpisode, contextPeriode, contextChapitre, contextCount, contextText]
    .every(el => !el.textContent) && contextLettres.childElementCount === 0
  contextBubble.hidden = empty
  // La flèche ne s'affiche que s'il y a de quoi déplier (nombre de lettres, contexte de l'épisode)
  const hasMore = Boolean(contextCount.textContent || contextText.textContent)
  contextBubble.classList.toggle('has-more', hasMore)
  if (!hasMore) contextBubble.classList.remove('open')
}

/** « 1805-10-08 » → « 8 octobre 1805 » (ou « 8 October 1805 »…), « 1805-10 » → « octobre 1805 » */
function formatDate(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  if (!m) return y
  const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d) || 1))
  const opts = d ? { day: 'numeric', month: 'long', year: 'numeric' } : { month: 'long', year: 'numeric' }
  try {
    return new Intl.DateTimeFormat(getLangInfo().locale, { ...opts, timeZone: 'UTC' }).format(date)
  } catch {
    return iso
  }
}

/** Repères en haut à gauche : épisode, période, chapitre, lettres racontées à ce tour. */
function updateAnnotation(ann) {
  contextEpisode.textContent = ann.episode || ''
  const debut = formatDate(ann.periode_debut)
  const fin = formatDate(ann.periode_fin)
  contextPeriode.textContent = debut && fin ? `${debut} — ${fin}` : (debut || fin)
  contextChapitre.textContent = ann.chapitre ? `${t('chapter')} : ${ann.chapitre}` : ''
  contextLettres.replaceChildren()
  for (const l of ann.lettres || []) {
    const li = document.createElement('li')
    const date = document.createElement('span')
    date.className = 'context-letter-date'
    date.textContent = formatDate(l.date)
    li.append(date, document.createTextNode(` ${l.titre || ''}`))
    contextLettres.appendChild(li)
  }
  // Lacune des archives entre la lettre précédente et celles de ce tour
  const lacune = ann.lacune
  contextLacune.textContent = lacune
    ? t('archiveGap').replace('{from}', formatDate(lacune.du)).replace('{to}', formatDate(lacune.au))
    : ''
  refreshNotesVisibility()
}

function setStatus(text, ready) {
  statusText.textContent = text
  statusDot.className = 'status-dot' + (ready ? ' ready' : '')
}

function setReady() {
  speaking = false
  pending = false
  setStatus(t('askQuestion'), true)
  updateControls()
}

function updateControls() {
  const canType = ready && !pending
  const typed = chatInput.value.trim().length > 0
  chatInput.disabled = !canType
  // Pendant que Napoléon parle, champ vide : le bouton l'arrête ; avec une question : elle l'interrompt.
  const stopMode = speaking && !typed
  sendBtn.disabled = !canType || (!typed && !speaking)
  sendBtn.textContent = stopMode ? t('stop') : t('send')
  sendBtn.classList.toggle('stop', stopMode)
  newBtn.hidden = history.length === 0
  newBtn.disabled = pending
  if (newBtn.hidden) resetNewButton()
  chatInput.placeholder = t('placeholderActive')
  // Sur mobile, pas de focus automatique : le clavier s'ouvrirait et cacherait Napoléon.
  if (canType && !speaking && !coarsePointer()) chatInput.focus()
}

function restoreConversation() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    if (!Array.isArray(saved.history)) return
    history = saved.history.filter(isChatMessage).slice(-MAX_VISIBLE_MESSAGES)
    // Une conversation enregistrée continue : la question suivante y fait suite.
    conversationId = saved.conversationId || null
    conversationActive = history.length > 0 && Boolean(conversationId)
  } catch (err) {
    console.warn('[Chat] Historique local illisible:', err)
    localStorage.removeItem(STORAGE_KEY)
  }
}

function persistConversation() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    active: conversationActive,
    conversationId,
    history
  }))
}

function trimHistory() {
  if (history.length > MAX_VISIBLE_MESSAGES) {
    history = history.slice(-MAX_VISIBLE_MESSAGES)
  }
}

function renderHistory() {
  chatLog.replaceChildren()
  if (history.length === 0) {
    addBubble(t('welcome'), 'system')
    chatLog.lastElementChild.classList.add('bubble-welcome')
    return
  }

  for (const message of history) {
    addBubble(message.content, message.role === 'assistant' ? 'napoleon' : 'user', message.sources)
    const body = chatLog.lastElementChild?.querySelector('.bubble-text')
    if (message.entites?.length && body) decorerTexte(body, message.entites, onEntite)
  }
  // Repères en haut à gauche : ceux de la dernière réponse qui en avait
  const lastAnn = [...history].reverse().find(m => m.annotation)?.annotation
  if (lastAnn) {
    currentEpisode = lastAnn.episode
    updateAnnotation(lastAnn)
  }
}

function isChatMessage(message) {
  return (
    message &&
    (message.role === 'user' || message.role === 'assistant') &&
    typeof message.content === 'string' &&
    message.content.trim().length > 0
  )
}

// ── Start ─────────────────────────────────────────────────────────────────────
init()
