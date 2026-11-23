# Claude Clipboard

Deux modes, la réponse de Claude arrive dans le presse-papiers (et dans l'historique **Win+V**) :

| Mode  | Action                                              |
|-------|-----------------------------------------------------|
| Texte | Sélectionne du texte n'importe où → **Ctrl+Shift+C** |
| Image | **Impr écran** → sélectionne la zone → **Ctrl+Shift+S** → **Win+V** |

Les deux modes utilisent le même `SYSTEM_PROMPT`. Une seule requête tourne à la fois.

## Installation (PowerShell Windows, pas WSL)

```powershell
cd C:\Users\Barro\Desktop\fikra
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U -r requirements.txt
```

> Si PowerShell refuse d'activer le venv :
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Clé API

1. Copie `.env.example` en `.env` :
   ```powershell
   copy .env.example .env
   ```
2. Ouvre `.env` et mets ta clé :
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
Le fichier `.env` doit rester **dans le même dossier que `claude_clipboard.py`**.
Ne le partage jamais (ni Git, ni capture d'écran).

## Lancement

```powershell
python claude_clipboard.py
```

- Les messages (envoi, réponse copiée, erreurs) s'affichent dans la console.
- Quitter : Ctrl+C dans la console.

Sans fenêtre console (arrière-plan, mais plus aucun message) :
```powershell
.\.venv\Scripts\pythonw.exe claude_clipboard.py
```
(pour l'arrêter : Gestionnaire des tâches → pythonw.exe)

## Mode image : détails

1. **Impr écran** : Windows ouvre l'outil Capture, sélectionne ta zone.
   L'image arrive dans le presse-papiers.
2. **Ctrl+Shift+S** : le script envoie à Claude l'image **actuellement** dans le presse-papiers.
3. **Win+V** (ou Ctrl+V) : colle la réponse.

- Si le presse-papiers ne contient pas d'image, un message d'erreur s'affiche.
- Attention : c'est l'image courante qui est envoyée. Si tu as copié une image
  plus tôt et pas refait de capture, c'est celle-là qui part.
- Les captures très grandes sont réduites à 2576 px sur le grand côté.

## Réglages

En haut de `claude_clipboard.py` : `MODEL`, `HOTKEY`, `SCREENSHOT_HOTKEY`, `MAX_TOKENS`,
`SYSTEM_PROMPT`, `IMAGE_PROMPT`, `MAX_IMAGE_EDGE`.

## Limites connues

- **Win+V** : l'historique doit être activé (Paramètres → Système → Presse-papiers).
- Les raccourcis ne fonctionnent pas dans les fenêtres lancées **en administrateur**,
  sauf si le script est lui-même lancé en administrateur.
- Ctrl+Shift+C et Ctrl+Shift+S sont interceptés tant que le script tourne :
  Ctrl+Shift+C ne fera plus « Inspecter » dans Chrome ni « Copier » dans Windows Terminal,
  Ctrl+Shift+S ne fera plus « Enregistrer sous » dans Word, VS Code, etc.
