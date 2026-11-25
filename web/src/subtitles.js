// Sous-titres défilants (mobile) : deux lignes au plus. Le texte monte au fil de la voix,
// les mots déjà prononcés s'éclairent ; à la fin de la réponse, les sous-titres s'effacent.
// Un toucher déplie le texte entier (défilement au doigt, il ne s'efface plus) ; un second le replie.

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
    this.finished = false
    this.el.setAttribute('role', 'button')
    this.el.tabIndex = 0
    this.el.addEventListener('click', () => this.toggle())
    this.el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.toggle() }
    })
  }

  get expanded() {
    return this.el.classList.contains('expanded')
  }

  /** Déplie ou replie le texte complet. */
  toggle(force) {
    if (!this.words.length) return
    const open = force ?? !this.expanded
    this.el.classList.toggle('expanded', open)
    this.el.setAttribute('aria-expanded', String(open))
    if (open) {
      clearTimeout(this.hideTimer)
      this.inner.style.transform = ''
      // Le mot en cours de lecture reste en vue
      const current = this.words[Math.max(0, this.index)]
      if (current) this.el.scrollTop = Math.max(0, current.offsetTop - this.el.clientHeight / 3)
    } else {
      this.el.scrollTop = 0
      this._follow()
      if (this.finished) this._scheduleHide()
    }
  }

  /** Nouveau texte : affiché au début, rien encore de prononcé. */
  show(text) {
    clearTimeout(this.hideTimer)
    this.index = -1
    this.finished = false
    this.inner.style.transform = ''
    this.el.scrollTop = 0
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
    if (!this.expanded) this._follow()   // déplié : le lecteur fait défiler lui-même
  }

  _follow() {
    if (this.index < 0) { this.inner.style.transform = ''; return }
    const lineHeight = parseFloat(getComputedStyle(this.inner).lineHeight) || 20
    const top = this.words[this.index].offsetTop
    this.inner.style.transform = `translateY(${-Math.max(0, top - lineHeight)}px)`
  }

  _scheduleHide() {
    clearTimeout(this.hideTimer)
    this.hideTimer = setTimeout(() => this.el.classList.remove('visible'), HIDE_AFTER_MS)
  }

  /** Fin de la réponse : tout est dit, puis les sous-titres disparaissent (sauf s'ils sont dépliés). */
  finish() {
    if (this.words.length) this.reach(this.words.length - 1)
    this.finished = true
    if (!this.expanded) this._scheduleHide()
  }

  clear() {
    clearTimeout(this.hideTimer)
    this.words = []
    this.index = -1
    this.finished = false
    this.inner.replaceChildren()
    this.el.classList.remove('visible', 'expanded')
    this.el.scrollTop = 0
  }
}
