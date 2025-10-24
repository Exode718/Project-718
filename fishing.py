import pyautogui
import json
import time
import math
import random
import cv2
import numpy as np
import os
from PIL import ImageGrab, Image
from utils import log, is_red_present, check_and_close_levelup_popup, is_fight_started, check_for_pause, is_stop_requested
from fight import handle_fight

with open("config.json", "r") as f:
    CONFIG = json.load(f)

PECHER_THRESHOLD = CONFIG["PECHER_THRESHOLD"]
FISHING_DELAY_MIN = CONFIG["FISHING_DELAY_MIN"]
FISHING_DELAY_MAX = CONFIG["FISHING_DELAY_MAX"]
FISHING_START_DELAY = CONFIG["FISHING_START_DELAY"]
CURSOR_RESET_DURATION = CONFIG["CURSOR_RESET_DURATION"]
FLOTTEUR_TIMEOUT = CONFIG["FLOTTEUR_TIMEOUT"]
FLOTTEUR_CHECK_INTERVAL = CONFIG["FLOTTEUR_CHECK_INTERVAL"]

MAP_FOLDER = "Maps"
IMAGE_FOLDER = "Images"
PECHER_IMAGE = os.path.join(IMAGE_FOLDER, "button_fish.png")

move_request_direction = None

def set_move_request(direction):
    global move_request_direction
    move_request_direction = direction

def get_move_request():
    global move_request_direction
    return move_request_direction


def capture_zone(x, y, size=10):
    box = (x - size, y - size, x + size, y + size)
    img = ImageGrab.grab(bbox=box)
    return np.array(img)

def detect_change_raw(before, after):
    return not np.array_equal(before, after)

def click_with_offset(x, y, offset_range=5, duration=0.05):
    offset_x = random.randint(-offset_range, offset_range)
    offset_y = random.randint(-offset_range, offset_range)
    pyautogui.moveTo(x + offset_x, y + offset_y, duration=duration)
    pyautogui.click()

def reset_cursor_to_case(x, y):
    pyautogui.moveTo(x, y, duration=CURSOR_RESET_DURATION)

def find_and_click_pecher_button(template_path=PECHER_IMAGE, threshold=PECHER_THRESHOLD, duration=0.05):
    screen = ImageGrab.grab()
    screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_BGR2GRAY)
    template = cv2.imread(template_path, 0)
    w, h = template.shape[::-1]
    res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    for pt in zip(*loc[::-1]):
        pyautogui.moveTo(pt[0] + w // 2, pt[1] + h // 2, duration=duration)
        pyautogui.click()
        return True
    return False

def wait_for_fishing_cycle_color(x, y, min_delay=FISHING_DELAY_MIN, max_delay=FISHING_DELAY_MAX, timeout=FLOTTEUR_TIMEOUT):
    start = time.time()
    while time.time() - start < timeout:
        if is_stop_requested():
            log("Arrêt d'urgence pendant la détection du flotteur.")
            return False
        if is_red_present(x, y):
            break
        time.sleep(FLOTTEUR_CHECK_INTERVAL)

    log(f"Pêche en cours... Attente d'au moins {min_delay}s.")
    time.sleep(min_delay)
    start = time.time()
    while time.time() - start < timeout:
        if is_stop_requested():
            log("Arrêt d'urgence pendant la pêche.")
            return False
        if not is_red_present(x, y):
            log("Reprise du scan.")
            return True
        time.sleep(FLOTTEUR_CHECK_INTERVAL)

    delay = random.uniform(min_delay, max_delay)
    log(f"Reprise du scan (timeout). Attente forcée de {delay:.2f}s.")
    time.sleep(delay)
    return False

def run_fishing_cycle(map_coords, map_data, gui_app, target_direction):
    check_for_pause()
    global move_request_direction
    move_request_direction = None

    cells = map_data.get("cells", [])
    exits = map_data.get("exits", {})

    if target_direction and target_direction in exits:
        log(f"Optimisation du trajet vers la sortie '{target_direction}'.")
        exit_pos = exits[target_direction]
        exit_x, exit_y = exit_pos['x'], exit_pos['y']

        def distance_to_exit(cell):
            return math.sqrt((cell['x'] - exit_x)**2 + (cell['y'] - exit_y)**2)

        cells.sort(key=distance_to_exit, reverse=True)
    else:
        log("Aucune sortie planifiée, parcours des points dans l'ordre du fichier.")

    if is_stop_requested() or move_request_direction:
        return False

    for cell in cells:
        if is_stop_requested() or move_request_direction:
            log("Arrêt d'urgence demandé. Interruption immédiate.")
            break
        
        if is_fight_started():
            log("COMBAT DÉTECTÉ (agression) ! Lancement de la gestion du combat.")
            auto_combat_enabled = gui_app.auto_combat_var.get()
            handle_fight(auto_combat_enabled, gui_app)
            log("Reprise du cycle de pêche après le combat. Redémarrage du scan sur la carte actuelle.")
            return run_fishing_cycle(map_coords, map_data, gui_app, target_direction)

        check_for_pause()

        x, y = cell["x"], cell["y"]

        gui_app.after(0, gui_app.highlight_spot, cell, "orange")

        before = capture_zone(x, y)
        pyautogui.moveTo(x, y, duration=0.05)
        time.sleep(0.05)
        after = capture_zone(x, y)

        is_fishing = False
        if detect_change_raw(before, after):
            log(f"Poisson trouvé à ({x}, {y})")
            click_with_offset(x, y, duration=0.05)

            if find_and_click_pecher_button():
                reset_cursor_to_case(x, y)
                gui_app.after(0, gui_app.highlight_spot, cell, "lightgreen") # Changement de couleur immédiat
                
                is_fishing = wait_for_fishing_cycle_color(x, y, min_delay=FISHING_START_DELAY)
                
                check_and_close_levelup_popup() # On vérifie les popups même si la pêche a échoué
                if is_fight_started():
                    auto_combat_enabled = gui_app.auto_combat_var.get()
                    handle_fight(auto_combat_enabled, gui_app)
                    log("Reprise du cycle de pêche après le combat. Redémarrage du scan sur la carte actuelle.")
                    return run_fishing_cycle(map_coords, map_data, gui_app, target_direction)
            else:
                log("Bouton 'Pêcher' non trouvé, passage au suivant.")

        if is_fishing:
            gui_app.after(0, gui_app.highlight_spot, cell, "orange")
        time.sleep(random.uniform(0.05, 0.1))
    
    return not (is_stop_requested() or move_request_direction)
