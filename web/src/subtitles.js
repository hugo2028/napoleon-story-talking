// Sous-titres défilants (mobile) : deux lignes au plus. Le texte monte au fil de la voix,
// les mots déjà prononcés s'éclairent ; à la fin de la réponse, les sous-titres s'effacent.

const HIDE_AFTER_MS = 4000

export class Subtitles {
  constructor(el) {
    this.el = el
    this.inner = document.createElement('div')
    this.inner.className = 'subtitles-inner'
    this.el.appendChild(this.inner)
    this.words = []
    this.index = -1
    this.hideTimer = null
  }

  /** Nouveau texte : affiché au début, rien encore de prononcé. */
  show(text) {
    clearTimeout(this.hideTimer)
    this.index = -1
    this.inner.style.transform = ''
    this.words = text.split(/\s+/).filter(Boolean).map((word) => {
      const span = document.createElement('span')
      span.textContent = `${word} `
      return span
    })
    this.inner.replaceChildren(...this.words)
    this.el.classList.toggle('visible', this.words.length > 0)
  }

  /** La voix en est au mot `i` : il s'éclaire, et sa ligne devient la dernière visible. */
  reach(i) {
    if (!this.words.length || i <= this.index) return
    const last = Math.min(i, this.words.length - 1)
    for (let k = this.index + 1; k <= last; k++) this.words[k].classList.add('said')
    this.index = last
    const lineHeight = parseFloat(getComputedStyle(this.inner).lineHeight) || 20
    const top = this.words[last].offsetTop
    this.inner.style.transform = `translateY(${-Math.max(0, top - lineHeight)}px)`
  }

  /** Fin de la réponse : tout est dit, puis les sous-titres disparaissent. */
  finish() {
    if (this.words.length) this.reach(this.words.length - 1)
    clearTimeout(this.hideTimer)
    this.hideTimer = setTimeout(() => this.el.classList.remove('visible'), HIDE_AFTER_MS)
  }

  clear() {
    clearTimeout(this.hideTimer)
    this.words = []
    this.index = -1
    this.inner.replaceChildren()
    this.el.classList.remove('visible')
  }
}
