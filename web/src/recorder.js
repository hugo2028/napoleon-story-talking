// Enregistrement d'une vidéo de démo : capture de l'onglet (image + son) avec l'API du navigateur,
// puis téléchargement d'un fichier .webm. Rien n'est envoyé à un serveur.

const MIME_CANDIDATES = [
  'video/webm;codecs=vp9,opus',
  'video/webm;codecs=vp8,opus',
  'video/webm',
]

export function recordingSupported() {
  return Boolean(navigator.mediaDevices?.getDisplayMedia && window.MediaRecorder)
}

export class DemoRecorder {
  constructor() {
    this.stream = null
    this.recorder = null
    this.chunks = []
    this.onStateChange = null   // (recording: boolean) => void
  }

  get recording() {
    return this.recorder?.state === 'recording'
  }

  /** Demande l'autorisation de capturer l'onglet. Renvoie { hasAudio }. */
  async start() {
    this.stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 30 },
      audio: true,                  // son de l'onglet : la voix de Napoléon
      preferCurrentTab: true,       // Chrome propose directement cet onglet
      selfBrowserSurface: 'include',
      surfaceSwitching: 'exclude',
      systemAudio: 'exclude',
    })
    const mimeType = MIME_CANDIDATES.find(m => MediaRecorder.isTypeSupported(m)) || ''
    this.chunks = []
    this.recorder = new MediaRecorder(this.stream, {
      ...(mimeType ? { mimeType } : {}),
      videoBitsPerSecond: 8_000_000,
    })
    this.recorder.ondataavailable = (e) => { if (e.data.size > 0) this.chunks.push(e.data) }
    this.recorder.onstop = () => this._save()
    // L'utilisateur peut aussi arrêter via la barre « Arrêter le partage » de Chrome
    for (const track of this.stream.getVideoTracks()) track.addEventListener('ended', () => this.stop())
    this.recorder.start(1000)
    this.onStateChange?.(true)
    return { hasAudio: this.stream.getAudioTracks().length > 0 }
  }

  stop() {
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop()
    for (const track of this.stream?.getTracks() ?? []) track.stop()
    this.stream = null
  }

  _save() {
    const blob = new Blob(this.chunks, { type: this.recorder?.mimeType || 'video/webm' })
    this.chunks = []
    this.recorder = null
    this.onStateChange?.(false)
    if (!blob.size) return
    const stamp = new Date().toISOString().slice(0, 16).replace(/[-:]/g, '').replace('T', '-')
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `napoleon-demo-${stamp}.webm`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  }
}
