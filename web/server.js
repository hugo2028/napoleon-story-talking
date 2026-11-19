import dotenv from 'dotenv'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __filename = fileURLToPath(import.meta.url)
const __dirname  = path.dirname(__filename)
dotenv.config({ path: path.join(__dirname, '..', '.env') })

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
  const { conversationId, messages, lang } = req.body
  const message = lastUserMessage(messages)

  if (!message) {
    return res.status(400).json({ error: 'Message utilisateur vide' })
  }

  try {
    const pyRes = await fetch(`${NAPOLEON_API}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: conversationId || null, message, lang: lang || 'fr' })
    })
    const data = await pyRes.json()
    if (!pyRes.ok) {
      console.error('[Agent]', data)
      return res.status(pyRes.status).json({ error: data.error || 'Erreur agent' })
    }
    res.json({ speech: data.speech || '', conversation_id: data.conversation_id, event: data.event, turn: data.turn, doc_count: data.doc_count ?? null, context: data.context ?? null, sources: data.sources ?? null, actions: data.actions ?? null, annotation: data.annotation ?? null })
  } catch (err) {
    console.error('[Agent]', err.message)
    res.status(500).json({ error: err.message })
  }
})

const PORT = process.env.PORT || 3002
app.listen(PORT, () => console.log(`Napoleon backend ready on :${PORT}`))
