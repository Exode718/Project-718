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
from PIL import ImageGrab, Image
import os
import threading
from utils import log, is_fight_started, check_and_close_fight_end_popup, check_for_pause, is_stop_requested, get_map_coordinates, image_file_lock
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
PLAYER_START_CELL_COLOR_RGB = (255, 0, 0)
MONSTER_START_CELL_COLOR_RGB = (0, 0, 255)
ALLY_IMAGES = [os.path.join(IMAGE_FOLDER, f"ally{i}.png") for i in range(1, 5)]
ENEMY_IMAGES = [os.path.join(IMAGE_FOLDER, f"enemy{i}.png") for i in range(1, 5)]
SHADOW_RGB_COLOR = (56, 44, 22)
ALLY_TEMPLATES = [cv2.imread(p, 0) for p in ALLY_IMAGES if os.path.exists(p)]
ENEMY_TEMPLATES = [cv2.imread(p, 0) for p in ENEMY_IMAGES if os.path.exists(p)]
MONSTER_START_COLORS_RGB = [tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) for h in COMBAT_CONFIG.get("MONSTER_COLORS_HEX", [])]

SPELL_COOLDOWNS = {}
CURRENT_TURN = 0

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
        if find_on_screen(MY_TURN_INDICATOR_IMAGE, threshold=0.95):
            return True
        time.sleep(0.2)
    return False

def wait_for_next_turn(timeout=30):
    log("[Combat Auto] Attente de la fin de notre tour...")
    start_time = time.time()
    while is_my_turn(timeout=0.5) and time.time() - start_time < timeout:
        time.sleep(0.5)
    
    log("[Combat Auto] Attente du début du prochain tour...")
    while not is_my_turn(timeout=0.5) and time.time() - start_time < timeout:
        time.sleep(0.5)
    return False

def ensure_mode_is_on(off_image, on_image, mode_name, retries=3, delay=0.5):
    if find_on_screen(on_image, threshold=0.9):
        log(f"[Combat Auto] {mode_name} est déjà activé.")
        return True

    for i in range(retries):
        off_button_pos = find_on_screen(off_image, threshold=0.9)
        if off_button_pos:
            log(f"[Combat Auto] {mode_name} est désactivé. Tentative d'activation ({i+1}/{retries})...")
            pyautogui.click(off_button_pos[0], off_button_pos[1])
            time.sleep(delay)
            if find_on_screen(on_image, threshold=0.9):
                log(f"[Combat Auto] {mode_name} activé avec succès.")
                return True
        log(f"[Combat Auto] Impossible de trouver le bouton '{mode_name}' (off) ou l'activation a échoué. Ré-essai...")

    log(f"[Combat Auto] AVERTISSEMENT: Échec de l'activation de {mode_name} après {retries} tentatives. Le combat peut être instable.")
    return False

def find_cells_by_color(target_color_rgb, tolerance=50, min_area=200, bbox=None):
    screen_pil = ImageGrab.grab(bbox=bbox)
    screen_np = np.array(screen_pil)
    
    lower_bound = np.array([max(0, c - tolerance) for c in target_color_rgb])
    upper_bound = np.array([min(255, c + tolerance) for c in target_color_rgb])
    
    screen_bgr = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)
    
    mask = cv2.inRange(screen_bgr, lower_bound[::-1], upper_bound[::-1])
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    positions = []
    for c in contours:
        if cv2.contourArea(c) > min_area:
            M = cv2.moments(c)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"]) + (bbox[0] if bbox else 0)
                cy = int(M["m01"] / M["m00"]) + (bbox[1] if bbox else 0)
                positions.append((cx, cy))
    screen_positions = positions
    grid_positions = [grid_instance.get_cell_from_screen_coords(pos[0], pos[1]) for pos in screen_positions]
    return list(set(filter(None, grid_positions)))

def is_monster_color_present_on_cell(screenshot_pil, grid_cell, colors_rgb, tolerance=20, radius=15, min_pixels=5):
    screen_pos = grid_instance.cells.get(grid_cell)
    if not screen_pos:
        return False

    game_area_x_offset, game_area_y_offset = 0, 24
    x_center_rel = screen_pos[0] - game_area_x_offset
    y_center_rel = screen_pos[1] - game_area_y_offset

    pixel_count = 0
    for x_offset in range(-radius, radius + 1):
        for y_offset in range(-radius, radius + 1):
            if x_offset**2 + y_offset**2 <= radius**2:
                try:
                    pixel = screenshot_pil.getpixel((x_center_rel + x_offset, y_center_rel + y_offset))
                    for color_rgb in colors_rgb:
                        if all(abs(pixel[i] - color_rgb[i]) <= tolerance for i in range(3)):
                            pixel_count += 1
                            if pixel_count >= min_pixels:
                                return True
                            break
                except IndexError:
                    continue
    return False

def is_shadow_present_on_cell(screenshot_pil, grid_cell, color_rgb, tolerance=20, radius=10, min_pixels=5):
    screen_pos = grid_instance.cells.get(grid_cell)
    if not screen_pos:
        return False

    game_area_x_offset, game_area_y_offset = 0, 24
    x_center_rel = screen_pos[0] - game_area_x_offset
    y_center_rel = screen_pos[1] - game_area_y_offset

    pixel_count = 0
    for x_offset in range(-radius, radius + 1):
        for y_offset in range(-radius, radius + 1):
            if x_offset**2 + y_offset**2 <= radius**2:
                try:
                    pixel = screenshot_pil.getpixel((x_center_rel + x_offset, y_center_rel + y_offset))
                    if all(abs(pixel[i] - color_rgb[i]) <= tolerance for i in range(3)):
                        pixel_count += 1
                except IndexError:
                    continue
    return pixel_count >= min_pixels

def find_entities_by_image(templates, screenshot_pil, combat_overrides, threshold=0.8, y_compensation_factor=1.5, exclude_rect=None):
    if not templates:
        return []

    screenshot_np = np.array(screenshot_pil)
    if exclude_rect:
        x1, y1, x2, y2 = exclude_rect
        screenshot_np[y1:y2, x1:x2] = 0
    screenshot_gray = cv2.cvtColor(screenshot_np, cv2.COLOR_BGR2GRAY)
    found_centers = []
    scores = {}
    for template in templates:
        if template is None: continue
        h, w = template.shape
        res = cv2.matchTemplate(screenshot_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)

        for pt in zip(*loc[::-1]):
            center_x, center_y = pt[0] + w // 2, pt[1] + h // 2
            is_duplicate = any(abs(center_x - fx) < 30 and abs(center_y - fy) < 30 for fx, fy in found_centers)
            if not is_duplicate:
                found_centers.append((center_x, center_y))
                scores[(center_x, center_y)] = res[pt[1], pt[0]]

    grid_positions = set()
    for center_x, center_y in found_centers:
        anchor_x, anchor_y = center_x, center_y + int(30 * (y_compensation_factor - 1.0))
        grid_cell = grid_instance.get_cell_from_screen_coords(anchor_x, anchor_y)
        if grid_cell and combat_overrides.get(str(grid_cell)) != "obstacle":
            if is_shadow_present_on_cell(screenshot_pil, grid_cell, SHADOW_RGB_COLOR):
                grid_positions.add((grid_cell, scores.get((center_x, center_y), 0)))

    return list(grid_positions)

def get_start_cells_from_grid(screenshot):
    global possible_player_starts, possible_monster_starts
    game_area = (0, 24, 1348, 808)
    
    possible_player_starts = find_cells_by_color(PLAYER_START_CELL_COLOR_RGB, tolerance=50, min_area=200, bbox=game_area)
    possible_monster_starts = find_cells_by_color(MONSTER_START_CELL_COLOR_RGB, tolerance=50, min_area=200, bbox=game_area)
    
    combat_state.possible_player_starts = possible_player_starts
    combat_state.possible_monster_starts = possible_monster_starts

    return possible_player_starts, possible_monster_starts


def get_closest_entity(player_pos, entity_list):
    if not player_pos or not entity_list:
        return None
    
    return min(entity_list, key=lambda entity: grid_instance.get_distance(player_pos, entity))

def is_placement_cell_occupied(cell_coord, cell_color_rgb):
    try:
        screen_pos = grid_instance.cells.get(cell_coord)
        if not screen_pos: return True

        pixel_at_center = pyautogui.pixel(screen_pos[0], screen_pos[1] - 10)
        is_occupied = all(abs(pixel_at_center[i] - cell_color_rgb[i]) > 50 for i in range(3))
        return is_occupied
    except Exception as e:
        log(f"[Combat Auto] Erreur lors de la vérification de l'occupation de la case {cell_coord}: {e}")
        return True
 
def verify_and_update_position(old_pos, destination_cell, game_area, gui_app, combat_overrides):
    log("[Combat Auto] Vérification de la position après mouvement...")
    pyautogui.moveTo(100, 100, duration=0.1)
    
    for attempt in range(3):
        time.sleep(0.7)
        screenshot_after_move = ImageGrab.grab(bbox=game_area)

        if is_shadow_present_on_cell(screenshot_after_move, destination_cell, SHADOW_RGB_COLOR):
            log(f"[Combat Auto] Déplacement réussi vers {destination_cell}.")
            combat_state.player_positions = [destination_cell]
            if gui_app: gui_app.after(0, gui_app.draw_map, True)
            return destination_cell, True

        new_pos_list = [p for p, s in find_entities_by_image(ALLY_TEMPLATES, screenshot_after_move, combat_overrides, y_compensation_factor=1.8)]
        if new_pos_list and new_pos_list[0] != old_pos:
            log(f"[Combat Auto] Déplacement réussi vers {new_pos_list[0]} (détection globale).")
            combat_state.player_positions = [new_pos_list[0]]
            if gui_app: gui_app.after(0, gui_app.draw_map, True)
            return new_pos_list[0], True

    log("[Combat Auto] Le déplacement a échoué (personnage bloqué ou clic invalide).")
    combat_state.player_positions = [old_pos]
    return old_pos, False

def update_targets_after_action(game_area, combat_overrides, gui_app):
    log("[Combat Auto] Ré-évaluation des cibles...")
    pyautogui.moveTo(100, 100, duration=0.1)
    screenshot = ImageGrab.grab(bbox=game_area)    
    monster_positions_with_scores = find_entities_by_image(ENEMY_TEMPLATES, screenshot, combat_overrides, y_compensation_factor=1.5, exclude_rect=(1190, 671, 1275, 701))
    combat_state.monster_positions = [p for p, s in monster_positions_with_scores]
    log(f"[Combat Auto] {len(combat_state.monster_positions)} cibles restantes.")
    if gui_app: gui_app.after(0, gui_app.draw_map, True)

class CombatState:
    def __init__(self):
        self.possible_player_starts = []
        self.possible_monster_starts = []
        self.monster_positions = []
        self.player_positions = []
        self.initial_placement_pos = None
        self.current_pa = None
        self.current_pm = None

    def reset(self):
        self.possible_player_starts = []
        self.possible_monster_starts = []
        self.monster_positions = []
        self.initial_placement_pos = None
        self.current_pa = None
        self.current_pm = None

combat_state = CombatState()

# --- Gestion du combat ---
def handle_fight_auto(gui_app=None):
    global combat_modes_checked, CURRENT_TURN, SPELL_COOLDOWNS

    combat_state.reset()
    if gui_app: gui_app.in_placement_phase = True
    CURRENT_TURN = 0
    SPELL_COOLDOWNS.clear()

    winsound.Beep(440, 500)
    log("[Combat Auto] Lancement de la gestion de combat.")

    # --- Phase de placement ---
    if find_on_screen(END_TURN_BUTTON_IMAGE, threshold=0.85, bbox=(1150, 750, 1300, 800)):
        log("[Combat Auto] Combat déjà en cours détecté. Passage de la phase de placement.")
        if gui_app: 
            gui_app.in_placement_phase = False
    else:
        log("[Combat Auto] Phase de placement...")
    pyautogui.moveTo(100, 100)

    if not grid_instance.is_calibrated:
        log("[Combat Auto] Erreur : La grille de combat n'est pas étalonnée. Passage en mode manuel.")
        handle_fight(auto_combat_enabled=False)
        return
    else:
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

        detected_monsters = []
        for cell in monster_starts:
            screen_pos = grid_instance.cells.get(cell)
            if screen_pos:
                has_shadow = is_shadow_present_on_cell(screenshot, cell, SHADOW_RGB_COLOR)
                has_monster_color = is_monster_color_present_on_cell(screenshot, cell, MONSTER_START_COLORS_RGB)

                if has_shadow or has_monster_color:
                    detected_monsters.append(cell)
        combat_state.monster_positions = detected_monsters
        log(f"[Combat Auto] {len(combat_state.monster_positions)} monstres détectés sur les cases de départ : {combat_state.monster_positions}")

        if not combat_state.monster_positions and monster_starts:
            log("[Combat Auto] Aucun monstre avec ombre détecté. Utilisation de toutes les cases de départ ennemies comme cibles potentielles.")
            combat_state.monster_positions = monster_starts

        if gui_app:
            gui_app.after(0, gui_app.draw_map, True)
            with image_file_lock:
                image_dir = os.path.join("Maps", "Images")
                os.makedirs(image_dir, exist_ok=True)
                tactic_path = os.path.join(image_dir, f"{get_map_coordinates()}Tactic.png")
                screenshot.save(tactic_path)

        if player_starts:
            current_player_pos_list = [p for p,s in find_entities_by_image(ALLY_TEMPLATES, screenshot, {}, y_compensation_factor=1.8)]
            current_player_pos = current_player_pos_list[0] if current_player_pos_list else None

            best_cell = None
            min_dist_to_closest_monster = float('inf')

            for start_cell in [p for p in player_starts if not is_placement_cell_occupied(p, PLAYER_START_CELL_COLOR_RGB)]:
                if not combat_state.monster_positions:
                    best_cell = start_cell
                    break
                dist_to_closest = min(grid_instance.get_distance(start_cell, monster_pos) for monster_pos in combat_state.monster_positions)
                if dist_to_closest < min_dist_to_closest_monster:
                    min_dist_to_closest_monster = dist_to_closest
                    best_cell = start_cell

            if not best_cell and player_starts:
                best_cell = player_starts[0]

            best_start_cell = best_cell
            combat_state.initial_placement_pos = best_start_cell
            
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

    def read_ap_mp():
        import pytesseract
        pa_pos = POSITIONS_CONFIG.get("PA_OCR_POS")
        pm_pos = POSITIONS_CONFIG.get("PM_OCR_POS")
        
        if not pa_pos or not pm_pos:
            return ACTION_POINTS, MOVEMENT_POINTS

        for attempt in range(3):
            try:
                screenshot = ImageGrab.grab()
                
                def ocr_zone(pos):
                    zone = (pos[0] - 10, pos[1] - 10, pos[0] + 10, pos[1] + 10) # Zone réduite à 20x20
                    img = screenshot.crop(zone)
                    img_gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
                    img_thresh = cv2.threshold(img_gray, 200, 255, cv2.THRESH_BINARY_INV)[1]
                    text = pytesseract.image_to_string(img_thresh, config='--psm 7 -c tessedit_char_whitelist=0123456789')
                    return int(text.strip())

                pa = ocr_zone(pa_pos)
                pm = ocr_zone(pm_pos)
                log(f"[OCR] PA lus: {pa}, PM lus: {pm}")
                return pa, pm
            except (ValueError, TypeError, pytesseract.TesseractError) as e:
                log(f"[OCR] Erreur de lecture PA/PM (essai {attempt+1}/3): {e}. Nouvel essai...")
                time.sleep(0.2)
        
        log("[OCR] Échec de la lecture des PA/PM après plusieurs tentatives. Utilisation des valeurs par défaut.")
        return ACTION_POINTS, MOVEMENT_POINTS

    game_area = (0, 24, 1348, 808)

    # --- Boucle principale de combat ---
    combat_is_finished = False
    while not combat_is_finished:
        if check_and_close_fight_end_popup():
            combat_is_finished = True
            break
        if is_stop_requested(): return
        check_for_pause()

        log("[Combat Auto] En attente de notre tour...")
        if not is_my_turn():
            time.sleep(0.5)
            continue

        CURRENT_TURN += 1
        log("[Combat Auto] C'est notre tour !")
        current_pa, current_pm = read_ap_mp()
        combat_state.current_pa = current_pa
        combat_state.current_pm = current_pm
        log(f"[Combat Auto] Début du tour {CURRENT_TURN} avec {current_pa} PA et {current_pm} PM.")
        spell_casts = {}

        # --- Analyse du terrain ---
        if not combat_modes_checked:
            if not ensure_mode_is_on("Images/creature_mode_off.png", "Images/creature_mode_on.png", "Mode Créature"): # Appel unique
                log("[Combat Auto] Le mode créature n'a pas pu être activé. Passage du tour.")
                pyautogui.press('f1')
                time.sleep(2)
                continue
            combat_modes_checked = True
        pyautogui.moveTo(100, 100, duration=0.1)

        log("[Combat Auto] Analyse du terrain pour ce tour...")
        time.sleep(0.5)
        screenshot_pil = ImageGrab.grab(bbox=game_area)
        current_map_coords = get_map_coordinates()
        grid_instance.map_obstacles(screenshot=screenshot_pil, map_coords=current_map_coords)
        time.sleep(0.5)
        
        player_positions_with_scores = find_entities_by_image(ALLY_TEMPLATES, screenshot_pil, grid_instance.combat_overrides, y_compensation_factor=1.8)
        combat_state.player_positions = [pos for pos, score in player_positions_with_scores]
        
        if not combat_state.player_positions and CURRENT_TURN == 1 and combat_state.initial_placement_pos:
            log(f"[Combat Auto] Détection du joueur échouée, utilisation de la position de départ mémorisée : {combat_state.initial_placement_pos}")
            combat_state.player_positions = [combat_state.initial_placement_pos]

        monster_positions_with_scores = find_entities_by_image(ENEMY_TEMPLATES, screenshot_pil, grid_instance.combat_overrides, y_compensation_factor=1.5, exclude_rect=(1190, 671, 1275, 701))
        combat_state.monster_positions = [pos for pos, score in monster_positions_with_scores]

        
        if not combat_state.player_positions and is_my_turn(timeout=0.5):
            log("[Combat Auto] Impossible de localiser le joueur. Fin du tour forcée.")
            time.sleep(2)
            pyautogui.press('f1')
            continue

        player_pos = combat_state.player_positions[0]
        if player_pos in combat_state.monster_positions:
            combat_state.monster_positions.remove(player_pos)

        if player_pos not in grid_instance.walkable_cells:
            grid_instance.walkable_cells.add(player_pos)


        
        log(f"[Combat Auto] Joueur détecté à : {player_pos}")
        if not combat_state.monster_positions:
            player_score_str = f"(Score: {player_positions_with_scores[0][1]:.2f})" if player_positions_with_scores else ""
            log(f"[Combat Auto] Joueur détecté à : {player_pos} {player_score_str}")

            log("[Combat Auto] Plus aucun monstre détecté. Fin du combat probable.")
            break
        
        monsters_log = []
        for pos, score in monster_positions_with_scores:
            monsters_log.append(f"{pos} (Score: {score:.2f})")
        log(f"[Combat Auto] {len(combat_state.monster_positions)} monstres détectés à : [{', '.join(monsters_log)}]")

        
        if gui_app:
            log("[Combat Auto] Rafraîchissement de la grille de debug.")
            gui_app.after(0, gui_app.draw_map, True)

        # --- Boucle d'actions du tour ---
        fight_over = False
        while current_pa > 0 and not fight_over:
            if check_for_pause():
                log("[Combat Auto] Reprise après pause. Ré-évaluation de la situation.")
                break

            target = get_closest_entity(player_pos, combat_state.monster_positions)
            if not target:
                log("[Combat Auto] Plus de cibles après ré-analyse. Fin du tour.")
                break

            action_taken = False
            best_attack_spell = None

            # --- 1. Tenter d'attaquer depuis la position actuelle ---
            if current_pa > 0:
                for spell in SPELLS:
                    if spell.get('is_movement'): continue

                    casts_this_turn = spell_casts.get(spell['name'], 0)
                    max_casts = spell.get('casts_per_turn', 99)
                    if current_pa >= spell['cost'] and casts_this_turn < max_casts:
                        dist = grid_instance.get_distance(player_pos, target)
                        in_range = spell.get('range_min', 1) <= dist <= spell.get('range_max', 0)
                        has_los = (not spell.get('requires_los', True)) or grid_instance.has_line_of_sight(player_pos, target)

                        if in_range and has_los:
                            best_attack_spell = spell
                            break
                        else:
                            log(f"[Debug] Sort '{spell['name']}': Portée? {'Oui' if in_range else 'Non'} (dist: {dist}, portée: {spell.get('range_min', 1)}-{spell.get('range_max', 0)}). LdV? {'Oui' if has_los else 'Non'}. Lancers: {casts_this_turn}/{max_casts}.")
                
            if best_attack_spell:
                log(f"[Combat Auto] Lancement de '{best_attack_spell['name']}' sur {target}.")
                keyboard.press_and_release(best_attack_spell['key'])
                time.sleep(random.uniform(0.2, 0.5))
                pyautogui.click(grid_instance.cells[target])
                time.sleep(random.uniform(1.2, 1.5))
                current_pa -= best_attack_spell['cost']
                action_taken = True
                log(f"[Combat Auto] PA restants: {current_pa}, PM restants: {current_pm}")
                spell_casts[best_attack_spell['name']] = spell_casts.get(best_attack_spell['name'], 0) + 1
                time.sleep(1.0)
                pyautogui.moveTo(100, 100, duration=0.1)
                if check_and_close_fight_end_popup():
                    fight_over = True
                    combat_is_finished = True; break
                update_targets_after_action(game_area, grid_instance.combat_overrides, gui_app)

            if fight_over or check_and_close_fight_end_popup():
                fight_over = True
                combat_is_finished = True
                break

            if action_taken: continue

            # --- 2. Tenter de se rapprocher si aucune attaque n'était possible ---
            if not best_attack_spell and (current_pm > 0 or any(s.get('is_movement') for s in SPELLS)):
                min_attack_cost = min((s.get('cost', 99) for s in SPELLS if not s.get('is_movement')), default=99)
                if current_pa < min_attack_cost:
                    log("[Combat Auto] Pas assez de PA pour attaquer après un déplacement. Fin du tour.")
                    break

                log("[Combat Auto] Aucune attaque possible. Tentative de rapprochement...")

                # --- Logique de déplacement PM (prioritaire) ---
                if current_pm > 0:
                    log(f"[Debug Path] Position joueur: {player_pos} (marchable? {player_pos in grid_instance.walkable_cells})")
                    player_neighbors = grid_instance.get_neighbors(player_pos)
                    log(f"[Debug Path] Voisins marchables du joueur ({len(player_neighbors)}): {player_neighbors}")
                    log(f"[Debug Path] Position cible: {target} (marchable? {target in grid_instance.walkable_cells})")
                    log(f"[Debug Path] Cible transparente pour LdV? {target in grid_instance.los_transparent_cells}")
                    
                    path = grid_instance.find_path(player_pos, target)

                    log(f"[Debug Path] Chemin trouvé : {path}")
                    if path and len(path) > 1:
                        move_target_cell = grid_instance.get_farthest_walkable_cell(path, current_pm)
                        
                        dist_after_move = grid_instance.get_distance(move_target_cell, target)
                        can_attack_after_pm_move = any(
                            spell['range_min'] <= dist_after_move <= spell['range_max'] and not spell.get('is_movement')
                            for spell in SPELLS
                        )

                        if can_attack_after_pm_move:
                            log(f"[Combat Auto] Déplacement de {player_pos} vers {move_target_cell} pour se mettre à portée.")

                            if move_target_cell in grid_instance.cells:
                                pyautogui.click(grid_instance.cells[move_target_cell])
                                time.sleep(0.5)
                                
                                new_pos, move_success = verify_and_update_position(player_pos, move_target_cell, game_area, gui_app, grid_instance.combat_overrides)
                                
                                if move_success:
                                    pm_used = grid_instance.get_path_distance(player_pos, new_pos)
                                    current_pm -= pm_used
                                    player_pos = new_pos
                                    action_taken = True
                                    if gui_app:
                                        gui_app.after(0, gui_app.draw_map, True)
                                    continue
                                else:
                                    current_pm = 0
                            else:
                                log(f"[Combat Auto] Erreur: La case de destination {move_target_cell} est invalide.")
                        else:
                            log("[Combat Auto] Déplacement PM insuffisant pour attaquer. Évaluation du sort de mouvement.")
                
                if not action_taken:
                    # --- Logique de sort de Mouvement ---
                    movement_spell = next((s for s in SPELLS if s.get('is_movement')), None)
                    can_use_movement_spell = False
                    if movement_spell:
                        spell_name = movement_spell['name']
                        cooldown = movement_spell.get('cooldown', 0)
                        last_used = SPELL_COOLDOWNS.get(spell_name, -999)
                        
                        if current_pa >= movement_spell['cost'] and \
                           spell_casts.get(spell_name, 0) < movement_spell.get('casts_per_turn', 99) and \
                           CURRENT_TURN >= last_used + cooldown:
                            can_use_movement_spell = True

                    if can_use_movement_spell:
                        movement_spell_cost = movement_spell['cost']
                        if current_pa < movement_spell_cost:
                            log(f"[Combat Auto] Pas assez de PA pour utiliser un sort de mouvement (coût: {movement_spell_cost}).")
                            break

                        log(f"[Combat Auto] Évaluation de l'utilisation de '{movement_spell['name']}' pour se rapprocher.")
                        path_to_target = grid_instance.find_path(player_pos, target)
                        if path_to_target:
                            teleport_cell = grid_instance.get_farthest_walkable_cell(path_to_target, movement_spell['range_max'])
                            if teleport_cell and grid_instance.get_distance(player_pos, teleport_cell) > current_pm:
                                log(f"[Combat Auto] Lancement de '{movement_spell['name']}' vers la case {teleport_cell}.")
                                keyboard.press_and_release(movement_spell['key'])
                                time.sleep(random.uniform(0.2, 0.5))
                                pyautogui.click(grid_instance.cells[teleport_cell])
                                time.sleep(1.5) # Pause pour l'animation de téléportation
                                time.sleep(random.uniform(1.2, 1.5))
                                current_pa -= movement_spell['cost']
                                action_taken = True
                                log(f"[Combat Auto] PA restants: {current_pa}, PM restants: {current_pm}")
                                spell_casts[movement_spell['name']] = spell_casts.get(movement_spell['name'], 0) + 1
                                SPELL_COOLDOWNS[movement_spell['name']] = CURRENT_TURN                                
                                new_pos, move_success = verify_and_update_position(player_pos, teleport_cell, game_area, gui_app, grid_instance.combat_overrides)
                                if move_success:
                                    player_pos = new_pos
                                    if gui_app:
                                        gui_app.after(0, gui_app.draw_map, True)
                                    action_taken = True
                                    continue
                
                # --- Fin de la logique de Téléportation ---

            if not action_taken:
                log("[Combat Auto] Aucune action possible. Fin du tour.")
                if not check_and_close_fight_end_popup():
                    time.sleep(2)
                    end_turn_button_info = find_on_screen(END_TURN_BUTTON_IMAGE)
                    if end_turn_button_info:
                        log("[Combat Auto] Clic sur 'Passer son tour'.")
                        click_random_in_rect(*end_turn_button_info)
                        wait_for_next_turn()
                    else:
                        log("[Combat Auto] Bouton 'Passer son tour' non trouvé, appui sur F1 en fallback.")
                        time.sleep(2)
                        pyautogui.press('f1')
                else:
                    combat_is_finished = True

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