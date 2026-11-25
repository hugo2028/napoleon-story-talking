import * as SpeechSDK from 'microsoft-cognitiveservices-speech-sdk'

const MAX_ACTION_REPEATS = 3
const PAUSE_RE = /\s*\[\s*pause\s*\]\s*/gi
const PAUSE_MS = 700
// Découpage pour la lecture : un premier morceau court (Napoléon commence vite à parler),
// puis des morceaux plus longs, préparés pendant que le précédent est joué.
const FIRST_SEGMENT_CHARS = 140
const SEGMENT_CHARS = 380
let tokenRefreshTimer = null   // renouvellement du jeton Azure (version en ligne)
/** Texte sans balises [pause], pour l'affichage. */
export function stripPauses(text = '') {
  return text.replace(PAUSE_RE, ' ').replace(/\s{2,}/g, ' ').trim()
}

/**
 * SpeechSynth — deux providers TTS au choix (contrôlé par TTS_PROVIDER dans .env) :
 *
 *  'azure'      → Azure Speech génère l'audio ET l'animation faciale, morceau par morceau ;
 *                 l'audio est joué par un élément <audio>.
 *
 *  'elevenlabs' → ElevenLabs génère l'audio (with-timestamps) ; Azure Speech
 *                 synthétise en pull-stream muet pour capturer les visèmes.
 *                 Alignement mot-par-mot. Consomme des crédits ElevenLabs.
 */
export class SpeechSynth {
  constructor(speechConfig, provider) {
    this._config     = speechConfig
    this._provider   = provider   // 'azure' | 'elevenlabs'
    this.onViseme    = null
    this.onWord      = null   // (indexDuMotAffiché, nombreDeMotsAffichés) => void — sous-titres
    this.onStart     = null
    this.onEnd       = null
    this.onAction    = null   // (animationName: string) => void — déclenché mid-speech
    // Animation faciale complète (Azure « FacialExpression ») : 60 images/s, 55 valeurs ARKit par image
    this.onFaceFrames = null  // (firstFrameIndex: number, frames: number[][]) => void
    this.onFaceClock  = null  // (frame0At: number) => void — instant (performance.now) de l'image 0
    this.onFaceReset  = null  // () => void
    this._timers     = []
    this._azureSynth = null
    this._run        = 0      // change à chaque arrêt : les suites d'une ancienne phrase s'ignorent
    // Lecture Azure par un élément <audio>
    this._audio          = null
    this._objectUrl      = null
    this._segmentPlaying = false
    this._syncTimer      = null
    this._finish         = null
    // Web Audio (mode ElevenLabs uniquement)
    this._audioSource = null
    this._audioCtx    = null
  }

  /** Change la langue et la voix Azure (prend effet à la prochaine phrase prononcée). */
  setLanguage({ locale, voice }) {
    if (!locale || !voice) return
    this._config.speechSynthesisLanguage  = locale
    this._config.speechSynthesisVoiceName = voice
  }

  static async create(lang = { locale: 'fr-FR', voice: 'fr-FR-AlainNeural' }) {
    const res = await fetch('/api/speech-config')
    const { key, token, region, endpoint, ttsProvider } = await res.json()
    if (!key && !token) throw new Error('AZURE_SPEECH_KEY manquant dans .env')

    const regionFromEndpoint = endpoint?.match(
      /^https?:\/\/([a-z0-9-]+)\.(?:api\.cognitive|cognitiveservices)\.azure\.com|^https?:\/\/([a-z0-9-]+)\.api\.cognitive\.microsoft\.com/
    )?.[1] ?? endpoint?.match(/^https?:\/\/([a-z0-9-]+)\./)?.[1]

    const effectiveRegion = region || regionFromEndpoint
    let config
    if (token && effectiveRegion) {
      // Version en ligne : jeton de 10 minutes délivré par le serveur, renouvelé toutes les 8 minutes
      config = SpeechSDK.SpeechConfig.fromAuthorizationToken(token, effectiveRegion)
      clearInterval(tokenRefreshTimer)
      tokenRefreshTimer = setInterval(async () => {
        try {
          const fresh = await (await fetch('/api/speech-config')).json()
          if (fresh.token) config.authorizationToken = fresh.token
        } catch (err) {
          console.warn('[Speech] renouvellement du jeton Azure impossible', err)
        }
      }, 8 * 60 * 1000)
    } else if (!key) {
      throw new Error('AZURE_SPEECH_REGION manquant')
    } else if (effectiveRegion) {
      config = SpeechSDK.SpeechConfig.fromSubscription(key, effectiveRegion)
    } else if (endpoint) {
      config = SpeechSDK.SpeechConfig.fromEndpoint(new URL(endpoint), key)
    } else {
      throw new Error('AZURE_SPEECH_REGION ou AZURE_ENDPOINT manquant dans .env')
    }
    config.speechSynthesisLanguage  = lang.locale
    config.speechSynthesisVoiceName = lang.voice
    config.speechSynthesisOutputFormat =
      SpeechSDK.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3

    const provider = ttsProvider || 'azure'
    console.log(`[Speech] provider=${provider}, région=${effectiveRegion}`)
    return new SpeechSynth(config, provider)
  }

  speak(text, actions = []) {
    if (this._provider === 'elevenlabs') return this._speakElevenLabs(text, actions)
    return this._speakAzure(text, actions)
  }

  // ── Azure : synthèse phrase par phrase, lecture par un élément <audio> ─────
  //
  // Chaque morceau est synthétisé en entier (audio + animation faciale + mots), puis joué par un
  // <audio> pendant que le suivant se prépare. Plus fiable sur mobile que la lecture en flux du SDK
  // (qui pouvait se couper), audible même iPhone en mode silencieux, et le visage suit l'horloge
  // réelle de l'audio (il se fige si la lecture est interrompue, et repart avec elle).

  /** À appeler pendant un geste de l'utilisateur (clic, envoi) : autorise la lecture audio sur mobile. */
  unlockAudio() {
    const audio = this._ensureAudio()
    if (this._audioUnlocked || this._segmentPlaying) return
    audio.src = silentWavUrl()
    audio.play().then(() => { this._audioUnlocked = true }).catch(() => {})
  }

  _ensureAudio() {
    if (!this._audio) {
      const audio = new Audio()
      audio.preload = 'auto'
      audio.setAttribute('playsinline', '')
      this._audio = audio
      // Retour sur la page (appel, autre appli, écran verrouillé) : la phrase en cours reprend.
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && this._segmentPlaying && audio.paused) {
          audio.play().catch(() => {})
        }
      })
    }
    return this._audio
  }

  async _speakAzure(text, actions = []) {
    this.stop()
    const run = this._run
    this._ensureAudio()
    const segments = splitSegments(text)
    if (!segments.length) { this.onEnd?.(); return }
    const scheduler = this._createWordActionScheduler(actions)
    const displayTotal = countWords(stripPauses(text))

    const pull  = SpeechSDK.AudioOutputStream.createPullStream()
    const synth = new SpeechSDK.SpeechSynthesizer(this._config, SpeechSDK.AudioConfig.fromStreamOutput(pull))
    this._azureSynth = synth
    const prepare = (i) => {
      if (i >= segments.length) return null
      const p = this._synthSegment(synth, segments[i].text)
      p.catch(() => {})   // l'erreur est traitée quand on attend ce morceau
      return p
    }

    let wordBase = 0
    let displayBase = 0
    let started = false
    let next = prepare(0)
    try {
      for (let i = 0; i < segments.length; i++) {
        const seg = await next
        if (run !== this._run) return
        next = prepare(i + 1)   // le morceau suivant se prépare pendant la lecture
        if (!started) { started = true; this.onStart?.() }
        const segDisplay = countWords(stripPauses(segments[i].text))
        await this._playSegment(run, seg, { scheduler, wordBase, displayBase, segDisplay, displayTotal })
        if (run !== this._run) return
        wordBase += seg.words.length
        displayBase += segDisplay
        if (segments[i].pauseAfter && i < segments.length - 1) await this._wait(run, PAUSE_MS)
        if (run !== this._run) return
      }
    } catch (err) {
      if (run !== this._run) return   // interrompu volontairement : pas une erreur
      throw err
    } finally {
      if (this._azureSynth === synth) {
        try { synth.close() } catch {}
        this._azureSynth = null
      }
    }
    this.onFaceReset?.()
    this.onEnd?.()
  }

  /** Synthétise un morceau : audio complet, images faciales, visèmes et instants des mots. */
  _synthSegment(synth, text) {
    return new Promise((resolve, reject) => {
      const visemes = []
      const words   = []
      const face    = []
      synth.visemeReceived = (_, e) => {
        visemes.push({ id: e.visemeId, ms: e.audioOffset / 10000 })
        if (e.animation) {
          try {
            const chunk = JSON.parse(e.animation)
            if (chunk.BlendShapes?.length) face.push([chunk.FrameIndex ?? 0, chunk.BlendShapes])
          } catch { /* image d'animation illisible : on garde les visèmes */ }
        }
      }
      synth.wordBoundary = (_, e) => {
        if (isWordBoundary(e)) words.push({ text: e.text, ms: e.audioOffset / 10000 })
      }
      synth.speakSsmlAsync(
        this._toSsml(text),
        result => {
          if (result.reason === SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
            resolve({ audio: result.audioData, visemes, words, face })
          } else {
            reject(new Error(result.errorDetails || 'Azure TTS failed'))
          }
        },
        err => reject(err instanceof Error ? err : new Error(String(err))),
      )
    })
  }

  /** Joue un morceau ; se résout à la fin de sa lecture (ou à l'arrêt). */
  _playSegment(run, seg, ctx) {
    const audio = this._audio
    if (this._objectUrl) URL.revokeObjectURL(this._objectUrl)
    this._objectUrl = URL.createObjectURL(new Blob([seg.audio], { type: 'audio/mpeg' }))

    this.onFaceReset?.()
    for (const [index, frames] of seg.face) this.onFaceFrames?.(index, frames)

    return new Promise((resolve, reject) => {
      let scheduled = false
      // Horloge du visage : l'image 0 correspond au début de l'audio, recalée sur sa position réelle.
      const sync = () => this.onFaceClock?.(performance.now() - audio.currentTime * 1000)
      const cleanup = () => {
        audio.onplaying = audio.onpause = audio.onended = audio.onerror = null
        clearInterval(this._syncTimer)
        this._segmentPlaying = false
        this._finish = null
      }
      this._finish = () => { cleanup(); resolve() }

      audio.onplaying = () => {
        sync()
        clearInterval(this._syncTimer)
        this._syncTimer = setInterval(sync, 250)
        if (scheduled || run !== this._run) return
        scheduled = true
        const t0 = performance.now() - audio.currentTime * 1000
        // Voix sans animation faciale : visèmes simples
        if (!seg.face.length) {
          for (const v of seg.visemes) this._at(t0 + v.ms, () => this.onViseme?.(v.id))
        }
        const n = seg.words.length
        seg.words.forEach((w, i) => {
          ctx.scheduler.onWord(ctx.wordBase + i, w.ms, t0)
          // Mot affiché correspondant (sous-titres) : proportionnel dans le morceau
          const shown = ctx.displayBase + Math.min(ctx.segDisplay - 1, Math.floor((i * ctx.segDisplay) / n))
          this._at(t0 + w.ms, () => this.onWord?.(shown, ctx.displayTotal))
        })
      }
      // Lecture interrompue (appel, autre appli…) : le visage se relâche au lieu de continuer seul.
      audio.onpause = () => {
        clearInterval(this._syncTimer)
        if (!audio.ended) this.onFaceClock?.(null)
      }
      audio.onended = () => { cleanup(); resolve() }
      audio.onerror = () => { cleanup(); reject(new Error('lecture audio impossible')) }

      this._segmentPlaying = true
      audio.src = this._objectUrl
      audio.play().catch(err => { cleanup(); reject(err) })
    })
  }

  _at(when, fn) {
    this._timers.push(setTimeout(fn, Math.max(0, when - performance.now())))
  }

  _wait(run, ms) {
    return new Promise(resolve => {
      this._finish = () => { this._finish = null; resolve() }
      this._timers.push(setTimeout(() => this._finish?.(), ms))
    })
  }

  // ── ElevenLabs : audio EL + visèmes Azure, alignement mot par mot ─────────

  async _speakElevenLabs(text, actions = []) {
    this.stop()
    this._timers = []

    if (!this._audioCtx || this._audioCtx.state === 'closed') {
      this._audioCtx = new AudioContext()
    }
    if (this._audioCtx.state === 'suspended') await this._audioCtx.resume()

    // ElevenLabs : la pause devient des points de suspension (silence naturel dans la voix)
    // (collés au mot précédent pour ne pas compter comme un mot dans l'alignement)
    const elText = text.replace(PAUSE_RE, '… ')
    const [{ audioBuffer, elWordStarts, elTotalMs }, { visemes, azureWordStarts, azureTotalMs }] =
      await Promise.all([
        this._fetchElevenLabsAudio(elText),
        this._captureAzureVisemes(text),
      ])

    const scale = azureTotalMs > 0 ? elTotalMs / azureTotalMs : 1
    console.log(
      `[Speech] EL ${elTotalMs.toFixed(0)}ms ${elWordStarts.length}mots | ` +
      `Azure ${azureTotalMs.toFixed(0)}ms ${azureWordStarts.length}mots | scale=${scale.toFixed(3)}`
    )

    const ctx    = this._audioCtx
    const source = ctx.createBufferSource()
    source.buffer = audioBuffer
    source.connect(ctx.destination)
    this._audioSource = source

    const playStart = performance.now()
    this.onStart?.()
    source.start()

    this._createWordActionScheduler(actions).scheduleFromWordStarts(elWordStarts, elTotalMs, playStart)

    for (const { id, ms } of visemes) {
      const elMs  = mapVisemeTime(ms, azureWordStarts, azureTotalMs, elWordStarts, elTotalMs)
      const delay = elMs - (performance.now() - playStart)
      const t     = setTimeout(() => this.onViseme?.(id), Math.max(0, delay))
      this._timers.push(t)
    }
    const endT = setTimeout(() => this.onEnd?.(), elTotalMs + 150)
    this._timers.push(endT)
  }

  async _fetchElevenLabsAudio(text) {
    const res = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    if (!res.ok) throw new Error(`ElevenLabs ${res.status}: ${await res.text()}`)
    const { audio, alignment } = await res.json()
    const binary  = atob(audio)
    const bytes   = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    const audioBuffer  = await this._audioCtx.decodeAudioData(bytes.buffer)
    const elTotalMs    = audioBuffer.duration * 1000
    const elWordStarts = buildElWordStarts(alignment)
    return { audioBuffer, elWordStarts, elTotalMs }
  }

  _captureAzureVisemes(text) {
    const pullStream  = SpeechSDK.AudioOutputStream.createPullStream()
    const audioConfig = SpeechSDK.AudioConfig.fromStreamOutput(pullStream)
    const synth       = new SpeechSDK.SpeechSynthesizer(this._config, audioConfig)
    this._azureSynth  = synth

    const visemes         = []
    const azureWordStarts = []
    let   maxOffsetMs     = 0

    synth.visemeReceived = (_, e) => {
      const ms = e.audioOffset / 10000
      maxOffsetMs = Math.max(maxOffsetMs, ms)
      visemes.push({ id: e.visemeId, ms })
    }
    synth.wordBoundary = (_, e) => {
      if (isWordBoundary(e)) {
        azureWordStarts.push(e.audioOffset / 10000)
      }
    }

    return new Promise((resolve) => {
      synth.speakSsmlAsync(
        this._toSsml(text),
        result => {
          synth.close(); this._azureSynth = null
          if (result.reason === SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
            resolve({ visemes, azureWordStarts, azureTotalMs: maxOffsetMs })
          } else {
            console.warn('[Speech] Azure visèmes échoués:', result.errorDetails)
            resolve({ visemes: [], azureWordStarts: [], azureTotalMs: 0 })
          }
        },
        err => {
          synth.close(); this._azureSynth = null
          console.warn('[Speech] Azure visèmes erreur:', err)
          resolve({ visemes: [], azureWordStarts: [], azureTotalMs: 0 })
        }
      )
    })
  }

  // ── Commun ───────────────────────────────────────────────────────────────

  _createWordActionScheduler(actions = [], audioBufferMs = 0) {
    const sortedActions = capRepeatedActions(actions)
      .filter(action => action?.animation)
      .map(action => ({
        animation: action.animation,
        wordStart: Math.max(0, Number(action.word_start) || 0),
      }))
      .sort((a, b) => a.wordStart - b.wordStart)
    let nextActionIdx = 0

    const scheduleAt = (animation, ms, playbackStart) => {
      const elapsed = playbackStart ? performance.now() - playbackStart : 0
      const delay = Math.max(0, ms + audioBufferMs - elapsed)
      const t = setTimeout(() => this.onAction?.(animation), delay)
      this._timers.push(t)
    }

    return {
      onWord: (wordIndex, ms, playbackStart) => {
        while (nextActionIdx < sortedActions.length &&
               wordIndex >= sortedActions[nextActionIdx].wordStart) {
          scheduleAt(sortedActions[nextActionIdx].animation, ms, playbackStart)
          nextActionIdx++
        }
      },
      scheduleFromWordStarts: (wordStarts, totalMs, playbackStart) => {
        while (nextActionIdx < sortedActions.length) {
          const action = sortedActions[nextActionIdx]
          const wordIdx = wordStarts.length > 0
            ? Math.min(wordStarts.length - 1, action.wordStart)
            : 0
          const ms = wordStarts[wordIdx] ?? Math.min(totalMs * 0.15, 350)
          scheduleAt(action.animation, ms, playbackStart)
          nextActionIdx++
        }
      },
    }
  }

  stop() {
    this._run++
    for (const t of (this._timers ?? [])) clearTimeout(t)
    this._timers = []
    clearInterval(this._syncTimer)
    if (this._audio && !this._audio.paused) this._audio.pause()
    this._finish?.()
    this.onFaceReset?.()
    if (this._azureSynth) {
      try { this._azureSynth.close() } catch {}
      this._azureSynth = null
    }
    if (this._audioSource) {
      try { this._audioSource.stop() } catch {}
      this._audioSource = null
    }
  }

  _toSsml(text) {
    const escaped = text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      // Respirations du récit : [pause] → silence (n'émet pas de wordBoundary, gestes inchangés)
      .replace(PAUSE_RE, ` <break time="${PAUSE_MS}ms"/> `)
    return `<speak version="1.0" xml:lang="${this._config.speechSynthesisLanguage}" xmlns:mstts="http://www.w3.org/2001/mstts">
  <voice name="${this._config.speechSynthesisVoiceName}">
    <mstts:viseme type="FacialExpression"/>
    <prosody rate="-3%">
      ${escaped}
    </prosody>
  </voice>
</speak>`
  }
}

// ── Découpage du texte pour la lecture Azure ──────────────────────────────────

/** Texte → morceaux à synthétiser ; `pauseAfter` : silence de respiration ([pause]) après le morceau. */
function splitSegments(text) {
  const parts = text.split(PAUSE_RE).map(p => p.trim()).filter(Boolean)
  const out = []
  parts.forEach((part, pi) => {
    const sentences = part.match(/[^.!?…]+(?:[.!?…]+["»”)]*\s*|$)/g) || [part]
    let current = ''
    for (const sentence of sentences) {
      const limit = out.length === 0 ? FIRST_SEGMENT_CHARS : SEGMENT_CHARS
      if (current && (current + sentence).length > limit) {
        out.push({ text: current.trim(), pauseAfter: false })
        current = ''
      }
      current += sentence
    }
    if (current.trim()) out.push({ text: current.trim(), pauseAfter: false })
    if (pi < parts.length - 1 && out.length) out[out.length - 1].pauseAfter = true
  })
  return out
}

function countWords(text) {
  return text.split(/\s+/).filter(Boolean).length
}

let silentUrl = null
/** Un court silence (WAV), joué pendant un geste de l'utilisateur pour autoriser l'audio sur mobile. */
function silentWavUrl() {
  if (silentUrl) return silentUrl
  const samples = 800
  const buf = new ArrayBuffer(44 + samples)
  const v = new DataView(buf)
  const str = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)) }
  str(0, 'RIFF'); v.setUint32(4, 36 + samples, true); str(8, 'WAVE'); str(12, 'fmt ')
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, 8000, true); v.setUint32(28, 8000, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true)
  str(36, 'data'); v.setUint32(40, samples, true)
  for (let i = 0; i < samples; i++) v.setUint8(44 + i, 128)
  silentUrl = URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }))
  return silentUrl
}

// ── Helpers alignement ElevenLabs ────────────────────────────────────────────

function buildElWordStarts(alignment) {
  if (!alignment?.characters) return []
  const chars  = alignment.characters
  const starts = alignment.character_start_times_seconds
  const words  = []
  let inWord   = false
  for (let i = 0; i < chars.length; i++) {
    const isWordChar = chars[i].trim() !== ''
    if (isWordChar && !inWord)  { inWord = true; words.push(starts[i] * 1000) }
    else if (!isWordChar)        { inWord = false }
  }
  return words
}

function isWordBoundary(event) {
  return event.boundaryType === SpeechSDK.SpeechSynthesisBoundaryType.Word ||
    event.boundaryType === undefined
}

function capRepeatedActions(actions = []) {
  const counts = new Map()
  return actions.map(action => {
    const animation = action?.animation
    if (!animation || animation.startsWith('cam:')) return action   // plan de caméra : jamais plafonné
    const count = (counts.get(animation) || 0) + 1
    counts.set(animation, count)
    if (count > MAX_ACTION_REPEATS) {
      return { ...action, animation: 'waiting' }
    }
    return action
  })
}

function mapVisemeTime(azureMs, azureWords, azureTotalMs, elWords, elTotalMs) {
  const n = Math.min(azureWords.length, elWords.length)
  if (n === 0) return azureTotalMs > 0 ? azureMs * (elTotalMs / azureTotalMs) : azureMs

  for (let i = 0; i < n; i++) {
    const azStart = azureWords[i]
    const azEnd   = i + 1 < n ? azureWords[i + 1] : azureTotalMs
    const elStart = elWords[i]
    const elEnd   = i + 1 < n ? elWords[i + 1] : elTotalMs
    if (azureMs >= azStart && azureMs < azEnd) {
      const ratio = (azEnd - azStart) > 0 ? (elEnd - elStart) / (azEnd - azStart) : 1
      return elStart + (azureMs - azStart) * ratio
    }
  }
  const azTail = azureTotalMs - azureWords[n - 1]
  const elTail = elTotalMs    - elWords[n - 1]
  return elWords[n - 1] + (azureMs - azureWords[n - 1]) * (azTail > 0 ? elTail / azTail : 1)
}

export const VISEME_LABELS = {
  0: 'sil', 1: 'æ,ə,ʌ', 2: 'ɑ', 3: 'ɔ', 4: 'ɛ,ʊ',
  5: 'ɝ', 6: 'j,i,ɪ', 7: 'w,u', 8: 'o', 9: 'aʊ',
  10: 'ɔɪ', 11: 'aɪ', 12: 'h', 13: 'ɹ', 14: 'l',
  15: 's,z', 16: 'ʃ,tʃ,dʒ,ʒ', 17: 'ð', 18: 'f,v',
  19: 'd,t,n,θ', 20: 'k,g,ŋ', 21: 'p,b,m'
}
