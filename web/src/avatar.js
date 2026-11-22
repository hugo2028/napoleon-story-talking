import * as THREE from 'https://esm.sh/three@0.168.0'
import { GLTFLoader } from 'https://esm.sh/three@0.168.0/examples/jsm/loaders/GLTFLoader.js'

const avatarUrl = new URL('../avatar/avatar.glb', import.meta.url).href
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
    this.container.replaceChildren(this.renderer.domElement)

    const hemi = new THREE.HemisphereLight(0xdde8ff, 0x1b1b22, 2.2)
    this.scene.add(hemi)

    const key = new THREE.DirectionalLight(0xffffff, 2.4)
    key.position.set(2, 4, 3)
    this.scene.add(key)

    const fill = new THREE.DirectionalLight(0x9eb8ff, 0.9)
    fill.position.set(-3, 2, 2)
    this.scene.add(fill)

    const loader = new GLTFLoader()
    const gltf = await loader.loadAsync(url)

    this.avatarRoot = gltf.scene
    this.scene.add(this.avatarRoot)

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

  _frameAvatar() {
    const box = new THREE.Box3().setFromObject(this.avatarRoot)
    box.getSize(this.frameSize)
    box.getCenter(this.frameCenter)
    this._setCameraTargets(this.cameraMode, true)
  }

  _setCameraTargets(mode = 'default', snap = false) {
    const center = this.frameCenter
    const size = this.frameSize
    const isClose = mode === 'closeup'
    // Écran en hauteur (mobile) : les repères couvrent le haut et les commandes le bas de l'image ;
    // la caméra recule pour que Napoléon tienne en entier dans la zone dégagée.
    const portrait = this.camera && this.camera.aspect < 0.8
    const focusY = center.y + size.y * (isClose ? 0.22 : portrait ? 0.04 : 0.12)
    const distance = isClose
      ? Math.max(2.2, size.y * 0.48 + 0.85)
      : Math.max(5.4, size.y * 1.3 + 2.7) * (portrait ? 1.5 : 1)

    this.cameraMode = mode
    this.cameraFovTarget = isClose ? 26 : 30
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
    this._updateCamera(dt)
    this.renderer.render(this.scene, this.camera)
  }

  _updateCamera(dt) {
    const ease = Math.min(1, dt * 3.2)
    this.cameraPosCurrent.lerp(this.cameraPosTarget, ease)
    this.cameraLookCurrent.lerp(this.cameraLookTarget, ease)
    this.cameraFovCurrent = THREE.MathUtils.lerp(this.cameraFovCurrent, this.cameraFovTarget, ease)
    this.camera.position.copy(this.cameraPosCurrent)
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
