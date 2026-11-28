// Mise en scène du décor de Longwood choisie par l'archiviste : le temps derrière la fenêtre et le tableau mural
// (la carte d'Hérisson de 1815, ses lieux, les lettres racontées). Le reste est dessiné dans le navigateur.
import * as THREE from 'three'
import { MAP_PLACES, MAP_FIT } from './mapPlaces.js'

// ── Temps qu'il fait ─────────────────────────────────────────────────────────
// brouillard (0-1), pluie (0-1), orage (0/1)
const WEATHER = {
  clair: { fog: 0, rain: 0, storm: 0 },
  brume: { fog: 0.85, rain: 0, storm: 0 },
  pluie: { fog: 0.35, rain: 1, storm: 0 },
  orage: { fog: 0.45, rain: 1, storm: 1 },
}

function rainTexture() {
  const c = document.createElement('canvas')
  c.width = 128
  c.height = 256
  const ctx = c.getContext('2d')
  ctx.strokeStyle = 'rgba(200, 215, 235, 0.55)'
  ctx.lineWidth = 1
  for (let k = 0; k < 70; k++) {
    const x = Math.random() * 128
    const y = Math.random() * 256
    const len = 10 + Math.random() * 22
    ctx.globalAlpha = 0.3 + Math.random() * 0.7
    ctx.beginPath()
    ctx.moveTo(x, y)
    ctx.lineTo(x - len * 0.12, y + len)
    ctx.stroke()
  }
  const tex = new THREE.CanvasTexture(c)
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping
  tex.repeat.set(1.5, 1.2)
  return tex
}

export class Weather {
  /** `sky` : centre du ciel derrière la fenêtre ; la fenêtre est 2,5 m devant, 0,2 m plus bas. */
  constructor(scene, sky) {
    this.state = { ...WEATHER.clair }
    this.target = { ...WEATHER.clair }
    this.flash = 0
    this.nextFlash = 4
    this.onLightning = null
    const basic = (opts) => new THREE.MeshBasicMaterial({ toneMapped: false, transparent: true, depthWrite: false, ...opts })
    // Brume : un voile gris-bleu entre le ciel et la fenêtre
    this.fog = new THREE.Mesh(new THREE.PlaneGeometry(6, 4.2), basic({ color: 0x5d6672, opacity: 0 }))
    this.fog.position.copy(sky).add(new THREE.Vector3(0, 0, 0.6))
    // Pluie : des filets qui tombent derrière la vitre
    this.rainTex = rainTexture()
    this.rain = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 2.2), basic({ map: this.rainTex, opacity: 0 }))
    this.rain.position.copy(sky).add(new THREE.Vector3(0, -0.2, 2.2))
    // Éclair : le ciel blanchit un instant
    this.bolt = new THREE.Mesh(new THREE.PlaneGeometry(6, 4.2),
      basic({ color: 0xdfe6ff, opacity: 0, blending: THREE.AdditiveBlending }))
    this.bolt.position.copy(sky).add(new THREE.Vector3(0, 0, 0.7))
    scene.add(this.fog, this.rain, this.bolt)
  }

  set(kind) {
    if (WEATHER[kind]) this.target = { ...WEATHER[kind] }
  }

  /** Avance d'une image ; renvoie l'éclat de l'éclair (0-1) pour éclairer la pièce. */
  update(t, dt) {
    const k = Math.min(1, dt * 0.4)                         // transitions de quelques secondes
    for (const key of ['fog', 'rain', 'storm']) this.state[key] += (this.target[key] - this.state[key]) * k
    this.fog.material.opacity = 0.75 * this.state.fog
    this.rain.material.opacity = 0.8 * this.state.rain
    this.rainTex.offset.y += dt * 2.2
    this.rainTex.offset.x += dt * 0.25
    // Éclairs : un double éclat à intervalles irréguliers, seulement par temps d'orage
    if (this.state.storm > 0.5 && t > this.nextFlash) {
      this.flash = 1
      this.nextFlash = t + 6 + Math.random() * 12
      this.secondFlashAt = t + 0.12 + Math.random() * 0.15
      this.onLightning?.()
    }
    if (this.secondFlashAt && t > this.secondFlashAt) {
      this.flash = Math.max(this.flash, 0.7)
      this.secondFlashAt = null
    }
    this.flash = Math.max(0, this.flash - dt * 4)
    this.bolt.material.opacity = 0.9 * this.flash
    return this.flash
  }
}

// ── Carte murale : la carte d'Hérisson (1815) et ses lieux ───────────────────
// Eustache Hérisson, « Carte de l'Europe dans son état actuel, comprenant en outre une partie de l'Asie, de
// l'Afrique et la mer Méditerranée », Paris, Desray et J. Goujon, 1815 (BnF, Cartes et plans, GE C-8218),
// domaine public. Recadrée et calée par scripts/build_map_places.py, qui écrit aussi mapPlaces.js.
const MAP_URL = new URL('../decor/carte_herisson_1815.jpg', import.meta.url).href
const MAP_ASPECT = 1800 / 1346
const LW = 1800, LH = 1346                     // taille du calque des noms (mêmes proportions que la carte)
/**
 * Lieux de la carte nommés dans un texte : [{ index du mot, nom }], dans l'ordre. Les mots sont ceux des
 * sous-titres (texte coupé aux espaces), pour suivre la voix mot à mot. Accents, majuscules, ponctuation et
 * élisions (« d'Arcole ») sont ignorés ; « Le Caire » est aussi reconnu par « Caire ».
 */
const PLACE_ALIASES = { 'La Moskowa': ['moskova', 'borodino'], 'Baylen': ['bailen'], "Saint-Jean-d'Acre": ['acre'] }
const fold = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/’/g, "'")
const cleanWord = (w) => fold(w).replace(/^[«"(\[]+|[»".,;:!?)\]]+$/g, '')
const PLACE_KEYS = MAP_PLACES.flatMap((p) => {
  const words = fold(p.name).split(/\s+/)
  const keys = [words]
  if (words.length > 1 && ['le', 'la', 'les'].includes(words[0])) keys.push(words.slice(1))
  for (const a of PLACE_ALIASES[p.name] || []) keys.push([a])
  return keys.map((k) => ({ name: p.name, words: k }))
}).sort((a, b) => b.words.length - a.words.length)

export function findPlaceMentions(text) {
  const words = text.split(/\s+/).filter(Boolean).map(cleanWord)
  const bare = words.map((w) => w.replace(/^(?:l|d|qu|jusqu)'/, ''))
  const out = []
  for (let i = 0; i < words.length; i++) {
    const hit = PLACE_KEYS.find((k) => k.words.every((kw, j) => words[i + j] === kw || (j === 0 && bare[i] === kw)))
    if (hit) {
      out.push({ index: i, name: hit.name })
      i += hit.words.length - 1
    }
  }
  return out
}

/** Position (u, v de 0 à 1) d'un point (longitude, latitude) sur la carte gravée : même calage que
 * scripts/build_map_places.py (polynôme, puis écart des repères réparti en inverse du carré de la distance). */
export function lonLatToUV(lon, lat) {
  const f = [1, lon, lat, lon * lon, lat * lat, lon * lat]
  let x = f.reduce((s, v, i) => s + v * MAP_FIT.cx[i], 0)
  let y = f.reduce((s, v, i) => s + v * MAP_FIT.cy[i], 0)
  let wsum = 0, dx = 0, dy = 0
  for (const [clon, clat, rx, ry] of MAP_FIT.control) {
    const d2 = (clon - lon) ** 2 + (clat - lat) ** 2
    if (d2 < 1e-9) { wsum = 1; dx = rx; dy = ry; break }
    wsum += 1 / d2; dx += rx / d2; dy += ry / d2
  }
  x += dx / wsum; y += dy / wsum
  const [x0, y0, x1, y1] = MAP_FIT.crop
  return { u: (x - x0) / (x1 - x0), v: (y - y0) / (y1 - y0) }
}

/** Ajoute à la carte un lieu nommé dans un récit (mémoire du visiteur) ; null s'il tombe hors de la gravure. */
export function addMapPlace(name, lon, lat) {
  if (!name || lon == null || lat == null) return null
  if (MAP_PLACES.some((p) => p.name === name)) return name
  const { u, v } = lonLatToUV(lon, lat)
  if (!(u > 0.01 && u < 0.99 && v > 0.01 && v < 0.99)) return null
  MAP_PLACES.push({ name, u: Math.round(u * 1e4) / 1e4, v: Math.round(v * 1e4) / 1e4, region: 'visite' })
  return name
}

const REGIONS = new Set([...MAP_PLACES.map((p) => p.region).filter(Boolean), 'sainte_helene'])

/**
 * Un lieu : son point, et son nom s'il ne chevauche aucun nom déjà posé (`taken` : rectangles occupés).
 * Les lieux sont posés par ordre d'importance : le lieu prononcé, ceux déjà cités, la région, les capitales.
 */
function placeLabel(ctx, place, color, size, bold, taken) {
  const x = place.u * LW, y = place.v * LH
  ctx.beginPath()
  ctx.arc(x, y, bold ? 10 : 7, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.fill()
  ctx.font = `${bold ? 'bold ' : ''}italic ${size}px Georgia, serif`
  const w = ctx.measureText(place.name).width
  const right = place.u > 0.85
  const tx = x + (right ? -14 : 14)
  const box = [right ? tx - w : tx, y - 10 - size * 0.8, right ? tx : tx + w, y - 10 + size * 0.25]
  if (taken.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) return
  taken.push(box)
  ctx.textAlign = right ? 'right' : 'left'
  ctx.lineWidth = 9
  ctx.strokeStyle = 'rgba(246, 236, 210, 0.9)'      // halo de papier clair : le nom se détache de la gravure
  ctx.strokeText(place.name, tx, y - 10)
  ctx.fillStyle = color
  ctx.fillText(place.name, tx, y - 10)
}

/**
 * Calque transparent des noms. `focus` : le lieu que Napoléon prononce, en grand ; `said` : ceux qu'il a déjà
 * cités ; puis les lieux de la région et les capitales, dont le nom s'efface s'il chevauche un nom plus important.
 */
function drawLabels(region, focus = null, said = []) {
  const c = document.createElement('canvas')
  c.width = LW
  c.height = LH
  const ctx = c.getContext('2d')
  const taken = []
  const byName = (n) => MAP_PLACES.find((p) => p.name === n)
  const done = new Set()
  const put = (p, color, size, bold) => {
    if (!p || done.has(p.name)) return
    done.add(p.name)
    placeLabel(ctx, p, color, size, bold, taken)
  }
  put(byName(focus), '#9a1c10', 76, true)
  for (const n of [...said].reverse()) put(byName(n), '#9a1c10', 52, true)
  if (region) for (const p of MAP_PLACES) if (p.region === region) put(p, '#9a1c10', focus ? 50 : 62, !focus)
  for (const p of MAP_PLACES) if (!p.region) put(p, '#3b2610', 50, false)
  // Cartouche sur le Sahara, en bas à gauche
  ctx.fillStyle = 'rgba(240, 228, 196, 0.92)'
  ctx.strokeStyle = '#5a3d18'
  ctx.lineWidth = 4
  ctx.fillRect(40, LH - 150, 640, 110)
  ctx.strokeRect(40, LH - 150, 640, 110)
  ctx.textAlign = 'center'
  ctx.fillStyle = '#3b2610'
  ctx.font = 'italic 48px Georgia, serif'
  ctx.fillText('Europe et Méditerranée', 360, LH - 92)
  ctx.font = 'italic 28px Georgia, serif'
  ctx.fillText('d\'après Hérisson, Paris, 1815', 360, LH - 58)
  if (region === 'sainte_helene') {             // hors de la carte, très loin au sud
    ctx.font = 'bold italic 46px Georgia, serif'
    ctx.textAlign = 'left'
    ctx.lineWidth = 9
    ctx.strokeStyle = 'rgba(246, 236, 210, 0.9)'
    ctx.strokeText('↓ Sainte-Hélène, à 1 900 lieues', 720, LH - 70)
    ctx.fillStyle = '#9a1c10'
    ctx.fillText('↓ Sainte-Hélène, à 1 900 lieues', 720, LH - 70)
  }
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

/** Lueur chaude sur les lieux de la région (ou sur la flèche de Sainte-Hélène). */
function drawGlow(region, focus = null) {
  const c = document.createElement('canvas')
  c.width = LW / 4
  c.height = LH / 4
  const ctx = c.getContext('2d')
  const focused = MAP_PLACES.find((p) => p.name === focus)
  const pts = focused ? [focused] : MAP_PLACES.filter((p) => p.region === region)
  const spots = pts.length ? pts.map((p) => [p.u * c.width, p.v * c.height]) : [[0.6 * c.width, 0.93 * c.height]]
  const r = pts.length > 1 ? 46 : 60
  for (const [x, y] of spots) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r)
    g.addColorStop(0, 'rgba(255, 190, 100, 0.3)')
    g.addColorStop(0.6, 'rgba(255, 150, 60, 0.12)')
    g.addColorStop(1, 'rgba(255, 140, 50, 0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, c.width, c.height)
  }
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

// ── Tableau mural : la carte et les lettres racontées ───────────────────────
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre',
  'novembre', 'décembre']

function dateFr(iso = '') {
  const [y, m, d] = String(iso).split('-').map(Number)
  if (!y) return ''
  if (!m) return String(y)
  return `${d ? (d === 1 ? '1er' : d) + ' ' : ''}${MOIS[m - 1]} ${y}`
}

function baizeTexture() {
  const c = document.createElement('canvas')
  c.width = c.height = 256
  const ctx = c.getContext('2d')
  ctx.fillStyle = '#1f3a26'                                   // feutre vert sombre
  ctx.fillRect(0, 0, 256, 256)
  for (let k = 0; k < 2500; k++) {                            // grain du drap
    ctx.fillStyle = `rgba(${Math.random() < 0.5 ? '0,0,0' : '120,150,110'},${Math.random() * 0.08})`
    ctx.fillRect(Math.random() * 256, Math.random() * 256, 1.5, 1.5)
  }
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping
  tex.repeat.set(4, 2.4)
  return tex
}

function wrapLines(ctx, text, maxWidth, maxLines) {
  const words = String(text || '').split(/\s+/).filter(Boolean)
  const lines = []
  let line = ''
  let used = 0
  for (const w of words) {
    const test = line ? `${line} ${w}` : w
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line)
      line = w
      if (lines.length === maxLines) break
    } else line = test
    used++
  }
  if (lines.length < maxLines && line) lines.push(line)
  if (used < words.length && lines.length) lines[lines.length - 1] = lines[lines.length - 1].replace(/\s*\S*$/, ' …')
  return lines
}

/** Une lettre épinglée : date, destinataire, premiers mots à la plume, cachet de cire. */
/** Cartel sous l'œuvre : titre, peintre et date, crédit. */
function captionTexture(info) {
  // Le titre entier, sur deux lignes au besoin (la police se réduit avant de couper)
  const w = 1000
  const measure = document.createElement('canvas').getContext('2d')
  let size = 40, lines
  for (; size >= 26; size -= 2) {
    measure.font = `italic ${size}px Georgia, serif`
    lines = wrapLines(measure, info.titre || '', w - 60, 3)
    if (lines.length <= 2) break
  }
  const lh = size * 1.2
  const h = Math.round(28 + lines.length * lh + 46)
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const ctx = c.getContext('2d')
  ctx.fillStyle = '#efe4c8'
  ctx.fillRect(0, 0, w, h)
  ctx.strokeStyle = '#7a5a2a'
  ctx.lineWidth = 5
  ctx.strokeRect(4, 4, w - 8, h - 8)
  ctx.textAlign = 'center'
  ctx.fillStyle = '#2e2010'
  ctx.font = `italic ${size}px Georgia, serif`
  lines.forEach((l, k) => ctx.fillText(l, w / 2, 22 + size + k * lh))
  ctx.font = '28px Georgia, serif'
  ctx.fillStyle = '#5a4020'
  ctx.fillText([info.peintre, info.date].filter(Boolean).join(', '), w / 2, h - 22)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return { tex, aspect: h / w }
}

const PAINTING_URLS = import.meta.glob('../decor/tableaux/*.jpg', { eager: true, query: '?url', import: 'default' })
const paintingUrl = (id) => PAINTING_URLS[`../decor/tableaux/${id}.jpg`] || null

function letterTexture(source) {
  const w = 384, h = 500
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const ctx = c.getContext('2d')
  const g = ctx.createLinearGradient(0, 0, w, h)
  g.addColorStop(0, '#e6d7b0')
  g.addColorStop(1, '#cdb98a')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)
  ctx.strokeStyle = 'rgba(90,60,20,0.35)'
  ctx.lineWidth = 3
  ctx.strokeRect(6, 6, w - 12, h - 12)
  ctx.fillStyle = '#2e1f0c'
  ctx.textAlign = 'center'
  ctx.font = 'bold italic 34px Georgia, serif'
  ctx.fillText({ oeuvres: 'Ses écrits', fiche: 'Souvenir' }[source.kind] || dateFr(source.date), w / 2, 62)
  ctx.font = 'italic 24px Georgia, serif'
  const title = (source.title || '').replace(/\.$/, '').toLowerCase().replace(/^./, (ch) => ch.toUpperCase())
  wrapLines(ctx, title, w - 50, 3).forEach((l, k) => ctx.fillText(l, w / 2, 104 + k * 30))
  ctx.textAlign = 'left'
  ctx.font = 'italic 21px Georgia, serif'
  ctx.fillStyle = 'rgba(46,31,12,0.85)'
  // Le texte de la lettre, autant qu'en contient la feuille (la lettre entière s'ouvre d'un clic)
  const body = (source.text || source.snippet || '').replace(/\s+/g, ' ')
  const lines = wrapLines(ctx, body, w - 56, 7)   // au-dessus du cachet
  const more = lines.join(' ').length < body.length - 5           // la lettre continue au-delà de la feuille
  lines.forEach((l, k) => ctx.fillText(more && k === lines.length - 1 ? `${l.replace(/\s*\S*$/, '')} …` : l, 28, 222 + k * 28))
  ctx.beginPath()                                             // cachet de cire
  ctx.arc(w - 62, h - 62, 30, 0, Math.PI * 2)
  ctx.fillStyle = '#7d1712'
  ctx.fill()
  ctx.font = 'bold 30px Georgia, serif'
  ctx.fillStyle = '#b8463a'
  ctx.textAlign = 'center'
  ctx.fillText('N', w - 62, h - 51)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

export class WallBoard {
  /**
   * Tableau de feutre vert encadré, accroché au mur du fond : la carte de l'Europe épinglée à gauche
   * (une région s'y éclaire) et les lettres de la réponse en cours épinglées à droite.
   */
  constructor(scene, center, width = 3.0, height = 1.1) {
    this.group = new THREE.Group()
    this.group.position.copy(center)
    this.materials = []                                       // assombris avec la pièce (feu, nuit)
    const basic = (opts) => {
      const m = new THREE.MeshBasicMaterial({ toneMapped: false, ...opts })
      m.userData.base = m.color.clone()                       // couleur propre, assombrie avec la pièce
      this.materials.push(m)
      return m
    }
    this.basic = basic
    this.group.add(new THREE.Mesh(new THREE.PlaneGeometry(width, height), basic({ map: baizeTexture() })))
    const wood = basic({ color: 0x3a2412 })
    const b = 0.05
    for (const [w, h, x, y] of [[width + 2 * b, b, 0, (height + b) / 2], [width + 2 * b, b, 0, -(height + b) / 2],
      [b, height, (width + b) / 2, 0], [b, height, -(width + b) / 2, 0]]) {
      const bar = new THREE.Mesh(new THREE.BoxGeometry(w, h, 0.04), wood)
      bar.position.set(x, y, 0.015)
      this.group.add(bar)
    }
    // Carte gravée, à gauche, légèrement de biais, épinglée aux coins ; par-dessus, la lueur de la région
    // et le calque des noms (capitales, lieux de la région en rouge, cartouche)
    const mapH = height - 0.12
    const mapW = mapH * MAP_ASPECT
    this.mapSize = { w: mapW, h: mapH }
    this.lastActivity = -Infinity                              // dernier changement visible (isActive)
    this.map = new THREE.Group()
    this.map.position.set(-width / 2 + mapW / 2 + 0.06, 0, 0.005)
    this.map.rotation.z = 0.01
    const mapTex = new THREE.TextureLoader().load(MAP_URL)
    mapTex.colorSpace = THREE.SRGBColorSpace
    mapTex.anisotropy = 4
    this.mapMesh = new THREE.Mesh(new THREE.PlaneGeometry(mapW, mapH), basic({ map: mapTex }))
    this.map.add(this.mapMesh)
    this.glow = new THREE.Mesh(new THREE.PlaneGeometry(mapW, mapH), new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false,
    }))
    this.glow.position.z = 0.002
    this.map.add(this.glow)
    this.labels = new THREE.Mesh(new THREE.PlaneGeometry(mapW, mapH),
      basic({ map: drawLabels(null), transparent: true, depthWrite: false }))
    this.labels.position.z = 0.003
    this.map.add(this.labels)
    this.pinMat = basic({ color: 0x8a1c14 })
    for (const [x, y] of [[-1, 1], [1, 1], [-1, -1], [1, -1]]) {
      const pin = new THREE.Mesh(new THREE.SphereGeometry(0.011, 8, 6), this.pinMat)
      pin.position.set(x * (mapW / 2 - 0.02), y * (mapH / 2 - 0.02), 0.01)
      this.map.add(pin)
    }
    this.group.add(this.map)
    // Les lettres, à droite
    // Œuvre (tableau choisi par l'archiviste) au milieu ; les lettres à droite, ou sur toute la place libre
    const free0 = -width / 2 + mapW + 0.14
    this.paintArea = { x0: free0, x1: free0 + 0.82, h: height - 0.2 }
    this.letterSpan = { full: { x0: free0, x1: width / 2 - 0.05 }, side: { x0: free0 + 0.9, x1: width / 2 - 0.05 } }
    this.letterArea = this.letterSpan.full
    this.painting = null
    this.letters = []
    this.lettersKey = ''
    this.glowTarget = 0
    this.region = null
    this.focus = null            // lieu que Napoléon est en train de nommer
    this.said = []               // lieux déjà nommés dans la réponse en cours
    scene.add(this.group)
  }

  highlight(region) {
    if (!REGIONS.has(region) || region === this.region) return
    this.region = region
    this.focus = null
    this.said = []
    this._redraw()
    this.glow.material.opacity = 0
    this._touch()
  }

  _touch() {
    this.lastActivity = performance.now()
  }

  /** Le tableau vient de changer (région, lieu nommé, œuvre, lettres) : la caméra le garde en vue. */
  isActive(windowMs = 9000) {
    return performance.now() - this.lastActivity < windowMs
  }

  /**
   * Point du tableau qui retient l'attention, en coordonnées du monde : le lieu que Napoléon nomme sur la
   * carte, sinon l'œuvre épinglée, sinon les lettres, sinon le centre de la carte.
   */
  attentionPoint() {
    const p = MAP_PLACES.find((q) => q.name === this.focus)
    if (p) return this.map.localToWorld(new THREE.Vector3((p.u - 0.5) * this.mapSize.w, (0.5 - p.v) * this.mapSize.h, 0))
    if (this.painting && !this.painting.fading) return this.painting.mesh.getWorldPosition(new THREE.Vector3())
    if (this.lastSources?.length) {
      const { x0, x1 } = this.letterArea
      return this.group.localToWorld(new THREE.Vector3((x0 + x1) / 2, 0, 0))
    }
    return this.map.getWorldPosition(new THREE.Vector3())
  }

  /** Napoléon nomme un lieu : il s'éclaire et son nom passe au premier plan ; le précédent reste nommé. */
  focusPlace(name) {
    if (!MAP_PLACES.some((p) => p.name === name) || name === this.focus) return
    if (this.focus) this.said = [...this.said.filter((n) => n !== this.focus), this.focus]
    this.focus = name
    this._redraw()
    this.glow.material.opacity = 0.15
    this._touch()
  }

  /** Nouvelle réponse : plus de lieu en cours ; la région reste éclairée. */
  resetPlaces() {
    if (!this.focus && !this.said.length) return
    this.focus = null
    this.said = []
    this._redraw()
  }

  _redraw() {
    this._swapMap(this.glow.material, drawGlow(this.region, this.focus))
    this._swapMap(this.labels.material, drawLabels(this.region, this.focus, this.said))
    this.glowTarget = this.region || this.focus ? 1 : 0
  }

  clear() {
    this.region = null
    this.focus = null
    this.said = []
    this.glowTarget = 0
    this._swapMap(this.labels.material, drawLabels(null))
    this.showPainting(null)
    this.showLetters([])
  }

  _swapMap(material, texture) {
    const old = material.map
    material.map = texture
    material.needsUpdate = true
    old?.dispose()
  }

  /**
   * Une œuvre épinglée entre la carte et les lettres, avec son cartel ({ id, titre, peintre, date }) ;
   * null l'enlève. Les lettres se resserrent à droite pendant qu'elle est là.
   */
  showPainting(info) {
    const id = info?.id || null
    if (id === (this.painting?.info.id || null)) return
    if (this.painting) {
      this.painting.fading = true
      this.letters.push(this.painting)            // s'efface avec les mêmes règles que les lettres
      this.painting = null
    }
    const url = id && paintingUrl(id)
    const span = url ? this.letterSpan.side : this.letterSpan.full
    if (span !== this.letterArea) {
      this.letterArea = span
      const key = this.lettersKey
      this.lettersKey = null
      this.showLetters(this.lastSources || [], true)
      this.lettersKey = key
    }
    if (!url) return
    const { x0, x1, h } = this.paintArea
    const group = new THREE.Group()
    group.position.set((x0 + x1) / 2, 0.06, 0.012)
    group.rotation.z = -0.008
    const mat = this.basic({ transparent: true, opacity: 0 })
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat)
    mesh.userData.painting = { ...info, url }     // repéré au clic (avatar.js) pour l'afficher en grand
    group.add(mesh)
    const caption = captionTexture(info)
    const capW = Math.min(0.66, x1 - x0 - 0.04)     // aussi large que la place le permet
    const capH = capW * caption.aspect
    const capMat = this.basic({ map: caption.tex, transparent: true, opacity: 0 })
    const cap = new THREE.Mesh(new THREE.PlaneGeometry(capW, capH), capMat)
    group.add(cap)
    new THREE.TextureLoader().load(url, (tex) => {
      tex.colorSpace = THREE.SRGBColorSpace
      tex.anisotropy = 4
      const aspect = tex.image.width / tex.image.height
      const maxW = x1 - x0 - 0.04, maxH = h - 0.06 - capH
      const pw = Math.min(maxW, maxH * aspect), ph = pw / aspect
      mesh.scale.set(pw, ph, 1)
      mesh.position.y = 0.05
      mesh.position.y = capH / 2
      cap.position.y = mesh.position.y - ph / 2 - 0.012 - capH / 2
      mat.map = tex
      mat.needsUpdate = true
      const pin = new THREE.Mesh(new THREE.SphereGeometry(0.012, 8, 6), this.pinMat)
      pin.position.set(0, 0.05 + ph / 2 - 0.02, 0.006)
      group.add(pin)
    })
    this.group.add(group)
    this.painting = { mesh: group, mat, mats: [mat, capMat], info, fading: false, delay: 0.2, target: mesh }
    this._touch()
    this.letters.push(this.painting)
  }

  /**
   * Objets du tableau que le visiteur peut regarder de près : la carte, l'œuvre épinglée, les lettres du tour.
   * Chacun : { id, label, meshes } (maillages à cadrer et à viser).
   */
  pois() {
    const out = [{ id: 'carte', label: 'La carte de l\'Europe', meshes: [this.mapMesh] }]
    if (this.painting && !this.painting.fading && this.painting.target.scale.x !== 1) {
      // La toile et son cartel (les plans du groupe ; l'épingle n'en est pas)
      const planes = this.painting.mesh.children.filter((m) => m.isMesh && m.geometry.type === 'PlaneGeometry')
      out.push({ id: 'tableau', label: this.painting.info.titre || 'L\'œuvre', meshes: planes })
    }
    const letters = this.letters.filter((l) => l !== this.painting && !l.fading).map((l) => l.mesh)
    if (letters.length) out.push({ id: 'lettres', label: letters.length > 1 ? 'Les lettres' : 'La lettre', meshes: letters })
    return out
  }

  /** Le maillage de l'œuvre affichée (pour le clic) ; null s'il n'y en a pas. */
  paintingMesh() {
    return this.painting?.target || null
  }

  /** Les lettres de la réponse (sources de l'API : date, titre, extrait) ; trois au plus. */
  showLetters(sources = [], relayout = false) {
    const list = (sources || []).filter((s) => s && (s.date || s.title)).slice(0, 3)
    this.lastSources = list
    const key = list.map((s) => `${s.date}|${s.title}`).join('#')
    if (key === this.lettersKey && !relayout) return
    this.lettersKey = key
    if (list.length && !relayout) this._touch()
    for (const l of this.letters) if (l !== this.painting) l.fading = true   // les précédentes s'effacent
    const { x0, x1 } = this.letterArea
    const n = list.length
    const lw = Math.min(0.31, (x1 - x0) / Math.max(1, n) - 0.015)
    const lh = lw * 1.3
    const step = n > 1 ? (x1 - x0 - lw) / (n - 1) : 0
    list.forEach((source, k) => {
      const mat = this.basic({ map: letterTexture(source), transparent: true, opacity: 0 })
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(lw, lh), mat)
      mesh.userData.source = source                 // la lettre entière s'ouvre au clic (avatar.js)
      const x = n > 1 ? x0 + lw / 2 + k * step : (x0 + x1) / 2
      mesh.position.set(x, (k % 2 ? -0.08 : 0.06) + (Math.random() - 0.5) * 0.04, 0.008 + k * 0.002)
      mesh.rotation.z = (Math.random() - 0.5) * 0.12
      const pin = new THREE.Mesh(new THREE.SphereGeometry(0.012, 8, 6), this.pinMat)
      pin.position.set(0, lh / 2 - 0.025, 0.006)
      mesh.add(pin)
      this.group.add(mesh)
      this.letters.push({ mesh, mat, fading: false, delay: 0.35 * k })
    })
  }

  update(t, dt, room = 1) {
    for (const m of this.materials) m.color.copy(m.userData.base).multiplyScalar(0.72 * room)
    const target = this.glowTarget * (0.82 + 0.18 * Math.sin(t * 1.7))   // la lueur respire doucement
    this.glow.material.opacity += (target - this.glow.material.opacity) * Math.min(1, dt * 1.5)
    for (const l of [...this.letters]) {
      const mats = l.mats || [l.mat]
      if (l.fading) {
        for (const m of mats) m.opacity -= dt * 1.5
        if (l.mat.opacity <= 0) {
          this.group.remove(l.mesh)
          for (const m of mats) {
            m.map?.dispose()
            m.dispose()
            this.materials.splice(this.materials.indexOf(m), 1)
          }
          this.letters.splice(this.letters.indexOf(l), 1)
        }
      } else if ((l.delay -= dt) <= 0) {
        for (const m of mats) m.opacity = Math.min(1, m.opacity + dt * 1.2)
      }
    }
  }
}
