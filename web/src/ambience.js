// Ambiance sonore de Longwood, générée dans le navigateur (Web Audio) : aucun fichier, aucun droit.
//   - le feu : un souffle sourd et des crépitements aléatoires ;
//   - la mer au loin : un ressac lent (bruit grave dont le volume ondule) ;
//   - le vent contre la fenêtre : un souffle filtré qui varie ;
//   - la pendule : un tic-tac discret.
// Le volume baisse quand Napoléon parle. Le navigateur n'autorise le son qu'après un geste de l'utilisateur :
// start() doit être appelé depuis un clic ou une touche.

const MASTER = 0.55          // volume général
const DUCKED = 0.35          // part du volume conservée pendant que Napoléon parle
const MUSIC = 0.3            // volume de la musique, sous l'ambiance
const MUSIC_DUCKED = 0.55    // part du volume de la musique conservée pendant que Napoléon parle

// Extraits musicaux choisis par l'archiviste (scène « musique ») : scripts/build_music.py, crédits dans docs/SCENE.md
const MUSIC_URLS = Object.fromEntries(['solennelle', 'melancolique', 'tendre', 'triomphale', 'marseillaise']
  .map((name) => [name, new URL(`../music/${name}.mp3`, import.meta.url).href]))

function noiseBuffer(ctx, seconds = 4, color = 'brown') {
  const len = Math.floor(ctx.sampleRate * seconds)
  const buf = ctx.createBuffer(1, len, ctx.sampleRate)
  const data = buf.getChannelData(0)
  let last = 0
  for (let i = 0; i < len; i++) {
    const white = Math.random() * 2 - 1
    if (color === 'white') data[i] = white
    else {                                   // bruit brun : grave et doux
      last = (last + 0.02 * white) / 1.02
      data[i] = last * 3.5
    }
  }
  return buf
}

export class Ambience {
  constructor() {
    this.ctx = null
    this.master = null
    this.enabled = false
    this.speaking = false
    this._timers = []
    this.musicName = null      // morceau joué
    this.musicWanted = null    // morceau demandé (gardé jusqu'au premier geste de l'utilisateur)
    this.musicTrack = null
    this.musicActive = false   // la musique ne se fait entendre que pendant les citations (setMusicActive)
  }

  /** Une citation commence (true) ou s'achève (false) : la musique choisie monte, puis s'efface. */
  setMusicActive(on) {
    if (on === this.musicActive) return
    this.musicActive = on
    if (this.ctx) this._applyVolume(on ? 1.2 : 2.5)
  }

  /** Musique de fond choisie par l'archiviste : fondu enchaîné vers ce morceau (en boucle), ou silence. */
  setMusic(name) {
    this.musicWanted = MUSIC_URLS[name] ? name : null
    if (this.ctx && this.enabled) this._playMusic(this.musicWanted)
  }

  _playMusic(name) {
    if (name === this.musicName) return
    this.musicName = name
    const now = this.ctx.currentTime
    const old = this.musicTrack
    if (old) {                                            // le morceau précédent s'efface en quelques secondes
      old.gain.gain.cancelScheduledValues(now)
      old.gain.gain.setTargetAtTime(0, now, 1.2)
      setTimeout(() => { old.el.pause(); old.src.disconnect() }, 7000)
    }
    this.musicTrack = null
    if (!name) return
    const el = new Audio(MUSIC_URLS[name])
    el.loop = true
    const src = this.ctx.createMediaElementSource(el)
    const gain = this.ctx.createGain()
    gain.gain.value = 0
    src.connect(gain).connect(this.musicBus)
    el.play().catch(() => {})
    gain.gain.setTargetAtTime(1, now, 1.5)
    this.musicTrack = { el, src, gain }
  }

  /** Démarre (ou reprend) le son. À appeler depuis un geste de l'utilisateur. */
  async start() {
    this.enabled = true
    if (!this.ctx) this._build()
    if (this.ctx.state === 'suspended') await this.ctx.resume()
    this._applyVolume(0.8)
    this._playMusic(this.musicWanted)
  }

  stop() {
    this.enabled = false
    if (this.ctx) this._applyVolume(0.4)
  }

  /** Temps qu'il fait : la pluie se fait entendre (pluie, orage), se tait sinon. */
  setWeather(kind) {
    this.rainLevel = kind === 'pluie' || kind === 'orage' ? 1 : 0
    if (this.rainGain) this.rainGain.gain.setTargetAtTime(0.07 * this.rainLevel, this.ctx.currentTime, 2)
  }

  /** Tonnerre : grondement grave, quelques instants après l'éclair. */
  thunder(delay = 0.5 + Math.random()) {
    if (!this.ctx || !this.enabled) return
    const src = this.ctx.createBufferSource()
    src.buffer = this.brown
    const lp = this.ctx.createBiquadFilter()
    lp.type = 'lowpass'
    lp.frequency.value = 140
    const g = this.ctx.createGain()
    const t = this.ctx.currentTime + delay
    g.gain.setValueAtTime(0, t)
    g.gain.linearRampToValueAtTime(1.4, t + 0.15)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 3.5)
    src.connect(lp).connect(g).connect(this.master)
    src.start(t, Math.random() * 2, 4)
  }

  /** Napoléon parle : l'ambiance s'efface un peu derrière sa voix. */
  setSpeaking(speaking) {
    this.speaking = speaking
    if (this.ctx) this._applyVolume(speaking ? 0.6 : 1.5)
  }

  _applyVolume(seconds) {
    const target = this.enabled ? MASTER * (this.speaking ? DUCKED : 1) : 0
    const now = this.ctx.currentTime
    this.master.gain.cancelScheduledValues(now)
    this.master.gain.setValueAtTime(this.master.gain.value, now)
    this.master.gain.linearRampToValueAtTime(target, now + seconds)
    const music = this.enabled && this.musicActive ? MUSIC * (this.speaking ? MUSIC_DUCKED : 1) : 0
    this.musicBus.gain.cancelScheduledValues(now)
    this.musicBus.gain.setValueAtTime(this.musicBus.gain.value, now)
    this.musicBus.gain.linearRampToValueAtTime(music, now + seconds)
  }

  _build() {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    this.ctx = ctx
    this.master = ctx.createGain()
    this.master.gain.value = 0
    this.master.connect(ctx.destination)
    this.musicBus = ctx.createGain()                       // musique : volume et effacement à part
    this.musicBus.gain.value = 0
    this.musicBus.connect(ctx.destination)
    const brown = noiseBuffer(ctx, 6, 'brown')
    const white = noiseBuffer(ctx, 2, 'white')
    this.brown = brown

    const loop = (buffer, rate = 1) => {
      const src = ctx.createBufferSource()
      src.buffer = buffer
      src.loop = true
      src.playbackRate.value = rate
      src.start(0, Math.random() * buffer.duration)
      return src
    }
    const lfo = (freq, depth, target, offset) => {
      const osc = ctx.createOscillator()
      osc.frequency.value = freq
      const g = ctx.createGain()
      g.gain.value = depth
      osc.connect(g).connect(target)
      target.value = offset
      osc.start()
    }

    // Feu : souffle sourd continu
    const fire = ctx.createBiquadFilter()
    fire.type = 'lowpass'
    fire.frequency.value = 420
    const fireGain = ctx.createGain()
    fireGain.gain.value = 0.28
    loop(brown, 0.9).connect(fire).connect(fireGain).connect(this.master)

    // Mer au loin : ressac lent, volume qui ondule toutes les ~9 s
    const sea = ctx.createBiquadFilter()
    sea.type = 'lowpass'
    sea.frequency.value = 320
    const seaGain = ctx.createGain()
    loop(brown, 0.6).connect(sea).connect(seaGain).connect(this.master)
    lfo(0.11, 0.12, seaGain.gain, 0.16)

    // Vent : souffle filtré dont la hauteur varie lentement
    const wind = ctx.createBiquadFilter()
    wind.type = 'bandpass'
    wind.Q.value = 0.8
    const windGain = ctx.createGain()
    windGain.gain.value = 0.05
    loop(white, 0.5).connect(wind).connect(windGain).connect(this.master)
    lfo(0.05, 180, wind.frequency, 520)

    // Pluie contre la vitre : bruit aigu filtré, muet par beau temps (setWeather)
    const rain = ctx.createBiquadFilter()
    rain.type = 'bandpass'
    rain.frequency.value = 4200
    rain.Q.value = 0.6
    this.rainGain = ctx.createGain()
    this.rainGain.gain.value = 0.07 * (this.rainLevel || 0)
    loop(white, 1.1).connect(rain).connect(this.rainGain).connect(this.master)

    // Crépitements du feu : brèves étincelles à intervalles aléatoires
    const crackle = () => {
      if (this.enabled) {
        const src = ctx.createBufferSource()
        src.buffer = white
        const bp = ctx.createBiquadFilter()
        bp.type = 'bandpass'
        bp.frequency.value = 1500 + Math.random() * 2500
        bp.Q.value = 2
        const g = ctx.createGain()
        const t = ctx.currentTime
        const peak = 0.05 + Math.random() * 0.12
        g.gain.setValueAtTime(0, t)
        g.gain.linearRampToValueAtTime(peak, t + 0.002)
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.02 + Math.random() * 0.05)
        src.connect(bp).connect(g).connect(this.master)
        src.start(t, Math.random() * 1.5, 0.1)
      }
      this._timers.push(setTimeout(crackle, 80 + Math.random() * (Math.random() < 0.2 ? 900 : 350)))
    }
    crackle()

    // Pendule : tic-tac à la seconde, deux hauteurs alternées
    let tock = false
    const tick = () => {
      if (this.enabled) {
        const src = ctx.createBufferSource()
        src.buffer = white
        const hp = ctx.createBiquadFilter()
        hp.type = 'bandpass'
        hp.frequency.value = tock ? 2600 : 3200
        hp.Q.value = 6
        const g = ctx.createGain()
        const t = ctx.currentTime
        g.gain.setValueAtTime(0.09, t)
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.012)
        src.connect(hp).connect(g).connect(this.master)
        src.start(t, Math.random(), 0.03)
        tock = !tock
      }
      this._timers.push(setTimeout(tick, 1000))
    }
    tick()
  }
}
