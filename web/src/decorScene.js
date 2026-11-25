// Mise en scène du décor de Longwood choisie par l'archiviste : le temps derrière la fenêtre et la carte murale.
// Tout est dessiné dans le navigateur (canvas) : aucune image ni donnée externe.
import * as THREE from 'three'

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

// ── Carte murale de l'Europe ─────────────────────────────────────────────────
// Côtes très simplifiées (longitude, latitude), dessinées à la plume façon carte ancienne.
const LON0 = -12, LON1 = 44, LAT0 = 27, LAT1 = 62
const SEAS = [
  // Atlantique, Manche, mer du Nord et Baltique
  [[-12, 27], [-10, 29], [-9.6, 30.4], [-8.5, 33.3], [-5.8, 35.8], [-5.6, 36.0], [-6.3, 36.5], [-9.0, 37.0],
    [-9.4, 38.7], [-8.7, 41.2], [-9.3, 43.0], [-5.7, 43.6], [-1.5, 43.5], [-1.2, 45.5], [-1.2, 46.2], [-4.7, 48.4],
    [-1.6, 49.7], [0.1, 49.5], [1.9, 51.0], [2.9, 51.2], [4.1, 52.0], [4.8, 53.0], [7.2, 53.4], [8.7, 53.9],
    [8.4, 55.5], [10.6, 57.7], [10.2, 56.2], [10.1, 54.4], [12.1, 54.2], [14.3, 53.9], [18.6, 54.4], [21.1, 55.7],
    [24.1, 57.0], [24.7, 59.4], [30.3, 59.9], [25.0, 60.2], [22.3, 60.4], [21.5, 62], [-12, 62]],
  // Méditerranée
  [[-5.6, 36.0], [-5.4, 36.2], [-4.4, 36.7], [-2.0, 36.8], [-0.5, 38.3], [0.2, 38.8], [-0.3, 39.5], [0.5, 40.5],
    [2.2, 41.4], [3.2, 42.3], [3.1, 43.1], [4.8, 43.3], [6.0, 43.1], [7.3, 43.7], [8.9, 44.4], [10.2, 43.9],
    [10.5, 42.9], [11.2, 42.4], [12.3, 41.7], [13.6, 41.2], [14.3, 40.8], [15.6, 40.0], [15.7, 38.9], [16.0, 38.0],
    [16.6, 38.4], [17.1, 39.0], [16.5, 39.7], [17.2, 40.5], [18.5, 40.1], [18.0, 40.6], [16.5, 41.3], [15.6, 41.9],
    [14.2, 42.4], [13.6, 43.5], [12.4, 44.2], [12.3, 45.3], [13.7, 45.7], [14.5, 45.2], [15.3, 44.3], [16.4, 43.5],
    [18.1, 42.6], [19.4, 41.9], [19.4, 40.4], [20.1, 39.6], [20.7, 38.8], [21.1, 37.9], [21.9, 36.8], [22.5, 36.4],
    [23.0, 36.5], [23.2, 37.9], [24.0, 38.0], [23.0, 39.2], [22.6, 40.3], [23.9, 40.2], [24.4, 40.9], [26.0, 40.8],
    [26.3, 40.1], [26.2, 39.4], [27.0, 38.5], [27.3, 37.4], [28.2, 36.7], [30.6, 36.8], [32.5, 36.1], [34.6, 36.8],
    [36.0, 36.5], [35.9, 35.0], [35.0, 33.0], [34.5, 31.5], [32.5, 31.1], [31.0, 31.6], [29.9, 31.2], [27.0, 31.4],
    [25.0, 31.6], [23.0, 32.6], [20.0, 32.1], [19.5, 30.5], [18.0, 30.8], [15.5, 32.3], [13.0, 32.9], [11.1, 33.3],
    [10.2, 34.3], [11.1, 35.2], [10.6, 36.4], [11.0, 37.1], [9.8, 37.3], [8.0, 36.9], [5.0, 36.8], [3.0, 36.8],
    [0.0, 35.8], [-2.0, 35.1], [-5.3, 35.9]],
  // Mer Noire
  [[28.0, 41.6], [27.5, 42.5], [27.9, 43.2], [28.6, 43.8], [29.6, 45.2], [30.7, 46.5], [31.7, 46.6], [33.5, 46.0],
    [32.5, 45.4], [33.5, 44.5], [34.5, 44.7], [36.5, 45.3], [37.5, 44.7], [38.5, 44.4], [40.0, 43.4], [41.6, 41.6],
    [40.0, 41.0], [38.0, 40.9], [36.0, 41.7], [34.0, 42.0], [31.5, 41.2], [29.1, 41.2]],
]
const ISLANDS = [
  [[-5.7, 50.1], [-3.5, 50.3], [1.4, 51.2], [1.7, 52.6], [0.2, 53.5], [-0.6, 54.5], [-1.6, 55.6], [-2.1, 57.1],
    [-1.8, 57.6], [-3.3, 58.6], [-5.0, 58.6], [-6.2, 57.5], [-5.6, 56.3], [-4.9, 55.0], [-3.0, 54.9], [-3.4, 54.0],
    [-3.0, 53.4], [-4.6, 53.3], [-4.2, 52.3], [-5.1, 51.8], [-3.0, 51.5], [-4.2, 51.2]],               // Grande-Bretagne
  [[-6.0, 52.2], [-6.0, 53.9], [-5.5, 54.6], [-7.3, 55.3], [-8.4, 55.0], [-10.0, 54.2], [-9.9, 53.5], [-9.1, 52.6],
    [-10.3, 51.9], [-9.5, 51.5], [-8.2, 51.8]],                                                         // Irlande
  [[5.0, 62], [5.2, 60.0], [5.6, 58.9], [7.0, 58.0], [8.5, 58.3], [10.6, 59.2], [11.3, 58.9], [11.9, 57.6],
    [12.8, 56.3], [14.2, 55.4], [16.0, 56.2], [16.6, 57.9], [18.7, 59.4], [17.2, 60.6], [17.6, 62]],    // Scandinavie
  [[12.2, 56.1], [12.6, 55.6], [11.8, 55.0], [10.9, 55.7]],                                             // Seeland
  [[9.4, 43.0], [9.6, 42.1], [9.2, 41.4], [8.6, 41.9], [8.6, 42.6]],                                     // Corse
  [[9.2, 41.2], [9.8, 40.6], [9.6, 39.1], [8.4, 38.9], [8.4, 40.6]],                                     // Sardaigne
  [[12.4, 37.8], [13.3, 38.2], [15.6, 38.3], [15.1, 36.7], [14.3, 37.0], [12.6, 37.6]],                  // Sicile
  [[23.5, 35.3], [26.3, 35.2], [26.0, 35.0], [24.0, 35.0]],                                             // Crète
  [[32.3, 35.1], [34.6, 35.6], [33.9, 34.9], [32.6, 34.7]],                                             // Chypre
  [[10.1, 42.85], [10.45, 42.85], [10.45, 42.72], [10.1, 42.72]],                                       // île d'Elbe
]
const CITIES = [
  ['Paris', 2.35, 48.85], ['Vienne', 16.37, 48.2], ['Berlin', 13.4, 52.5], ['Madrid', -3.7, 40.4],
  ['Moscou', 37.6, 55.75], ['Rome', 12.5, 41.9], ['Le Caire', 31.2, 30.05], ['Londres', -0.1, 51.5],
]
// Régions que l'archiviste peut éclairer : centre (lon, lat), rayon (degrés), légende
const REGIONS = {
  corse: [9.0, 42.1, 1.6, 'Corse'],
  france: [2.5, 46.6, 4.8, 'France'],
  italie: [10.0, 44.6, 3.2, 'Italie'],
  egypte: [31.0, 30.6, 3.4, 'Égypte'],
  espagne: [-3.7, 40.3, 4.4, 'Espagne'],
  autriche: [16.2, 48.5, 3.0, 'Autriche'],
  prusse: [12.5, 52.4, 3.4, 'Prusse'],
  pologne: [20.5, 53.6, 3.4, 'Pologne'],
  allemagne: [11.5, 50.6, 3.0, 'Saxe'],
  russie: [33.0, 55.0, 6.0, 'Russie'],
  belgique: [4.4, 50.7, 1.8, 'Waterloo'],
  angleterre: [-1.5, 52.6, 3.0, 'Angleterre'],
  elbe: [10.3, 42.78, 1.0, 'Île d\'Elbe'],
  sainte_helene: null,                       // hors de la carte : la flèche en bas à gauche s'éclaire
}

const W = 1024, H = 672
const px = (lon) => ((lon - LON0) / (LON1 - LON0)) * W
const py = (lat) => H - ((lat - LAT0) / (LAT1 - LAT0)) * H

function trace(ctx, pts) {
  ctx.beginPath()
  pts.forEach(([lon, lat], i) => (i ? ctx.lineTo(px(lon), py(lat)) : ctx.moveTo(px(lon), py(lat))))
  ctx.closePath()
}

function drawMap() {
  const c = document.createElement('canvas')
  c.width = W
  c.height = H
  const ctx = c.getContext('2d')
  ctx.fillStyle = '#c8ad74'                                   // terres : parchemin
  ctx.fillRect(0, 0, W, H)
  ctx.lineJoin = 'round'
  for (const sea of SEAS) {
    trace(ctx, sea)
    ctx.fillStyle = '#8d8b6c'                                 // mers : vert-de-gris passé, presque sépia
    ctx.fill()
  }
  for (const island of ISLANDS) {
    trace(ctx, island)
    ctx.fillStyle = '#bda06a'
    ctx.fill()
  }
  ctx.strokeStyle = '#4b3518'
  ctx.lineWidth = 2
  for (const shape of [...SEAS, ...ISLANDS]) { trace(ctx, shape); ctx.stroke() }
  // Le Nil
  ctx.beginPath()
  ctx.moveTo(px(31.0), py(31.4))
  ctx.quadraticCurveTo(px(31.2), py(29), px(31.4), py(27))
  ctx.strokeStyle = '#5d7a78'
  ctx.lineWidth = 2.5
  ctx.stroke()
  // Villes
  ctx.fillStyle = '#3b2a14'
  ctx.font = 'italic 22px Georgia, serif'
  for (const [name, lon, lat] of CITIES) {
    ctx.beginPath()
    ctx.arc(px(lon), py(lat), 4, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillText(name, px(lon) + 7, py(lat) - 6)
  }
  // Cartouche et flèche vers Sainte-Hélène, très loin au sud
  ctx.font = 'italic 30px Georgia, serif'
  ctx.fillText('Carte de l\'Europe', px(2), H - 22)            // cartouche sur le Sahara, loin des régions
  ctx.font = 'italic 21px Georgia, serif'
  ctx.fillText('↙ Sainte-Hélène, à 1 900 lieues', 18, H - 18)
  // Bords jaunis et ombrés
  const vignette = ctx.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, W * 0.62)
  vignette.addColorStop(0, 'rgba(60,40,15,0)')
  vignette.addColorStop(1, 'rgba(60,40,15,0.45)')
  ctx.fillStyle = vignette
  ctx.fillRect(0, 0, W, H)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

function drawHighlight(region) {
  const c = document.createElement('canvas')
  c.width = W
  c.height = H
  const ctx = c.getContext('2d')
  const spec = REGIONS[region]
  const [x, y, r, label] = spec
    ? [px(spec[0]), py(spec[1]), (spec[2] / (LON1 - LON0)) * W, spec[3]]
    : [40, H - 30, 70, null]                                 // Sainte-Hélène : la flèche du coin
  const g = ctx.createRadialGradient(x, y, 0, x, y, r * 1.6)
  g.addColorStop(0, 'rgba(255, 196, 110, 0.85)')
  g.addColorStop(0.55, 'rgba(255, 160, 70, 0.35)')
  g.addColorStop(1, 'rgba(255, 140, 50, 0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, W, H)
  if (label) {
    ctx.font = 'bold italic 42px Georgia, serif'
    ctx.lineWidth = 6
    ctx.strokeStyle = 'rgba(255, 236, 200, 0.85)'             // halo clair autour du nom
    ctx.fillStyle = 'rgba(120, 24, 16, 1)'                    // encre rouge
    ctx.textAlign = 'center'
    ctx.strokeText(label, x, y - r * 0.15)
    ctx.fillText(label, x, y - r * 0.15)
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
  ctx.fillText(dateFr(source.date), w / 2, 62)
  ctx.font = 'italic 24px Georgia, serif'
  const title = (source.title || '').replace(/\.$/, '').toLowerCase().replace(/^./, (ch) => ch.toUpperCase())
  wrapLines(ctx, title, w - 50, 3).forEach((l, k) => ctx.fillText(l, w / 2, 104 + k * 30))
  ctx.textAlign = 'left'
  ctx.font = 'italic 21px Georgia, serif'
  ctx.fillStyle = 'rgba(46,31,12,0.85)'
  wrapLines(ctx, source.snippet, w - 56, 7).forEach((l, k) => ctx.fillText(l, 28, 222 + k * 28))
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
  constructor(scene, center, width = 1.9, height = 1.1) {
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
    // Carte, à gauche, légèrement de biais, épinglée aux coins
    const mapW = width * 0.56
    const mapH = mapW * (H / W)
    this.map = new THREE.Group()
    this.map.position.set(-width / 2 + mapW / 2 + 0.07, 0.02, 0.005)
    this.map.rotation.z = 0.012
    this.map.add(new THREE.Mesh(new THREE.PlaneGeometry(mapW, mapH), basic({ map: drawMap() })))
    this.glow = new THREE.Mesh(new THREE.PlaneGeometry(mapW, mapH), new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false,
    }))
    this.glow.position.z = 0.002
    this.map.add(this.glow)
    this.pinMat = basic({ color: 0x8a1c14 })
    for (const [x, y] of [[-1, 1], [1, 1], [-1, -1], [1, -1]]) {
      const pin = new THREE.Mesh(new THREE.SphereGeometry(0.011, 8, 6), this.pinMat)
      pin.position.set(x * (mapW / 2 - 0.02), y * (mapH / 2 - 0.02), 0.01)
      this.map.add(pin)
    }
    this.group.add(this.map)
    // Les lettres, à droite
    this.letterArea = { x0: -width / 2 + mapW + 0.14, x1: width / 2 - 0.05 }
    this.letters = []
    this.lettersKey = ''
    this.glowTarget = 0
    this.region = null
    scene.add(this.group)
  }

  highlight(region) {
    if (!(region in REGIONS) || region === this.region) return
    this.region = region
    const old = this.glow.material.map
    this.glow.material.map = drawHighlight(region)
    this.glow.material.needsUpdate = true
    old?.dispose()
    this.glow.material.opacity = 0
    this.glowTarget = 1
  }

  clear() {
    this.region = null
    this.glowTarget = 0
    this.showLetters([])
  }

  /** Les lettres de la réponse (sources de l'API : date, titre, extrait) ; trois au plus. */
  showLetters(sources = []) {
    const list = (sources || []).filter((s) => s && (s.date || s.title)).slice(0, 3)
    const key = list.map((s) => `${s.date}|${s.title}`).join('#')
    if (key === this.lettersKey) return
    this.lettersKey = key
    for (const l of this.letters) l.fading = true             // les précédentes s'effacent
    const { x0, x1 } = this.letterArea
    const n = list.length
    const lw = Math.min(0.31, (x1 - x0) / Math.max(1, n) - 0.015)
    const lh = lw * 1.3
    const step = n > 1 ? (x1 - x0 - lw) / (n - 1) : 0
    list.forEach((source, k) => {
      const mat = this.basic({ map: letterTexture(source), transparent: true, opacity: 0 })
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(lw, lh), mat)
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
      if (l.fading) {
        l.mat.opacity -= dt * 1.5
        if (l.mat.opacity <= 0) {
          this.group.remove(l.mesh)
          l.mat.map?.dispose()
          l.mat.dispose()
          this.materials.splice(this.materials.indexOf(l.mat), 1)
          this.letters.splice(this.letters.indexOf(l), 1)
        }
      } else if ((l.delay -= dt) <= 0) {
        l.mat.opacity = Math.min(1, l.mat.opacity + dt * 1.2)
      }
    }
  }
}
