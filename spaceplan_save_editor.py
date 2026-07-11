#!/usr/bin/env python3
"""
spaceplan_save_editor.py
Outil interactif (terminal, sans GUI) pour lire, patcher et restaurer la
sauvegarde du clone Spaceplan (com.devolver.spaceplan) - projet etudiant HENSA.

Contrairement a Antimatter Dimensions, ce fichier de sauvegarde vit dans le
stockage EXTERNE de l'app (/sdcard/Android/data/...), donc pas besoin de
`run-as` pour le lire/l'ecrire : un simple `adb pull` / `adb push` suffit.

Format du fichier : XML .NET classique, MAIS les nombres decimaux utilisent
la VIRGULE comme separateur (ex: "2113,88999398613") au lieu du point.
Le script convertit automatiquement dans les deux sens pour ne jamais
corrompre la sauvegarde.

Usage :
    python spaceplan_save_editor.py
    -> ouvre directement un menu :
        [1] Appliquer des facilites (choisir + personnaliser)
        [2] Reset : restaurer la sauvegarde d'origine
        [3] Voir l'etat actuel de la sauvegarde
        [4] Quitter

Necessite : adb dans le PATH, device connecte (`adb devices`), Python 3.
"""

import argparse
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "com.devolver.spaceplan"
DEVICE_SAVE_PATH = "/sdcard/Android/data/com.devolver.spaceplan/files/SpaceplanProgress.text"
LOCAL_SAVE = Path("SpaceplanProgress.text")
LOCAL_BACKUP = Path("SpaceplanProgress.text.bak")
DEVICE_CONFIG = Path("device_config.json")


# ---------------------------------------------------------------------------
# Helpers adb (identiques au script Antimatter Dimensions, pour coherence)
# ---------------------------------------------------------------------------

def run(cmd, check=True):
    print(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            f"Impossible de trouver la commande '{cmd[0]}'. Verifie qu'adb est "
            "installe et accessible (pkg install android-tools sur Termux, ou "
            "ajoute platform-tools au PATH sur Windows)."
        )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"Commande echouee: {' '.join(cmd)}")
    return result


def adb(*args, check=True):
    return run(["adb", *args], check=check)


def load_device_config():
    if DEVICE_CONFIG.exists():
        try:
            return json.loads(DEVICE_CONFIG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_device_config(address: str):
    DEVICE_CONFIG.write_text(json.dumps({"address": address}), encoding="utf-8")


def has_device():
    result = adb("devices", check=False)
    lines = [l for l in result.stdout.splitlines()[1:] if l.strip()]
    return any("\tdevice" in l for l in lines)


def connect_device(address: str = None):
    if address is None:
        config = load_device_config()
        if config and config.get("address"):
            address = config["address"]
            print(f"(reutilisation de la derniere adresse connue : {address})")
        else:
            raise RuntimeError(
                "Aucune adresse enregistree. Lance d'abord :\n"
                "  python spaceplan_save_editor.py connect <ip:port>"
            )
    adb("connect", address)
    if not has_device():
        raise RuntimeError(f"Connexion a {address} echouee ou non autorisee.")
    save_device_config(address)
    print(f"OK : connecte a {address} (adresse memorisee).")


def ensure_device_connected():
    if has_device():
        return
    config = load_device_config()
    if config and config.get("address"):
        print("Aucun device actif, tentative de reconnexion automatique...")
        adb("connect", config["address"], check=False)
        if has_device():
            print(f"OK : reconnecte automatiquement a {config['address']}.")
            return
    raise RuntimeError(
        "Aucun device detecte par adb.\n"
        "  1. Verifie que le debogage USB/sans-fil est actif.\n"
        "  2. Reconnecte avec : python spaceplan_save_editor.py connect <ip:port>\n"
        "  3. Verifie avec `adb devices`."
    )


# ---------------------------------------------------------------------------
# Pull / Push (pas de run-as necessaire : stockage externe)
# ---------------------------------------------------------------------------

def pull_save():
    ensure_device_connected()
    adb("pull", DEVICE_SAVE_PATH, str(LOCAL_SAVE))
    print(f"OK : sauvegarde recuperee dans {LOCAL_SAVE.resolve()}")


def push_save():
    ensure_device_connected()
    if not LOCAL_SAVE.exists():
        raise RuntimeError(f"{LOCAL_SAVE} introuvable. Lance d'abord `pull` ou patch.")
    adb("push", str(LOCAL_SAVE), DEVICE_SAVE_PATH)
    adb("shell", "am", "force-stop", PACKAGE)
    print("OK : sauvegarde envoyee sur le telephone, app fermee proprement (force-stop).")
    print("Relance le jeu manuellement pour voir le resultat.")


def restore_backup():
    if not LOCAL_BACKUP.exists():
        raise RuntimeError(f"{LOCAL_BACKUP} introuvable, rien a restaurer.")
    shutil.copy(LOCAL_BACKUP, LOCAL_SAVE)
    print(f"{LOCAL_SAVE} restaure a partir de {LOCAL_BACKUP}.")


# ---------------------------------------------------------------------------
# Conversion nombres FR (virgule) <-> float Python
# ---------------------------------------------------------------------------

def parse_num(text: str) -> float:
    if text is None or text.strip() == "":
        return 0.0
    return float(text.strip().replace(",", "."))


def fmt_int(value) -> str:
    return str(int(round(float(value))))


def fmt_float_comma(value) -> str:
    """Formate un float avec virgule comme separateur decimal (style .NET FR)."""
    value = float(value)
    if value == int(value):
        return str(int(value))
    s = f"{value:.13g}"
    return s.replace(".", ",")


# ---------------------------------------------------------------------------
# Navigation XML par chemin de tags (ex: ['GeneralPower','Power'])
# ---------------------------------------------------------------------------

def find_el(root, path):
    el = root
    for tag in path:
        el = el.find(tag)
        if el is None:
            raise RuntimeError(f"Chemin XML introuvable : {'/'.join(path)}")
    return el


def get_text(root, path):
    return find_el(root, path).text


def set_text(root, path, text):
    find_el(root, path).text = text


# ---------------------------------------------------------------------------
# Fonctions d'application "groupees"
# ---------------------------------------------------------------------------

ITEM_TYPES = [
    "RepairSolarPanel", "Potato", "Probetato", "Spudnik",
    "PotatoPlant", "TaterTower", "SpudGun", "PotatoLauncher",
]

IDEA_TYPES = [
    "SpudIncubator", "SolarAmbience", "MarisPipers", "PolishedSolarPanels",
    "KinetigenOverclock", "CleanSolarPanels", "KinetigenTweak",
]


def apply_items_maxed(root, value):
    """Debloque (Revealed) et remplit tous les Items avec `value` unites."""
    for item in root.findall("Items/Item"):
        item.find("Count").text = fmt_int(value)
        state = item.find("BuyableState")
        if state is not None and state.text != "Bought":
            state.text = "Revealed"
        conditions = item.find("ConditionsMet")
        if conditions is not None:
            conditions.text = "True"


def apply_ideas_all_bought(root, _value=None):
    """Marque toutes les Ideas (recherches) comme achetees."""
    for idea in root.findall("Ideas/Idea"):
        state = idea.find("BuyableState")
        if state is not None:
            state.text = "Bought"


def apply_story_progress(root, _value=None):
    """Debloque les jalons narratifs principaux (sonde posee, System Peeker vu,
    booster active). Experimental : ne garantit pas de debloquer TOUT le
    contenu narratif, certains textes restent lies a des compteurs internes."""
    story = find_el(root, ["StoryData"])
    def set_if_present(tag, text):
        el = story.find(tag)
        if el is not None:
            el.text = text
    set_if_present("ProbetatoLanded", "True")
    set_if_present("SystemPeekerChecked", "True")
    set_if_present("BoosterActivated", "True")
    set_if_present("ProbetatoesLaunched", "50")
    set_if_present("AnalysisData", "999")


# ---------------------------------------------------------------------------
# Registre des facilites
# ---------------------------------------------------------------------------
# kind:
#   "float_comma" -> texte au format virgule .NET, valeur demandee = nombre reel
#   "int"          -> texte entier simple
#   "group"        -> fonction personnalisee avec une valeur numerique
#   "flag"         -> fonction personnalisee sans valeur (confirmer oui/non)

CHEATS = [
    {
        "id": "power",
        "name": "Power (watts)",
        "description": "Ressource principale du jeu, sert a tout acheter (Items, Ideas).",
        "path": ["GeneralPower", "Power"],
        "kind": "float_comma",
        "default": 1e7,
    },
    {
        "id": "power_modifier",
        "name": "Universal Power Modifier",
        "description": "Multiplicateur global de production de Power. Plus il est haut, plus tout produit vite.",
        "path": ["GeneralPower", "UniversalPowerModifier"],
        "kind": "int",
        "default": 50,
    },
    {
        "id": "time_away_cap",
        "name": "Plafond de temps hors-ligne (secondes)",
        "description": "Duree maximale d'absence prise en compte pour calculer les gains hors-ligne. Par defaut 300s (5 min) ; augmenter permet de recuperer plus de progression a la reconnexion.",
        "path": ["GeneralPower", "TimeAwayCap"],
        "kind": "int",
        "default": 86400,
    },
    {
        "id": "kinetigen_power",
        "name": "Puissance du Kinetigen (par clic)",
        "description": "Watts generes par clic manuel sur le Kinetigen.",
        "path": ["Kinetigen", "KinetigenPowerGeneration"],
        "kind": "int",
        "default": 1000,
    },
    {
        "id": "kinetigen_efficiency",
        "name": "Efficacite Sparkifier du Kinetigen",
        "description": "Bonus d'efficacite lie a l'upgrade Kinetigen Sparkifier.",
        "path": ["Kinetigen", "KinetigenSparkifierEfficiency"],
        "kind": "int",
        "default": 100,
    },
    {
        "id": "items_maxed",
        "name": "[GROUPE] Debloquer + remplir tous les Items",
        "description": (
            "Debloque (Revealed) et met la quantite choisie pour les 8 Items : "
            "RepairSolarPanel, Potato, Probetato, Spudnik, PotatoPlant, "
            "TaterTower, SpudGun, PotatoLauncher."
        ),
        "kind": "group",
        "apply": apply_items_maxed,
        "default": 500,
    },
    {
        "id": "ideas_all_bought",
        "name": "[FLAG] Debloquer toutes les Ideas (recherches)",
        "description": (
            "Marque les 7 recherches comme achetees : SpudIncubator, "
            "SolarAmbience, MarisPipers, PolishedSolarPanels, "
            "KinetigenOverclock, CleanSolarPanels, KinetigenTweak."
        ),
        "kind": "flag",
        "apply": apply_ideas_all_bought,
    },
    {
        "id": "story_progress",
        "name": "[FLAG][EXPERIMENTAL] Debloquer les jalons narratifs principaux",
        "description": (
            "Marque la sonde comme posee, le System Peeker comme verifie, le "
            "booster comme active. Experimental : certains textes narratifs "
            "peuvent rester lies a d'autres compteurs internes non couverts ici."
        ),
        "kind": "flag",
        "apply": apply_story_progress,
    },
]


# ---------------------------------------------------------------------------
# Menu interactif
# ---------------------------------------------------------------------------

def print_menu():
    print("\n=== Facilites disponibles (Spaceplan) ===")
    for i, cheat in enumerate(CHEATS, start=1):
        print(f"[{i:2d}] {cheat['name']}")
        print(f"     -> {cheat['description']}")
        if cheat["kind"] in ("float_comma", "int", "group"):
            print(f"     (valeur par defaut suggeree : {cheat['default']})")
    print()


def prompt_value(cheat):
    default = cheat.get("default")
    raw = input(f"   Valeur pour '{cheat['name']}' [defaut = {default}] : ").strip()
    if raw == "":
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        print("   Valeur invalide, on garde la valeur par defaut.")
        return default


def apply_cheat(root, cheat):
    kind = cheat["kind"]

    if kind == "float_comma":
        value = prompt_value(cheat)
        set_text(root, cheat["path"], fmt_float_comma(value))
        print(f"   -> {cheat['name']} = {value}")

    elif kind == "int":
        value = prompt_value(cheat)
        set_text(root, cheat["path"], fmt_int(value))
        print(f"   -> {cheat['name']} = {int(value)}")

    elif kind == "group":
        value = prompt_value(cheat)
        cheat["apply"](root, value)
        print(f"   -> {cheat['name']} applique avec valeur {value} par element")

    elif kind == "flag":
        confirm = input(f"   Appliquer '{cheat['name']}' ? [o/N] : ").strip().lower()
        if confirm == "o":
            cheat["apply"](root)
            print(f"   -> {cheat['name']} applique")
        else:
            print("   -> ignore")


def interactive_patch():
    if not LOCAL_SAVE.exists():
        raise RuntimeError(f"{LOCAL_SAVE} introuvable. Lance d'abord `pull`.")

    tree = ET.parse(LOCAL_SAVE)
    root = tree.getroot()

    print_menu()
    selection = input(
        "Entre les numeros des facilites a appliquer, separes par des virgules\n"
        "(ex: 1,2,6) ou 'all' pour tout, ou 'q' pour annuler : "
    ).strip()

    if selection.lower() == "q":
        print("Annule, aucun changement.")
        return

    if selection.lower() == "all":
        chosen = CHEATS
    else:
        try:
            indices = [int(x.strip()) for x in selection.split(",") if x.strip()]
            chosen = [CHEATS[i - 1] for i in indices]
        except (ValueError, IndexError):
            print("Selection invalide, aucun changement applique.")
            return

    shutil.copy(LOCAL_SAVE, LOCAL_BACKUP)
    print(f"\nSauvegarde de securite creee : {LOCAL_BACKUP.resolve()}")

    print("\n--- Application des facilites choisies ---")
    for cheat in chosen:
        print(f"\n> {cheat['name']}")
        apply_cheat(root, cheat)

    tree.write(LOCAL_SAVE, encoding="utf-8", xml_declaration=True)
    print(f"\nOK : {LOCAL_SAVE} mis a jour.")


def show_status():
    if not LOCAL_SAVE.exists():
        raise RuntimeError(f"{LOCAL_SAVE} introuvable. Lance d'abord `pull`.")
    tree = ET.parse(LOCAL_SAVE)
    root = tree.getroot()

    print("--- Etat actuel (sauvegarde locale) ---")
    print(f"  Power                : {parse_num(get_text(root, ['GeneralPower', 'Power'])):.2f}")
    print(f"  UniversalPowerModifier : {get_text(root, ['GeneralPower', 'UniversalPowerModifier'])}")
    print(f"  KinetigenPowerGeneration : {get_text(root, ['Kinetigen', 'KinetigenPowerGeneration'])}")
    print(f"  CurrentPlanet        : {get_text(root, ['StoryData', 'CurrentPlanet'])}")
    print("\n  Items (Count / Etat) :")
    for item in root.findall("Items/Item"):
        name = item.find("ItemType").text
        count = item.find("Count").text
        state = item.find("BuyableState").text
        print(f"    {name:<18} count={count:<8} etat={state}")
    print("\n  Ideas (Etat) :")
    for idea in root.findall("Ideas/Idea"):
        name = idea.find("ResearchType").text
        state = idea.find("BuyableState").text
        print(f"    {name:<20} etat={state}")


# ---------------------------------------------------------------------------
# Actions automatiques (pull/push geres en interne)
# ---------------------------------------------------------------------------

def patch_and_push():
    print("\n>> Recuperation de la sauvegarde actuelle...")
    pull_save()
    interactive_patch()
    print("\n>> Envoi de la sauvegarde modifiee sur le telephone...")
    push_save()
    print("\nTermine. Relance le jeu sur ton telephone pour voir le resultat.")


def restore_and_push():
    if not LOCAL_BACKUP.exists():
        print("Aucune sauvegarde .bak locale trouvee : rien a restaurer.")
        print("(Le .bak est cree automatiquement la premiere fois que tu patches.)")
        return
    restore_backup()
    print("\n>> Envoi de la sauvegarde restauree sur le telephone...")
    push_save()
    print("\nTermine. Relance le jeu : tu devrais retrouver l'etat d'avant patch.")


def status_from_device():
    print("\n>> Recuperation de la sauvegarde actuelle...")
    pull_save()
    show_status()


def main_menu():
    while True:
        print("\n=== Spaceplan - Save Editor ===")
        print("[1] Appliquer des facilites (choisir + personnaliser)")
        print("[2] Reset : restaurer la sauvegarde d'origine")
        print("[3] Voir l'etat actuel de la sauvegarde")
        print("[4] Quitter")
        choice = input("\nTon choix : ").strip()

        try:
            if choice == "1":
                patch_and_push()
            elif choice == "2":
                restore_and_push()
            elif choice == "3":
                status_from_device()
            elif choice == "4":
                print("A bientot !")
                break
            else:
                print("Choix invalide, entre 1, 2, 3 ou 4.")
        except RuntimeError as e:
            print(f"\nErreur : {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Editeur de sauvegarde Spaceplan (projet etudiant)")
    sub = parser.add_subparsers(dest="command")

    connect_parser = sub.add_parser("connect", help="[avance] Connecte adb (ip:port)")
    connect_parser.add_argument("address", nargs="?", default=None)
    sub.add_parser("pull", help="[avance] Recupere la sauvegarde du telephone")
    sub.add_parser("list", help="[avance] Affiche le menu des facilites sans rien modifier")
    sub.add_parser("patch", help="[avance] Menu interactif seul (sans pull/push automatique)")
    sub.add_parser("push", help="[avance] Envoie la sauvegarde locale sur le telephone")
    sub.add_parser("restore", help="[avance] Restaure la sauvegarde .bak (local seulement)")
    sub.add_parser("status", help="[avance] Affiche l'etat de la sauvegarde locale (sans pull)")

    args = parser.parse_args()

    try:
        if args.command is None:
            main_menu()
        elif args.command == "connect":
            connect_device(args.address)
        elif args.command == "pull":
            pull_save()
        elif args.command == "list":
            print_menu()
        elif args.command == "patch":
            interactive_patch()
        elif args.command == "push":
            push_save()
        elif args.command == "restore":
            restore_backup()
        elif args.command == "status":
            show_status()
    except RuntimeError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
