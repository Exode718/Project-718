import pyautogui
import json
import time
import math
import cv2
import random
import numpy as np
import winsound
from PIL import ImageGrab
import os

from utils import log, is_fight_started, check_and_close_fight_end_popup, check_for_pause, is_stop_requested
from grid import grid_instance

with open("config.json", "r") as f: CONFIG = json.load(f)

COMBAT_CONFIG = CONFIG.get("COMBAT", {})
POSITIONS_CONFIG = CONFIG.get("POSITIONS", {})
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
TIMELINE_ANCHOR_IMAGE = os.path.join(IMAGE_FOLDER, "timeline.png")

PLAYER_START_CELL_COLOR = ([0, 150, 150], [10, 255, 255])      # Rouge (cases de départ du joueur)
MONSTER_START_CELL_COLOR = ([90, 100, 100], [125, 255, 255])   # Bleu (cases de départ des monstres)
PLAYER_FEET_CIRCLE_COLOR = ([40, 100, 100], [55, 255, 255])    # Pieds Perso (#FFCC00)
MONSTER_FEET_CIRCLE_COLOR = ([25, 100, 100], [45, 255, 255])  # Pieds Ennemis (#C28319)

# --- State Flags ---
combat_modes_checked = False

def find_on_screen(template_path, threshold=0.8, bbox=None):
    """Trouve la première occurrence d'un template sur l'écran."""
    # --- Optimisation par position pré-configurée ---
    template_name = os.path.basename(template_path).replace('.png', '').upper() + "_POS"
    predefined_pos = POSITIONS_CONFIG.get(template_name)

    # Si une position est définie, on utilise un petit bbox autour
    if predefined_pos and len(predefined_pos) == 2:
        x, y = predefined_pos
        search_area = 100 # Rayon de recherche
        bbox = (x - search_area, y - search_area, x + search_area, y + search_area)

    try: # --- Recherche d'image ---
        screen = ImageGrab.grab(bbox=bbox)
        screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_BGR2GRAY)
        template = cv2.imread(template_path, 0)
        if template is None: return None
        
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)

        if len(loc[0]) > 0:
            h, w = template.shape
            offset_x = bbox[0] if bbox else 0
            offset_y = bbox[1] if bbox else 0
            return (loc[1][0] + w // 2 + offset_x, loc[0][0] + h // 2 + offset_y)
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

def ensure_mode_is_on(off_image, on_image, mode_name):
    """Vérifie si un mode est activé, l'active si besoin, et confirme."""
    if find_on_screen(off_image, threshold=0.9):
        log(f"[Combat Auto] {mode_name} est désactivé. Tentative d'activation...")
        off_button_pos = find_on_screen(off_image, threshold=0.9)
        if off_button_pos:
            pyautogui.click(off_button_pos)
            time.sleep(0.5)
            if find_on_screen(on_image, threshold=0.9):
                log(f"[Combat Auto] {mode_name} activé avec succès.")
                return True
            else:
                log(f"[Combat Auto] Échec de l'activation de {mode_name}.")
                return False
    elif find_on_screen(on_image, threshold=0.9):
        log(f"[Combat Auto] {mode_name} est déjà activé.")
        return True
    return False

def find_entities_by_color(color_range_list, min_area=100, bbox=None):
    """
    Trouve les centres des zones de couleur sur l'écran.
    Retourne une liste de positions (x, y).
    """
    screen_pil = ImageGrab.grab(bbox=bbox)
    screen_np = np.array(screen_pil)
    screen_hsv = cv2.cvtColor(screen_np, cv2.COLOR_RGB2HSV)
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

                    if bbox:
                        positions.append((cx + bbox[0], cy + bbox[1]))
                    else:
                        positions.append((cx, cy))
    return positions

def find_entities_on_grid(color_ranges, min_area=100, bbox=None):
    """Trouve les entités et retourne leurs coordonnées de grille."""
    if min_area < 100: # Seuil pour différencier la recherche de cercles de la recherche de cases de départ
        screenshot = ImageGrab.grab(bbox=bbox)
        hsv_screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2HSV)
        grid_positions = []
        offset_x, offset_y = (bbox[0], bbox[1]) if bbox else (0, 0)

        for cell_coord, screen_pos in grid_instance.cells.items():
            y_offset = 15 # Réduction de l'offset pour être plus proche du centre
            scan_size = 7 # Augmentation de la zone de scan
            x_center, y_center = screen_pos[0] - offset_x, screen_pos[1] - offset_y + y_offset
            
            x_start, y_start = x_center - scan_size, y_center - scan_size
            x_end, y_end = x_center + scan_size, y_center + scan_size

            if not (0 <= x_start < screenshot.width and 0 <= y_start < screenshot.height and x_end <= screenshot.width and y_end <= screenshot.height):
                continue

            roi = hsv_screenshot[y_start:y_end, x_start:x_end]
            for color_range in color_ranges:
                mask = cv2.inRange(roi, np.array(color_range[0]), np.array(color_range[1]))
                if np.count_nonzero(mask) >= 9: # Si on trouve au moins une zone de 3x3 pixels
                    grid_positions.append(cell_coord)
                    break
        return list(set(grid_positions))

    # --- Pour la phase de placement, on utilise la détection de contours (plus fiable pour les grandes zones) ---
    screen_positions = find_entities_by_color(color_ranges, min_area, bbox=bbox)
    grid_positions = [grid_instance.get_cell_from_screen_coords(pos[0], pos[1]) for pos in screen_positions]
    return list(set(filter(None, grid_positions)))

def get_start_cells_from_grid(screenshot):
    """
    Parcourt la grille pour trouver les cases de départ en vérifiant la couleur de chaque case.
    Retourne deux listes : les cases de départ du joueur (rouges) et celles des monstres (bleues).
    """
    global possible_player_starts, possible_monster_starts
    game_area = (0, 24, 1348, 808)
    
    possible_player_starts = find_entities_on_grid([PLAYER_START_CELL_COLOR], min_area=200, bbox=game_area)
    possible_monster_starts = find_entities_on_grid([MONSTER_START_CELL_COLOR], min_area=200, bbox=game_area)
    
    combat_state.possible_player_starts = possible_player_starts
    combat_state.possible_monster_starts = possible_monster_starts

    return possible_player_starts, possible_monster_starts


def get_closest_entity(player_pos, entity_list):
    """Trouve l'entité la plus proche du joueur sur la grille."""
    if not player_pos or not entity_list:
        return None
    
    return min(entity_list, key=lambda entity: grid_instance.get_distance(player_pos, entity))

def is_placement_cell_occupied(cell_coord, cell_color_range, occupation_threshold=0.5):
    """
    Vérifie si une case de placement est occupée en regardant si le centre n'est PLUS de la bonne couleur.
    """
    try:
        screen_pos = grid_instance.cells.get(cell_coord)
        if not screen_pos: return True

        pixel_rgb = pyautogui.pixel(screen_pos[0], screen_pos[1])
        pixel_hsv = cv2.cvtColor(np.uint8([[pixel_rgb]]), cv2.COLOR_RGB2HSV)[0][0]

        is_center_colored = cell_color_range[0][0] <= pixel_hsv[0] <= cell_color_range[1][0] and cell_color_range[0][1] <= pixel_hsv[1] <= cell_color_range[1][1]

        # Une case est occupée si son centre n'est plus de la couleur de départ.
        if cell_color_range == MONSTER_START_CELL_COLOR:
            return not is_center_colored
        elif cell_color_range == PLAYER_START_CELL_COLOR:
            return not is_center_colored
        return False
    except Exception as e:
        log(f"[Combat Auto] Erreur lors de la vérification de l'occupation de la case {cell_coord}: {e}")
        return True

class CombatState:
    """Classe pour centraliser l'état du combat et le partager avec la GUI."""
    def __init__(self):
        self.possible_player_starts = []
        self.possible_monster_starts = []
        self.monster_positions = []

    def reset(self):
        self.possible_player_starts = []
        self.possible_monster_starts = []
        self.monster_positions = []

combat_state = CombatState()

def handle_fight_auto(gui_app=None):
    combat_state.reset()
    if gui_app: gui_app.in_placement_phase = True
    log("[Combat Auto] Lancement de la gestion de combat.")
    
    log("[Combat Auto] Déplacement de la souris pour ne pas gêner le scan.")
    pyautogui.moveTo(1, pyautogui.size().height - 1)

    if not grid_instance.is_calibrated:
        log("[Combat Auto] Erreur : La grille de combat n'est pas étalonnée. Passage en mode manuel.")
        handle_fight(auto_combat_enabled=False)
        return

    log("[Combat Auto] Phase de placement...")
    time.sleep(1)

    global combat_modes_checked
    if not combat_modes_checked:
        log("[Combat Auto] Vérification des modes de combat (première fois).")
        ensure_mode_is_on("Images/tactical_mode_off.png", "Images/tactical_mode_on.png", "Mode Tactique")
        ensure_mode_is_on("Images/lock_mode_off.png", "Images/lock_mode_on.png", "Verrouillage du combat")
        ensure_mode_is_on("Images/creature_mode_off.png", "Images/creature_mode_on.png", "Mode Créature")
        combat_modes_checked = True


    game_area = (0, 24, 1348, 808)
    screenshot = ImageGrab.grab(bbox=game_area)
    player_starts, monster_starts = get_start_cells_from_grid(screenshot)
    log(f"[Combat Auto] {len(player_starts)} cases de départ alliées trouvées : {player_starts}")
    log(f"[Combat Auto] {len(monster_starts)} cases de départ ennemies trouvées : {monster_starts}")

    combat_state.monster_positions = [
        cell for cell in monster_starts 
        if is_placement_cell_occupied(cell, MONSTER_START_CELL_COLOR)
    ]
    log(f"[Combat Auto] {len(combat_state.monster_positions)} monstres détectés sur les cases de départ : {combat_state.monster_positions}")

    if gui_app:
        gui_app.after(0, gui_app.draw_map, True)

    player_position = None
    player_circles = find_entities_on_grid([PLAYER_FEET_CIRCLE_COLOR], bbox=game_area)
    if player_circles:
        player_position = player_circles[0]

    if not player_position and player_starts and combat_state.monster_positions:
        # --- Stratégie de placement : minimiser la distance au monstre le plus proche ---
        best_cell = None
        min_dist_to_closest_monster = float('inf')

        for start_cell in [p for p in player_starts if not is_placement_cell_occupied(p, PLAYER_START_CELL_COLOR)]:
            dist_to_closest = min(grid_instance.get_distance(start_cell, monster_pos) for monster_pos in combat_state.monster_positions)
            if dist_to_closest < min_dist_to_closest_monster:
                min_dist_to_closest_monster = dist_to_closest
                best_cell = start_cell
        best_start_cell = best_cell
        
        if best_start_cell and best_start_cell in grid_instance.cells:
            screen_pos = grid_instance.cells[best_start_cell]
            log(f"[Combat Auto] Meilleure case de départ : {best_start_cell}. Clic sur {screen_pos}.")
            pyautogui.click(screen_pos)
            time.sleep(0.5)

    ready_button = find_on_screen("Images/button_ready.png")
    log("[Combat Auto] Appui sur 'F1' pour être prêt.")
    pyautogui.press('f1')

    log("[Combat Auto] Attente du début du combat...")
    if gui_app: gui_app.in_placement_phase = False

    time.sleep(2.5)
    while not check_and_close_fight_end_popup():
        if is_stop_requested(): return
        check_for_pause()

        log("[Combat Auto] En attente de notre tour...")
        if not is_my_turn():
            time.sleep(1)
            continue

        log("[Combat Auto] C'est notre tour !")
        if gui_app:
            log("[Combat Auto] Rafraîchissement de la grille de debug.")
            gui_app.after(0, gui_app.draw_map, True)
        
        grid_instance.map_obstacles()

        current_pa = ACTION_POINTS
        current_pm = MOVEMENT_POINTS

        while True:
            player_pos_list = find_entities_on_grid([PLAYER_FEET_CIRCLE_COLOR], min_area=50, bbox=game_area)
            if not player_pos_list:
                log("[Combat Auto] Impossible de localiser le joueur. Fin du tour.")
                break
            player_pos = player_pos_list[0]

            monster_pos_list = find_entities_on_grid([MONSTER_FEET_CIRCLE_COLOR], min_area=50, bbox=game_area)
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
                            time.sleep(random.uniform(0.2, 0.5))
                            pyautogui.click(grid_instance.cells[target])
                            time.sleep(random.uniform(1.2, 1.5))
                            current_pa -= spell['cost']
                            action_taken = True
                            break
            if action_taken:
                continue

            if current_pm > 0:
                log("[Combat Auto] Aucune attaque possible. Tentative de déplacement.")
                path = grid_instance.find_path(player_pos, target)
                if path and len(path) > 1:
                    move_target_cell = path[min(len(path) - 1, current_pm)]
                    log(f"[Combat Auto] Déplacement de {player_pos} vers {move_target_cell}.")
                    pyautogui.click(grid_instance.cells[move_target_cell])
                    time.sleep(random.uniform(1.5, 2.0))
                    current_pm = 0
                    action_taken = True
                    continue

            if not action_taken:
                log("[Combat Auto] Aucune action possible. Fin du tour.")
                log("[Combat Auto] Appui sur 'F1' pour passer le tour.")
                pyautogui.press('f1')
                break
        time.sleep(2)

    log("[Combat Auto] Combat terminé.")
    time.sleep(3)

def handle_fight(auto_combat_enabled=False, gui_app=None):
    if auto_combat_enabled:
        handle_fight_auto(gui_app)
        if gui_app: gui_app.after(0, gui_app.draw_map, False)
        return

    if gui_app: gui_app.after(0, gui_app.draw_map, True)
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
            if gui_app: gui_app.after(0, gui_app.draw_map, False)
            time.sleep(3)
            return
        
        time.sleep(1)

    log("Timeout de la gestion du combat.")