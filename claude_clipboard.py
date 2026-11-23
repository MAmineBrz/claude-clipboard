"""
claude_clipboard.py
-------------------
Deux modes, la réponse de Claude est copiée dans le presse-papiers
(donc visible dans l'historique Win+V et prête à être collée avec Ctrl+V) :

  - TEXTE : sélectionne du texte n'importe où, appuie sur Ctrl+Shift+C.
  - IMAGE : Impr écran -> sélectionne la zone -> Ctrl+Shift+S ; l'image
            présente dans le presse-papiers est envoyée à Claude.

Lancement :  python claude_clipboard.py   (avec le Python Windows, pas WSL)
Arrêt     :  Ctrl+C dans la console, ou fermer la fenêtre.
"""

import base64
import io
import os
import sys
import threading
import time
from pathlib import Path

# ============================================================================
# CONFIGURATION — modifie ces constantes selon tes besoins
# ============================================================================
MODEL = "claude-sonnet-5-5"        # Modèle Claude utilisé
HOTKEY = "ctrl+shift+c"            # Raccourci mode texte (intercepté)
SCREENSHOT_HOTKEY = "ctrl+shift+s" # Raccourci mode image (intercepté)
MAX_TOKENS = 10000                 # Longueur maximale de la réponse
SYSTEM_PROMPT = (
    "Tu reçois une question à choix multiples (QCM de revision ). "
    "Donne UNIQUEMENT la réponse demandée, rien d'autre : aucune introduction, "
    "aucune explication, aucun raisonnement, aucune phrase avant ou après. "
    "Réponds exactement à ce que la question demande : elle peut demander la ou les "
    "propositions VRAIES, ou au contraire la ou les propositions FAUSSES "
    "(ex: 'laquelle est fausse', 'trouve l'intrus'). Lis bien la consigne.\n"
    "Format de sortie :\n"
    "- Si les propositions sont étiquetées par des lettres (A, B, C...) : "
    "réponds seulement par la ou les lettres demandées, sans ponctuation finale. "
    "Plusieurs réponses : lettres séparées par une virgule (ex: A, C).\n"
    "- Si les propositions n'ont PAS de lettres : recopie mot pour mot, exactement, "
    "le texte de la ou des propositions demandées, et rien de plus.\n"
    "- Si la question demande du code : donne seulement le code optimisé, "
    "sans commentaire ni explication autour.\n"
    "Ne commente jamais ton choix. Ne décris jamais ce que tu fais. "
    "Ta sortie entière doit être la réponse et seulement la réponse."
)
IMAGE_PROMPT = "Réponds à la question présente dans l'image."
COPY_TIMEOUT_S = 1.0               # Temps max d'attente du Ctrl+C simulé
MAX_IMAGE_EDGE = 2576              # Résolution max utile pour le modèle (grand côté)
REQUEST_TIMEOUT_S = 120            # Délai max d'une requête API (secondes)
# ============================================================================

# --- Vérification des dépendances (message clair si une lib manque) --------
try:
    import anthropic
    import keyboard
    import pyperclip
    from dotenv import load_dotenv
    from PIL import Image, ImageGrab
except ImportError as exc:
    print(f"[ERREUR] Dépendance manquante : {exc.name}")
    print("         Lance :  pip install -r requirements.txt")
    sys.exit(1)

if sys.platform != "win32":
    print("[ERREUR] Ce script doit être lancé avec le Python de Windows (pas WSL).")
    sys.exit(1)


# ----------------------------------------------------------------------------
# Notifications : message console horodaté (sans son)
# ----------------------------------------------------------------------------
def notify(kind: str, message: str) -> None:
    """kind = 'start' | 'ok' | 'error'."""
    stamp = time.strftime("%H:%M:%S")
    labels = {"start": "ENVOI", "ok": "OK", "error": "ERREUR"}
    print(f"[{stamp}] [{labels.get(kind, kind)}] {message}", flush=True)


# ----------------------------------------------------------------------------
# Chargement de la clé API depuis .env (situé à côté du script)
# ----------------------------------------------------------------------------
def load_api_key() -> str:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key or key.startswith("sk-ant-xxxx"):
        print("[ERREUR] Clé API manquante.")
        print(f"         Crée le fichier {env_path}")
        print("         avec la ligne :  ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)
    return key


# ----------------------------------------------------------------------------
# MODE TEXTE : on simule Ctrl+C et on lit le presse-papiers
# ----------------------------------------------------------------------------
def wait_modifiers_released(timeout: float = 1.0) -> None:
    """Attend que l'utilisateur relâche Ctrl/Shift, sinon le Ctrl+C simulé
    deviendrait un Ctrl+Shift+C (et relancerait notre propre raccourci)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not (keyboard.is_pressed("shift") or keyboard.is_pressed("ctrl")):
            return
        time.sleep(0.02)
    # Toujours enfoncées après le délai : on force le relâchement
    for key in ("shift", "ctrl"):
        keyboard.release(key)


def capture_selection() -> str:
    wait_modifiers_released()

    pyperclip.copy("")           # on vide pour détecter une vraie copie
    keyboard.send("ctrl+c")      # copie simulée dans l'appli active

    deadline = time.time() + COPY_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(0.05)
        try:
            text = pyperclip.paste()
        except pyperclip.PyperclipException:
            continue  # presse-papiers momentanément verrouillé par une autre appli
        if text:
            return text
    return ""


def get_text_content():
    """Renvoie (contenu, description) ou None si rien à envoyer."""
    text = capture_selection()
    if not text.strip():
        notify("error", "Aucun texte sélectionné.")
        return None
    preview = text.strip().replace("\n", " ")[:60]
    return text, f"{len(text)} caractères : « {preview}… »"


# ----------------------------------------------------------------------------
# MODE IMAGE : on lit l'image déjà présente dans le presse-papiers
# ----------------------------------------------------------------------------
def image_to_base64_png(img: "Image.Image") -> str:
    # Réduit les captures très grandes (multi-écrans, 4K) : au-delà, le modèle
    # n'en tire rien de plus et on paierait des tokens pour rien.
    if max(img.size) > MAX_IMAGE_EDGE:
        img = img.copy()
        img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def get_image_content():
    """Renvoie (contenu, description) ou None si pas d'image."""
    try:
        img = ImageGrab.grabclipboard()
    except OSError:
        notify("error", "Presse-papiers momentanément inaccessible, réessaie.")
        return None

    # None = pas d'image ; list = des fichiers copiés depuis l'Explorateur
    if not isinstance(img, Image.Image):
        notify("error", "Aucune image dans le presse-papiers — fais d'abord ta "
                        "capture (Impr écran), puis Ctrl+Shift+S.")
        return None

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_to_base64_png(img),
            },
        },
        {"type": "text", "text": IMAGE_PROMPT},
    ]
    w, h = img.size
    return content, f"capture d'écran {w}x{h}"


# ----------------------------------------------------------------------------
# Appel à l'API Claude (content = texte brut OU liste de blocs image/texte)
# ----------------------------------------------------------------------------
def ask_claude(client: anthropic.Anthropic, content) -> str:
    params = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": content}],
    }
    if SYSTEM_PROMPT:
        params["system"] = SYSTEM_PROMPT

    response = client.messages.create(**params)

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude a refusé de répondre à cette demande.")

    answer = "".join(b.text for b in response.content if b.type == "text").strip()
    if not answer:
        raise RuntimeError("Réponse vide reçue de l'API.")
    if response.stop_reason == "max_tokens":
        print("  (réponse tronquée : augmente MAX_TOKENS si besoin)")
    return answer


# ----------------------------------------------------------------------------
# Traitement commun aux deux modes (exécuté dans un thread)
# ----------------------------------------------------------------------------
busy = threading.Lock()  # empêche deux requêtes simultanées


def process_request(client: anthropic.Anthropic, get_content) -> None:
    """get_content() -> (contenu à envoyer, description) ou None."""
    if not busy.acquire(blocking=False):
        notify("error", "Une requête est déjà en cours, patiente.")
        return
    try:
        result = get_content()
        if result is None:
            return  # l'erreur a déjà été affichée
        content, description = result

        notify("start", f"Envoi à {MODEL} ({description})")

        t0 = time.time()
        answer = ask_claude(client, content)

        pyperclip.copy(answer)   # -> presse-papiers + historique Win+V
        notify("ok", f"Réponse copiée ({len(answer)} caractères, "
                     f"{time.time() - t0:.1f} s). Colle avec Ctrl+V ou Win+V.")

    except anthropic.AuthenticationError:
        notify("error", "Clé API invalide (401). Vérifie ANTHROPIC_API_KEY dans .env.")
    except anthropic.PermissionDeniedError:
        notify("error", "Accès refusé (403) : la clé n'a pas accès à ce modèle.")
    except anthropic.NotFoundError:
        notify("error", f"Modèle introuvable (404) : vérifie MODEL = '{MODEL}'.")
    except anthropic.RateLimitError:
        notify("error", "Limite de requêtes atteinte (429). Réessaie dans un moment.")
    except anthropic.BadRequestError as exc:
        notify("error", f"Requête invalide (400) : {exc.message}")
    except anthropic.APIStatusError as exc:
        notify("error", f"Erreur API {exc.status_code} : {exc.message}")
    except anthropic.APIConnectionError:
        notify("error", "Erreur réseau : impossible de joindre l'API (connexion ou délai dépassé).")
    except Exception as exc:  # filet de sécurité : le script ne doit jamais planter
        notify("error", f"{type(exc).__name__} : {exc}")
    finally:
        busy.release()


def start_in_thread(client: anthropic.Anthropic, get_content) -> None:
    threading.Thread(target=process_request, args=(client, get_content), daemon=True).start()


# ----------------------------------------------------------------------------
# Point d'entrée
# ----------------------------------------------------------------------------
def main() -> None:
    api_key = load_api_key()
    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=REQUEST_TIMEOUT_S,
        max_retries=2,  # réessaie automatiquement sur erreurs réseau / 429 / 5xx
    )

    # MODE TEXTE — suppress=True : l'appli active ne reçoit pas Ctrl+Shift+C.
    # Le Ctrl+C normal n'est pas affecté.
    keyboard.add_hotkey(
        HOTKEY,
        lambda: start_in_thread(client, get_text_content),
        suppress=True,
        trigger_on_release=True,
    )

    # MODE IMAGE — l'image est déjà dans le presse-papiers (capture faite avant).
    # suppress=True : l'appli active ne reçoit pas Ctrl+Shift+S.
    keyboard.add_hotkey(
        SCREENSHOT_HOTKEY,
        lambda: start_in_thread(client, get_image_content),
        suppress=True,
        trigger_on_release=True,
    )

    print(f"Prêt. Modèle : {MODEL}")
    print(f"  Texte : sélectionne du texte puis appuie sur {HOTKEY.upper()}.")
    print(f"  Image : Impr écran -> sélectionne la zone -> {SCREENSHOT_HOTKEY.upper()}.")
    print("  Puis colle la réponse avec Ctrl+V ou Win+V.")
    print("Ctrl+C dans cette fenêtre pour quitter.\n")

    try:
        keyboard.wait()  # bloque indéfiniment en écoutant le clavier
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
