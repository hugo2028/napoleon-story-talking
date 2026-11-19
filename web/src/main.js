import { AvatarPlayer, avatarModelAvailable } from './avatar.js'
import { PortraitAvatar } from './portraitAvatar.js'
import { SpeechSynth, stripPauses } from './speechSynth.js'
import { LANGS, t, getLang, getLangInfo, setLang, applyStaticTexts } from './i18n.js'
import { DemoRecorder, recordingSupported } from './recorder.js'

// ── DOM refs ──────────────────────────────────────────────────────────────────
const avatarCanvas = document.getElementById('avatar-canvas')
const chatForm     = document.getElementById('chat-form')
const chatInput    = document.getElementById('chat-input')
const sendBtn      = document.getElementById('send-btn')
const chatLog      = document.getElementById('chat-log')
const statusDot    = document.getElementById('status-dot')
const statusText   = document.getElementById('status-text')
const contextBubble = document.getElementById('context-bubble')
const contextCount  = document.getElementById('context-count')
const contextText   = document.getElementById('context-text')
const contextEpisode  = document.getElementById('context-episode')
const contextPeriode  = document.getElementById('context-periode')
const contextChapitre = document.getElementById('context-chapitre')
const contextLettres  = document.getElementById('context-lettres')
const startBtn     = document.getElementById('start-conversation-btn')
const endBtn       = document.getElementById('end-conversation-btn')
const resetBtn     = document.getElementById('reset-conversation-btn')
const langButton   = document.getElementById('lang-button')
const langMenu     = document.getElementById('lang-menu')
const recordBtn    = document.getElementById('record-btn')

// ── State ─────────────────────────────────────────────────────────────────────
let avatar   = null
let synth    = null
let speaking = false
let pending  = false
let ready    = false
let conversationActive = false
let conversationId = null
let history = []

const STORAGE_KEY = 'napoleon.conversation.v1'
const MAX_VISIBLE_MESSAGES = 80

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  initLanguage()
  setStatus(t('loadingAvatar'), false)
  restoreConversation()
  renderHistory()
  updateControls()

  try {
    if (await avatarModelAvailable()) {
      avatar = await AvatarPlayer.create(avatarCanvas)
    } else {
      // Pas de modèle 3D (dépôt public) : médaillon 2D, tout le reste fonctionne pareil
      console.info('[Avatar] web/avatar/avatar.glb absent — portrait 2D de repli')
      avatar = await PortraitAvatar.create(avatarCanvas)
    }
  } catch (err) {
    console.error('[Avatar]', err)
    setStatus(t('avatarError'), false)
    return
  }

  try {
    synth = await SpeechSynth.create(getLangInfo())
    synth.onViseme = (id)    => avatar?.setViseme(id)
    synth.onAction = (anim)  => avatar?.switchAnimation(anim)
    synth.onStart  = () => { speaking = true;  avatar?.startTalking() }
    synth.onEnd    = () => { speaking = false; avatar?.stopTalking(); setReady() }
    ready = true
    setReady()
  } catch (err) {
    console.error('[Speech] Erreur init TTS:', err)
    setStatus(t('ttsUnavailable') + (err.message || err), false)
    ready = true
  }

  updateControls()
}

// ── Langue ────────────────────────────────────────────────────────────────────
function initLanguage() {
  for (const [code, info] of Object.entries(LANGS)) {
    const li = document.createElement('li')
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.setAttribute('role', 'option')
    btn.dataset.lang = code
    btn.innerHTML = info.flag   // SVG statique défini dans i18n.js
    btn.append(document.createTextNode(info.label))
    btn.addEventListener('click', () => { chooseLanguage(code); closeLangMenu(true) })
    li.appendChild(btn)
    langMenu.appendChild(li)
  }
  renderLangButton()
  applyStaticTexts()
}

function renderLangButton() {
  const info = getLangInfo()
  langButton.innerHTML = `${info.flag}<span>${info.label}</span><span class="caret">▾</span>`
  for (const btn of langMenu.querySelectorAll('button')) {
    btn.setAttribute('aria-selected', String(btn.dataset.lang === getLang()))
  }
}

function openLangMenu() {
  langMenu.hidden = false
  langButton.setAttribute('aria-expanded', 'true')
  langMenu.querySelector('[aria-selected="true"]')?.focus()
}

function closeLangMenu(focusButton = false) {
  langMenu.hidden = true
  langButton.setAttribute('aria-expanded', 'false')
  if (focusButton) langButton.focus()
}

langButton.addEventListener('click', () => (langMenu.hidden ? openLangMenu() : closeLangMenu()))
document.addEventListener('click', (e) => {
  if (!langMenu.hidden && !e.target.closest('#lang-picker')) closeLangMenu()
})
langMenu.addEventListener('keydown', (e) => {
  const items = [...langMenu.querySelectorAll('button')]
  const i = items.indexOf(document.activeElement)
  if (e.key === 'Escape') { e.preventDefault(); closeLangMenu(true) }
  else if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus() }
  else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus() }
})

// La langue peut changer en cours de conversation : la réponse suivante et la voix suivent.
function chooseLanguage(code) {
  if (code === getLang()) return
  setLang(code)
  renderLangButton()
  applyStaticTexts()
  synth?.setLanguage(getLangInfo())
  renderHistory()
  if (ready && !pending && !speaking) setReady()
  else updateControls()
}

// ── Enregistrement de démo ────────────────────────────────────────────────────
const recorder = new DemoRecorder()

function renderRecordButton() {
  const on = recorder.recording
  recordBtn.dataset.i18n = on ? 'stopRecording' : 'record'
  recordBtn.textContent = t(recordBtn.dataset.i18n)
  recordBtn.classList.toggle('recording', on)
  recordBtn.setAttribute('aria-pressed', String(on))
}

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

// ── Chat ──────────────────────────────────────────────────────────────────────
startBtn.addEventListener('click', async () => {
  if (!ready || pending || speaking) return
  await startConversation()
})

endBtn.addEventListener('click', () => {
  if (!conversationActive) return
  endConversation()
})

resetBtn.addEventListener('click', () => {
  resetConversation()
})

chatForm.addEventListener('submit', async (e) => {
  e.preventDefault()
  const text = chatInput.value.trim()
  if (!text || speaking || pending || !conversationActive) return
  chatInput.value = ''

  await respond(text, true)
})

async function startConversation() {
  conversationActive = true
  conversationId = crypto.randomUUID?.() || String(Date.now())
  history = []
  clearNotes()
  renderHistory()
  persistConversation()
  addBubble(t('started'), 'system')
  updateControls()
}

function endConversation() {
  conversationActive = false
  pending = false
  speaking = false
  synth?.stop()
  avatar?.stopTalking()
  persistConversation()
  addBubble(t('ended'), 'system')
  setStatus(t('endedStatus'), true)
  updateControls()
}

function resetConversation() {
  conversationActive = false
  pending = false
  speaking = false
  conversationId = null
  history = []
  synth?.stop()
  avatar?.stopTalking()
  localStorage.removeItem(STORAGE_KEY)
  clearNotes()
  renderHistory()
  setStatus(ready ? t('readyIdle') : t('initializing'), ready)
  updateControls()
}

async function respond(userText, showUser = true) {
  if (showUser) addBubble(userText, 'user')

  setStatus(t('thinking'), false)
  pending = true
  updateControls()
  speaking = false  // reset au cas où

  history.push({ role: 'user', content: userText })
  persistConversation()

  let speech = ''
  let apiDocCount = null
  let apiContext  = null
  let apiSources  = null
  let apiActions  = []
  let apiAnnotation = null
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversationId, lang: getLang(), messages: history.map(({ role, content }) => ({ role, content })) })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'Erreur LLM')
    speech      = data.speech || ''
    apiDocCount = data.doc_count ?? null
    apiContext  = data.context ?? null
    apiSources  = data.sources ?? null
    apiActions  = data.actions ?? []
    apiAnnotation = data.annotation ?? null
  } catch (err) {
    speech = t('commsDown')
    console.error('[Chat]', err)
  }

  history.push({ role: 'assistant', content: speech, sources: apiSources, annotation: apiAnnotation })
  trimHistory()
  persistConversation()
  addBubble(speech, 'napoleon', apiSources)
  // Les notes suivent chaque réponse : nouvel épisode → nouveau contexte, sinon on garde
  // le contexte de l'épisode en cours mais chapitre et lettres sont ceux de CETTE réponse.
  if (apiAnnotation) {
    const episodeChanged = apiAnnotation.episode !== currentEpisode
    currentEpisode = apiAnnotation.episode
    if (episodeChanged) updateContextBubble(apiDocCount, apiContext, true)
    else if (apiDocCount != null || apiContext) updateContextBubble(apiDocCount, apiContext)
    updateAnnotation(apiAnnotation)
  } else if (apiDocCount != null || apiContext) {
    updateContextBubble(apiDocCount, apiContext)
  }
  pending = false
  updateControls()

  if (synth && speech) {
    setStatus(t('speaking'), false)
    try {
      await synth.speak(speech, apiActions)
    } catch (err) {
      console.error('[Speech] Erreur TTS:', err)
      setStatus(t('ttsError') + (err.message || err), false)
      speaking = false
      avatar?.stopTalking()
      setReady()
    }
  } else {
    setReady()
  }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function addBubble(text, role, sources = null) {
  const div = document.createElement('div')
  div.className = `bubble bubble-${role}`
  div.textContent = stripPauses(text)

  if (role === 'napoleon' && sources && sources.length > 0) {
    const btn = document.createElement('button')
    btn.className = 'source-toggle'
    btn.textContent = `📜 ${t('letters', sources.length)} · ${t('sources')}`

    const panel = document.createElement('div')
    panel.className = 'source-panel'
    panel.hidden = true

    for (const s of sources) {
      const item = document.createElement('div')
      item.className = 'source-item'
      const dateSpan = document.createElement('span')
      dateSpan.className = 'source-date'
      dateSpan.textContent = s.date || '?'
      const snippetSpan = document.createElement('span')
      snippetSpan.className = 'source-snippet'
      snippetSpan.textContent = s.snippet || ''
      item.appendChild(dateSpan)
      item.appendChild(snippetSpan)
      if (s.url) {
        const link = document.createElement('a')
        link.className = 'source-link'
        link.href = s.url
        link.target = '_blank'
        link.rel = 'noopener'
        link.textContent = 'Gallica ↗'
        item.appendChild(link)
      }
      panel.appendChild(item)
    }

    btn.addEventListener('click', () => { panel.hidden = !panel.hidden })
    div.appendChild(btn)
    div.appendChild(panel)
  }

  chatLog.appendChild(div)
  chatLog.scrollTop = chatLog.scrollHeight
}

let currentEpisode = null

/** Compteur de lettres + contexte historique de l'épisode. `replace` efface l'ancien épisode. */
function updateContextBubble(docCount, text, replace = false) {
  if (!replace && docCount == null && !text) return
  if (replace || docCount != null) {
    contextCount.textContent = docCount != null ? `${t('letters', docCount)} · ${t('source')}` : ''
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

function refreshNotesVisibility() {
  const empty = [contextEpisode, contextPeriode, contextChapitre, contextCount, contextText]
    .every(el => !el.textContent) && contextLettres.childElementCount === 0
  contextBubble.hidden = empty
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
  refreshNotesVisibility()
}

function setStatus(text, ready) {
  statusText.textContent = text
  statusDot.className = 'status-dot' + (ready ? ' ready' : '')
}

function setReady() {
  speaking = false
  pending = false
  setStatus(conversationActive ? t('askQuestion') : t('readyIdle'), true)
  updateControls()
}

function updateControls() {
  const canStart = ready && !conversationActive && !pending && !speaking
  const canInteract = ready && conversationActive && !pending && !speaking
  startBtn.disabled = !canStart
  endBtn.disabled = !conversationActive
  resetBtn.disabled = !ready && history.length === 0
  chatInput.disabled = !canInteract
  sendBtn.disabled = !canInteract
  chatInput.placeholder = conversationActive
    ? t('placeholderActive')
    : t('placeholderIdle')
  if (canInteract) chatInput.focus()
}

function restoreConversation() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    if (!Array.isArray(saved.history)) return
    history = saved.history.filter(isChatMessage).slice(-MAX_VISIBLE_MESSAGES)
    conversationActive = Boolean(saved.active)
    conversationId = saved.conversationId || null
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
    addBubble(t('empty'), 'system')
    return
  }

  for (const message of history) {
    addBubble(message.content, message.role === 'assistant' ? 'napoleon' : 'user', message.sources)
  }
  // Repères en haut à gauche : ceux de la dernière réponse qui en avait
  const lastAnn = [...history].reverse().find(m => m.annotation)?.annotation
  if (lastAnn) {
    currentEpisode = lastAnn.episode
    updateAnnotation(lastAnn)
  }
  if (!conversationActive) {
    addBubble(t('endedHistory'), 'system')
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
