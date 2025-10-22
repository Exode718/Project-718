import pyautogui
import json
import time
import math
import cv2
import numpy as np
import winsound
from PIL import ImageGrab
import os

from utils import log, is_fight_started, check_and_close_fight_end_popup, check_for_pause, is_stop_requested
from grid import grid_instance

# --- Configuration ---
with open("config.json", "r") as f: CONFIG = json.load(f)

COMBAT_CONFIG = CONFIG.get("COMBAT", {})
ACTION_POINTS = COMBAT_CONFIG.get("ACTION_POINTS", 6)
MOVEMENT_POINTS = COMBAT_CONFIG.get("MOVEMENT_POINTS", 3)
SPELLS = COMBAT_CONFIG.get("SPELLS", [])
SPELLS.sort(key=lambda x: x.get('priority', 99))

IMAGE_FOLDER = "Images"
END_TURN_BUTTON_IMAGE = os.path.join(IMAGE_FOLDER, "button_end_turn.png")
MY_TURN_INDICATOR_IMAGE = os.path.join(IMAGE_FOLDER, "my_turn_indicator.png")
EMPTY_BLUE_CELL_IMAGE = os.path.join(IMAGE_FOLDER, "empty_blue_cell.png")
EMPTY_RED_CELL_IMAGE = os.path.join(IMAGE_FOLDER, "empty_red_cell.png")
CELL_MASK_IMAGE = os.path.join(IMAGE_FOLDER, "cell_mask.png")

PLAYER_START_CELL_COLOR = ([90, 100, 100], [110, 255, 255]) # Bleu
MONSTER_START_CELL_COLOR = ([0, 100, 100], [10, 255, 255]) # Rouge
PLAYER_FEET_CIRCLE_COLOR = ([0, 100, 100], [10, 255, 255])   # Rouge (comme les cases de départ ennemies)
MONSTER_FEET_CIRCLE_COLOR = ([90, 100, 100], [110, 255, 255]) # Bleu (comme les cases de départ alliées)

# --- Fonctions de combat ---

def find_on_screen(template_path, threshold=0.8):
    """Trouve la première occurrence d'un template sur l'écran."""
    try:
        screen = ImageGrab.grab()
        screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_BGR2GRAY)
        template = cv2.imread(template_path, 0)
        if template is None: return None
        
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        
        if len(loc[0]) > 0:
            h, w = template.shape
            return (loc[1][0] + w // 2, loc[0][0] + h // 2)
    except Exception as e:
        log(f"[Combat] Erreur lors de la recherche de {template_path}: {e}")
    return None

def is_my_turn(timeout=2):
    """Vérifie si c'est le tour du joueur en cherchant l'indicateur."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if find_on_screen(MY_TURN_INDICATOR_IMAGE, threshold=0.85):
            return True
        time.sleep(0.2)
    return False

def find_entities_by_color(color_range_list, min_area=100):
    """
    Trouve les centres des zones de couleur sur l'écran.
    Retourne une liste de positions (x, y).
    """
    screen = np.array(ImageGrab.grab())
    screen_hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    positions = []
    for color_range in color_range_list:
        mask = cv2.inRange(screen_hsv, np.array(color_range[0]), np.array(color_range[1]))
        contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if cv2.contourArea(c) > min_area:
                M = cv2.moments(c)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    positions.append((cx, cy))
    return positions

def find_entities_on_grid(color_ranges, min_area=100):
    """Trouve les entités et retourne leurs coordonnées de grille."""
    screen_positions = find_entities_by_color(color_ranges, min_area)
    grid_positions = []
    for pos in screen_positions:
        cell = grid_instance.get_cell_from_screen_coords(pos[0], pos[1])
        if cell:
            grid_positions.append(cell)
    return list(set(grid_positions)) # Éliminer les doublons

def get_closest_entity(player_pos, entity_list):
    """Trouve l'entité la plus proche du joueur sur la grille."""
    if not player_pos or not entity_list:
        return None
    
    closest_entity = None
    min_dist = float('inf')
    
    for entity in entity_list:
        dist = (abs(player_pos[0] - entity[0]) 
              + abs(player_pos[0] + player_pos[1] - entity[0] - entity[1]) 
              + abs(player_pos[1] - entity[1])) / 2
        if dist < min_dist:
            min_dist = dist
            closest_entity = entity
            
    return closest_entity

def is_cell_occupied(cell_coord, empty_cell_image_path, threshold=0.85):
    """
    Vérifie si une case de la grille est occupée en la comparant à une image de référence.
    Retourne True si la case est occupée, False sinon.
    """
    if not os.path.exists(empty_cell_image_path):
        log(f"[Combat Auto] Image de référence introuvable : {empty_cell_image_path}")
        return True

    try:
        template = cv2.imread(empty_cell_image_path, cv2.IMREAD_COLOR)
        mask = cv2.imread(CELL_MASK_IMAGE, cv2.IMREAD_GRAYSCALE)

        if template is None:
            log(f"[Combat Auto] Template introuvable : {empty_cell_image_path}")
            return True

        h, w, _ = template.shape
        
        screen_pos = grid_instance.cells.get(cell_coord)
        if not screen_pos:
            return True

        bbox = (screen_pos[0] - w//2, screen_pos[1] - h//2, screen_pos[0] + w//2, screen_pos[1] + h//2)
        live_cell_img_pil = ImageGrab.grab(bbox=bbox)
        live_cell_img = cv2.cvtColor(np.array(live_cell_img_pil), cv2.COLOR_RGB2BGR)
        
        res = cv2.matchTemplate(live_cell_img, template, cv2.TM_CCOEFF_NORMED, mask=mask)
        return res[0][0] < threshold # Si la similarité est faible, la case est occupée
    except Exception as e:
        log(f"[Combat Auto] Erreur lors de la vérification de l'occupation de la case {cell_coord}: {e}")
        return True

def handle_fight_auto():
    """Gère un combat de manière automatique en utilisant la grille étalonnée."""
    log("[Combat Auto] Lancement de la gestion de combat.")

    if not grid_instance.is_calibrated:
        log("[Combat Auto] Erreur : La grille de combat n'est pas étalonnée. Arrêt du combat auto.")
        handle_fight()
        return

    grid_instance.map_obstacles()

    log("[Combat Auto] Phase de placement...")
    time.sleep(1)
    
    possible_player_starts = find_entities_on_grid([PLAYER_START_CELL_COLOR], min_area=200)
    possible_monster_starts = find_entities_on_grid([MONSTER_START_CELL_COLOR], min_area=200)
    log(f"[Combat Auto] Cases de départ possibles : Alliées {possible_player_starts}, Ennemies {possible_monster_starts}")

    monster_positions = [
        cell for cell in possible_monster_starts 
        if is_cell_occupied(cell, EMPTY_RED_CELL_IMAGE)
    ]
    monster_positions.extend([
        cell for cell in possible_player_starts
        if is_cell_occupied(cell, EMPTY_BLUE_CELL_IMAGE)
    ])

    player_position = None
    player_circles = find_entities_on_grid([PLAYER_FEET_CIRCLE_COLOR])
    if player_circles:
        player_position = player_circles[0]

    if not player_position and possible_player_starts and monster_positions:
        avg_monster_x = sum(p[0] for p in monster_positions) / len(monster_positions)
        avg_monster_y = sum(p[1] for p in monster_positions) / len(monster_positions)
        
        best_start_cell = get_closest_entity((avg_monster_x, avg_monster_y), [p for p in possible_player_starts if not is_cell_occupied(p, EMPTY_BLUE_CELL_IMAGE)])
        
        if best_start_cell and best_start_cell in grid_instance.cells:
            screen_pos = grid_instance.cells[best_start_cell]
            log(f"[Combat Auto] Meilleure case de départ : {best_start_cell}. Clic sur {screen_pos}.")
            pyautogui.click(screen_pos)
            time.sleep(0.5)

    ready_button = find_on_screen("Images/button_ready.png")
    if ready_button:
        log("[Combat Auto] Clic sur 'Prêt'.")
        pyautogui.click(ready_button)
    
    time.sleep(2)

    while not check_and_close_fight_end_popup():
        if is_stop_requested(): return
        check_for_pause()

        log("[Combat Auto] En attente de notre tour...")
        if not is_my_turn():
            time.sleep(1)
            continue

        log("[Combat Auto] C'est notre tour !")
        current_pa = ACTION_POINTS
        current_pm = MOVEMENT_POINTS

        while True:
            player_pos_list = find_entities_on_grid([PLAYER_FEET_CIRCLE_COLOR])
            if not player_pos_list:
                log("[Combat Auto] Impossible de localiser le joueur. Fin du tour.")
                break
            player_pos = player_pos_list[0]

            monster_pos_list = find_entities_on_grid([MONSTER_FEET_CIRCLE_COLOR])
            if not monster_pos_list:
                log("[Combat Auto] Plus aucun monstre détecté. Fin du combat probable.")
                break

            target = get_closest_entity(player_pos, monster_pos_list)
            if not target:
                break

            action_taken = False
            for spell in SPELLS:
                if current_pa >= spell['cost']:
                    dist = grid_instance.get_distance(player_pos, target)
                    if spell['range_min'] <= dist <= spell['range_max']:
                        if grid_instance.has_line_of_sight(player_pos, target):
                            log(f"[Combat Auto] Lancement de '{spell['name']}' sur {target}.")
                            pyautogui.press(spell['key'])
                            time.sleep(0.3)
                            pyautogui.click(grid_instance.cells[target])
                            time.sleep(1.2)
                            current_pa -= spell['cost']
                            action_taken = True
                            break
            if action_taken:
                continue

            if current_pm > 0:
                path = grid_instance.find_path(player_pos, target)
                if path and len(path) > 1:
                    move_target_cell = path[min(len(path) - 1, current_pm)]
                    log(f"[Combat Auto] Déplacement de {player_pos} vers {move_target_cell}.")
                    pyautogui.click(grid_instance.cells[move_target_cell])
                    time.sleep(1.5)
                    current_pm = 0
                    action_taken = True
                    continue

            if not action_taken:
                log("[Combat Auto] Aucune action possible. Fin du tour.")
                break

        end_turn_button = find_on_screen(END_TURN_BUTTON_IMAGE)
        if end_turn_button:
            pyautogui.click(end_turn_button)
        time.sleep(2)

    log("[Combat Auto] Combat terminé.")
    time.sleep(3)

def handle_fight(auto_combat_enabled=False):
    if auto_combat_enabled:
        handle_fight_auto()
        return

    winsound.Beep(440, 500)
    log("Début de la gestion du combat. En attente de la fin du combat (gestion manuelle).")
    fight_timeout = 300
    start_time = time.time()

    while time.time() - start_time < fight_timeout:
        check_for_pause()
        if is_stop_requested():
            log("Arrêt demandé pendant le combat.")
            return

        if check_and_close_fight_end_popup():
            log("Combat terminé. Reprise des activités.")
            time.sleep(3)
            return
        
        time.sleep(1)

    log("Timeout de la gestion du combat.")