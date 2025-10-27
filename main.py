from fishing import run_fishing_cycle, set_move_request
from utils import log, set_log_callback, is_stop_requested, check_for_pause
from fight import handle_fight, is_fight_started
import pytesseract
import os
import json
import time
import re
import cv2
import numpy as np
from PIL import ImageGrab
import pyautogui
from tkinter import messagebox

# --- Constantes ---
MAP_FOLDER = "Maps"
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def request_map_change(direction):
    set_move_request(direction)

def get_map_coordinates_single_pass():
    # --- OCR pour les coordonnées de la carte ---
    screenshot = ImageGrab.grab()
    crop_box = (0, 85, 300, 110)
    cropped = screenshot.crop(crop_box)
    try:
        img = cv2.cvtColor(np.array(cropped), cv2.COLOR_RGB2GRAY)
        img = cv2.threshold(img, 240, 255, cv2.THRESH_BINARY)[1]
        text = pytesseract.image_to_string(img, config='--psm 6')
        match = re.search(r'(-?\d+)\s*,\s*(-?\d+)', text)
        if match:
            x, y = match.groups()
            return f"{x},{y}"
    except Exception as e:
        pass
    return None

def get_map_coordinates():
    first_pass = get_map_coordinates_single_pass()
    if not first_pass:
        return None

    time.sleep(0.25)
    second_pass = get_map_coordinates_single_pass()

    if first_pass == second_pass:
        return first_pass
    else:
        log(f"Incohérence OCR : 1ère lecture='{first_pass}', 2ème lecture='{second_pass}'. Nouvel essai.")
    return None

def prompt_yes_no(message):
    return messagebox.askyesno("Création de map", message)

def load_cells(map_coords):
    # --- Gestion des fichiers de carte ---
    path = os.path.join(MAP_FOLDER, f"{map_coords}.json")
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r") as f:
            data = json.load(f)
    except Exception as e:
        log(f"Erreur lors du chargement du fichier de map : {e}")
        return None
    return data["cells"]

def create_map_interactively(map_coords, config, is_editing=False):
    # --- Outil de création de carte interactif ---
    import pyautogui, keyboard
    if not is_editing:
        log(f"Aucune donnée pour la map {map_coords}. Lancement de l'outil de création.")
        if not prompt_yes_no("Voulez-vous créer cette map maintenant ?"):
            log("Création de map annulée.")
            return None
    else:
        log(f"Lancement de l'outil de modification pour la map {map_coords}.")

    if config is None:
        with open("config.json", "r") as f:
            config = json.load(f)
    
    keys_config = config.get("MAP_CREATION_KEYS", {})
    key_add_spot = keys_config.get("ADD_SPOT", "j")
    key_save_bg = keys_config.get("SAVE_BACKGROUND", "s")
    exit_keys_map = {
        keys_config.get("EXIT_UP", "8"): 'haut', keys_config.get("EXIT_DOWN", "2"): 'bas',
        keys_config.get("EXIT_LEFT", "4"): 'gauche', keys_config.get("EXIT_RIGHT", "6"): 'droite',
        keys_config.get("EXIT_UP_LEFT", "7"): 'haut-gauche', keys_config.get("EXIT_UP_RIGHT", "9"): 'haut-droite',
        keys_config.get("EXIT_DOWN_LEFT", "1"): 'bas-gauche', keys_config.get("EXIT_DOWN_RIGHT", "3"): 'bas-droite'
    }

    log("\n--- Création de la map ---")
    log(f"1. Survolez les cases de PÊCHE et appuyez sur '{key_add_spot}'.")
    log(f"2. Appuyez sur '{key_save_bg}' pour sauvegarder le fond de la carte.")
    log("3. Survolez les cases de SORTIE et utilisez les touches configurées.")
    log("3. Appuyez sur 'Entrée' pour terminer.")

    cells = []
    exits = {}
    if is_editing:
        try:
            existing_data = load_map_data(map_coords)
            cells = existing_data.get("cells", [])
            exits = existing_data.get("exits", {})
            log(f"Données existantes chargées : {len(cells)} spots, {len(exits)} sorties.")
        except FileNotFoundError:
            log("Aucun fichier existant trouvé, création d'une nouvelle carte.")

    try:
        while True:
            event = keyboard.read_event(suppress=True)
            if event.event_type != keyboard.KEY_DOWN:
                continue
            
            key_name = event.name

            if key_name == 'enter':
                log("Fin de la création de la map.")
                break
            elif key_name == key_add_spot:
                x, y = pyautogui.position()
                cells.append({"x": x, "y": y})
                log(f"Case de pêche ajoutée : ({x}, {y})")
            elif key_name == key_save_bg:
                log("Capture du fond de la carte...")
                game_area = (0, 24, 1348, 808)
                screenshot = ImageGrab.grab(bbox=game_area)
                bg_path = os.path.join(MAP_FOLDER, f"{map_coords}.png")
                screenshot.save(bg_path)
                log(f"Fond de carte sauvegardé sous : {bg_path}")
            else:
                if key_name in exit_keys_map:
                    actual_key = key_name.split('+')[-1]
                    direction = exit_keys_map[actual_key]
                    x, y = pyautogui.position()
                    exits[direction] = {"x": x, "y": y}
                    log(f"Sortie '{direction.capitalize()}' ajoutée : ({x}, {y})")
    except KeyboardInterrupt:
        pass

    map_data = {"map": map_coords, "cells": cells, "exits": exits}
    os.makedirs(MAP_FOLDER, exist_ok=True)
    with open(os.path.join(MAP_FOLDER, f"{map_coords}.json"), "w") as f:
        json.dump(map_data, f, indent=4)
    log(f"Map {map_coords} sauvegardée avec {len(cells)} cases de pêche et {len(exits)} sorties.")
    return cells

def load_map_data(map_coords):
    with open(os.path.join(MAP_FOLDER, f"{map_coords}.json"), "r") as f:
        return json.load(f)

def get_next_map_coords(current_coords_str, direction):
    x, y = map(int, current_coords_str.split(','))
    
    moves = {
        "haut": (x, y - 1),
        "bas": (x, y + 1),
        "gauche": (x - 1, y),
        "droite": (x + 1, y),
        "haut-gauche": (x - 1, y - 1),
        "haut-droite": (x + 1, y - 1),
        "bas-gauche": (x - 1, y + 1),
        "bas-droite": (x + 1, y + 1),
    }
    
    next_x, next_y = moves.get(direction, (x, y))
    return f"{next_x},{next_y}"

def find_exit_with_fallback(map_data, primary_direction):
    exits = map_data.get("exits", {})
    if primary_direction in exits:
        return primary_direction

    fallbacks = {
        "gauche": ["haut-gauche", "bas-gauche"],
        "droite": ["haut-droite", "bas-droite"],
        "haut": ["haut-gauche", "haut-droite"],
        "bas": ["bas-gauche", "bas-droite"],
    }
    for fallback in fallbacks.get(primary_direction, []):
        if fallback in exits:
            return fallback
    return None

def wait_for_map_change(old_coords, timeout=20):
    start_time = time.time()
    while time.time() - start_time < timeout:
        new_coords = get_map_coordinates()
        if new_coords and new_coords != old_coords:
            log(f"[Trajet] Déplacement réussi vers : {new_coords}.")
            return True
        time.sleep(0.5)
    log("[Trajet] Timeout : le changement de map n'a pas été détecté.")
    return False

def main_bot_logic(log_cb, finish_cb):
    # --- Logique principale du bot ---
    set_log_callback(log_cb)
    
    with open("config.json", "r") as f:
        config = json.load(f)
    gui_app = log_cb.__self__

    visited_maps = set()
    previous_coords = None

    try:
        if gui_app.auto_combat_var.get():
            pyautogui.moveTo(100, 100, duration=0.1)
            log("Vérification de l'état de combat au démarrage...")
            if is_fight_started(template_path="Images/button_end_turn.png", checks=1):
                log("Combat déjà en cours détecté (tour de jeu). Lancement de la gestion.")
                handle_fight(True, gui_app)
            elif is_fight_started(template_path="Images/button_ready.png", checks=1):
                log("Combat déjà en cours détecté (phase de placement). Lancement de la gestion.")
                handle_fight(True, gui_app)
            else:
                log("Aucun combat en cours.")
        else:
            log("Combat auto désactivé, pas de vérification initiale.")


        while not is_stop_requested():
            check_for_pause()

            if gui_app.combat_only_var.get():
                log("Mode 'Combat Only' activé. En attente d'un combat...")
                while not is_fight_started() and not is_stop_requested():
                    check_for_pause()
                    time.sleep(1)
                if is_stop_requested(): break

            if is_fight_started():
                if not gui_app.in_combat_view:
                    log("COMBAT DÉTECTÉ (inattendu) ! Lancement de la gestion du combat.")
                    auto_combat_enabled = gui_app.auto_combat_var.get()
                    handle_fight(auto_combat_enabled, gui_app)
                    log("Reprise des activités après le combat.")
                    time.sleep(2)
                continue
            
            if gui_app.auto_combat_var.get() and not gui_app.combat_only_var.get():
                if is_fight_started(checks=1, interval=0):
                    continue
                time.sleep(3)

            coords = get_map_coordinates()
            if not coords:
                log("Impossible de détecter les coordonnées de la map. Nouvel essai dans 10s.")
                time.sleep(10)
                continue

            log(f"Map détectée : {coords}")
            try:
                map_data = load_map_data(coords)
                if not map_data.get("cells") and not map_data.get("exits"):
                    log(f"La map {coords} est vide. Lancement de l'éditeur...")
                    create_map_interactively(coords, config, is_editing=True)
                    map_data = load_map_data(coords)
                    if not map_data.get("cells") and not map_data.get("exits"):
                        log(f"La map {coords} est toujours vide après édition. Arrêt.")
                        break

            except FileNotFoundError:
                new_cells = create_map_interactively(coords, config)
                try:
                    map_data = load_map_data(coords)
                    if not map_data.get("cells") and not map_data.get("exits"):
                        log(f"La map {coords} est toujours vide après création. Arrêt.")
                        break
                except FileNotFoundError:
                    log(f"Le bot ne peut pas continuer sur la map {coords} sans données. Arrêt.")
                    break

            target_direction = None
            visited_maps.add(coords)
            
            unvisited_options = []
            visited_options = []
            previous_map_option = None

            for direction, exit_pos in map_data.get("exits", {}).items():
                next_coords = get_next_map_coords(coords, direction)
                if os.path.exists(os.path.join(MAP_FOLDER, f"{next_coords}.json")):
                    if next_coords == previous_coords:
                        previous_map_option = direction
                    elif next_coords not in visited_maps:
                        unvisited_options.append(direction)
                    else:
                        visited_options.append(direction)
            
            if unvisited_options:
                target_direction = unvisited_options[0]
            elif visited_options:
                target_direction = visited_options[0]
            elif previous_map_option:
                target_direction = previous_map_option

            log(f"{len(map_data.get('cells', []))} cases pêchables sur la map {coords}.")
            cycle_completed = run_fishing_cycle(coords, map_data, gui_app, target_direction)
            
            if is_stop_requested():
                break

            if not cycle_completed:
                from fishing import get_move_request
                move_direction = get_move_request()
                if move_direction:
                    log(f"[Trajet] Déplacement demandé vers '{move_direction}'.")
                    map_data = load_map_data(coords)
                    final_direction = find_exit_with_fallback(map_data, move_direction)

                    if final_direction:
                        exit_pos = map_data["exits"][final_direction]
                        pyautogui.click(exit_pos["x"], exit_pos["y"])
                        log(f"[Trajet] Clic sur la sortie '{final_direction}'. Attente du changement de map...")
                    else:
                        log(f"[Trajet] Aucune sortie trouvée pour la direction '{move_direction}'.")
            
            elif cycle_completed:
                if target_direction:
                    log(f"[Trajet] Cycle de pêche terminé. Déplacement vers '{target_direction}'.")
                    exit_pos = map_data["exits"][target_direction]
                    pyautogui.click(exit_pos["x"], exit_pos["y"])
                    if wait_for_map_change(coords):
                        gui_app.after(100, gui_app.draw_map) 

                else:
                    log("[Trajet] Aucune carte adjacente connue trouvée. Le bot s'arrête.")
                    break

            previous_coords = coords

    finally:
        finish_cb()

if __name__ == "__main__":
    log("Pour lancer le bot, exécutez le fichier 'gui.py'")
