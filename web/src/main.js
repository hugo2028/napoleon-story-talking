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
const recordBtn    = document.getElementById('record-btn')
const settingsBtn      = document.getElementById('settings-btn')
const settingsDialog   = document.getElementById('settings-dialog')
const settingsForm     = document.getElementById('settings-form')
const settingsClose    = document.getElementById('settings-close')
const settingsSave     = document.getElementById('settings-save')
const settingsMessage  = document.getElementById('settings-message')
const langGrid         = document.getElementById('lang-grid')
const openaiKeyInput   = document.getElementById('openai-key')
const azureKeyInput    = document.getElementById('azure-key')
const azureRegionInput = document.getElementById('azure-region')
const openaiState      = document.getElementById('openai-state')
const azureState       = document.getElementById('azure-state')

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
  initSettings()
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

  const status = await refreshConfigStatus()
  if (status.azure) await initSpeech()
  ready = true
  if (!status.api) setStatus(t('apiUnreachable'), false)
  else if (!status.openai || !status.azure) {
    setStatus(t('missingKeys'), false)
    openSettings()
  } else if (synth) setReady()
  updateControls()
}

/** (Re)crée la synthèse vocale Azure — au démarrage ou après la saisie d'une clé. */
async function initSpeech() {
  try {
    synth?.stop()
    synth = await SpeechSynth.create(getLangInfo())
    synth.onViseme = (id)    => avatar?.setViseme(id)
    synth.onAction = (anim)  => avatar?.switchAnimation(anim)
    synth.onStart  = () => { speaking = true;  avatar?.startTalking() }
    synth.onEnd    = () => { speaking = false; avatar?.stopTalking(); setReady() }
    return true
  } catch (err) {
    console.error('[Speech] Erreur init TTS:', err)
    synth = null
    setStatus(t('ttsUnavailable') + (err.message || err), false)
    return false
  }
}

// ── Paramètres : langue + clés API ───────────────────────────────────────────
let configStatus = { openai: false, azure: false, azureRegion: '', api: false }

async function refreshConfigStatus() {
  try {
    const res = await fetch('/api/config-status')
    configStatus = await res.json()
  } catch {
    configStatus = { openai: false, azure: false, azureRegion: '', api: false }
  }
  renderKeyFields()
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
  renderLangGrid()
  applyStaticTexts()
  renderKeyFields()
}

function renderLangGrid() {
  for (const btn of langGrid.querySelectorAll('button')) {
    btn.setAttribute('aria-pressed', String(btn.dataset.lang === getLang()))
  }
}

/** Champs de clés : jamais pré-remplis ; un champ vide conserve la clé déjà configurée. */
function renderKeyFields() {
  openaiKeyInput.placeholder = configStatus.openai ? t('keyConfigured') : 'sk-…'
  azureKeyInput.placeholder = configStatus.azure ? t('keyConfigured') : t('azureKeyPlaceholder')
  if (!azureRegionInput.value) azureRegionInput.value = configStatus.azureRegion || ''
  openaiState.textContent = configStatus.openai ? '✓' : ''
  azureState.textContent = configStatus.azure ? '✓' : ''
}

function openSettings() {
  settingsMessage.textContent = ''
  renderKeyFields()
  if (!settingsDialog.open) settingsDialog.showModal()
}

settingsBtn.addEventListener('click', openSettings)
settingsClose.addEventListener('click', () => settingsDialog.close())

settingsForm.addEventListener('submit', async (e) => {
  e.preventDefault()
  const body = {
    openaiKey: openaiKeyInput.value.trim(),
    azureKey: azureKeyInput.value.trim(),
    azureRegion: azureRegionInput.value.trim() !== (configStatus.azureRegion || '') || azureKeyInput.value.trim()
      ? azureRegionInput.value.trim() : '',
  }
  if (!body.openaiKey && !body.azureKey && !body.azureRegion) {
    settingsDialog.close()
    return
  }
  settingsSave.disabled = true
  settingsMessage.className = 'settings-message'
  settingsMessage.textContent = t('saving')
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'error')
    openaiKeyInput.value = ''
    azureKeyInput.value = ''
    const status = await refreshConfigStatus()
    if ((body.azureKey || body.azureRegion) && status.azure) await initSpeech()
    settingsMessage.classList.add('ok')
    settingsMessage.textContent = t('saved')
    if (status.openai && status.azure && synth) setReady()
  } catch (err) {
    const code = err.message
    settingsMessage.classList.add('error')
    settingsMessage.textContent = t(
      code === 'invalid_openai_key' ? 'invalidOpenai'
        : code === 'invalid_azure' ? 'invalidAzure'
          : code === 'api_unreachable' ? 'apiUnreachable' : 'saveFailed')
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
  renderKeyFields()
  if (SHOW_RECORDER) renderRecordButton()
  synth?.setLanguage(getLangInfo())
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
    speech = err.message === 'missing_openai_key' ? t('missingKeys') : t('commsDown')
    if (err.message === 'missing_openai_key') openSettings()
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
