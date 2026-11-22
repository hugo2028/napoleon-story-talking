// Conditions d'utilisation de la version en ligne (PUBLIC_MODE côté serveur : configStatus.readOnly).
// À la première visite, le visiteur doit les accepter ; ensuite, un lien discret permet de les relire.
// En local (dépôt cloné), rien ne s'affiche.
import { getLang } from './i18n.js'

const ACCEPT_KEY = 'napoleon.terms.v1'
const UPDATED = { fr: 'novembre 2026', en: 'November 2026' }

const TEXT = {
  fr: {
    title: "Conditions d'utilisation",
    link: "Conditions d'utilisation",
    accept: "J'accepte",
    close: 'Fermer',
    intro: "Ce site est un projet personnel et non commercial, accessible sur invitation. En l'utilisant, vous acceptez les conditions suivantes.",
    sections: [
      ['Accès', [
        "L'accès est réservé aux personnes invitées. Le mot de passe est personnel : ne le partagez pas et ne le publiez pas.",
      ]],
      ['Le modèle 3D de Napoléon', [
        "Le modèle 3D, ses textures, animations et expressions sont utilisés sous licence et ne sont pas libres de droits.",
        "Sont interdits : la copie, le téléchargement, l'extraction (y compris depuis le navigateur ou le trafic réseau), la reproduction, la modification, la redistribution, la revente, la location et toute exploitation commerciale du modèle ou de ses éléments, ainsi que leur utilisation pour entraîner ou alimenter un système d'intelligence artificielle.",
      ]],
      ["Captures et enregistrements", [
        "Toute reproduction de l'avatar (captures d'écran, vidéos, enregistrements, diffusion en direct) est interdite sans autorisation écrite préalable, en particulier à des fins commerciales ou de publication.",
      ]],
      ['Usage du service', [
        "Il est interdit d'interroger le site de manière automatisée (robots, aspiration de contenu), de tenter de contourner ses protections, d'en perturber le fonctionnement ou de l'utiliser à des fins illicites.",
      ]],
      ['Contenus générés par intelligence artificielle', [
        "Les réponses de « Napoléon » sont produites par des modèles d'IA à partir de sa correspondance. Il s'agit d'une reconstitution : elles peuvent contenir des erreurs, des approximations ou des anachronismes et ne constituent ni une source historique ni l'expression d'une personne réelle. Les lettres citées sont consultables sur Gallica pour vérification.",
      ]],
      ['Textes historiques', [
        "Les lettres proviennent d'éditions du XIXᵉ siècle numérisées par la Bibliothèque nationale de France (Gallica, « Source gallica.bnf.fr / BnF ») et par le Projet Gutenberg ; leur réutilisation obéit aux conditions de ces institutions. Le code source de l'application est publié sous licence MIT, à l'exclusion du modèle 3D.",
      ]],
      ['Données', [
        "Vos messages sont transmis à OpenAI (génération des réponses) et à Microsoft Azure (voix) pour être traités. La conversation est gardée temporairement en mémoire sur le serveur, sans être archivée, et son historique est conservé dans votre navigateur. Aucun cookie publicitaire ni outil de mesure d'audience n'est utilisé. N'indiquez pas d'informations personnelles ou sensibles dans vos messages.",
      ]],
      ['Responsabilité', [
        "Le service est fourni « en l'état », sans garantie de disponibilité ni d'exactitude, et peut être modifié, interrompu ou fermé à tout moment. L'accès peut être retiré en cas de non-respect de ces conditions.",
      ]],
    ],
    updated: 'Dernière mise à jour',
  },
  en: {
    title: 'Terms of use',
    link: 'Terms of use',
    accept: 'I accept',
    close: 'Close',
    intro: 'This site is a personal, non-commercial project available by invitation. By using it, you accept the following terms.',
    sections: [
      ['Access', [
        'Access is restricted to invited people. The password is personal: do not share or publish it.',
      ]],
      ['The 3D model of Napoleon', [
        'The 3D model, its textures, animations and expressions are used under licence and are not free to use.',
        'The following are prohibited: copying, downloading, extracting (including from the browser or network traffic), reproducing, modifying, redistributing, reselling, renting or commercially exploiting the model or any part of it, and using it to train or feed an artificial intelligence system.',
      ]],
      ['Screenshots and recordings', [
        'Any reproduction of the avatar (screenshots, videos, recordings, live streaming) is prohibited without prior written permission, in particular for commercial use or publication.',
      ]],
      ['Use of the service', [
        'Automated querying (bots, content scraping), attempts to bypass its protections, disrupting its operation and any unlawful use are prohibited.',
      ]],
      ['AI-generated content', [
        "“Napoleon's” answers are produced by AI models from his correspondence. They are a reconstruction: they may contain errors, approximations or anachronisms, and are neither a historical source nor the words of a real person. The quoted letters can be checked on Gallica.",
      ]],
      ['Historical texts', [
        'The letters come from 19th-century editions digitised by the Bibliothèque nationale de France (Gallica, “Source gallica.bnf.fr / BnF”) and by Project Gutenberg; their reuse is subject to those institutions’ terms. The application source code is released under the MIT licence, excluding the 3D model.',
      ]],
      ['Data', [
        'Your messages are sent to OpenAI (answer generation) and Microsoft Azure (voice) for processing. The conversation is kept temporarily in the server’s memory, without being archived, and its history is stored in your browser. No advertising cookies or audience-measurement tools are used. Do not include personal or sensitive information in your messages.',
      ]],
      ['Liability', [
        'The service is provided “as is”, with no guarantee of availability or accuracy, and may be changed, interrupted or closed at any time. Access may be withdrawn if these terms are not respected.',
      ]],
    ],
    updated: 'Last updated',
  },
}

const STYLE = `
#terms-dialog { margin: auto; width: min(620px, calc(100vw - 24px)); max-height: calc(100dvh - 24px); padding: 0;
  background: var(--surface2); color: var(--text); border: 1px solid var(--border); border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0,0,0,.6); font-family: system-ui, sans-serif; }
#terms-dialog::backdrop { background: rgba(0,0,0,.7); backdrop-filter: blur(3px); }
#terms-dialog .terms-body { padding: 20px 22px; display: flex; flex-direction: column; gap: 12px; font-size: 13px; line-height: 1.55; }
#terms-dialog h3 { font-family: Georgia, serif; font-weight: 400; font-size: 14px; letter-spacing: .2em; text-transform: uppercase; color: var(--gold); }
#terms-dialog h4 { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--gold-dim); margin-top: 4px; }
#terms-dialog p { color: var(--text); }
#terms-dialog .terms-updated { font-size: 11px; color: var(--text-dim); }
#terms-dialog .terms-actions { position: sticky; bottom: 0; display: flex; justify-content: flex-end; padding: 12px 22px;
  background: var(--surface2); border-top: 1px solid var(--border); }
#terms-dialog button { min-height: 34px; padding: 7px 16px; border-radius: 8px; border: 1px solid var(--gold-dim);
  background: rgba(201,168,76,.12); color: var(--gold); font: inherit; cursor: pointer; }
#terms-link { position: fixed; left: 12px; bottom: 8px; z-index: 4; font: 11px system-ui, sans-serif; color: var(--text-dim);
  background: none; border: 0; cursor: pointer; text-decoration: underline; opacity: .75; }
#terms-link:hover, #terms-link:focus-visible { color: var(--gold); opacity: 1; }
#terms-settings-link { align-self: flex-start; padding: 0; border: 0; background: none; color: var(--gold); font: 12px system-ui, sans-serif; text-decoration: underline; cursor: pointer; }
@media (max-width: 680px) { #terms-link { display: none; } }
`

function readAccepted() {
  try { return localStorage.getItem(ACCEPT_KEY) === 'yes' } catch { return false }
}

function saveAccepted() {
  try { localStorage.setItem(ACCEPT_KEY, 'yes') } catch { /* stockage indisponible : on redemandera */ }
}

function build() {
  const style = document.createElement('style')
  style.textContent = STYLE
  document.head.appendChild(style)

  const dialog = document.createElement('dialog')
  dialog.id = 'terms-dialog'
  dialog.setAttribute('aria-labelledby', 'terms-title')
  document.body.appendChild(dialog)

  const link = document.createElement('button')
  link.type = 'button'
  link.id = 'terms-link'
  document.body.appendChild(link)

  // Également dans « Paramètres » (seul accès sur mobile, où l'écran reste dégagé)
  const settingsLink = document.createElement('button')
  settingsLink.type = 'button'
  settingsLink.id = 'terms-settings-link'
  document.getElementById('settings-form')?.appendChild(settingsLink)

  return { dialog, link, settingsLink }
}

function render(dialog, link, settingsLink, mustAccept) {
  const L = TEXT[getLang()] || TEXT.en
  link.textContent = L.link
  settingsLink.textContent = L.link
  dialog.replaceChildren()
  const body = document.createElement('div')
  body.className = 'terms-body'
  const h3 = document.createElement('h3')
  h3.id = 'terms-title'
  h3.textContent = L.title
  const intro = document.createElement('p')
  intro.textContent = L.intro
  body.append(h3, intro)
  for (const [heading, paragraphs] of L.sections) {
    const h4 = document.createElement('h4')
    h4.textContent = heading
    body.appendChild(h4)
    for (const text of paragraphs) {
      const p = document.createElement('p')
      p.textContent = text
      body.appendChild(p)
    }
  }
  const updated = document.createElement('p')
  updated.className = 'terms-updated'
  updated.textContent = `${L.updated} : ${UPDATED[getLang()] || UPDATED.en}`
  body.appendChild(updated)

  const actions = document.createElement('div')
  actions.className = 'terms-actions'
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.textContent = mustAccept ? L.accept : L.close
  btn.addEventListener('click', () => {
    if (mustAccept) saveAccepted()
    dialog.close()
  })
  actions.appendChild(btn)
  dialog.append(body, actions)
}

async function init() {
  let readOnly = false
  try {
    const status = await (await fetch('/api/config-status')).json()
    readOnly = Boolean(status.readOnly)
  } catch { /* serveur injoignable : rien à afficher */ }
  if (!readOnly) return

  const { dialog, link, settingsLink } = build()
  // Tant qu'elles ne sont pas acceptées, la fenêtre ne se ferme pas avec Échap.
  dialog.addEventListener('cancel', (e) => { if (!readAccepted()) e.preventDefault() })
  const open = () => {
    document.getElementById('settings-dialog')?.close?.()
    render(dialog, link, settingsLink, !readAccepted())
    dialog.showModal()
  }
  link.addEventListener('click', open)
  settingsLink.addEventListener('click', open)
  render(dialog, link, settingsLink, !readAccepted())
  if (!readAccepted()) dialog.showModal()
}

init()
