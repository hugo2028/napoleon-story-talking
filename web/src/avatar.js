import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { Weather, WallBoard } from './decorScene.js'

const avatarUrl = new URL('../avatar/avatar.glb', import.meta.url).href
// Décor de Longwood : lumière précalculée dans Blender (scripts/build_longwood_scene.py), affichée telle quelle
const decorUrl = new URL('../decor/longwood.glb', import.meta.url).href

// Repères du décor : lus dans le GLB (objets « ancre_* » du script Blender) ; ces valeurs ne servent que
// si un ancien fichier n'en contient pas. Coordonnées three.js (Blender x, y, z → three x, z, -y).
const DECOR_ANCHOR_DEFAULTS = {
  lustre: new THREE.Vector3(1.75, 2.5, -1.3),
  bougie: new THREE.Vector3(1.6, 1.09, -2.0),
  feu: new THREE.Vector3(-2.8, 0.5, 0.4),
  ciel: new THREE.Vector3(-1.75, 2.0, -5.1),
  tableau: new THREE.Vector3(1.45, 1.55, -2.62),
}
const DEFAULT_AVATAR_URL = import.meta.env.DEV
  ? `${avatarUrl}?t=${Date.now()}`
  : avatarUrl

/** Le modèle 3D est-il présent ? (absent du dépôt public : le serveur de dev renvoie alors index.html) */
export async function avatarModelAvailable(url = avatarUrl) {
  try {
    const res = await fetch(url, { method: 'HEAD', cache: 'no-store' })
    return res.ok && !(res.headers.get('content-type') || '').includes('text/html')
  } catch {
    return false
  }
}

// L'avatar a une shape key par identifiant de visème Azure : viseme_00 … viseme_21.
const AZURE_VISEME_TO_MORPH = Object.fromEntries(
  Array.from({ length: 22 }, (_, id) => [id, `viseme_${String(id).padStart(2, '0')}`])
)
const SILENCE_MORPH = AZURE_VISEME_TO_MORPH[0]

const IDLE_ACTION_NAME = 'idle_weight_shift'
const TALK_ACTION_NAME = 'talk_speaking_with_gestures'
const TALK_ACTION_NAMES = [TALK_ACTION_NAME]
const ACTION_REPLAY_COOLDOWN_MS = 3000
// Ordre des 55 valeurs d'une image faciale Azure : les 52 expressions ARKit, puis le roulis
// de la tête et des yeux (non utilisés ici).
const AZURE_BLENDSHAPES = ['eyeBlinkLeft', 'eyeLookDownLeft', 'eyeLookInLeft', 'eyeLookOutLeft', 'eyeLookUpLeft',
  'eyeSquintLeft', 'eyeWideLeft', 'eyeBlinkRight', 'eyeLookDownRight', 'eyeLookInRight', 'eyeLookOutRight',
  'eyeLookUpRight', 'eyeSquintRight', 'eyeWideRight', 'jawForward', 'jawLeft', 'jawRight', 'jawOpen', 'mouthClose',
  'mouthFunnel', 'mouthPucker', 'mouthLeft', 'mouthRight', 'mouthSmileLeft', 'mouthSmileRight', 'mouthFrownLeft',
  'mouthFrownRight', 'mouthDimpleLeft', 'mouthDimpleRight', 'mouthStretchLeft', 'mouthStretchRight',
  'mouthRollLower', 'mouthRollUpper', 'mouthShrugLower', 'mouthShrugUpper', 'mouthPressLeft', 'mouthPressRight',
  'mouthLowerDownLeft', 'mouthLowerDownRight', 'mouthUpperUpLeft', 'mouthUpperUpRight', 'browDownLeft',
  'browDownRight', 'browInnerUp', 'browOuterUpLeft', 'browOuterUpRight', 'cheekPuff', 'cheekSquintLeft',
  'cheekSquintRight', 'noseSneerLeft', 'noseSneerRight', 'tongueOut']
const FACE_FPS = 60
// Réflexion entre deux réponses : une animation « thinking » si le modèle en contient une,
// sinon une attitude composée (tête penchée, regard ailleurs) et, de temps en temps, un geste pensif.
const THINK_ACTION_NAME = 'thinking'
const THINK_GESTURES = ['gesture_look_away', 'head_shake_thoughtful']

export class AvatarPlayer {
  constructor(container) {
    this.container = container
    this.renderer = null
    this.camera = null
    this.scene = null
    this.clock = new THREE.Clock()
    this.mixer = null
    this.avatarRoot = null
    this.faceMesh = null
    this.morphDict = null
    this.morphInfluences = null
    this.activeMorphName = SILENCE_MORPH
    this.activeMorphStrength = 0
    this.actions = new Map()
    this.baseAction = null
    this.talkAction = null
    this.gestureAction = null
    this.currentBodyAction = null
    this.talkVariants = []
    this.morphNames = []
    this.clipNames = []
    this._raf = 0
    this._visemeResetTimer = null
    this._gestureReturnTimer = null
    this._lastActionPlayAt = new Map()
    this.isSpeaking = false
    this.overlayMorphs = {}
    this.headBone = null
    this.neckBone = null
    this.elapsed = 0
    this.nextBlinkAt = 0.6
    this.blinkUntil = 0
    this.nextGazeAt = 1.2
    this.gazeUntil = 0
    this.gazeDirection = 0
    this.nextHeadMoveAt = 1.5
    this.headMoveUntil = 0
    this.headTarget = { x: 0, y: 0, z: 0 }
    this.headCurrent = { x: 0, y: 0, z: 0 }
    this.faceFrames = []        // images faciales Azure, indexées par numéro d'image
    this.faceClock = null       // performance.now() de l'image 0
    this.faceValues = null      // valeurs de l'image courante (null : pas d'animation faciale)
    this.isThinking = false
    this.nextThinkGestureAt = 0
    this.nextThinkPoseAt = 0
    this.thinkPose = { x: 0, y: 0, z: 0 }
    this.thinkGaze = 'down'
    this.frameCenter = new THREE.Vector3()
    this.frameSize = new THREE.Vector3(1, 1, 1)
    this.cameraMode = 'default'
    this.cameraLookCurrent = new THREE.Vector3()
    this.cameraLookTarget = new THREE.Vector3()
    this.cameraPosCurrent = new THREE.Vector3()
    this.cameraPosTarget = new THREE.Vector3()
    this.cameraFovCurrent = 30
    this.cameraFovTarget = 30
  }

  static async create(container, url = DEFAULT_AVATAR_URL) {
    const player = new AvatarPlayer(container)
    await player._init(url)
    return player
  }

  async _init(url) {
    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color(0x0f1018)

    const width = this.container.clientWidth || 360
    const height = this.container.clientHeight || 420

    this.camera = new THREE.PerspectiveCamera(30, width / height, 0.1, 100)
    this.camera.position.set(0, 1.5, 3.2)

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.setSize(width, height)
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    // Rendu « cinéma » : les blancs de l'uniforme gardent leur relief au lieu de saturer.
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 0.92
    this.container.replaceChildren(this.renderer.domElement)

    // Éclairage d'ambiance (pièce virtuelle) : reflets et ombrages doux sur la peau et le tissu.
    const pmrem = new THREE.PMREMGenerator(this.renderer)
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
    this.scene.environmentIntensity = 0.4
    pmrem.dispose()

    const hemi = new THREE.HemisphereLight(0xf2e6d0, 0x1a1612, 0.7)
    this.scene.add(hemi)

    // Lumière principale chaude, de trois quarts haut (comme une fenêtre ou une bougie haute)
    const key = new THREE.DirectionalLight(0xffe9cf, 2.4)
    key.position.set(2.2, 4, 3)
    this.scene.add(key)

    // Débouchage froid et léger de l'autre côté
    const fill = new THREE.DirectionalLight(0xb8c8ff, 0.55)
    fill.position.set(-3, 2, 2)
    this.scene.add(fill)

    // Lumière de contour dorée derrière lui : la silhouette se détache du fond sombre
    const rim = new THREE.DirectionalLight(0xffcf8a, 3.0)
    rim.position.set(-1.5, 3, -4)
    this.scene.add(rim)
    this.lights = { hemi, key, fill, rim }

    // Le décor se charge en parallèle de l'avatar ; s'il manque, le fond uni reste.
    this._loadDecor().catch(err => console.info('[Décor] non chargé, fond uni conservé :', err?.message || err))

    const loader = new GLTFLoader()
    const gltf = await loader.loadAsync(url)

    this.avatarRoot = gltf.scene
    this.scene.add(this.avatarRoot)
    this._addContactShadow()

    this._frameAvatar()

    this.faceMesh = this._findFaceMesh(this.avatarRoot)
    if (!this.faceMesh || !this.faceMesh.morphTargetDictionary || !this.faceMesh.morphTargetInfluences) {
      throw new Error('Aucun mesh avec morph targets trouve dans le GLB')
    }

    this.morphDict = this.faceMesh.morphTargetDictionary
    this.morphInfluences = this.faceMesh.morphTargetInfluences
    this.morphNames = Object.keys(this.morphDict)
    // Os Mixamo : "mixamorig:Head" devient "mixamorigHead" (three.js retire les ':')
    this.headBone = this._findBone(['mixamorigHead', 'Head'])
    this.neckBone = this._findBone(['mixamorigNeck', 'Neck'])

    this.mixer = new THREE.AnimationMixer(this.avatarRoot)
    this.clipNames = gltf.animations.map(clip => clip.name)
    for (const clip of gltf.animations) {
      this.actions.set(clip.name, this.mixer.clipAction(clip))
    }

    this.baseAction = this.actions.get(IDLE_ACTION_NAME) || null
    this.talkAction = this.actions.get(TALK_ACTION_NAME) || null
    this.talkVariants = [this.talkAction].filter(Boolean)

    this._playBaseAction()

    this._setMorphImmediate(SILENCE_MORPH, 0)

    window.addEventListener('resize', () => this._resize())
    this._tick()
  }

  /**
   * Décor de Longwood : un seul maillage dont la texture contient déjà la lumière (précalculée dans
   * Blender). Affiché sans éclairage ni tone mapping, il ne coûte presque rien, même sur mobile.
   */
  async _loadDecor(url = decorUrl) {
    const gltf = await new GLTFLoader().loadAsync(url)
    const materials = []
    gltf.scene.traverse(obj => {
      if (!obj.isMesh) return
      const map = obj.material?.map || null
      if (map) map.colorSpace = THREE.SRGBColorSpace
      obj.material = new THREE.MeshBasicMaterial({ map, toneMapped: false })
      materials.push(obj.material)
    })
    this.decorRoot = gltf.scene
    this.decorMaterials = materials
    gltf.scene.updateMatrixWorld(true)
    this.decorAnchors = Object.fromEntries(Object.entries(DECOR_ANCHOR_DEFAULTS).map(([name, fallback]) => {
      const node = gltf.scene.getObjectByName(`ancre_${name}`)
      return [name, node ? node.getWorldPosition(new THREE.Vector3()) : fallback.clone()]
    }))
    this.scene.add(gltf.scene)
    this.scene.add(this._makeSky())
    // Temps derrière la fenêtre et carte murale, réglés par l'archiviste (setWeather, highlightMap)
    this.weather = new Weather(this.scene, this.decorAnchors.ciel)
    this.weather.onLightning = () => this.onLightning?.()
    // Tableau mural (carte et lettres racontées), là où était la porte
    this.wallMap = new WallBoard(this.scene, this.decorAnchors.tableau.clone().add(new THREE.Vector3(0, 0, 0.02)))
    if (this._pendingScene) this.applyScene(this._pendingScene)
    this._matchLightsToDecor()
    this._addDecorLife()
    // Le titre superposé passe à l'encre brune sur le papier peint clair (index.html, .with-decor)
    this.container.parentElement?.classList.add('with-decor')
  }

  /**
   * Ciel vu par la fenêtre : le crépuscule (mer sombre, horizon embrasé) et, par-dessus, la nuit étoilée
   * dont l'opacité suit setNightfall().
   */
  _makeSky() {
    const paint = (stops, stars = 0) => {
      const c = document.createElement('canvas')
      c.width = 128
      c.height = 256
      const ctx = c.getContext('2d')
      const g = ctx.createLinearGradient(0, 256, 0, 0)         // du bas (mer) vers le haut (ciel)
      for (const [pos, color] of stops) g.addColorStop(pos, color)
      ctx.fillStyle = g
      ctx.fillRect(0, 0, 128, 256)
      for (let k = 0; k < stars; k++) {                         // étoiles, au-dessus de l'horizon
        const a = 0.35 + Math.random() * 0.65
        ctx.fillStyle = `rgba(235,238,255,${a})`
        ctx.fillRect(Math.random() * 128, Math.random() * 256 * 0.6, Math.random() < 0.15 ? 1.6 : 1, 1)
      }
      const tex = new THREE.CanvasTexture(c)
      tex.colorSpace = THREE.SRGBColorSpace
      return tex
    }
    const dusk = paint([[0, '#05080e'], [0.36, '#121a26'], [0.365, '#d98a4a'], [0.45, '#9a6058'],
      [0.62, '#3a3a64'], [1, '#141a34']])
    const night = paint([[0, '#020308'], [0.36, '#070b14'], [0.365, '#1c2236'], [0.42, '#141a2c'],
      [1, '#05070f']], 90)
    const group = new THREE.Group()
    const plane = (map, opacity) => new THREE.Mesh(new THREE.PlaneGeometry(6, 4.2),
      new THREE.MeshBasicMaterial({ map, toneMapped: false, transparent: opacity < 1, opacity, depthWrite: false }))
    group.add(plane(dusk, 1))
    this.nightSky = plane(night, 0)
    this.nightSky.position.z = 0.01
    group.add(this.nightSky)
    group.position.copy(this.decorAnchors.ciel)                 // 2,5 m derrière la fenêtre du mur du fond
    return group
  }

  /**
   * Le soir tombe (0 = crépuscule, 1 = nuit) : le ciel s'assombrit et s'étoile, la pièce et la lumière froide
   * de la fenêtre baissent, les bougies prennent le relais. La transition prend une vingtaine de secondes.
   */
  setNightfall(value) {
    this.nightTarget = THREE.MathUtils.clamp(value, 0, 1)
  }

  /**
   * Mise en scène choisie par l'archiviste : { meteo: clair|brume|pluie|orage, carte: région }.
   * Avant le chargement du décor, elle est gardée et appliquée dès qu'il arrive.
   */
  applyScene(scene = {}) {
    if (!this.weather) { this._pendingScene = { ...this._pendingScene, ...scene }; return }
    if (scene.meteo) this.weather.set(scene.meteo)
    if (scene.carte) this.wallMap.highlight(scene.carte)
    if (scene.lettres) this.wallMap.showLetters(scene.lettres)
    if (scene.reset) { this.weather.set('clair'); this.wallMap.clear() }
  }

  /** Les lumières de l'avatar reprennent celles du décor : feu et lustre chauds, fenêtre froide derrière lui. */
  _matchLightsToDecor() {
    const { hemi, key, fill, rim } = this.lights
    hemi.color.set(0xf5e2c0)
    hemi.groundColor.set(0x2a2016)
    hemi.intensity = 0.55
    key.color.set(0xffe4c8)                  // cheminée (à gauche) et lustre
    key.intensity = 1.9
    key.position.set(-2.4, 3.4, 2.6)
    fill.color.set(0xc4d0ff)                 // reflet froid des murs côté droit
    fill.intensity = 0.4
    fill.position.set(3, 2, 2.5)
    rim.color.set(0xa8b8ff)                  // jour finissant par la fenêtre, derrière à gauche
    rim.intensity = 2.0
    rim.position.set(-2, 2.2, -3)
    const top = new THREE.DirectionalLight(0xffcf8a, 1.3)   // lustre, au-dessus du bureau, derrière lui à droite
    top.position.copy(this.decorAnchors.lustre).add(new THREE.Vector3(-0.2, 0.8, 0))
    this.scene.add(top)
    // Feu de cheminée : une lumière qui vacille sur Napoléon (côté gauche, bas)
    this.fireLight = new THREE.PointLight(0xff9a50, 2.2, 9, 1.6)
    this.fireLight.position.copy(this.decorAnchors.feu)
    this.scene.add(this.fireLight)
  }

  /** Flammes vivantes (lustre, bougie du bureau) et éclats du cristal du lustre, par-dessus la texture figée. */
  _addDecorLife() {
    const glow = (inner, outer) => {
      const c = document.createElement('canvas')
      c.width = c.height = 64
      const g = c.getContext('2d').createRadialGradient(32, 32, 0, 32, 32, 32)
      g.addColorStop(0, inner)
      g.addColorStop(0.35, outer)
      g.addColorStop(1, 'rgba(0,0,0,0)')
      const ctx = c.getContext('2d')
      ctx.fillStyle = g
      ctx.fillRect(0, 0, 64, 64)
      const tex = new THREE.CanvasTexture(c)
      tex.colorSpace = THREE.SRGBColorSpace
      return tex
    }
    const flameTex = glow('rgba(255,236,190,1)', 'rgba(255,150,50,0.35)')
    const sparkTex = glow('rgba(255,255,255,1)', 'rgba(210,225,255,0.25)')
    const sprite = (tex, pos, size) => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({
        map: tex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, toneMapped: false,
      }))
      s.position.copy(pos)
      s.scale.setScalar(size)
      this.scene.add(s)
      return s
    }
    this.decorFlames = []
    for (let k = 0; k < 8; k++) {           // 8 bougies sur la couronne du lustre
      const a = (k / 8) * Math.PI * 2
      const p = this.decorAnchors.lustre.clone().add(new THREE.Vector3(0.3 * Math.cos(a), 0.07, -0.3 * Math.sin(a)))
      this.decorFlames.push({ sprite: sprite(flameTex, p, 0.09), size: 0.09, phase: Math.random() * 10 })
    }
    this.decorFlames.push({ sprite: sprite(flameTex, this.decorAnchors.bougie, 0.08), size: 0.08, phase: 3.1 })
    // Poussières en suspension : dans la lumière de la fenêtre, et autour de la bougie du bureau
    const win = this.decorAnchors.ciel
    const candle = this.decorAnchors.bougie
    const count = 140
    const positions = new Float32Array(count * 3)
    this.dustDrift = []
    for (let i = 0; i < count; i++) {
      const nearCandle = i % 5 === 0
      const d = nearCandle
        ? { x: candle.x + (Math.random() - 0.5) * 0.7, y: candle.y + Math.random() * 0.8, z: candle.z + (Math.random() - 0.5) * 0.6 }
        : { x: win.x + (Math.random() - 0.5) * 1.3, y: 0.4 + Math.random() * 2.2, z: -2.4 + Math.random() * 2.4 }
      d.s = 0.08 + Math.random() * 0.2
      d.p = Math.random() * 10
      this.dustDrift.push(d)
      positions.set([d.x, d.y, d.z], i * 3)
    }
    const dustGeo = new THREE.BufferGeometry()
    dustGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    this.dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({
      map: sparkTex, color: 0xffe2b8, size: 0.018, sizeAttenuation: true, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false,
    }))
    this.scene.add(this.dust)

    // Éclats : quelques points du cône de pampilles qui scintillent tour à tour
    this.decorSparkles = []
    for (let k = 0; k < 26; k++) {
      const a = Math.random() * Math.PI * 2
      const h = Math.random()                                  // 0 = couronne, 1 = sommet
      const r = 0.3 - 0.24 * h
      const p = this.decorAnchors.lustre.clone().add(new THREE.Vector3(r * Math.cos(a), -0.02 + 0.52 * h, -r * Math.sin(a)))
      const s = sprite(sparkTex, p, 0.05)
      s.material.opacity = 0
      this.decorSparkles.push({ sprite: s, speed: 0.6 + Math.random() * 1.4, phase: Math.random() * 10 })
    }
  }

  _updateDecor(t, dt = 1 / 60) {
    if (!this.decorMaterials) return
    const lightning = this.weather ? this.weather.update(t, dt) : 0
    // Respiration lente et irrégulière de la lumière du feu et des bougies
    const flicker = 0.5 * Math.sin(t * 7.3) + 0.3 * Math.sin(t * 13.1 + 1.3) + 0.2 * Math.sin(t * 23.7 + 0.4)
    this.night = THREE.MathUtils.lerp(this.night ?? 0, this.nightTarget ?? 0, 0.002)   // ~20 s de transition
    const night = this.night
    const room = (0.985 + 0.015 * flicker) * (1 - 0.24 * night) + 0.35 * lightning
    for (const m of this.decorMaterials) m.color.setScalar(room)
    this.wallMap?.update(t, dt, room)
    if (this.weather) this.weather.fog.material.color.set(0x5d6672).multiplyScalar(1 - 0.6 * night)
    if (this.nightSky) this.nightSky.material.opacity = night
    if (this.lights) this.lights.rim.intensity = 2.0 * (1 - 0.55 * night) + 6 * lightning   // l'éclair le découpe
    if (this.fireLight) this.fireLight.intensity = 2.2 * (0.85 + 0.15 * flicker)
    for (const f of this.decorFlames) {
      const w = 0.88 + 0.12 * Math.sin(t * 11 + f.phase) * Math.sin(t * 5.3 + f.phase * 2)
      const s = f.size * w * (1 + 0.3 * night)                  // la nuit, les flammes rayonnent davantage
      f.sprite.scale.set(s, s * 1.25, 1)
    }
    for (const s of this.decorSparkles) {
      s.sprite.material.opacity = Math.pow(Math.max(0, Math.sin(t * s.speed + s.phase)), 24)
    }
    if (this.dust) {
      const pos = this.dust.geometry.attributes.position
      for (let i = 0; i < pos.count; i++) {
        const d = this.dustDrift[i]
        pos.setXYZ(i, d.x + 0.06 * Math.sin(t * d.s + d.p), d.y + 0.08 * Math.sin(t * d.s * 0.7 + d.p * 2),
          d.z + 0.06 * Math.cos(t * d.s * 0.8 + d.p))
      }
      pos.needsUpdate = true
      this.dust.material.opacity = 0.55 - 0.25 * night         // moins de lumière du jour, moins de poussière visible
    }
  }

  /** Ombre douce au sol sous les pieds : le personnage est posé, il ne flotte plus. */
  _addContactShadow() {
    const box = new THREE.Box3().setFromObject(this.avatarRoot)
    const size = new THREE.Vector3()
    const center = new THREE.Vector3()
    box.getSize(size)
    box.getCenter(center)
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 128
    const ctx = canvas.getContext('2d')
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64)
    g.addColorStop(0, 'rgba(0,0,0,0.55)')
    g.addColorStop(0.55, 'rgba(0,0,0,0.25)')
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, 128, 128)
    const texture = new THREE.CanvasTexture(canvas)
    const radius = Math.max(size.x, size.z) * 0.9
    const shadow = new THREE.Mesh(
      new THREE.PlaneGeometry(radius * 2, radius * 1.2),
      new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, toneMapped: false })
    )
    shadow.rotation.x = -Math.PI / 2
    shadow.position.set(center.x, box.min.y + 0.002, center.z)
    shadow.renderOrder = -1
    this.scene.add(shadow)
  }

  _frameAvatar() {
    const box = new THREE.Box3().setFromObject(this.avatarRoot)
    box.getSize(this.frameSize)
    box.getCenter(this.frameCenter)
    this._setCameraTargets(this.cameraMode, true)
  }

  _setCameraTargets(mode = 'default', snap = false) {
    const center = this.frameCenter
    const size = this.frameSize
    const isFace = mode === 'face'                 // gros plan : le visage (aveu, regret, émotion)
    const isClose = mode === 'closeup' || isFace   // plan rapproché : le buste
    // Écran en hauteur (mobile) : les repères couvrent le haut et les commandes le bas de l'image ;
    // la caméra recule pour que Napoléon tienne en entier dans la zone dégagée.
    const portrait = this.camera && this.camera.aspect < 0.8
    const focusY = center.y + size.y * (isFace ? 0.32 : isClose ? 0.22 : portrait ? 0.04 : 0.12)
    const distance = isFace
      ? Math.max(1.25, size.y * 0.3 + 0.6) * (portrait ? 1.25 : 1)
      : isClose
        ? Math.max(2.2, size.y * 0.48 + 0.85)
        : Math.max(5.4, size.y * 1.3 + 2.7) * (portrait ? 1.5 : 1)

    this.cameraMode = mode
    this.cameraFovTarget = isFace ? 24 : isClose ? 26 : 30
    this.cameraLookTarget.set(center.x, focusY, center.z)
    this.cameraPosTarget.set(center.x, focusY + (isClose ? 0.05 : 0), center.z + distance)

    if (snap) {
      this.cameraLookCurrent.copy(this.cameraLookTarget)
      this.cameraPosCurrent.copy(this.cameraPosTarget)
      this.cameraFovCurrent = this.cameraFovTarget
      this.camera.fov = this.cameraFovCurrent
      this.camera.updateProjectionMatrix()
      this.camera.position.copy(this.cameraPosCurrent)
      this.camera.lookAt(this.cameraLookCurrent)
    }
  }

  _findBone(names) {
    for (const name of names) {
      const bone = this.avatarRoot.getObjectByName(name)
      if (bone) return bone
    }
    return null
  }

  _findFaceMesh(root) {
    let fallback = null
    root.traverse(obj => {
      if (!obj.isMesh) return
      if (obj.morphTargetDictionary && obj.morphTargetInfluences) {
        if (obj.name === 'Wolf3D_Avatar') {
          fallback = obj
          return
        }
        if (!fallback) fallback = obj
      }
    })
    return fallback
  }

  _resize() {
    if (!this.renderer || !this.camera) return
    const width = this.container.clientWidth || 360
    const height = this.container.clientHeight || 420
    this.camera.aspect = width / height
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(width, height)
    if (this.avatarRoot) this._setCameraTargets(this.cameraMode, false)
  }

  _tick() {
    this._raf = requestAnimationFrame(() => this._tick())
    const dt = this.clock.getDelta()
    this.elapsed += dt
    // Retire le décalage procédural de l'image précédente avant que le mixer n'écrive la pose :
    // si aucune action n'écrit la tête à cette image, le décalage ne s'accumule pas (rotation infinie).
    if (this._headBase && this.headBone) this.headBone.quaternion.copy(this._headBase)
    if (this._neckBase && this.neckBone) this.neckBone.quaternion.copy(this._neckBase)
    if (this.mixer) this.mixer.update(dt)
    this._updateProceduralState()
    this._updateMorphs(dt)
    this._applyHeadOffsets(dt)
    this._updateDecor(this.elapsed, dt)
    this._updateCamera(dt)
    this.renderer.render(this.scene, this.camera)
  }

  _updateCamera(dt) {
    const ease = Math.min(1, dt * 3.2)
    this.cameraPosCurrent.lerp(this.cameraPosTarget, ease)
    this.cameraLookCurrent.lerp(this.cameraLookTarget, ease)
    this.cameraFovCurrent = THREE.MathUtils.lerp(this.cameraFovCurrent, this.cameraFovTarget, ease)
    this.camera.position.copy(this.cameraPosCurrent)
    // Légère dérive, comme une caméra tenue qui respire : donne de la profondeur au décor
    const t = this.elapsed
    this.camera.position.x += 0.035 * Math.sin(t * 0.13) + 0.012 * Math.sin(t * 0.41)
    this.camera.position.y += 0.018 * Math.sin(t * 0.09 + 1.1)
    this.camera.fov = this.cameraFovCurrent
    this.camera.updateProjectionMatrix()
    this.camera.lookAt(this.cameraLookCurrent)
  }

  _updateProceduralState() {
    this.overlayMorphs = {}

    if (this.elapsed >= this.nextBlinkAt) {
      this.blinkUntil = this.elapsed + 0.18
      this.nextBlinkAt = this.elapsed + 2.0 + Math.random() * 2.0
    }
    if (this.elapsed < this.blinkUntil) {
      this.overlayMorphs.eyeBlinkLeft = 1
      this.overlayMorphs.eyeBlinkRight = 1
      this.overlayMorphs.eyesClosed = 0.55
    }

    if (this.isSpeaking && this.elapsed >= this.nextGazeAt) {
      this.gazeDirection = Math.random() < 0.5 ? -1 : 1
      this.gazeUntil = this.elapsed + 0.45 + Math.random() * 0.35
      this.nextGazeAt = this.elapsed + 1.8 + Math.random() * 2.2
    }
    if (this.elapsed < this.gazeUntil) {
      if (this.gazeDirection < 0) {
        this.overlayMorphs.eyesLookDown = 0.55
      } else {
        this.overlayMorphs.eyesLookUp = 0.45
      }
    }

    if (this.isSpeaking && this.elapsed >= this.nextHeadMoveAt) {
      this.headMoveUntil = this.elapsed + 0.8 + Math.random() * 0.8
      this.nextHeadMoveAt = this.elapsed + 2.5 + Math.random() * 2.8
      this.headTarget = {
        x: THREE.MathUtils.degToRad(-2 + Math.random() * 4),
        y: THREE.MathUtils.degToRad(-4 + Math.random() * 8),
        z: THREE.MathUtils.degToRad(-2 + Math.random() * 4),
      }
    }
    if (this.elapsed >= this.headMoveUntil) {
      this.headTarget = { x: 0, y: 0, z: 0 }
    }

    if (this.isSpeaking) {
      this.overlayMorphs.mouthSmileLeft = 0.06
      this.overlayMorphs.mouthSmileRight = 0.06
    }

    if (this.isThinking) this._updateThinking()
  }

  /** Attitude de réflexion : la tête se penche et change lentement d'appui, le regard se pose ailleurs. */
  _updateThinking() {
    if (this.elapsed >= this.nextThinkPoseAt) {
      this.nextThinkPoseAt = this.elapsed + 2.4 + Math.random() * 1.8
      const side = Math.random() < 0.5 ? -1 : 1
      this.thinkGaze = Math.random() < 0.65 ? 'down' : 'up'
      this.thinkPose = {
        x: THREE.MathUtils.degToRad(this.thinkGaze === 'down' ? 6 + Math.random() * 3 : -4 - Math.random() * 2),
        y: THREE.MathUtils.degToRad(side * (5 + Math.random() * 5)),
        z: THREE.MathUtils.degToRad(side * (3 + Math.random() * 3)),
      }
    }
    this.headTarget = this.thinkPose
    if (this.thinkGaze === 'down') this.overlayMorphs.eyesLookDown = 0.45
    else this.overlayMorphs.eyesLookUp = 0.4

    const thinkClip = this.actions.get(THINK_ACTION_NAME)
    if (!thinkClip && this.elapsed >= this.nextThinkGestureAt) {
      this.nextThinkGestureAt = this.elapsed + 6 + Math.random() * 4
      const available = THINK_GESTURES.filter(name => this.actions.has(name))
      if (available.length) this.playNamedGesture(available[Math.floor(Math.random() * available.length)])
    }
  }

  /** Napoléon réfléchit pendant que l'archiviste cherche ses lettres. */
  startThinking() {
    if (this.isThinking) return
    this.isThinking = true
    this.nextThinkPoseAt = this.elapsed
    this.nextThinkGestureAt = this.elapsed + 1.2
    const thinkClip = this.actions.get(THINK_ACTION_NAME)
    if (thinkClip) this._switchBodyAction(thinkClip, 0.4)
  }

  stopThinking() {
    if (!this.isThinking) return
    this.isThinking = false
    this.headTarget = { x: 0, y: 0, z: 0 }
    if (!this.isSpeaking && this.baseAction) this._switchBodyAction(this.baseAction, 0.4)
  }

  // ── Animation faciale complète (Azure « FacialExpression ») ──────────────
  resetFace() {
    this.faceFrames = []
    this.faceClock = null
    this.faceValues = null
  }

  addFaceFrames(firstIndex, frames) {
    for (let i = 0; i < frames.length; i++) this.faceFrames[firstIndex + i] = frames[i]
  }

  setFaceClock(frame0At) {
    this.faceClock = frame0At
  }

  /** Valeurs de l'image faciale à l'instant présent (interpolées), ou null hors animation. */
  _currentFaceValues() {
    if (this.faceClock === null || !this.faceFrames.length) return null
    const f = (performance.now() - this.faceClock) / 1000 * FACE_FPS
    if (f < 0) return null
    if (f >= this.faceFrames.length) {
      // fin de la phrase : on relâche (ou on attend les images suivantes encore en route)
      return f > this.faceFrames.length + FACE_FPS * 0.5 ? null : this.faceValues
    }
    const i = Math.floor(f)
    const a = this.faceFrames[i]
    const b = this.faceFrames[i + 1] || a
    if (!a) return this.faceValues
    const t = f - i
    return a.map((v, k) => v + ((b[k] ?? v) - v) * t)
  }

  _updateMorphs(dt) {
    if (!this.morphInfluences) return
    this.faceValues = this._currentFaceValues()
    if (this.faceValues) {
      // Le visage suit Azure image par image ; clignements et regard procéduraux s'ajoutent.
      const face = {}
      AZURE_BLENDSHAPES.forEach((name, k) => { face[name] = this.faceValues[k] || 0 })
      for (const name of this.morphNames) {
        const idx = this.morphDict[name]
        const target = Math.min(1, Math.max(face[name] || 0, this.overlayMorphs[name] || 0))
        this.morphInfluences[idx] = THREE.MathUtils.lerp(this.morphInfluences[idx], target, Math.min(1, dt * 30))
      }
      return
    }
    const targetIndex = this.morphDict[this.activeMorphName]
    const relaxSpeed = 10
    for (const name of this.morphNames) {
      const idx = this.morphDict[name]
      const visemeTarget = idx === targetIndex ? this.activeMorphStrength : 0
      const overlayTarget = this.overlayMorphs[name] || 0
      const target = Math.min(1, visemeTarget + overlayTarget)
      this.morphInfluences[idx] = THREE.MathUtils.lerp(this.morphInfluences[idx], target, Math.min(1, dt * relaxSpeed))
    }
    // Les visèmes viseme_00…21 incluent déjà l'ouverture de mâchoire : pas de jawOpen additionnel.
  }

  _setMorphImmediate(name, strength) {
    if (!this.morphDict || this.morphDict[name] === undefined) return
    for (const morphName of this.morphNames) {
      const idx = this.morphDict[morphName]
      this.morphInfluences[idx] = morphName === name ? strength : 0
    }
    this.activeMorphName = name
    this.activeMorphStrength = strength
  }

  _playBaseAction() {
    if (!this.baseAction) return
    this._switchBodyAction(this.baseAction, 0)
  }

  _switchBodyAction(nextAction, fadeDuration = 0.25) {
    if (!nextAction) return

    const previous = this.currentBodyAction
    if (previous === nextAction) {
      nextAction.paused = false
      nextAction.enabled = true
      nextAction.setEffectiveTimeScale(1)
      nextAction.setEffectiveWeight(1)
      nextAction.play()
      return
    }

    nextAction.reset()
    nextAction.enabled = true
    nextAction.paused = false
    nextAction.clampWhenFinished = false
    nextAction.setLoop(THREE.LoopRepeat)
    nextAction.setEffectiveTimeScale(1)
    nextAction.setEffectiveWeight(1)
    nextAction.play()

    if (previous) {
      previous.enabled = true
      previous.paused = false
      previous.crossFadeTo(nextAction, fadeDuration, true)
    } else {
      nextAction.fadeIn(fadeDuration)
    }

    this.currentBodyAction = nextAction
  }

  setViseme(id) {
    if (this.faceValues) return
    const morphName = AZURE_VISEME_TO_MORPH[id] || SILENCE_MORPH
    if (this.morphDict?.[morphName] === undefined) {
      this.activeMorphName = SILENCE_MORPH
      this.activeMorphStrength = 0
      return
    }
    this.activeMorphName = morphName
    this.activeMorphStrength = id === 0 ? 0 : 1
    clearTimeout(this._visemeResetTimer)
    this._visemeResetTimer = setTimeout(() => {
      this.activeMorphName = SILENCE_MORPH
      this.activeMorphStrength = 0
    }, 140)
  }

  startTalking() {
    this.isThinking = false
    this.isSpeaking = true
    if (this.talkAction) {
      this._switchBodyAction(this.talkAction, 0.25)
    }
  }

  stopTalking() {
    this.isSpeaking = false
    this.resetFace()
    if (this.baseAction) {
      this._switchBodyAction(this.baseAction, 0.35)
    }
    this.activeMorphName = SILENCE_MORPH
    this.activeMorphStrength = 0
    this.headTarget = { x: 0, y: 0, z: 0 }
  }

  playNamedGesture(name) {
    const next = this.actions.get(name)
    if (!next || next === this.currentBodyAction) return false
    clearTimeout(this._gestureReturnTimer)
    this.gestureAction = next

    next.reset()
    next.setLoop(THREE.LoopOnce, 1)
    next.clampWhenFinished = true
    next.paused = false
    next.enabled = true

    const previous = this.currentBodyAction
    next.setEffectiveTimeScale(1)
    next.setEffectiveWeight(1)
    next.play()
    if (previous && previous !== next) {
      previous.enabled = true
      previous.paused = false
      previous.crossFadeTo(next, 0.18)
    } else {
      next.fadeIn(0.18)
    }
    this.currentBodyAction = next

    const durationMs = Math.max(350, next.getClip().duration * 1000 - 120)
    this._gestureReturnTimer = setTimeout(() => {
      if (this.currentBodyAction !== next) return
      const fallback = this.isSpeaking ? this.talkAction
        : (this.isThinking && this.actions.get(THINK_ACTION_NAME)) || this.baseAction
      if (fallback && fallback !== next) {
        this._switchBodyAction(fallback, 0.25)
      }
    }, durationMs)

    return true
  }

  /** Bascule l'animation de corps en cours (crossfade 0.4s). Utilisé pour la synchro mid-speech. */
  switchAnimation(name) {
    if (name === 'waiting') {
      return true
    }

    const action = this.actions.get(name)
    if (!action) return false

    const now = performance.now()
    const lastPlayAt = this._lastActionPlayAt.get(name) ?? -Infinity
    if (now - lastPlayAt < ACTION_REPLAY_COOLDOWN_MS) {
      return true
    }
    this._lastActionPlayAt.set(name, now)

    if (!TALK_ACTION_NAMES.includes(name)) {
      return this.playNamedGesture(name)
    }
    this._switchBodyAction(action, 0.4)
    return true
  }

  setCameraMode(mode = 'default') {
    this._setCameraTargets(mode, false)
  }

  _applyHeadOffsets(dt) {
    const ease = Math.min(1, dt * 4)
    this.headCurrent.x = THREE.MathUtils.lerp(this.headCurrent.x, this.headTarget.x, ease)
    this.headCurrent.y = THREE.MathUtils.lerp(this.headCurrent.y, this.headTarget.y, ease)
    this.headCurrent.z = THREE.MathUtils.lerp(this.headCurrent.z, this.headTarget.z, ease)

    const qOffsetHead = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(this.headCurrent.x, this.headCurrent.y, this.headCurrent.z, 'XYZ')
    )
    const qOffsetNeck = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(this.headCurrent.x * 0.35, this.headCurrent.y * 0.35, this.headCurrent.z * 0.2, 'XYZ')
    )

    if (this.neckBone) {
      this._neckBase = (this._neckBase || new THREE.Quaternion()).copy(this.neckBone.quaternion)
      this.neckBone.quaternion.multiply(qOffsetNeck)
    }
    if (this.headBone) {
      this._headBase = (this._headBase || new THREE.Quaternion()).copy(this.headBone.quaternion)
      this.headBone.quaternion.multiply(qOffsetHead)
    }
  }

  destroy() {
    cancelAnimationFrame(this._raf)
    clearTimeout(this._visemeResetTimer)
    clearTimeout(this._gestureReturnTimer)
    this.renderer?.dispose()
  }
}

export function listSupportedVisemes() {
  return { ...AZURE_VISEME_TO_MORPH }
}
