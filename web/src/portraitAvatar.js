// Avatar de repli quand web/avatar/avatar.glb est absent (dépôt public : le modèle 3D n'est pas
// distribué). Médaillon 2D en SVG — silhouette au bicorne — qui s'anime quand Napoléon parle.
// Même interface que AvatarPlayer : main.js et speechSynth.js n'ont rien à changer.

const SVG = `
<svg class="portrait-svg" viewBox="0 0 400 400" role="img" aria-label="Napoléon Bonaparte">
  <defs>
    <radialGradient id="portrait-bg" cx="50%" cy="42%" r="60%">
      <stop offset="0" stop-color="#2a2318"/>
      <stop offset="1" stop-color="#0c0a08"/>
    </radialGradient>
  </defs>
  <circle cx="200" cy="200" r="186" fill="url(#portrait-bg)"/>
  <circle class="portrait-ring" cx="200" cy="200" r="186" fill="none" stroke="#c9a84c" stroke-width="3"/>
  <circle cx="200" cy="200" r="174" fill="none" stroke="#c9a84c" stroke-opacity="0.35" stroke-width="1"/>
  <g class="portrait-bust" fill="#c9a84c">
    <!-- buste : épaulettes et col droit de l'uniforme -->
    <path d="M92 372 C96 330 120 304 160 294 C172 290 184 286 190 280 L196 262 L240 258
             C244 272 250 284 262 292 C300 302 318 330 322 372 Z"/>
    <!-- tête de profil, regard vers la gauche : front, nez, lèvres, menton -->
    <path d="M176 150 L250 148 C262 164 268 186 264 210 C262 230 256 248 244 262 L198 268
             C186 262 176 256 170 250 C164 244 162 238 163 232 C160 230 158 227 159 224
             C156 222 155 219 158 216 C155 214 153 212 154 209 C148 207 144 204 145 200
             C150 194 156 188 160 182 C162 172 166 160 176 150 Z"/>
    <!-- mâchoire (lèvre inférieure et menton) : s'ouvre légèrement avec les visèmes -->
    <path class="portrait-jaw" d="M159 224 C158 228 160 232 163 233 C162 240 166 248 174 254
             C182 260 192 264 202 266 L206 246 C196 240 186 232 178 226 Z"/>
    <!-- mèche sur le front -->
    <path d="M174 152 C168 160 166 168 168 174 C172 166 178 160 186 156 Z"/>
    <!-- bicorne « en bataille » : demi-lune vue de profil -->
    <path d="M140 160 C150 118 182 90 214 88 C246 90 278 118 290 160
             C262 150 234 146 214 146 C194 146 166 150 140 160 Z"/>
    <path d="M140 160 C166 150 194 146 214 146 C234 146 262 150 290 160" fill="none"
          stroke="#0c0a08" stroke-opacity="0.45" stroke-width="2"/>
    <!-- cocarde -->
    <circle cx="190" cy="118" r="9" fill="#0c0a08"/>
    <circle cx="190" cy="118" r="5.5"/>
  </g>
</svg>`

const STYLE = `
.portrait-avatar { width: 100%; height: 100%; display: grid; place-items: center; }
.portrait-svg { width: min(78%, 70vh); height: auto; filter: drop-shadow(0 10px 40px rgba(0,0,0,.6)); }
.portrait-bust { transform-origin: 200px 300px; transition: transform .6s ease; }
.portrait-avatar.speaking .portrait-bust { animation: portrait-breathe 3.2s ease-in-out infinite; }
.portrait-jaw { transform-origin: 158px 222px; transition: transform 70ms linear; }
.portrait-ring { transition: stroke-opacity .2s, stroke-width .2s; }
.portrait-avatar.speaking .portrait-ring { stroke-width: 4; }
@keyframes portrait-breathe { 50% { transform: rotate(-1.2deg) translateY(-2px); } }
@media (prefers-reduced-motion: reduce) {
  .portrait-avatar.speaking .portrait-bust { animation: none; }
}`

export class PortraitAvatar {
  constructor(container) {
    this.container = container
    this.isSpeaking = false
    this._visemeTimer = null
    if (!document.getElementById('portrait-avatar-style')) {
      const style = document.createElement('style')
      style.id = 'portrait-avatar-style'
      style.textContent = STYLE
      document.head.appendChild(style)
    }
    this.root = document.createElement('div')
    this.root.className = 'portrait-avatar'
    this.root.innerHTML = SVG
    container.replaceChildren(this.root)
    this.jaw = this.root.querySelector('.portrait-jaw')
    this.ring = this.root.querySelector('.portrait-ring')
  }

  static async create(container) {
    return new PortraitAvatar(container)
  }

  /** Visème Azure (0 = silence) : la mâchoire s'ouvre, le cercle s'illumine. */
  setViseme(id) {
    const open = id === 0 ? 0 : 0.35 + ((id * 37) % 10) / 16
    this._setOpen(open)
    clearTimeout(this._visemeTimer)
    this._visemeTimer = setTimeout(() => this._setOpen(0), 140)
  }

  _setOpen(amount) {
    this.jaw.style.transform = `rotate(${(-amount * 9).toFixed(2)}deg)`
    this.ring.style.strokeOpacity = String(0.65 + amount * 0.35)
  }

  startTalking() {
    this.isSpeaking = true
    this.root.classList.add('speaking')
  }

  stopTalking() {
    this.isSpeaking = false
    this.root.classList.remove('speaking')
    this._setOpen(0)
  }

  switchAnimation() { return true }
  setCameraMode() {}
  destroy() { clearTimeout(this._visemeTimer) }
}
