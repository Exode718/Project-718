import pyautogui
import json
import time
import math
import cv2
import random
import numpy as np
import winsound
import pyperclip
import keyboard
from PIL import ImageGrab
import os

from utils import log, is_fight_started, check_and_close_fight_end_popup, check_for_pause, is_stop_requested
from grid import grid_instance

# --- Configuration Globale ---
with open("config.json", "r") as f: CONFIG = json.load(f)

COMBAT_CONFIG = CONFIG.get("COMBAT", {})
POSITIONS_CONFIG = CONFIG.get("POSITIONS", {})
ACTION_POINTS = COMBAT_CONFIG.get("ACTION_POINTS", 6)
MOVEMENT_POINTS = COMBAT_CONFIG.get("MOVEMENT_POINTS", 3)
SPELLS = COMBAT_CONFIG.get("SPELLS", [])
SPELLS.sort(key=lambda x: x.get('priority', 99))

# --- Constantes d'Images ---
IMAGE_FOLDER = "Images"
END_TURN_BUTTON_IMAGE = os.path.join(IMAGE_FOLDER, "button_end_turn.png")
MY_TURN_INDICATOR_IMAGE = os.path.join(IMAGE_FOLDER, "my_turn_indicator.png")
PLAYER_START_CELL_COLOR = ([0, 150, 150], [10, 255, 255])      # Rouge (cases de départ du joueur)
MONSTER_START_CELL_COLOR = ([90, 100, 100], [125, 255, 255])   # Bleu (cases de départ des monstres)
PLAYER_FEET_CIRCLE_COLOR_NORMAL = ([25, 100, 100], [35, 255, 255]) # Jaune/Or normal (C7A556)
PLAYER_FEET_CIRCLE_COLOR_HOVER = ([25, 50, 150], [35, 180, 255])   # Jaune/Or survol (DCC899)
MONSTER_FEET_CIRCLE_COLOR_NORMAL = ([10, 180, 100], [25, 255, 200]) # Orange/Marron normal
MONSTER_FEET_CIRCLE_COLOR_HOVER = ([20, 100, 150], [30, 255, 255])  # Orange/Marron survol (D9B474)
ALLY_IMAGES = [os.path.join(IMAGE_FOLDER, f"ally{i}.png") for i in range(1, 5)]
ENEMY_IMAGES = [os.path.join(IMAGE_FOLDER, f"enemy{i}.png") for i in range(1, 5)]
ALLY_TEMPLATES = [cv2.imread(p, 0) for p in ALLY_IMAGES if os.path.exists(p)]
ENEMY_TEMPLATES = [cv2.imread(p, 0) for p in ENEMY_IMAGES if os.path.exists(p)]

combat_modes_checked = False

def click_random_in_rect(x, y, w, h):
    inner_w, inner_h = int(w * 0.8), int(h * 0.8)
    rand_x = random.randint(x - inner_w // 2, x + inner_w // 2)
    rand_y = random.randint(y - inner_h // 2, y + inner_h // 2)
    pyautogui.click(rand_x, rand_y)


def find_on_screen(template_path, threshold=0.8, bbox=None):
    template_name = os.path.basename(template_path).replace('.png', '').upper() + "_POS"
    predefined_pos = POSITIONS_CONFIG.get(template_name)

    if predefined_pos and len(predefined_pos) == 2:
        x, y = predefined_pos
        search_area = 100
        bbox = (x - search_area, y - search_area, x + search_area, y + search_area)

    try:
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
            return (loc[1][0] + w // 2 + offset_x, loc[0][0] + h // 2 + offset_y, w, h)
    except Exception as e:
        log(f"[Combat] Erreur lors de la recherche de {template_path}: {e}")
    return None

def is_my_turn(timeout=2):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if find_on_screen(MY_TURN_INDICATOR_IMAGE, threshold=0.85):
            return True
        time.sleep(0.2)
    return False

def ensure_mode_is_on(off_image, on_image, mode_name):
    if find_on_screen(off_image, threshold=0.9):
        log(f"[Combat Auto] {mode_name} est désactivé. Tentative d'activation...")
        off_button_pos = find_on_screen(off_image, threshold=0.9)
        if off_button_pos:
            pyautogui.click(off_button_pos[0], off_button_pos[1])
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

def find_entities_on_grid(color_ranges, min_area=100, bbox=None, exclude_rect=None):
    if min_area < 100:
        screenshot = ImageGrab.grab(bbox=bbox)
        hsv_screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2HSV)
        grid_positions = []
        offset_x, offset_y = (bbox[0], bbox[1]) if bbox else (0, 0)
        scan_radius = 10

        for cell_coord, screen_pos in grid_instance.cells.items():
            if exclude_rect and (exclude_rect[0] - offset_x <= screen_pos[0] - offset_x <= exclude_rect[2] - offset_x and \
                                 exclude_rect[1] - offset_y <= screen_pos[1] - offset_y <= exclude_rect[3] - offset_y):
                continue

            x_center, y_center = screen_pos[0] - offset_x, screen_pos[1] - offset_y
            
            x_start, y_start = x_center - scan_radius, y_center - scan_radius
            x_end, y_end = x_center + scan_radius, y_center + scan_radius

            if not (0 <= x_start < screenshot.width and 0 <= y_start < screenshot.height and x_end <= screenshot.width and y_end <= screenshot.height):
                continue

            roi = hsv_screenshot[y_start:y_end, x_start:x_end]
            
            mask_circle = np.zeros(roi.shape[:2], dtype="uint8")
            cv2.circle(mask_circle, (scan_radius, scan_radius), scan_radius, 255, -1)

            for color_range in color_ranges:
                color_mask = cv2.inRange(roi, np.array(color_range[0]), np.array(color_range[1]))
                masked_color = cv2.bitwise_and(color_mask, color_mask, mask=mask_circle)
                if np.count_nonzero(masked_color) >= 30:
                        grid_positions.append(cell_coord)
                        break
        return list(set(grid_positions))

    screen_positions = find_entities_by_color(color_ranges, min_area, bbox=bbox)
    grid_positions = [grid_instance.get_cell_from_screen_coords(pos[0], pos[1]) for pos in screen_positions]
    return list(set(filter(None, grid_positions)))

def find_entities_by_image(templates, screenshot_gray, threshold=0.8, y_compensation_factor=1.5):
    if not templates:
        return []

    found_centers = []
    for template in templates:
        if template is None: continue
        h, w = template.shape
        res = cv2.matchTemplate(screenshot_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)

        for pt in zip(*loc[::-1]):
            center_x, center_y = pt[0] + w // 2, pt[1] + h // 2
            is_duplicate = False
            for (fx, fy) in found_centers:
                if abs(center_x - fx) < 30 and abs(center_y - fy) < 30:
                    is_duplicate = True
                    break
            if not is_duplicate:
                found_centers.append((center_x, center_y))

    grid_positions = set()
    for center_x, center_y in found_centers:
        anchor_x, anchor_y = center_x, center_y + int(30 * (y_compensation_factor - 1.0))
        grid_cell = grid_instance.get_cell_from_screen_coords(anchor_x, anchor_y)
        if grid_cell:
            grid_positions.add(grid_cell)
    return list(grid_positions)

def get_start_cells_from_grid(screenshot):
    global possible_player_starts, possible_monster_starts
    game_area = (0, 24, 1348, 808)
    
    possible_player_starts = find_entities_on_grid([PLAYER_START_CELL_COLOR], min_area=200, bbox=game_area)
    possible_monster_starts = find_entities_on_grid([MONSTER_START_CELL_COLOR], min_area=200, bbox=game_area)
    
    combat_state.possible_player_starts = possible_player_starts
    combat_state.possible_monster_starts = possible_monster_starts

    return possible_player_starts, possible_monster_starts


def get_closest_entity(player_pos, entity_list):
    if not player_pos or not entity_list:
        return None
    
    return min(entity_list, key=lambda entity: grid_instance.get_distance(player_pos, entity))

def is_placement_cell_occupied(cell_coord, cell_color_range):
    try:
        screen_pos = grid_instance.cells.get(cell_coord)
        if not screen_pos: return True

        pixel_rgb = pyautogui.pixel(screen_pos[0], screen_pos[1] - 10)
        pixel_hsv = cv2.cvtColor(np.uint8([[pixel_rgb]]), cv2.COLOR_RGB2HSV)[0][0]

        is_center_colored = cell_color_range[0][0] <= pixel_hsv[0] <= cell_color_range[1][0] and cell_color_range[0][1] <= pixel_hsv[1] <= cell_color_range[1][1]

        if cell_color_range == MONSTER_START_CELL_COLOR:
            return not is_center_colored
        elif cell_color_range == PLAYER_START_CELL_COLOR:
            return not is_center_colored
        return False
    except Exception as e:
        log(f"[Combat Auto] Erreur lors de la vérification de l'occupation de la case {cell_coord}: {e}")
        return True

class CombatState:
    def __init__(self):
        self.possible_player_starts = []
        self.possible_monster_starts = []
        self.monster_positions = []
        self.player_positions = []

    def reset(self):
        self.possible_player_starts = []
        self.possible_monster_starts = []
        self.monster_positions = []

combat_state = CombatState()

# --- Gestion du combat ---
def handle_fight_auto(gui_app=None):
    global combat_modes_checked

    combat_state.reset()
    if gui_app: gui_app.in_placement_phase = True
    log("[Combat Auto] Lancement de la gestion de combat.")

    # --- Phase de placement ---
    pyautogui.moveTo(100, 100)

    if not grid_instance.is_calibrated:
        log("[Combat Auto] Erreur : La grille de combat n'est pas étalonnée. Passage en mode manuel.")
        handle_fight(auto_combat_enabled=False)
        return

    log("[Combat Auto] Phase de placement...")
    time.sleep(1)

    if not combat_modes_checked:
        log("[Combat Auto] Vérification des modes de combat (première fois).")
        ensure_mode_is_on("Images/tactical_mode_off.png", "Images/tactical_mode_on.png", "Mode Tactique")
        ensure_mode_is_on("Images/lock_mode_off.png", "Images/lock_mode_on.png", "Verrouillage du combat")

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

    if player_starts and combat_state.monster_positions:
        current_player_pos_list = find_entities_on_grid([PLAYER_FEET_CIRCLE_COLOR_NORMAL, PLAYER_FEET_CIRCLE_COLOR_HOVER], min_area=50, bbox=game_area)
        current_player_pos = current_player_pos_list[0] if current_player_pos_list else None

        best_cell = None
        min_dist_to_closest_monster = float('inf')

        for start_cell in [p for p in player_starts if not is_placement_cell_occupied(p, PLAYER_START_CELL_COLOR)]:
            dist_to_closest = min(grid_instance.get_distance(start_cell, monster_pos) for monster_pos in combat_state.monster_positions)
            if dist_to_closest < min_dist_to_closest_monster:
                min_dist_to_closest_monster = dist_to_closest
                best_cell = start_cell
        best_start_cell = best_cell
        
        if best_start_cell and best_start_cell != current_player_pos and best_start_cell in grid_instance.cells:
            screen_pos = grid_instance.cells[best_start_cell]
            log(f"[Combat Auto] Meilleure case de départ : {best_start_cell}. Clic sur {screen_pos}.")
            pyautogui.click(screen_pos)
            time.sleep(0.5)

    ready_button_info = find_on_screen("Images/button_ready.png")
    if ready_button_info:
        log("[Combat Auto] Clic sur 'Prêt'.")
        click_random_in_rect(*ready_button_info)
        pyautogui.moveTo(100, 100, duration=0.1)
    else:
        log("[Combat Auto] Bouton 'Prêt' non trouvé, appui sur F1 en fallback.")
        time.sleep(2)
        pyautogui.press('f1')

    log("[Combat Auto] Attente du début du combat...")
    if gui_app: 
        gui_app.in_placement_phase = False
    
    log("[Combat Auto] Attente de 3s pour la stabilisation de l'interface de combat...")
    time.sleep(3)
    if gui_app: gui_app.after(0, gui_app.draw_map, True)

    game_area = (0, 24, 1348, 808)

    # --- Boucle principale de combat ---
    while not check_and_close_fight_end_popup():
        if is_stop_requested(): return
        check_for_pause()

        log("[Combat Auto] En attente de notre tour...")
        if not is_my_turn():
            time.sleep(0.5)
            continue

        log("[Combat Auto] C'est notre tour !")
        log(f"[Combat Auto] Début du tour avec {ACTION_POINTS} PA et {MOVEMENT_POINTS} PM.")
        current_pa = ACTION_POINTS
        current_pm = MOVEMENT_POINTS
        spell_casts = {}

        # --- Analyse du terrain ---
        if not combat_modes_checked:
            ensure_mode_is_on("Images/creature_mode_off.png", "Images/creature_mode_on.png", "Mode Créature")
            combat_modes_checked = True

        pyautogui.moveTo(100, 100, duration=0.1)

        log("[Combat Auto] Analyse du terrain pour ce tour...")
        screenshot_pil = ImageGrab.grab(bbox=game_area)
        screenshot_gray = cv2.cvtColor(np.array(screenshot_pil), cv2.COLOR_BGR2GRAY)
        grid_instance.map_obstacles(screenshot=screenshot_pil, color_tolerance=0)
        time.sleep(0.1)
        
        combat_state.player_positions = find_entities_by_image(ALLY_TEMPLATES, screenshot_gray, y_compensation_factor=2.2)
        combat_state.monster_positions = find_entities_by_image(ENEMY_TEMPLATES, screenshot_gray, y_compensation_factor=1.5)
        
        if not combat_state.player_positions:
            log("[Combat Auto] Impossible de localiser le joueur. Fin du tour forcée.")
            time.sleep(2)
            pyautogui.press('f1')
            continue
        
        player_pos = combat_state.player_positions[0]
        if player_pos in combat_state.monster_positions:
            combat_state.monster_positions.remove(player_pos)

        if player_pos not in grid_instance.walkable_cells:
            grid_instance.walkable_cells.add(player_pos)
        for monster_pos in combat_state.monster_positions:
            if monster_pos not in grid_instance.los_transparent_cells:
                grid_instance.los_transparent_cells.add(monster_pos)
        
        log(f"[Combat Auto] Joueur détecté à : {player_pos}")
        if not combat_state.monster_positions:
            log("[Combat Auto] Plus aucun monstre détecté. Fin du combat probable.")
            break
        log(f"[Combat Auto] {len(combat_state.monster_positions)} monstres détectés à : {combat_state.monster_positions}")
        
        if gui_app:
            log("[Combat Auto] Rafraîchissement de la grille de debug.")
            gui_app.after(0, gui_app.draw_map, True)

        # --- Boucle d'actions du tour ---
        fight_over = False
        while current_pa > 0 and not fight_over:
            if check_for_pause():
                log("[Combat Auto] Reprise après pause. Ré-évaluation de la situation.")
                break

            log("[Combat Auto] Ré-analyse du terrain avant l'action.")
            screenshot_pil = ImageGrab.grab(bbox=game_area)
            screenshot_gray = cv2.cvtColor(np.array(screenshot_pil), cv2.COLOR_BGR2GRAY)
            grid_instance.map_obstacles(screenshot=screenshot_pil, color_tolerance=0)
            time.sleep(0.05)

            combat_state.player_positions = find_entities_by_image(ALLY_TEMPLATES, screenshot_gray, y_compensation_factor=2.2)
            combat_state.monster_positions = find_entities_by_image(ENEMY_TEMPLATES, screenshot_gray, y_compensation_factor=1.5)
            if not combat_state.player_positions:
                log("[Combat Auto] Impossible de localiser le joueur après ré-analyse. Fin du tour forcée.")
                pyautogui.press('f1')
                break
            player_pos = combat_state.player_positions[0]
            if player_pos in combat_state.monster_positions:
                combat_state.monster_positions.remove(player_pos)
            
            if player_pos not in grid_instance.walkable_cells:
                grid_instance.walkable_cells.add(player_pos)
            for monster_pos in combat_state.monster_positions:
                if monster_pos not in grid_instance.los_transparent_cells:
                    grid_instance.los_transparent_cells.add(monster_pos)

            if gui_app: gui_app.after(0, gui_app.draw_map, True)

            min_spell_cost = min((spell['cost'] for spell in SPELLS), default=float('inf'))
            if current_pa < min_spell_cost and current_pm == 0:
                log("[Combat Auto] PA/PM insuffisants pour toute action. Fin du tour.")
                break

            target = get_closest_entity(player_pos, combat_state.monster_positions)
            if not target:
                log("[Combat Auto] Plus de cibles après ré-analyse. Fin du tour.")
                break

            action_taken = False
            can_attack_from_current_pos = False
            for spell in SPELLS:
                if current_pa >= spell['cost'] and spell_casts.get(spell['name'], 0) < spell.get('casts_per_turn', 99):
                    dist = grid_instance.get_distance(player_pos, target)
                    in_range = spell['range_min'] <= dist <= spell['range_max']
                    has_los = grid_instance.has_line_of_sight(player_pos, target)

                    if in_range and has_los:
                        can_attack_from_current_pos = True
                        log(f"[Combat Auto] Lancement de '{spell['name']}' sur {target}.")
                        keyboard.press_and_release(spell['key'])
                        time.sleep(random.uniform(0.2, 0.5))
                        pyautogui.click(grid_instance.cells[target])
                        time.sleep(random.uniform(1.2, 1.5))
                        current_pa -= spell['cost']
                        action_taken = True
                        spell_casts[spell['name']] = spell_casts.get(spell['name'], 0) + 1
                        pyautogui.moveTo(100, 100, duration=0.1)
                        if check_and_close_fight_end_popup():
                            fight_over = True
                            break
                        new_monsters = find_entities_by_image(ENEMY_TEMPLATES, cv2.cvtColor(np.array(ImageGrab.grab(bbox=game_area)), cv2.COLOR_BGR2GRAY), y_compensation_factor=1.5)
                        combat_state.monster_positions = new_monsters
                        log(f"[Combat Auto] Ré-évaluation des monstres : {len(new_monsters)} restants.")
                        if check_and_close_fight_end_popup(): break
                        break
                    else:
                        log(f"[Debug] Sort '{spell['name']}': Portée? {'Oui' if in_range else 'Non'} (dist: {dist}, portée: {spell['range_min']}-{spell['range_max']}). LdV? {'Oui' if has_los else 'Non'}.")
                else:
                    pass
            
            if fight_over or check_and_close_fight_end_popup():
                fight_over = True
                break

            if action_taken: continue

            if not can_attack_from_current_pos and current_pm > 0:
                log("[Combat Auto] Aucune attaque possible. Tentative de rapprochement...")

                log(f"[Debug Path] Position joueur: {player_pos} (marchable? {player_pos in grid_instance.walkable_cells})")
                player_neighbors = grid_instance.get_neighbors(player_pos)
                log(f"[Debug Path] Voisins marchables du joueur ({len(player_neighbors)}): {player_neighbors}")
                log(f"[Debug Path] Position cible: {target} (marchable? {target in grid_instance.walkable_cells})")
                log(f"[Debug Path] Cible transparente pour LdV? {target in grid_instance.los_transparent_cells}")
                
                path = grid_instance.find_path(player_pos, target)

                log(f"[Debug Path] Chemin trouvé : {path}")
                if path and len(path) > 1:
                    move_target_cell = grid_instance.get_farthest_walkable_cell(path, current_pm)
                    log(f"[Combat Auto] Déplacement de {player_pos} vers {move_target_cell} pour se mettre à portée.")

                    if move_target_cell in grid_instance.cells:
                        pyautogui.click(grid_instance.cells[move_target_cell])
                        time.sleep(random.uniform(2.0, 2.5))

                        new_pos_list = find_entities_by_image(ALLY_TEMPLATES, cv2.cvtColor(np.array(ImageGrab.grab(bbox=game_area)), cv2.COLOR_BGR2GRAY), y_compensation_factor=2.2)
                        new_pos = new_pos_list[0] if new_pos_list else player_pos

                        if new_pos != player_pos:
                            pm_used = grid_instance.get_path_distance(player_pos, new_pos)
                            current_pm -= pm_used
                            player_pos = new_pos
                            log(f"[Combat Auto] Déplacement réussi vers {new_pos}.")
                            action_taken = True
                            continue
                        else:
                            log("[Combat Auto] Le déplacement a échoué (personnage bloqué ou clic invalide).")
                            current_pm = 0 
                    else:
                        log(f"[Combat Auto] Erreur: La case de destination {move_target_cell} est invalide.")
                else:
                    log("[Combat Auto] Aucun chemin trouvé vers la cible.")

            if not action_taken or current_pa <= 0:
                log("[Combat Auto] Aucune action possible. Fin du tour.")
                if not check_and_close_fight_end_popup():
                    time.sleep(2)
                    end_turn_button_info = find_on_screen(END_TURN_BUTTON_IMAGE)
                    if end_turn_button_info:
                        log("[Combat Auto] Clic sur 'Passer son tour'.")
                        click_random_in_rect(*end_turn_button_info)
                    else:
                        log("[Combat Auto] Bouton 'Passer son tour' non trouvé, appui sur F1 en fallback.")
                        time.sleep(2)
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

    # --- Gestion manuelle ---
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