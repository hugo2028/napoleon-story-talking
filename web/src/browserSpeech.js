// Voix de secours, sans clé : la synthèse vocale intégrée au navigateur (Web Speech API).
// Même interface que SpeechSynth (Azure) : speak(text, actions), stop(), setLanguage(),
// onStart / onEnd / onViseme / onAction. Le navigateur ne fournit pas de visèmes : la bouche
// bouge pendant la parole sans être synchronisée phonème par phonème, comme avec Azure.

const PAUSE_RE = /\s*\[\s*pause\s*\]\s*/gi
const PAUSE_MS = 700
const MAX_CHUNK = 220            // Chrome coupe les énoncés trop longs : on découpe par phrases
const MOUTH_VISEMES = [1, 2, 4, 6, 9, 11, 13, 19]
const NATURAL_RE = /natural|neural|online|premium|enhanced/i
// Prénoms des voix masculines courantes (Edge, Chrome, Windows, macOS) : Napoléon parle d'une voix d'homme.
const MALE_RE = /\b(henri|remy|rémy|paul|gerard|gérard|antoine|thomas|jean|fabrice|ryan|guy|andrew|brian|christopher|eric|roger|steffan|david|mark|daniel|alex|oliver|george|alvaro|álvaro|jorge|dario|raul|pablo|diego|giuseppe|cosimo|luca|conrad|florian|killian|jonas|jan|stefan|markus|duarte|antonio|fabio|julio|dmitry|dmitri|pavel|marek|maarten|shakir|hamed|yunxi|yunjian|yunyang|kangkang|keita|daichi|naoki|injoon|hyunsu|madhur|prabhat|mattias|jeppe|antonin|antonín|jakub|nestoras|emil|ahmet|ostap|enric|ander|arnaud|joan)\b/i

export class BrowserSpeech {
  constructor(lang) {
    this._lang = lang
    this._timers = []
    this._mouth = null
    this._run = 0
    this.onViseme = null
    this.onStart = null
    this.onEnd = null
    this.onAction = null
  }

  static supported() {
    return typeof window !== 'undefined' && 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window
  }

  /** Attend que le navigateur ait chargé ses voix (chargement asynchrone sous Chrome). */
  static async create(lang) {
    if (!BrowserSpeech.supported()) throw new Error('speechSynthesis indisponible')
    if (!speechSynthesis.getVoices().length) {
      await new Promise((resolve) => {
        const done = () => { speechSynthesis.removeEventListener('voiceschanged', done); resolve() }
        speechSynthesis.addEventListener('voiceschanged', done)
        setTimeout(done, 1500)
      })
    }
    return new BrowserSpeech(lang)
  }

  setLanguage(lang) {
    this._lang = lang
  }

  /** Meilleure voix pour la langue : locale exacte, voix « naturelles » (neuronales), puis voix d'homme. */
  _voice() {
    const locale = (this._lang?.locale || 'fr-FR').toLowerCase()
    const prefix = locale.slice(0, 2)
    let best = null
    let bestScore = -1
    for (const v of speechSynthesis.getVoices()) {
      const vl = v.lang.replace('_', '-').toLowerCase()
      if (!vl.startsWith(prefix)) continue
      const score = (vl === locale ? 4 : 0) + (NATURAL_RE.test(v.name) ? 3 : 0) + (MALE_RE.test(v.name) ? 2 : 0)
      if (score > bestScore) { best = v; bestScore = score }
    }
    return best
  }

  /** Texte → segments à dire, avec un silence entre les parties séparées par [pause]. */
  _segments(text) {
    const out = []
    for (const part of text.split(PAUSE_RE).map(s => s.trim()).filter(Boolean)) {
      const sentences = part.match(/[^.!?…]+[.!?…]*["»”]?\s*/g) || [part]
      let chunk = ''
      for (const sentence of sentences) {
        if (chunk && (chunk + sentence).length > MAX_CHUNK) { out.push({ text: chunk.trim(), pause: 0 }); chunk = '' }
        chunk += sentence
      }
      if (chunk.trim()) out.push({ text: chunk.trim(), pause: 0 })
      if (out.length) out[out.length - 1].pause = PAUSE_MS
    }
    if (out.length) out[out.length - 1].pause = 0
    return out
  }

  speak(text, actions = []) {
    this.stop()
    const run = ++this._run
    const segments = this._segments(text)
    const voice = this._voice()
    const pending = [...(actions || [])].sort((a, b) => (a.word_start ?? 0) - (b.word_start ?? 0))
    let wordIndex = 0
    let started = false

    const fireActions = () => {
      while (pending.length && (pending[0].word_start ?? 0) <= wordIndex) this.onAction?.(pending.shift().animation)
    }

    return new Promise((resolve) => {
      const finish = () => {
        this._stopMouth()
        if (run === this._run) this.onEnd?.()
        resolve()
      }
      const sayNext = (i) => {
        if (run !== this._run) return resolve()
        if (i >= segments.length) return finish()
        const seg = segments[i]
        const u = new SpeechSynthesisUtterance(seg.text)
        u.lang = this._lang?.locale || 'fr-FR'
        if (voice) u.voice = voice
        u.rate = 0.97
        const wordsInSegment = seg.text.split(/\s+/).filter(Boolean).length
        const firstWord = wordIndex
        let sawBoundary = false
        u.onstart = () => {
          if (!started) { started = true; this.onStart?.() }
          fireActions()
          this._startMouth()
        }
        u.onboundary = (e) => {
          if (e.name && e.name !== 'word') return
          sawBoundary = true
          wordIndex++
          fireActions()
        }
        u.onend = () => {
          this._stopMouth()
          // Voix sans événements de mots : on avance d'un segment entier.
          if (!sawBoundary) { wordIndex = firstWord + wordsInSegment; fireActions() }
          if (run !== this._run) return resolve()
          const t = setTimeout(() => sayNext(i + 1), seg.pause)
          this._timers.push(t)
        }
        u.onerror = (e) => {
          if (e.error !== 'interrupted' && e.error !== 'canceled') console.warn('[Voix navigateur]', e.error)
          u.onend()
        }
        speechSynthesis.speak(u)
      }
      sayNext(0)
    })
  }

  _startMouth() {
    this._stopMouth()
    let k = 0
    this._mouth = setInterval(() => {
      k++
      this.onViseme?.(k % 3 === 0 ? 0 : MOUTH_VISEMES[Math.floor(Math.random() * MOUTH_VISEMES.length)])
    }, 110)
  }

  _stopMouth() {
    if (this._mouth) clearInterval(this._mouth)
    this._mouth = null
    this.onViseme?.(0)
  }

  stop() {
    this._run++
    for (const t of this._timers) clearTimeout(t)
    this._timers = []
    this._stopMouth()
    if (BrowserSpeech.supported()) speechSynthesis.cancel()
  }
}
