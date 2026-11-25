import { AvatarPlayer, avatarModelAvailable } from './avatar.js'
import { PortraitAvatar } from './portraitAvatar.js'
import { SpeechSynth, stripPauses } from './speechSynth.js'
import { LANGS, t, getLang, getLangInfo, getSpeechInfo, setLang, applyStaticTexts } from './i18n.js'
import { DemoRecorder, recordingSupported } from './recorder.js'
import { BrowserSpeech } from './browserSpeech.js'
import { PROVIDERS, providerFromUrl } from './providers.js'
import { Subtitles } from './subtitles.js'
import { Ambience } from './ambience.js'
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
const ambienceBtn  = document.getElementById('ambience-btn')
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
// Plans du narrateur ([cam:…]) → modes de caméra de l'avatar (avatar.js, _setCameraTargets)
const CAMERA_SHOTS = { large: 'default', rapproche: 'closeup', visage: 'face' }
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
  restoreScene()
  if (avatar) avatar.onLightning = () => ambience.thunder()
  if (import.meta.env.DEV) window.__avatar = avatar   // essais dans la console (développement seulement)
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
  synth.onWord   = (i) => subtitles.reach(i)
  synth.onStart  = () => { speaking = true;  avatar?.startTalking(); ambience.setSpeaking(true); updateControls() }
  synth.onEnd    = () => { speaking = false; avatar?.stopTalking(); ambience.setSpeaking(false); subtitles.finish(); setReady() }
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
const AMBIENCE_KEY = 'napoleon.ambience'
const NIGHT_AFTER_ANSWERS = 10   // la nuit est tombée après une dizaine de réponses

function ambienceWanted() {
  try { return localStorage.getItem(AMBIENCE_KEY) !== 'off' } catch { return true }
}

function renderAmbienceButton() {
  const on = ambienceWanted()
  ambienceBtn.textContent = t(on ? 'ambienceOn' : 'ambienceOff')
  ambienceBtn.setAttribute('aria-pressed', String(on))
  ambienceBtn.classList.toggle('muted', !on)
}

ambienceBtn.addEventListener('click', () => {
  const on = !ambienceWanted()
  try { localStorage.setItem(AMBIENCE_KEY, on ? 'on' : 'off') } catch {}
  if (on) ambience.start()
  else ambience.stop()
  renderAmbienceButton()
})

// Le navigateur n'autorise le son qu'après un geste de l'utilisateur : premier clic ou première touche.
function unlockAmbience() {
  if (ambienceWanted() && !ambience.enabled) ambience.start()
}
document.addEventListener('pointerdown', unlockAmbience, { capture: true })
document.addEventListener('keydown', unlockAmbience, { capture: true })
renderAmbienceButton()

/** Mise en scène de l'archiviste : temps derrière la fenêtre (image et son), région éclairée sur la carte. */
function applyScene(scene) {
  if (!scene) return
  avatar?.applyScene?.(scene)
  if (scene.meteo) ambience.setWeather(scene.meteo)
}

/** Reprise d'une conversation enregistrée : la dernière mise en scène connue de chaque élément. */
function restoreScene() {
  const scene = {}
  for (const m of history) {
    if (m.role !== 'assistant' || !m.scene) continue
    if (m.scene.meteo) scene.meteo = m.scene.meteo
    if (m.scene.carte) scene.carte = m.scene.carte
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
  applyScene({ ...apiScene, lettres: apiSources || [] })
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
    subtitles.show(stripPauses(speech))
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
    btn.textContent = `📜 ${t('letters', sources.length)} · ${t('sources')}`
    btn.type = 'button'

    const panel = document.createElement('div')
    panel.className = 'source-panel'
    panel.hidden = true

    // Un clic déplie la liste ; chaque ligne (date, destinataire) est le lien vers Gallica.
    for (const s of sources) {
      const item = document.createElement(s.url ? 'a' : 'div')
      item.className = 'source-item'
      if (s.url) {
        item.href = s.url
        item.target = '_blank'
        item.rel = 'noopener'
      }
      const dateSpan = document.createElement('span')
      dateSpan.className = 'source-date'
      dateSpan.textContent = formatDate(s.date) || s.date || '?'
      const titleSpan = document.createElement('span')
      titleSpan.className = 'source-title'
      titleSpan.textContent = s.title || s.snippet || ''
      item.append(dateSpan, titleSpan)
      if (s.url) {
        const arrow = document.createElement('span')
        arrow.className = 'source-link'
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
