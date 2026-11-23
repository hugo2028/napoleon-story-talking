// Clavier virtuel sur mobile : l'avatar et la page restent en place, seule la zone de saisie
// remonte au-dessus du clavier.
//
// Quand le clavier s'ouvre, le navigateur réduit la zone visible (visualViewport) et la fait
// souvent défiler vers le haut pour montrer le champ. On compense ce défilement sur l'avatar
// (--vv-top) et on pose la zone de saisie juste au-dessus du clavier (--kb).

const vv = window.visualViewport

function update() {
  const root = document.documentElement
  const offset = Math.max(0, vv.offsetTop)
  const keyboard = Math.max(0, window.innerHeight - vv.height - offset)
  root.style.setProperty('--vv-top', `${offset}px`)
  root.style.setProperty('--kb', `${keyboard}px`)
  root.classList.toggle('keyboard-open', keyboard > 80)
}

if (vv) {
  vv.addEventListener('resize', update)
  vv.addEventListener('scroll', update)
  update()
}
