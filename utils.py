import time
import numpy as np
import cv2
from PIL import ImageGrab
from datetime import datetime
import pyautogui

RED_RGB = (204, 0, 0)
RED_TOLERANCE = 0

# --- Global State Management ---
stop_requested = False
is_paused = False

def set_pause_state(state: bool):
    global is_paused
    is_paused = state

def set_stop_state(state: bool):
    global stop_requested
    stop_requested = state

def is_stop_requested():
    return stop_requested

def check_for_pause():
    was_paused = False
    while is_paused:
        was_paused = True
        time.sleep(0.1)
    return was_paused

log_callback = None

def set_log_callback(callback):
    global log_callback
    log_callback = callback

def log(msg):
    formatted_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(formatted_msg)
    if log_callback:
        log_callback(formatted_msg)

def is_red_present(x, y, size=10, target_color=RED_RGB, tolerance=30, min_pixels=5):
    box = (x - size, y - size, x + size, y + size)
    img = ImageGrab.grab(bbox=box)
    img_np = np.array(img)
    diff = np.abs(img_np - target_color)
    mask = np.all(diff <= tolerance, axis=-1)
    count = np.count_nonzero(mask)
    return count >= min_pixels

def check_and_close_levelup_popup(template_path="Images/button_ok.png", threshold=0.8):
    try:
        template = cv2.imread(template_path, 0)
        if template is None:
            return False
        w, h = template.shape[::-1]
        screen = ImageGrab.grab()
        screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        for pt in zip(*loc[::-1]):
            pyautogui.moveTo(pt[0] + w // 2, pt[1] + h // 2, duration=0.2)
            pyautogui.click()
            log("Popup métier détecté : clic sur OK.")
            return True
        return False
    except Exception as e:
        log(f"Erreur lors de la recherche du bouton '{template_path}': {e}")
        return False

def check_and_close_fight_end_popup(template_path="Images/button_X.png", threshold=0.8):
    try:
        template = cv2.imread(template_path, 0)
        if template is None: return False
        w, h = template.shape[::-1]
        screen = ImageGrab.grab()
        screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        if len(loc[0]) > 0:
            pyautogui.moveTo(loc[1][0] + w // 2, loc[0][0] + h // 2, duration=0.2)
            pyautogui.click()
            log("Fin de combat détectée : clic sur le bouton pour fermer.")
            return True
    except Exception as e:
        log(f"Erreur lors de la recherche du bouton '{template_path}': {e}")
        return False

def is_fight_started(template_path="Images/button_ready.png", threshold=0.8, checks=2, interval=0.1):
    try:
        template = cv2.imread(template_path, 0)
        if template is None:
            return False
        for i in range(checks):
            screen = ImageGrab.grab()
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)
            res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
            if np.any(res >= threshold):
                return True
            if i < checks - 1:
                time.sleep(interval)
        return False
    except Exception as e:
        log(f"Erreur lors de la détection du début de combat : {e}")
        return False
