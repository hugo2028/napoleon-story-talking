import * as SpeechSDK from 'microsoft-cognitiveservices-speech-sdk'

const MAX_ACTION_REPEATS = 3
const PAUSE_RE = /\s*\[\s*pause\s*\]\s*/gi
const PAUSE_MS = 700
let tokenRefreshTimer = null   // renouvellement du jeton Azure (version en ligne)
/** Texte sans balises [pause], pour l'affichage. */
export function stripPauses(text = '') {
  return text.replace(PAUSE_RE, ' ').replace(/\s{2,}/g, ' ').trim()
}

/**
 * SpeechSynth — deux providers TTS au choix (contrôlé par TTS_PROVIDER dans .env) :
 *
 *  'azure'      → Azure Speech joue l'audio ET génère les visèmes en un seul appel.
 *                 Gratuit, pas de crédits consommés.
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
    this.onWord      = null
    this.onStart     = null
    this.onEnd       = null
    this.onAction    = null   // (animationName: string) => void — déclenché mid-speech
    // Animation faciale complète (Azure « FacialExpression ») : 60 images/s, 55 valeurs ARKit par image
    this.onFaceFrames = null  // (firstFrameIndex: number, frames: number[][]) => void
    this.onFaceClock  = null  // (frame0At: number) => void — instant (performance.now) de l'image 0
    this.onFaceReset  = null  // () => void
    this._timers     = []
    this._azureSynth = null
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
      SpeechSDK.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3

    const provider = ttsProvider || 'azure'
    console.log(`[Speech] provider=${provider}, région=${effectiveRegion}`)
    return new SpeechSynth(config, provider)
  }

  speak(text, actions = []) {
    if (this._provider === 'elevenlabs') return this._speakElevenLabs(text, actions)
    return this._speakAzure(text, actions)
  }

  // ── Azure : un seul appel, audio + visèmes simultanés ────────────────────

  _speakAzure(text, actions = []) {
    this.stop()
    this._timers = []

    const audioConfig = SpeechSDK.AudioConfig.fromDefaultSpeakerOutput()
    const synth       = new SpeechSDK.SpeechSynthesizer(this._config, audioConfig)
    this._azureSynth  = synth

    let playbackStart    = null
    const pending        = []
    let maxAudioOffsetMs = 0
    // Azure synthesisStarted fires before audio reaches speakers (~200ms buffer delay)
    const AUDIO_BUFFER_MS = 200

    const actionScheduler = this._createWordActionScheduler(actions, AUDIO_BUFFER_MS)
    let wordCount = 0
    this.onFaceReset?.()

    const schedule = (id, ms) => {
      maxAudioOffsetMs = Math.max(maxAudioOffsetMs, ms)
      if (playbackStart === null) {
        pending.push({ id, ms })
      } else {
        const delay = ms + AUDIO_BUFFER_MS - (performance.now() - playbackStart)
        const t = setTimeout(() => this.onViseme?.(id), Math.max(0, delay))
        this._timers.push(t)
      }
    }

    const flushPending = () => {
      for (const { id, ms } of pending) {
        const delay = ms + AUDIO_BUFFER_MS - (performance.now() - playbackStart)
        const t = setTimeout(() => this.onViseme?.(id), Math.max(0, delay))
        this._timers.push(t)
      }
      pending.length = 0
    }

    synth.visemeReceived = (_, e) => {
      schedule(e.visemeId, e.audioOffset / 10000)
      if (e.animation) {
        try {
          const chunk = JSON.parse(e.animation)
          if (chunk.BlendShapes?.length) this.onFaceFrames?.(chunk.FrameIndex ?? 0, chunk.BlendShapes)
        } catch { /* image d'animation illisible : on garde les visèmes */ }
      }
    }

    synth.wordBoundary = (_, e) => {
      const ms = e.audioOffset / 10000
      maxAudioOffsetMs = Math.max(maxAudioOffsetMs, ms)

      if (isWordBoundary(e)) {
        actionScheduler.onWord(wordCount, ms, playbackStart)
        wordCount++
      }

      const t = setTimeout(
        () => this.onWord?.(e.text, ms),
        playbackStart ? Math.max(0, ms + AUDIO_BUFFER_MS - (performance.now() - playbackStart)) : 0
      )
      this._timers.push(t)
    }

    synth.synthesisStarted = () => {
      playbackStart = performance.now()
      this.onFaceClock?.(playbackStart + AUDIO_BUFFER_MS)
      flushPending()
      this.onStart?.()
    }

    synth.synthesisCompleted = () => {
      if (playbackStart === null) {
        playbackStart = performance.now()
        this.onFaceClock?.(playbackStart + AUDIO_BUFFER_MS)
        this.onStart?.()
        flushPending()
      }
      const elapsed   = performance.now() - playbackStart
      const remaining = Math.max(0, maxAudioOffsetMs - elapsed) + 250
      const t = setTimeout(() => this.onEnd?.(), remaining)
      this._timers.push(t)
    }

    return new Promise((resolve, reject) => {
      synth.speakSsmlAsync(
        this._toSsml(text),
        result => {
          synth.close()
          this._azureSynth = null
          if (result.reason === SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
            resolve(result)
          } else {
            reject(new Error(result.errorDetails || 'Azure TTS failed'))
          }
        },
        err => { synth.close(); this._azureSynth = null; reject(err) }
      )
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
    for (const t of (this._timers ?? [])) clearTimeout(t)
    this._timers = []
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
    if (!animation) return action
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
