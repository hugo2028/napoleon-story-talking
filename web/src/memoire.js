// Mémoire du visiteur : les personnes, lieux, événements et institutions qu'il a rencontrés dans les récits,
// et les liens entre eux. Gardée dans son navigateur (rien sur le serveur, pas de compte) : elle survit aux
// rechargements et aux nouvelles conversations, et se consulte comme une carte mentale.
//
// Pour chaque réponse, le serveur (POST /api/entites) relève les noms NOUVEAUX : ils sont mis en évidence à leur
// première apparition seulement ; un clic ouvre leur fiche et met le récit en pause.

import { t } from './i18n.js'

const KEY = 'napoleon.memoire.v1'
export const TYPES = {
  personne:    { icone: '👤', couleur: '#8a2c1c' },
  lieu:        { icone: '📍', couleur: '#2f5d3a' },
  evenement:   { icone: '⚔',  couleur: '#7a5a12' },
  institution: { icone: '🏛', couleur: '#2c4a7a' },
  episode:     { icone: '📖', couleur: '#5a4632' },
}

/** Première apparition de `mention` dans `texte`, en mot entier (« Rome » n'est pas dans « compromettre »),
 * sans tenir compte de la casse ; -1 si absente. Les apostrophes droites et courbes se valent. */
export function chercherMot(texte, mention) {
  const motif = mention.trim().split(/\s+/).filter(Boolean)
    .map((mot) => mot.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/['’]/g, "['’]"))
    .join('\\s+')
  if (!motif) return { index: -1, longueur: 0 }
  const m = new RegExp(`(?<![\\p{L}\\p{N}])${motif}(?![\\p{L}\\p{N}])`, 'iu').exec(texte)
  return m ? { index: m.index, longueur: m[0].length } : { index: -1, longueur: 0 }
}

const slug = (s) => (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)

export class Memoire {
  constructor() {
    this.data = { entites: {}, liens: [], docs: {}, vus: {} }
    try {
      const d = JSON.parse(localStorage.getItem(KEY) || 'null')
      if (d?.entites && Array.isArray(d.liens)) this.data = { docs: {}, vus: {}, liensDebloques: {}, ...d }
    } catch { /* navigation privée, stockage bloqué : mémoire de la session seulement */ }
    // Un lien n'existe que s'il est attesté par une lettre ou un passage des Œuvres (graphe du corpus) : ni les
    // liens déduits du récit généré, ni les anciens nœuds « épisode » locaux ne sont gardés
    this.data.liens = []
    for (const [id, e] of Object.entries(this.data.entites)) if (e.type === 'episode') delete this.data.entites[id]
    this.data.liensDebloques ??= {}
  }

  static cle(a, b) { return a < b ? `${a}|${b}` : `${b}|${a}` }

  lienDebloque(a, b) { return !!this.data.liensDebloques[Memoire.cle(a, b)] }

  /** Liens du corpus que la conversation vient de débloquer ; renvoie ceux qui sont nouveaux. */
  debloquerLiens(liens = []) {
    const nouveaux = []
    for (const l of liens) {
      const k = Memoire.cle(l.de, l.vers)
      if (this.data.liensDebloques[k]) continue
      this.data.liensDebloques[k] = { de: l.de, vers: l.vers, relation: l.relation || '', source: l.source || null,
        vu: Date.now() }
      nouveaux.push(l)
    }
    this.save()
    return nouveaux
  }

  debloquerEpisodes(refs = []) {
    for (const r of refs) this.data.vus[r] ??= Date.now()
    this.save()
  }

  /** Ce que le visiteur a débloqué, par catégorie. */
  compter() {
    const c = { personne: 0, lieu: 0, evenement: 0, institution: 0, lettre: 0, oeuvre: 0, tableau: 0, episode: 0,
      lien: Object.keys(this.data.liensDebloques).length }
    for (const e of Object.values(this.data.entites)) if (c[e.type] != null) c[e.type]++
    for (const d of Object.values(this.data.docs)) if (c[d.genre] != null) c[d.genre]++
    c.episode = this.refsVues().filter((r) => r.startsWith('episode:')).length
    return c
  }

  /** Tout ce que le visiteur a rencontré : noms, documents servis, nœuds ouverts dans la carte. */
  refsVues() {
    return [...new Set([...Object.keys(this.data.entites), ...Object.keys(this.data.docs), ...Object.keys(this.data.vus)])]
  }

  aVu(ref) { return !!(this.data.entites[ref] || this.data.docs[ref] || this.data.vus[ref]) }

  /** Un nœud vu, sous la forme qu'attend la carte (pour ceux que le graphe du corpus ne connaît pas). */
  local(ref) {
    const e = this.data.entites[ref]
    if (e) return { ref, genre: e.type, nom: e.nom, notice: e.notice, poids: 1 }
    const d = this.data.docs[ref]
    return d ? { ref, ...d } : null
  }

  marquerVu(n) {
    this.data.vus[n.ref] = Date.now()
    this.save()
  }

  /** Documents servis par une réponse (lettres, passages des Œuvres, tableau épinglé), reliés à l'épisode. */
  ajouterDocuments(docs, episode = '') {
    for (const d of docs) {
      if (!d?.ref) continue
      if (!this.data.docs[d.ref]) {
        this.data.docs[d.ref] = { genre: d.genre, nom: d.nom, date: d.date || '', image: d.image || null, episode }
      }
    }
    this.save()
  }

  save() {
    try { localStorage.setItem(KEY, JSON.stringify(this.data)) } catch { /* idem */ }
  }

  get taille() { return Object.values(this.data.entites).filter((e) => e.type !== 'episode').length }

  /** Ce que le visiteur connaît déjà, envoyé au serveur pour qu'il ne le renvoie pas. */
  connus() {
    return Object.values(this.data.entites).filter((e) => e.type !== 'episode').map((e) => ({ id: e.id, nom: e.nom }))
  }

  get(id) { return this.data.entites[id] }

  voisins(id) {
    return this.data.liens.filter((l) => l.de === id || l.vers === id)
      .map((l) => ({ id: l.de === id ? l.vers : l.de, relation: l.relation, sens: l.de === id ? 'vers' : 'de' }))
      .filter((v) => this.data.entites[v.id])
  }

  /** Ajoute les noms d'une réponse, reliés à l'épisode où ils ont été rencontrés. */
  ajouter({ entites = [], liens = [] }, episode = '') {
    for (const e of entites) {
      if (this.data.entites[e.id]) continue
      this.data.entites[e.id] = { ...e, vu: Date.now(), episode }
    }
    this.save()
  }

  _lier(de, vers, relation) {
    if (!de || !vers || de === vers) return
    if (this.data.liens.some((l) => (l.de === de && l.vers === vers) || (l.de === vers && l.vers === de))) return
    this.data.liens.push({ de, vers, relation: relation || '' })
  }

  effacer() {
    this.data = { entites: {}, liens: [], docs: {}, vus: {}, liensDebloques: {} }
    this.save()
  }
}

/**
 * Met en évidence, dans un bloc de texte, la première apparition de chaque nom nouveau. `onClick(entite)`.
 */
export function decorerTexte(el, entites, onClick) {
  for (const e of entites) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    let node
    while ((node = walker.nextNode())) {
      if (node.parentElement?.closest('.entite')) continue
      const { index: k, longueur } = chercherMot(node.data, e.mention)
      if (k < 0) continue
      const after = node.splitText(k)
      after.splitText(longueur)
      const b = document.createElement('button')
      b.type = 'button'
      b.className = `entite entite-${e.type}`
      b.textContent = after.data
      b.title = e.nom
      b.addEventListener('click', (ev) => { ev.stopPropagation(); onClick(e) })
      after.replaceWith(b)
      break
    }
  }
}

/** Index (en mots du texte affiché) de la première apparition de chaque nom : pour suivre la voix. */
export function indexDesMentions(texte, entites) {
  const out = []
  for (const e of entites) {
    const { index: k } = chercherMot(texte, e.mention)
    if (k < 0) continue
    const avant = texte.slice(0, k).split(/\s+/).filter(Boolean).length
    const n = e.mention.split(/\s+/).filter(Boolean).length
    // Mot coupé par la mention (« d'Essling ») : il compte comme le premier mot de la mention
    const colle = k > 0 && !/\s/.test(texte[k - 1])
    out.push({ index: colle ? Math.max(0, avant - 1) : avant, mots: n, entite: e })
  }
  return out.sort((a, b) => a.index - b.index)
}

// ── Fiche d'un nom ────────────────────────────────────────────────────────────

/**
 * Fiche : nom, notice, épisode où il a été rencontré, liens vers d'autres noms. `options.onClose` à la fermeture,
 * `options.onCarte` pour ouvrir la carte mentale sur ce nom.
 */
export function ouvrirFiche(memoire, entite, options = {}) {
  let el = document.getElementById('entite-card')
  if (!el) {
    el = document.createElement('aside')
    el.id = 'entite-card'
    el.setAttribute('role', 'dialog')
    document.body.appendChild(el)
  }
  const e = memoire.get(entite.id) || entite
  const type = TYPES[e.type] || TYPES.personne
  el.replaceChildren()
  const head = document.createElement('div')
  head.className = 'entite-card-head'
  const titre = document.createElement('h4')
  titre.textContent = `${type.icone} ${e.nom}`
  titre.style.color = type.couleur
  const fermer = document.createElement('button')
  fermer.type = 'button'
  fermer.className = 'entite-card-close'
  fermer.textContent = '×'
  fermer.setAttribute('aria-label', t('close'))
  head.append(titre, fermer)
  el.appendChild(head)
  if (e.notice) {
    const p = document.createElement('p')
    p.textContent = e.notice
    el.appendChild(p)
  }
  if (e.episode) {
    const p = document.createElement('p')
    p.className = 'entite-card-meta'
    p.textContent = `${t('memSeenIn')} : ${e.episode}`
    el.appendChild(p)
  }
  const voisins = memoire.voisins(e.id).filter((v) => memoire.get(v.id)?.type !== 'episode')
  if (voisins.length) {
    const ul = document.createElement('ul')
    ul.className = 'entite-card-liens'
    for (const v of voisins.slice(0, 12)) {
      const li = document.createElement('li')
      const autre = memoire.get(v.id)
      const b = document.createElement('button')
      b.type = 'button'
      b.className = `entite entite-${autre.type}`
      b.textContent = autre.nom
      b.addEventListener('click', () => ouvrirFiche(memoire, autre, options))
      const rel = document.createElement('span')
      rel.textContent = v.relation ? ` — ${v.relation}` : ''
      li.append(b, rel)
      ul.appendChild(li)
    }
    el.appendChild(ul)
  }
  const pied = document.createElement('div')
  pied.className = 'entite-card-actions'
  if (options.reprendre) {
    const r = document.createElement('button')
    r.type = 'button'
    r.className = 'chat-action primary'
    r.textContent = `▶ ${t('memResume')}`
    r.addEventListener('click', () => fermerFiche())
    pied.appendChild(r)
  }
  if (options.onCarte) {
    const c = document.createElement('button')
    c.type = 'button'
    c.className = 'chat-action'
    c.textContent = `🕸 ${t('memMap')}`
    c.addEventListener('click', () => { fermerFiche(true); options.onCarte(e.id) })
    pied.appendChild(c)
  }
  const note = document.createElement('p')
  note.className = 'entite-card-note'
  note.textContent = t('memNoticeNote')
  el.append(pied, note)
  el.hidden = false
  const fermerFiche = (versCarte = false) => {
    el.hidden = true
    document.removeEventListener('keydown', echap)
    options.onClose?.(versCarte)
  }
  const echap = (ev) => { if (ev.key === 'Escape') fermerFiche() }
  document.addEventListener('keydown', echap)
  fermer.addEventListener('click', () => fermerFiche())
}

// ── Progression ───────────────────────────────────────────────────────────────

export const CATEGORIES = ['personne', 'lieu', 'evenement', 'institution', 'tableau', 'lettre', 'oeuvre', 'episode', 'lien']
let totauxCache = null
export async function totaux() {
  if (!totauxCache) {
    try { totauxCache = await (await fetch('/api/graphe/totaux')).json() } catch { totauxCache = {} }
  }
  return totauxCache
}

/** {categorie: {n, total, pct}} et le total : moyenne des catégories (17 984 lettres ne doivent pas tout écraser). */
export function progression(compte, tot) {
  const cats = {}
  for (const k of CATEGORIES) {
    const total = tot?.[k] || 0
    if (!total) continue
    const n = Math.min(compte[k] || 0, total)
    cats[k] = { n, total, pct: (100 * n) / total }
  }
  const vals = Object.values(cats)
  return { cats, total: vals.length ? vals.reduce((s, c) => s + c.pct, 0) / vals.length : 0 }
}

const pctTxt = (x) => `${x < 10 ? x.toFixed(1) : Math.round(x)} %`.replace('.', ',')

/** Bandeau des nouveautés après une réponse : « 🔓 +2 personnes, +1 lieu, +3 liens — 4,2 % ». */
export async function annoncer(avant, apres) {
  const gains = CATEGORIES.map((k) => [k, (apres[k] || 0) - (avant[k] || 0)]).filter(([, d]) => d > 0)
  if (!gains.length) return
  const tot = await totaux()
  const pr = progression(apres, tot)
  let el = document.getElementById('memoire-toast')
  if (!el) {
    el = document.createElement('div')
    el.id = 'memoire-toast'
    el.setAttribute('role', 'status')
    document.body.appendChild(el)
  }
  el.replaceChildren()
  const ligne = gains.map(([k, d]) => `+${d} ${t(d > 1 ? `memCat_${k}_n` : `memCat_${k}_1`)}`).join(', ')
  el.append(Object.assign(document.createElement('strong'), { textContent: `🔓 ${ligne}` }),
    Object.assign(document.createElement('span'), { textContent: ` — ${t('memProgress')} ${pctTxt(pr.total)}` }))
  el.classList.add('visible')
  clearTimeout(el._t)
  el._t = setTimeout(() => el.classList.remove('visible'), 6000)
}

function panneauProgression(memoire, tot) {
  const pr = progression(memoire.compter(), tot)
  const box = document.createElement('div')
  box.className = 'memoire-progression'
  const anneau = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  anneau.setAttribute('viewBox', '0 0 44 44')
  anneau.setAttribute('class', 'memoire-anneau-total')
  const C = 2 * Math.PI * 18
  anneau.innerHTML = `<circle cx="22" cy="22" r="18" class="fond"/><circle cx="22" cy="22" r="18" class="plein" `
    + `stroke-dasharray="${(C * pr.total) / 100} ${C}" transform="rotate(-90 22 22)"/>`
    + `<text x="22" y="25.5" text-anchor="middle">${Math.round(pr.total)}%</text>`
  box.appendChild(anneau)
  const barres = document.createElement('div')
  barres.className = 'memoire-barres'
  for (const [k, c] of Object.entries(pr.cats)) {
    const ligne = document.createElement('div')
    ligne.className = 'memoire-barre'
    ligne.title = `${c.n} / ${c.total}`
    const nom = document.createElement('span')
    nom.textContent = `${(TYPES[k] || GENRES_DOC[k] || { icone: '🔗' }).icone} ${t(`memCat_${k}_n`)}`
    const jauge = document.createElement('i')
    const plein = document.createElement('b')
    plein.style.width = `${Math.max(c.pct, c.n ? 2 : 0)}%`
    jauge.appendChild(plein)
    const val = document.createElement('small')
    val.textContent = `${c.n}/${c.total}`
    ligne.append(nom, jauge, val)
    barres.appendChild(ligne)
  }
  box.appendChild(barres)
  return box
}

// ── Carte mentale : des bulles ────────────────────────────────────────────────
//
// Les nœuds vus par le visiteur (noms, lettres, passages des Œuvres, tableaux, épisodes) et, autour d'eux, des
// bulles estompées « à découvrir » fournies par le graphe du corpus (POST /api/graphe/sous-graphe). Une bulle
// porte l'image de son nœud quand il en a une (tableau, portrait). Un moteur de recherche interroge tout le corpus
// (GET /api/graphe/recherche) ; le panneau de droite montre la fiche, le texte entier et les voisins d'un nœud.

const SVG = 'http://www.w3.org/2000/svg'
export const GENRES_DOC = {
  lettre:  { icone: '✉', couleur: '#6b5a3a', label: 'memType_lettre' },
  oeuvre:  { icone: '📜', couleur: '#5e4a2a', label: 'memType_oeuvre' },
  tableau: { icone: '🖼', couleur: '#4a3a5e', label: 'memType_tableau' },
  episode: { icone: '📖', couleur: '#5a4632', label: 'memType_episode' },
}
const style = (genre) => TYPES[genre] || GENRES_DOC[genre] || TYPES.personne

function el(tag, cls, texte) {
  const e = document.createElement(tag)
  if (cls) e.className = cls
  if (texte != null) e.textContent = texte
  return e
}

async function api(url, corps) {
  const r = await fetch(url, corps ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corps) } : undefined)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

/** Rayon d'une bulle : les épisodes et les nœuds très cités sont plus gros ; les bulles à découvrir, petites. */
function rayon(n) {
  if (n.decouvrir) return 14
  if (n.genre === 'episode') return 30
  if (n.genre === 'tableau') return 30
  if (n.genre === 'lettre' || n.genre === 'oeuvre') return 18
  return 18 + Math.min(16, Math.sqrt(n.poids || 1) * 1.6)
}

/** Ouvre la mémoire (plein écran) ; `focus` : un nœud à mettre en avant. `options.onVu(noeud)` : le visiteur a
 * ouvert un nœud (il entre dans sa mémoire). */
export async function ouvrirCarte(memoire, focus = null, options = {}) {
  const { forceSimulation, forceLink, forceManyBody, forceCollide, forceX, forceY } = await import('d3-force')
  let dlg = document.getElementById('memoire-dialog')
  if (!dlg) {
    dlg = document.createElement('dialog')
    dlg.id = 'memoire-dialog'
    document.body.appendChild(dlg)
  }
  dlg.replaceChildren()

  // En-tête : titre, moteur de recherche, effacer, fermer
  const head = el('div', 'memoire-head')
  const titre = el('h3', null, `🕮 ${t('memTitle')}`)
  const boite = el('div', 'memoire-recherche')
  const recherche = el('input')
  recherche.type = 'search'
  recherche.placeholder = t('memSearch')
  recherche.setAttribute('aria-label', t('memSearch'))
  const liste = el('ul', 'memoire-resultats')
  liste.hidden = true
  boite.append(recherche, liste)
  const vider = el('button', 'chat-action', t('memClear'))
  vider.type = 'button'
  const fermer = el('button', 'entite-card-close', '×')
  fermer.type = 'button'
  fermer.setAttribute('aria-label', t('close'))
  head.append(titre, boite, vider, fermer)
  const legende = el('div', 'memoire-legende')
  for (const [k, v] of [...Object.entries(TYPES), ...Object.entries(GENRES_DOC)]) {
    if (k === 'episode' && TYPES[k] && GENRES_DOC[k] && legende.querySelector('[data-k="episode"]')) continue
    const s = el('span')
    s.dataset.k = k
    const i = el('i')
    i.style.background = v.couleur
    s.append(i, t(v.label || `memType_${k}`))
    legende.appendChild(s)
  }
  const tot = await totaux()
  const prog = panneauProgression(memoire, tot)
  const corps = el('div', 'memoire-corps')
  const zone = el('div', 'memoire-zone')
  const panneau = el('aside', 'memoire-panneau')
  panneau.hidden = true
  corps.append(zone, panneau)
  dlg.append(head, prog, legende, corps)
  fermer.addEventListener('click', () => dlg.close())
  vider.addEventListener('click', () => {
    if (window.confirm(t('memClearConfirm'))) { memoire.effacer(); ouvrirCarte(memoire, null, options) }
  })
  if (!dlg.open) dlg.showModal()

  // Données : le sous-graphe des nœuds vus, plus les noms locaux que le graphe ne connaît pas
  const vus = memoire.refsVues()
  let graphe = { noeuds: [], liens: [] }
  try { graphe = await api('/api/graphe/sous-graphe', { vus }) } catch (err) { console.warn('[Mémoire]', err) }
  const noeuds = new Map(graphe.noeuds.map((n) => [n.ref, { ...n }]))
  for (const ref of vus) {
    if (noeuds.has(ref)) continue
    const local = memoire.local(ref)
    if (local) noeuds.set(ref, local)
  }
  const liens = []
  const lienVu = new Set()
  const ajouterLien = (de, vers, relation, force = 1) => {
    const k = [de, vers].sort().join('|')
    if (de === vers || lienVu.has(k) || !noeuds.has(de) || !noeuds.has(vers)) return
    lienVu.add(k)
    liens.push({ source: de, target: vers, relation, force })
  }
  // Liens entre deux entités : seulement ceux que la conversation a débloqués ; vers un document, un épisode ou
  // une bulle à découvrir : montrés (ils disent où chercher)
  const estDoc = (r) => r.includes(':')
  for (const l of graphe.liens) {
    const a = noeuds.get(l.de), b = noeuds.get(l.vers)
    if (!a || !b) continue
    if (!estDoc(l.de) && !estDoc(l.vers) && !a.decouvrir && !b.decouvrir && !memoire.lienDebloque(l.de, l.vers)) continue
    ajouterLien(l.de, l.vers, l.relation, l.force)
  }
  for (const l of Object.values(memoire.data.liensDebloques)) ajouterLien(l.de, l.vers, l.relation, 6)

  if (!noeuds.size) {
    zone.appendChild(el('p', 'memoire-vide', t('memEmpty')))
  }

  // Dessin
  const svg = document.createElementNS(SVG, 'svg')
  const defs = document.createElementNS(SVG, 'defs')
  const monde = document.createElementNS(SVG, 'g')
  const gl = document.createElementNS(SVG, 'g')
  const gn = document.createElementNS(SVG, 'g')
  monde.append(gl, gn)
  svg.append(defs, monde)
  zone.appendChild(svg)
  let vue = { x: 0, y: 0, k: 1 }
  const appliquerVue = () => monde.setAttribute('transform', `translate(${vue.x},${vue.y}) scale(${vue.k})`)

  const traits = new Map()
  const bulles = new Map()
  const dessinerLien = (l) => {
    const line = document.createElementNS(SVG, 'line')
    line.setAttribute('class', 'memoire-lien')
    line.style.strokeWidth = String(Math.min(4, 0.8 + Math.log2(1 + (l.force || 1)) * 0.5))
    const tt = document.createElementNS(SVG, 'title')
    tt.textContent = l.relation || ''
    line.appendChild(tt)
    gl.appendChild(line)
    traits.set(l, line)
  }
  const dessinerBulle = (n) => {
    const g = document.createElementNS(SVG, 'g')
    g.setAttribute('class', `memoire-bulle memoire-${n.genre}${n.decouvrir ? ' decouvrir' : ''}`)
    const r = rayon(n)
    const fond = document.createElementNS(SVG, 'circle')
    fond.setAttribute('r', r)
    fond.setAttribute('fill', style(n.genre).couleur)
    g.appendChild(fond)
    if (n.image) {
      // L'image remplit la bulle (motif SVG), cadrée au centre
      const id = `img-${bulles.size}-${Math.random().toString(36).slice(2, 7)}`
      const pat = document.createElementNS(SVG, 'pattern')
      pat.setAttribute('id', id)
      pat.setAttribute('patternContentUnits', 'objectBoundingBox')
      pat.setAttribute('width', 1)
      pat.setAttribute('height', 1)
      const img = document.createElementNS(SVG, 'image')
      img.setAttribute('href', n.image)
      img.setAttribute('width', 1)
      img.setAttribute('height', 1)
      img.setAttribute('preserveAspectRatio', 'xMidYMid slice')
      pat.appendChild(img)
      defs.appendChild(pat)
      const disque = document.createElementNS(SVG, 'circle')
      disque.setAttribute('r', r - 2)
      disque.setAttribute('fill', `url(#${id})`)
      g.appendChild(disque)
    } else {
      const ic = document.createElementNS(SVG, 'text')
      ic.setAttribute('class', 'memoire-icone')
      ic.setAttribute('dy', '0.35em')
      ic.style.fontSize = `${Math.round(r * 0.9)}px`
      ic.textContent = style(n.genre).icone
      g.appendChild(ic)
    }
    const anneau = document.createElementNS(SVG, 'circle')
    anneau.setAttribute('class', 'memoire-anneau')
    anneau.setAttribute('r', r)
    g.appendChild(anneau)
    if (n.decouvrir) {
      const cad = document.createElementNS(SVG, 'text')
      cad.setAttribute('class', 'memoire-cadenas')
      cad.setAttribute('x', r * 0.62)
      cad.setAttribute('y', -r * 0.5)
      cad.textContent = '🔒'
      g.appendChild(cad)
    }
    const txt = document.createElementNS(SVG, 'text')
    txt.setAttribute('class', 'memoire-nom')
    txt.setAttribute('y', r + 14)
    const nom = n.nom || n.ref
    txt.textContent = nom.length > 30 ? `${nom.slice(0, 28)}…` : nom
    g.appendChild(txt)
    gn.appendChild(g)
    bulles.set(n.ref, g)
    // Clic : la fiche ; glisser : déplacer la bulle
    let drag = null
    g.addEventListener('pointerdown', (ev) => {
      ev.stopPropagation()
      g.setPointerCapture(ev.pointerId)
      drag = { x: ev.clientX, y: ev.clientY, moved: false }
      n.fx = n.x; n.fy = n.y
      sim.alphaTarget(0.2).restart()
    })
    g.addEventListener('pointermove', (ev) => {
      if (!drag) return
      const dx = (ev.clientX - drag.x) / vue.k, dy = (ev.clientY - drag.y) / vue.k
      if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true
      n.fx += dx; n.fy += dy
      drag.x = ev.clientX; drag.y = ev.clientY
    })
    g.addEventListener('pointerup', () => {
      sim.alphaTarget(0)
      n.fx = null; n.fy = null
      if (drag && !drag.moved) selectionner(n.ref)
      drag = null
    })
  }

  const W = () => zone.clientWidth || 900
  const H = () => zone.clientHeight || 600
  const sim = forceSimulation([...noeuds.values()])
    .force('lien', forceLink(liens).id((n) => n.ref).distance((l) => 70 + rayon(l.source) + rayon(l.target))
      .strength((l) => Math.min(0.9, 0.15 + (l.force || 1) * 0.04)))
    .force('charge', forceManyBody().strength((n) => (n.decouvrir ? -60 : -220)))
    .force('collision', forceCollide().radius((n) => rayon(n) + 6).strength(0.9))
    .force('x', forceX(0).strength(0.04))
    .force('y', forceY(0).strength(0.05))
    .on('tick', () => {
      for (const [l, line] of traits) {
        line.setAttribute('x1', l.source.x); line.setAttribute('y1', l.source.y)
        line.setAttribute('x2', l.target.x); line.setAttribute('y2', l.target.y)
      }
      for (const n of noeuds.values()) bulles.get(n.ref)?.setAttribute('transform', `translate(${n.x},${n.y})`)
    })
  for (const l of liens) dessinerLien(l)
  for (const n of noeuds.values()) dessinerBulle(n)
  vue = { x: W() / 2, y: H() / 2, k: 1 }
  appliquerVue()

  // Ajoute un nœud (et ses liens vers les bulles présentes) pendant l'exploration
  const ajouterNoeud = (n, depuis = null, relation = '') => {
    if (!noeuds.has(n.ref)) {
      const p = depuis && noeuds.get(depuis)
      const nn = { ...n, x: (p?.x ?? 0) + (Math.random() - 0.5) * 80, y: (p?.y ?? 0) + (Math.random() - 0.5) * 80 }
      noeuds.set(n.ref, nn)
      dessinerBulle(nn)
      sim.nodes([...noeuds.values()])
    }
    if (depuis) {
      const avant = liens.length
      ajouterLien(depuis, n.ref, relation, n.force || 1)
      if (liens.length > avant) { dessinerLien(liens[liens.length - 1]); sim.force('lien').links(liens) }
    }
    sim.alpha(0.5).restart()
    return noeuds.get(n.ref)
  }

  const centrer = (ref) => {
    const n = noeuds.get(ref)
    if (!n) return
    vue = { ...vue, x: W() / 2 - n.x * vue.k - (panneau.hidden ? 0 : 0), y: H() / 2 - n.y * vue.k }
    appliquerVue()
  }
  const surligner = (ref) => {
    const proches = new Set([ref])
    for (const l of liens) {
      if (l.source.ref === ref) proches.add(l.target.ref)
      if (l.target.ref === ref) proches.add(l.source.ref)
    }
    for (const [r, g] of bulles) {
      g.classList.toggle('estompe', !!ref && !proches.has(r))
      g.classList.toggle('choisie', r === ref)
    }
    for (const [l, line] of traits) line.classList.toggle('estompe', !!ref && l.source.ref !== ref && l.target.ref !== ref)
  }

  // Panneau : fiche du nœud, texte entier pour une lettre ou un passage, voisins à explorer
  async function selectionner(ref) {
    surligner(ref)
    panneau.hidden = false
    panneau.replaceChildren(el('p', 'memoire-attente', '…'))
    let info
    try { info = await api(`/api/graphe/noeud?ref=${encodeURIComponent(ref)}&texte=1`) } catch { info = null }
    const n = info?.noeud || noeuds.get(ref) || memoire.local(ref)
    if (!n) { panneau.replaceChildren(el('p', 'memoire-vide', t('memUnknown'))); return }
    // Un nœud verrouillé ne s'ouvre pas : il se découvre en conversant (lettres et Œuvres)
    if (!memoire.aVu(ref)) {
      panneau.replaceChildren()
      const fermerV = el('button', 'entite-card-close', '×')
      fermerV.type = 'button'
      fermerV.addEventListener('click', () => { panneau.hidden = true; surligner(null) })
      const hv = el('h4', null, `🔒 ${n.nom}`)
      panneau.append(fermerV, hv, el('p', 'entite-card-meta', t(style(n.genre).label || `memType_${n.genre}`)),
        el('p', null, t('memLocked')))
      if (options.onDemander) {
        const demander = el('button', 'chat-action primary', `💬 ${t('memAskBtn')}`)
        demander.type = 'button'
        demander.addEventListener('click', () => { dlg.close(); options.onDemander(n) })
        panneau.appendChild(demander)
      }
      return
    }
    panneau.replaceChildren()
    const fermerP = el('button', 'entite-card-close', '×')
    fermerP.type = 'button'
    fermerP.addEventListener('click', () => { panneau.hidden = true; surligner(null) })
    const h = el('h4', null, `${style(n.genre).icone} ${n.nom}`)
    h.style.color = style(n.genre).couleur
    panneau.append(fermerP, h)
    const meta = [t(style(n.genre).label || `memType_${n.genre}`), n.date, n.naissance && n.mort
      ? `${n.naissance} – ${n.mort}` : null].filter(Boolean).join(' · ')
    panneau.appendChild(el('p', 'entite-card-meta', meta))
    if (n.image) {
      const img = el('img', 'memoire-image')
      img.src = n.image
      img.alt = n.nom
      panneau.appendChild(img)
    }
    const local = memoire.local(ref)
    if (n.notice || local?.notice) panneau.appendChild(el('p', null, n.notice || local.notice))
    if (n.resume) panneau.appendChild(el('p', 'memoire-resume', n.resume))
    if (info?.extrait && (n.genre === 'lettre' || n.genre === 'oeuvre')) {
      const texte = el('div', 'memoire-texte', info.extrait)
      panneau.appendChild(texte)
    }
    const voisins = info?.voisins || []
    if (voisins.length) {
      panneau.appendChild(el('h5', null, t('memLinks')))
      const ul = el('ul', 'memoire-voisins')
      for (const v of voisins.slice(0, 20)) {
        const li = el('li')
        const ouvert = memoire.aVu(v.ref)
        // Entre deux entités, un lien non débloqué reste caché : la voisine apparaît, verrouillée
        const b = el('button', `entite entite-${v.genre}`, `${ouvert ? style(v.genre).icone : '🔒'} ${v.nom}`)
        b.type = 'button'
        if (ouvert) b.classList.add('vu')
        b.addEventListener('click', () => {
          ajouterNoeud({ ...v, decouvrir: !memoire.aVu(v.ref) }, ref, v.relation)
          setTimeout(() => { centrer(v.ref); selectionner(v.ref) }, 250)
        })
        const montrerRel = ouvert && (v.ref.includes(':') || ref.includes(':') || memoire.lienDebloque(ref, v.ref))
        li.append(b, el('span', 'memoire-relation', montrerRel && v.relation ? ` ${v.relation}` : ''))
        ul.appendChild(li)
      }
      panneau.appendChild(ul)
    }
    panneau.appendChild(el('p', 'entite-card-note', t(n.genre === 'lettre' || n.genre === 'oeuvre' || n.genre === 'tableau'
      ? 'memSourceNote' : 'memNoticeNote')))
  }

  // Moteur de recherche : tout le corpus ; ce que le visiteur a déjà vu passe en premier
  let attente = null
  recherche.addEventListener('input', () => {
    clearTimeout(attente)
    const q = recherche.value.trim()
    if (q.length < 2) { liste.hidden = true; return }
    attente = setTimeout(async () => {
      let res = []
      try { res = (await api(`/api/graphe/recherche?q=${encodeURIComponent(q)}&limite=40`)).resultats } catch { /* */ }
      res.sort((a, b) => (memoire.aVu(b.ref) - memoire.aVu(a.ref)) || 0)
      liste.replaceChildren()
      for (const r of res.slice(0, 25)) {
        const li = el('li')
        const b = el('button', null)
        b.type = 'button'
        b.append(el('span', 'memoire-res-icone', memoire.aVu(r.ref) ? style(r.genre).icone : '🔒'),
          el('span', 'memoire-res-nom', r.nom),
          el('span', 'memoire-res-meta', [r.date, memoire.aVu(r.ref) ? '✓' : ''].filter(Boolean).join(' ')))
        b.addEventListener('click', () => {
          liste.hidden = true
          ajouterNoeud({ ...r, decouvrir: !memoire.aVu(r.ref) })
          setTimeout(() => { centrer(r.ref); selectionner(r.ref) }, 250)
        })
        li.appendChild(b)
        liste.appendChild(li)
      }
      if (!res.length) liste.appendChild(el('li', 'memoire-vide', t('memNoResult')))
      liste.hidden = false
    }, 220)
  })
  recherche.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') liste.hidden = true })

  // Déplacer la vue (glisser le fond), zoomer (molette, pincement)
  let pan = null
  svg.addEventListener('pointerdown', (ev) => {
    pan = { x: ev.clientX, y: ev.clientY }
    svg.setPointerCapture(ev.pointerId)
    liste.hidden = true
  })
  svg.addEventListener('pointermove', (ev) => {
    if (!pan) return
    vue.x += ev.clientX - pan.x; vue.y += ev.clientY - pan.y
    pan = { x: ev.clientX, y: ev.clientY }
    appliquerVue()
  })
  svg.addEventListener('pointerup', () => { pan = null })
  svg.addEventListener('wheel', (ev) => {
    ev.preventDefault()
    const f = ev.deltaY > 0 ? 1 / 1.12 : 1.12
    const r = svg.getBoundingClientRect()
    const mx = ev.clientX - r.left, my = ev.clientY - r.top
    const k = Math.min(3, Math.max(0.25, vue.k * f))
    vue = { x: mx - ((mx - vue.x) * k) / vue.k, y: my - ((my - vue.y) * k) / vue.k, k }
    appliquerVue()
  }, { passive: false })
  dlg.addEventListener('close', () => sim.stop(), { once: true })

  if (focus && noeuds.has(focus)) setTimeout(() => { centrer(focus); selectionner(focus) }, 400)
}
