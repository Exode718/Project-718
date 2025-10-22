import os
import math
import pyautogui
import keyboard
from tkinter import messagebox
import heapq
from utils import log

GRID_CONFIG_PATH = "grid_config.json"
class Grid:
    def __init__(self):
        self.is_calibrated = False
        self.origin = (0, 0)
        self.u_vec = (0, 0)
        self.v_vec = (0, 0)
        self.cells = {}
        self.walkable_cells = set()
        self.tactical_colors = [
            (185, 206, 113),  # #B9CE71 (Case marchable standard)
            (171, 191, 105),  # #ABBF69 (Case marchable standard, autre teinte)
            (144, 168, 61),   # #90A83D (Icône de sortie sur case marchable)
            (137, 160, 57)    # #89A039 (Icône de sortie sur case marchable, autre teinte)
        ]
        self.load_config()

    def load_config(self):
        """Charge la configuration de la grille depuis un fichier JSON."""
        import json
        if os.path.exists(GRID_CONFIG_PATH):
            try:
                with open(GRID_CONFIG_PATH, 'r') as f:
                    config = json.load(f)
                    self.origin = tuple(config['origin'])
                    self.u_vec = tuple(config['u_vec'])
                    self.v_vec = tuple(config['v_vec'])
                    self.is_calibrated = True
                    self._generate_grid_coordinates()
                    log("[Grille] Configuration de la grille chargée.")
            except Exception as e:
                log(f"[Grille] Erreur lors du chargement de la configuration : {e}")
                self.is_calibrated = False

    def save_config(self):
        """Sauvegarde la configuration actuelle de la grille."""
        import json
        config = {
            'origin': self.origin,
            'u_vec': self.u_vec,
            'v_vec': self.v_vec,
        }
        with open(GRID_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=4)
        log("[Grille] Configuration de la grille sauvegardée.")

    def calibrate(self):
        """Lance le processus d'étalonnage manuel simple à 3 clics."""
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
        """Fonction utilitaire pour comparer la similarité des couleurs."""
        return c1 is not None and c2 is not None and all(abs(c1[i] - c2[i]) <= tolerance for i in range(3))

    def _wait_for_click(self):
        """Attend que l'utilisateur appuie sur 'Entrée' et retourne la position de la souris."""
        import time
        while True:
            if keyboard.is_pressed('enter'):
                break
            time.sleep(0.01)
        return pyautogui.position()

    def _find_cell_center_from_point(self, start_pos):
        """Trouve le centre géométrique d'une case à partir d'un point situé à l'intérieur."""
        screenshot = pyautogui.screenshot()
        if not (0 <= start_pos[0] < screenshot.width and 0 <= start_pos[1] < screenshot.height):
            raise ValueError(f"Le point de départ {start_pos} est hors de l'écran.")
        start_color_tuple = screenshot.getpixel(start_pos)
        x_start, y_start = start_pos
        
        search_area = 200
        min_x, max_x = x_start, x_start
        min_y, max_y = y_start, y_start
        
        # Balayage horizontal
        # Gauche
        for x in range(x_start, x_start - search_area, -1):
            if not self._colors_are_similar(screenshot.getpixel((x, y_start)), start_color_tuple, 10): break
            min_x = x
        # Droite
        for x in range(x_start, x_start + search_area): # No change
            if not self._colors_are_similar(screenshot.getpixel((x, y_start)), start_color_tuple, 10): break
            max_x = x

        # Balayage vertical
        # Haut
        for y in range(y_start, y_start - search_area, -1): # Utilise x_start pour le balayage vertical
            if not self._colors_are_similar(screenshot.getpixel((x_start, y)), start_color_tuple, 10): break
            min_y = y
        # Bas
        for y in range(y_start, y_start + search_area): # Utilise x_start pour le balayage vertical
            if not self._colors_are_similar(screenshot.getpixel((x_start, y)), start_color_tuple, 10): break
            max_y = y

        # Le centre est la moyenne des extrêmes
        return ((min_x + max_x) // 2, (min_y + max_y) // 2)

    def _generate_grid_coordinates(self):
        """Génère les coordonnées écran pour chaque case de la grille."""
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
        """Trouve la case la plus proche d'une coordonnée écran."""
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
        """Analyse la grille pour identifier les cases marchables et les obstacles en mode tactique."""
        if not self.cells or not self.tactical_colors:
            log("[Grille] Impossible de mapper les obstacles : grille non étalonnée ou couleurs tactiques non définies.")
            return

        self.walkable_cells.clear()
        
        if screenshot is None:
            screenshot = pyautogui.screenshot()

        for cell_coord, screen_pos in self.cells.items():
            if 0 <= screen_pos[0] < screenshot.width and 0 <= screen_pos[1] < screenshot.height:
                pixel_color = screenshot.getpixel(screen_pos)
            else:
                continue

            if sum(pixel_color) < 50:
                continue

            for tac_color in self.tactical_colors:
                if all(abs(pixel_color[i] - tac_color[i]) <= color_tolerance for i in range(3)):
                    self.walkable_cells.add(cell_coord)
                    break
        log(f"[Grille] Cartographie terminée : {len(self.walkable_cells)} cases marchables trouvées.")

    def get_neighbors(self, cell):
        """Retourne les voisins marchables d'une case."""
        q, r = cell
        neighbors = [
            (q + 1, r), (q - 1, r), (q, r + 1), (q, r - 1),
            (q + 1, r - 1), (q - 1, r + 1)
        ]
        return [n for n in neighbors if n in self.walkable_cells]

    def get_distance(self, cell1, cell2):
        """Calcule la distance de grille (Manhattan) entre deux cases."""
        return (abs(cell1[0] - cell2[0]) 
              + abs(cell1[0] + cell1[1] - cell2[0] - cell2[1]) 
              + abs(cell1[1] - cell2[1])) / 2

    def has_line_of_sight(self, start, end):
        """Vérifie la ligne de vue entre deux cases en utilisant l'algorithme de Bresenham."""
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
            if cell not in self.walkable_cells:
                return False
        return True

    def find_path(self, start, end):
        """Trouve le chemin le plus court en utilisant l'algorithme A*."""
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