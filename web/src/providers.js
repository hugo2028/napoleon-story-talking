// Fournisseurs proposés pour la partie agent (archiviste + narrateur). Tous exposent une API
// compatible OpenAI ; « Autre » accepte n'importe quelle URL compatible. Aucun modèle n'est écrit
// ici : la liste vient de l'API du fournisseur (route /models), selon la clé saisie.
export const PROVIDERS = {
  openai:     { label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', keyUrl: 'https://platform.openai.com/api-keys' },
  anthropic:  { label: 'Anthropic (Claude)', baseUrl: 'https://api.anthropic.com/v1', keyUrl: 'https://console.anthropic.com/settings/keys' },
  mistral:    { label: 'Mistral AI', baseUrl: 'https://api.mistral.ai/v1', keyUrl: 'https://console.mistral.ai/api-keys' },
  gemini:     { label: 'Google Gemini', baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai', keyUrl: 'https://aistudio.google.com/apikey' },
  openrouter: { label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1', keyUrl: 'https://openrouter.ai/keys' },
  groq:       { label: 'Groq', baseUrl: 'https://api.groq.com/openai/v1', keyUrl: 'https://console.groq.com/keys' },
  ollama:     { label: 'Ollama (local)', baseUrl: 'http://localhost:11434/v1', keyUrl: 'https://ollama.com/download', noKey: true },
  custom:     { label: '…', baseUrl: '', keyUrl: '' },
}

/** Fournisseur correspondant à une URL déjà configurée. */
export function providerFromUrl(url = '') {
  const clean = url.replace(/\/+$/, '')
  return Object.keys(PROVIDERS).find(k => k !== 'custom' && PROVIDERS[k].baseUrl === clean) || 'custom'
}
