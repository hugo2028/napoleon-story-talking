import dotenv from 'dotenv'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'

const __filename = fileURLToPath(import.meta.url)
const __dirname  = path.dirname(__filename)
const ENV_PATH   = path.join(__dirname, '..', '.env')
dotenv.config({ path: ENV_PATH })

// ── Clés saisies dans « Paramètres » : écrites dans le .env local, jamais renvoyées ──
const LOCAL_ADDRS = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1'])
const isLocal = (req) => LOCAL_ADDRS.has(req.socket.remoteAddress)

/** Met à jour (ou ajoute) des variables dans .env sans toucher au reste du fichier. */
function upsertEnv(vars) {
  let text = fs.existsSync(ENV_PATH) ? fs.readFileSync(ENV_PATH, 'utf8') : ''
  for (const [key, value] of Object.entries(vars)) {
    const line = `${key}=${value}`
    const re = new RegExp(`^#?\\s*${key}=.*$`, 'm')
    text = re.test(text) ? text.replace(re, line) : `${text.replace(/\s*$/, '')}\n${line}\n`
    process.env[key] = value
  }
  fs.writeFileSync(ENV_PATH, text.startsWith('\n') ? text.slice(1) : text)
}

const azureConfigured = () =>
  Boolean(process.env.AZURE_SPEECH_KEY && (process.env.AZURE_SPEECH_REGION || process.env.AZURE_ENDPOINT))

/** Vérifie une clé Azure Speech en demandant un jeton de 10 minutes à la région indiquée. */
async function azureKeyWorks(key, region) {
  try {
    const res = await fetch(`https://${region}.api.cognitive.microsoft.com/sts/v1.0/issueToken`, {
      method: 'POST',
      headers: { 'Ocp-Apim-Subscription-Key': key, 'Content-Length': '0' },
    })
    return res.ok
  } catch {
    return false
  }
}

import express from 'express'
import cors from 'cors'

const app = express()
app.use(cors())
app.use(express.json())

const NAPOLEON_API      = process.env.NAPOLEON_API_URL || 'http://localhost:5001'
const ELEVENLABS_KEY    = process.env.ELEVENLABS_API_KEY || ''
const ELEVENLABS_VOICE  = process.env.ELEVENLABS_VOICE_ID || ''

function lastUserMessage(messages) {
  if (!Array.isArray(messages)) return ''
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === 'user' && typeof messages[i].content === 'string') {
      return messages[i].content.trim()
    }
  }
  return ''
}

// Expose Azure Speech credentials + TTS provider to the frontend
app.get('/api/speech-config', (req, res) => {
  res.json({
    key:         process.env.AZURE_SPEECH_KEY,
    region:      process.env.AZURE_SPEECH_REGION,
    endpoint:    process.env.AZURE_ENDPOINT,
    ttsProvider: process.env.TTS_PROVIDER || 'azure',   // 'azure' | 'elevenlabs'
  })
})

// État de la configuration (sans jamais renvoyer les clés) : l'interface ouvre « Paramètres »
// si aucun modèle n'est configuré. Azure Speech est optionnel (voix du navigateur sinon).
app.get('/api/config-status', async (req, res) => {
  let agent = { llm: false }
  let api = true
  try {
    agent = await (await fetch(`${NAPOLEON_API}/config/status`)).json()
  } catch {
    api = false
  }
  res.json({ ...agent, azure: azureConfigured(), azureRegion: process.env.AZURE_SPEECH_REGION || '', api })
})

// Modèles proposés par un fournisseur (liste de choix dans « Paramètres »).
app.post('/api/config/models', async (req, res) => {
  if (!isLocal(req)) return res.status(403).json({ error: 'forbidden' })
  try {
    const r = await fetch(`${NAPOLEON_API}/config/models`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: req.body.baseUrl || '', api_key: req.body.apiKey || '' }),
    })
    res.status(r.status).json(await r.json())
  } catch {
    res.status(502).json({ error: 'api_unreachable' })
  }
})

// Enregistre la configuration saisie dans « Paramètres » (machine locale uniquement), après vérification.
app.post('/api/config', async (req, res) => {
  if (!isLocal(req)) return res.status(403).json({ error: 'forbidden' })
  const b = req.body || {}
  const azureKey    = (b.azureKey || '').trim()
  const azureRegion = (b.azureRegion || '').trim().toLowerCase()

  // Voix Azure (optionnelle)
  if (azureKey || azureRegion) {
    const key = azureKey || process.env.AZURE_SPEECH_KEY || ''
    const region = azureRegion || process.env.AZURE_SPEECH_REGION || ''
    if (!key || !/^[a-z0-9]+$/.test(region)) return res.status(400).json({ error: 'invalid_azure' })
    if (!(await azureKeyWorks(key, region))) return res.status(400).json({ error: 'invalid_azure' })
    upsertEnv({ AZURE_SPEECH_KEY: key, AZURE_SPEECH_REGION: region })
  }

  // Partie agent : fournisseur, clé, modèles, clé d'embeddings (vérifiés par l'API Python)
  if (b.agent) {
    const a = b.agent
    try {
      const r = await fetch(`${NAPOLEON_API}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base_url: a.baseUrl || '', api_key: (a.apiKey || '').trim(),
          model: a.model || '', agent_model: a.agentModel || '',
          ...(a.embeddingKey !== undefined ? { embedding_key: (a.embeddingKey || '').trim() } : {}),
        }),
      })
      const data = await r.json()
      if (!r.ok) return res.status(400).json({ error: data.error || 'invalid_llm' })
      const vars = { LLM_BASE_URL: data.base_url, LLM_MODEL: data.model, AGENT_MODEL: data.agent_model }
      if ((a.apiKey || '').trim()) vars.LLM_API_KEY = a.apiKey.trim()
      if ((a.embeddingKey || '').trim()) vars.EMBEDDING_API_KEY = a.embeddingKey.trim()
      upsertEnv(vars)
    } catch {
      return res.status(502).json({ error: 'api_unreachable' })
    }
  }
  res.json({ ok: true })
})

// ElevenLabs TTS proxy — évite d'exposer la clé API au frontend
app.post('/api/tts', async (req, res) => {
  const { text } = req.body
  if (!text)              return res.status(400).json({ error: 'text requis' })
  if (!ELEVENLABS_KEY)   return res.status(500).json({ error: 'ELEVENLABS_API_KEY manquant dans .env' })
  if (!ELEVENLABS_VOICE) return res.status(500).json({ error: 'ELEVENLABS_VOICE_ID manquant dans .env' })

  try {
    // with-timestamps retourne JSON { audio_base64, alignment: { characters, character_start_times_seconds, character_end_times_seconds } }
    const elRes = await fetch(
      `https://api.elevenlabs.io/v1/text-to-speech/${ELEVENLABS_VOICE}/with-timestamps`,
      {
        method: 'POST',
        headers: {
          'xi-api-key': ELEVENLABS_KEY,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text,
          model_id: 'eleven_multilingual_v2',
          voice_settings: { stability: 0.5, similarity_boost: 0.75 },
        }),
      }
    )
    if (!elRes.ok) {
      const errText = await elRes.text()
      console.error('[ElevenLabs]', elRes.status, errText)
      return res.status(elRes.status).json({ error: errText })
    }
    const data = await elRes.json()
    res.json({ audio: data.audio_base64, alignment: data.alignment })
  } catch (err) {
    console.error('[ElevenLabs]', err.message)
    res.status(500).json({ error: err.message })
  }
})

// Agent chat endpoint — proxy vers napoleon_api.py (Python Flask, port 5001)
app.post('/api/chat', async (req, res) => {
  const { conversationId, messages, lang, langName } = req.body
  const message = lastUserMessage(messages)

  if (!message) {
    return res.status(400).json({ error: 'Message utilisateur vide' })
  }

  try {
    const pyRes = await fetch(`${NAPOLEON_API}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: conversationId || null, message, lang: lang || 'fr', lang_name: langName || '' })
    })
    const data = await pyRes.json()
    if (!pyRes.ok) {
      console.error('[Agent]', data)
      return res.status(pyRes.status).json({ error: data.error || 'Erreur agent', code: data.error })
    }
    res.json({ speech: data.speech || '', conversation_id: data.conversation_id, event: data.event, turn: data.turn, doc_count: data.doc_count ?? null, context: data.context ?? null, sources: data.sources ?? null, actions: data.actions ?? null, annotation: data.annotation ?? null })
  } catch (err) {
    console.error('[Agent]', err.message)
    res.status(500).json({ error: err.message })
  }
})

const PORT = process.env.PORT || 3002
app.listen(PORT, () => console.log(`Napoleon backend ready on :${PORT}`))
