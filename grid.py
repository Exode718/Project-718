import os
import math
import pyautogui
import keyboard
from tkinter import messagebox
import heapq
from utils import log

class Grid:
    def __init__(self):
        self.is_calibrated = False
        self.origin = (0, 0)
        self.u_vec = (0, 0)
        self.v_vec = (0, 0)
        self.cells = {}
        self.walkable_cells = set()
        self.los_transparent_cells = set()
        self.tactical_colors = [
            (185, 206, 113),  # #B9CE71 (Case marchable)
            (171, 191, 105),  # #ABBF69 (Case marchable)
            (180, 183, 112),  # #B4B770 (Case marchable)
            (167, 170, 104),  # #A7AA68 (Case marchable)
            (144, 168, 61),   # #90A83D (Sortie sur case marchable)
            (137, 160, 57),   # #89A039 (Sortie sur case marchable, autre teinte)
        ]
        self.load_config()

    def load_config(self):
        import json
        config_path = "config.json"
        old_config_path = "grid_config.json"

        if os.path.exists("config.json"):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                grid_config = config.get('GRID')
                if grid_config and 'origin' in grid_config:
                    self._apply_config(grid_config)
                    log("[Grille] Configuration de la grille chargée depuis config.json.")
                    return
            except Exception as e:
                log(f"[Grille] Erreur lors du chargement de la configuration : {e}")
        
        # --- Migration de l'ancienne configuration ---
        if os.path.exists(old_config_path):
            log(f"[Grille] Ancien fichier '{old_config_path}' trouvé. Tentative de migration...")
            try:
                with open(old_config_path, 'r') as f:
                    old_grid_config = json.load(f)
                self._apply_config(old_grid_config)
                self.save_config()
                os.remove(old_config_path)
                log(f"[Grille] Migration réussie. '{old_config_path}' a été supprimé.")
                return
            except Exception as e:
                log(f"[Grille] Échec de la migration : {e}")

        self.is_calibrated = False
        log("[Grille] Aucune configuration de grille valide trouvée.")

    def _apply_config(self, grid_config):
        self.origin = tuple(grid_config['origin'])
        self.u_vec = tuple(grid_config['u_vec'])
        self.v_vec = tuple(grid_config['v_vec'])
        self.is_calibrated = True
        self._generate_grid_coordinates()

    def save_config(self):
        import json
        try:
            with open("config.json", 'r') as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            config = {}
        
        config['GRID'] = {'origin': self.origin, 'u_vec': self.u_vec, 'v_vec': self.v_vec}
        
        with open("config.json", 'w') as f:
            json.dump(config, f, indent=4)
        log("[Grille] Configuration de la grille sauvegardée dans config.json.")

    def calibrate(self):
        messagebox.showinfo("Étalonnage - Étape 1/3", "Survolez le centre d'une case (ex: votre case de départ) et appuyez sur 'Entrée'.")
        self.origin = self._find_cell_center_from_point(self._wait_for_click())
        log(f"[Grille] Origine enregistrée : {self.origin}")

        messagebox.showinfo("Étalonnage - Étape 2/3", "Survolez le centre de la case à DROITE de la précédente et appuyez sur 'Entrée'.")
        p_right = self._find_cell_center_from_point(self._wait_for_click())
        self.u_vec = (p_right[0] - self.origin[0], p_right[1] - self.origin[1])

        messagebox.showinfo("Étalonnage - Étape 3/3", "Survolez le centre de la case en BAS à DROITE de la première et appuyez sur 'Entrée'.")
        p_bottom_right = self._find_cell_center_from_point(self._wait_for_click())
        self.v_vec = (p_bottom_right[0] - self.origin[0], p_bottom_right[1] - self.origin[1])
        log(f"[Grille] Vecteur U (droite) calculé : {self.u_vec}, Vecteur V (bas-droite) calculé : {self.v_vec}")

        self.is_calibrated = True
        self.save_config()
        self._generate_grid_coordinates()
        messagebox.showinfo("Étalonnage Terminé", "La grille a été étalonnée avec succès.")

    def _colors_are_similar(self, c1, c2, tolerance=10):
        return c1 is not None and c2 is not None and all(abs(c1[i] - c2[i]) <= tolerance for i in range(3))

    def _wait_for_click(self):
        import time
        while True:
            if keyboard.is_pressed('enter'):
                break
            time.sleep(0.01)
        return pyautogui.position()

    def _find_cell_center_from_point(self, start_pos):
        screenshot = pyautogui.screenshot()
        if not (0 <= start_pos[0] < screenshot.width and 0 <= start_pos[1] < screenshot.height):
            raise ValueError(f"Le point de départ {start_pos} est hors de l'écran.")
        start_color_tuple = screenshot.getpixel(start_pos)
        x_start, y_start = start_pos
        
        search_area = 200
        min_x, max_x = x_start, x_start
        min_y, max_y = y_start, y_start
        
        # Balayage horizontal
        for x in range(x_start, x_start - search_area, -1):
            if not self._colors_are_similar(screenshot.getpixel((x, y_start)), start_color_tuple, 10): break
            min_x = x
        for x in range(x_start, x_start + search_area):
            if not self._colors_are_similar(screenshot.getpixel((x, y_start)), start_color_tuple, 10): break
            max_x = x

        # Balayage vertical
        for y in range(y_start, y_start - search_area, -1):
            if not self._colors_are_similar(screenshot.getpixel((x_start, y)), start_color_tuple, 10): break
            min_y = y
        for y in range(y_start, y_start + search_area): 
            if not self._colors_are_similar(screenshot.getpixel((x_start, y)), start_color_tuple, 10): break
            max_y = y

        return ((min_x + max_x) // 2, (min_y + max_y) // 2)

    def _generate_grid_coordinates(self):
        if not self.is_calibrated:
            return

        self.map_radius = 25
        self.cells.clear()
        for r in range(-self.map_radius, self.map_radius + 1):
            for q in range(-self.map_radius, self.map_radius + 1):
                if abs(q + r) <= self.map_radius:
                    x = self.origin[0] + q * self.u_vec[0] + r * self.v_vec[0]
                    y = self.origin[1] + q * self.u_vec[1] + r * self.v_vec[1]
                    self.cells[(q, r)] = (int(x), int(y))

    def get_cell_from_screen_coords(self, x, y):
        if not self.is_calibrated:
            return None

        closest_cell = None
        min_dist = float('inf')

        for cell_coord, screen_pos in self.cells.items():
            dist = math.hypot(x - screen_pos[0], y - screen_pos[1])
            if dist < min_dist:
                min_dist = dist
                closest_cell = cell_coord
        
        return closest_cell
    
    def map_obstacles(self, color_tolerance=15, screenshot=None):
        if not self.cells or not self.tactical_colors:
            log("[Grille] Impossible de mapper les obstacles : grille non étalonnée ou couleurs tactiques non définies.")
            return

        self.walkable_cells.clear()
        self.los_transparent_cells.clear()
        
        if screenshot is None:
            screenshot = pyautogui.screenshot()

        # --- Scan en spirale pour la robustesse ---
        spiral_moves = [(0, 0)]
        for i in range(1, 4): # Rayon de 3 pixels
            for dx in range(-i, i + 1):
                spiral_moves.append((dx, i))
                spiral_moves.append((dx, -i))
            for dy in range(-i + 1, i):
                spiral_moves.append((i, dy))
                spiral_moves.append((-i, dy))

        black_color_threshold = 30

        for cell_coord, screen_pos in self.cells.items():
            found_walkable = False

            # --- Étape 1: Chercher une couleur de case marchable (tactique) ---
            for dx, dy in spiral_moves:
                scan_x, scan_y = screen_pos[0] + dx, screen_pos[1] + dy
                if not (0 <= scan_x < screenshot.width and 0 <= scan_y < screenshot.height):
                    continue
                pixel_color = screenshot.getpixel((scan_x, scan_y))
                if sum(pixel_color) < 50: # Ignorer les pixels très sombres
                    continue
                for tac_color in self.tactical_colors:
                    if all(abs(pixel_color[i] - tac_color[i]) <= color_tolerance for i in range(3)):
                        self.walkable_cells.add(cell_coord)
                        self.los_transparent_cells.add(cell_coord)
                        found_walkable = True
                        break
                if found_walkable:
                    break
            
            # --- Étape 2: Si non marchable, vérifier si elle bloque la Ligne de Vue (LOS) ---
            if not found_walkable:
                has_black = False
                for dx, dy in spiral_moves:
                    scan_x, scan_y = screen_pos[0] + dx, screen_pos[1] + dy
                    if not (0 <= scan_x < screenshot.width and 0 <= scan_y < screenshot.height):
                        continue
                    pixel_color = screenshot.getpixel((scan_x, scan_y))
                    if sum(pixel_color) < black_color_threshold:
                        self.los_transparent_cells.add(cell_coord)
                        has_black = True
                        break

        log(f"[Grille] Cartographie terminée : {len(self.walkable_cells)} cases marchables trouvées.")

    def get_neighbors(self, cell):
        q, r = cell
        neighbors = [
            (q + 1, r), (q - 1, r), (q, r + 1), (q, r - 1),
            (q + 1, r - 1), (q - 1, r + 1)
        ]
        return [n for n in neighbors if n in self.walkable_cells]

    def get_distance(self, cell1, cell2):
        return (abs(cell1[0] - cell2[0]) 
              + abs(cell1[0] + cell1[1] - cell2[0] - cell2[1]) 
              + abs(cell1[1] - cell2[1])) / 2

    def has_line_of_sight(self, start, end):
        if start not in self.walkable_cells or end not in self.walkable_cells:
            return False

        line_cells = []
        x0, y0 = start
        x1, y1 = end
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            line_cells.append((x0, y0))
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
        
        for cell in line_cells[1:-1]:
            if cell not in self.los_transparent_cells:
                return False
        return True

    def find_path(self, start, end):
        if start not in self.walkable_cells or end not in self.walkable_cells:
            return None

        frontier = [(0, start)]
        came_from = {start: None}
        cost_so_far = {start: 0}

        while frontier:
            _, current = heapq.heappop(frontier)

            if current == end:
                path = []
                while current is not None:
                    path.append(current)
                    current = came_from[current]
                return path[::-1]

            for next_cell in self.get_neighbors(current):
                new_cost = cost_so_far[current] + 1
                if next_cell not in cost_so_far or new_cost < cost_so_far[next_cell]:
                    cost_so_far[next_cell] = new_cost
                    priority = new_cost + self.get_distance(end, next_cell)
                    heapq.heappush(frontier, (priority, next_cell))
        return None

grid_instance = Grid()