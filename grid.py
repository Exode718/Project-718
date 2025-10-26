import os
import pyautogui
import keyboard
from tkinter import messagebox
import heapq
from utils import log

class Grid:
    # --- Initialisation et Configuration ---
    def __init__(self):
        self.is_calibrated = False
        self.origin = (0, 0)
        self.u_vec = (0, 0)
        self.v_vec = (0, 0)
        self.cells = {}
        self.cell_width = 96.5
        self.cell_height = 49.5
        self.walkable_cells = set()
        self.los_transparent_cells = set()
        self.tactical_colors = [ (185, 206, 113), (171, 191, 105), (180, 183, 112), (167, 170, 104), (144, 168, 61), (137, 160, 57) ]
        self.load_config()

    def load_config(self):
        import json
        config_path = "config.json"

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

        self.is_calibrated = False
        log("[Grille] Aucune configuration de grille valide trouvée.")

    def _apply_config(self, grid_config):
        self.origin = tuple(grid_config['origin'])
        self.cell_width = grid_config.get('CELL_WIDTH', 96.5)
        self.cell_height = grid_config.get('CELL_HEIGHT', 49.5)

        self.u_vec = (self.cell_width / 2.0, self.cell_height / 2.0)
        self.v_vec = (-self.cell_width / 2.0, self.cell_height / 2.0)

        self.is_calibrated = True
        self._generate_grid_coordinates()

    def save_config(self):
        import json
        try:
            with open("config.json", 'r') as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            config = {}
        
        config['GRID'] = {
            'origin': self.origin, 
            'u_vec': self.u_vec, 
            'v_vec': self.v_vec,
            'CELL_WIDTH': self.cell_width,
            'CELL_HEIGHT': self.cell_height
        }
        
        with open("config.json", 'w') as f:
            json.dump(config, f, indent=4)
        log("[Grille] Configuration de la grille sauvegardée dans config.json.")

    def calibrate(self):
        messagebox.showinfo("Étalonnage de la grille", "Survolez le centre de n'importe quelle case (par exemple, la case (0,0)) et appuyez sur 'Entrée'.")
        self.origin = self._find_cell_center_from_point(self._wait_for_click())
        log(f"[Grille] Origine enregistrée : {self.origin}")

        self.u_vec = (self.cell_width / 2.0, self.cell_height / 2.0)
        self.v_vec = (-self.cell_width / 2.0, self.cell_height / 2.0)
        log(f"[Grille] Vecteur U (droite) calculé : {self.u_vec}, Vecteur V (bas-droite) calculé : {self.v_vec}")

        self.is_calibrated = True
        self.save_config()
        self._generate_grid_coordinates()
        messagebox.showinfo("Étalonnage Terminé", "La grille a été étalonnée avec succès.")

    # --- Fonctions Utilitaires Internes ---
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

    # --- Génération et Accès à la Grille ---
    def _generate_grid_coordinates(self):
        if not self.is_calibrated:
            return

        self.map_radius = 25
        self.cells.clear()
        for r in range(-self.map_radius, self.map_radius + 1):
            for q in range(-self.map_radius, self.map_radius + 1):
                x = self.origin[0] + q * self.u_vec[0] + r * self.v_vec[0]
                y = self.origin[1] + q * self.u_vec[1] + r * self.v_vec[1]
                self.cells[(q, r)] = (int(x), int(y))

    def get_cell_from_screen_coords(self, x, y):
        if not self.is_calibrated:
            return None

        import math
        closest_cell = None
        min_dist = float('inf')

        for cell_coord, screen_pos in self.cells.items():
            dist = math.hypot(x - screen_pos[0], y - screen_pos[1])
            if dist < min_dist:
                min_dist = dist
                closest_cell = cell_coord
        
        return closest_cell
    
    # --- Logique de Combat ---
    def map_obstacles(self, color_tolerance=15, screenshot=None):
        if not self.cells or not self.tactical_colors:
            log("[Grille] Impossible de mapper les obstacles : grille non étalonnée ou couleurs tactiques non définies.")
            return

        self.walkable_cells.clear()
        self.los_transparent_cells.clear()
        
        if screenshot is None:
            screenshot = pyautogui.screenshot()

        scan_moves = [(0, 0)]
        for i in range(1, 4): # Rayon de 3 pixels
            for dx in range(-i, i + 1):
                scan_moves.append((dx, i))
                scan_moves.append((dx, -i))
            for dy in range(-i + 1, i):
                scan_moves.append((i, dy))
                scan_moves.append((-i, dy))

        black_color_threshold = 30

        for cell_coord, screen_pos in self.cells.items():
            is_potentially_walkable = False
            is_hole = False

            for dx, dy in scan_moves:
                scan_x, scan_y = screen_pos[0] + dx, screen_pos[1] + dy
                if not (0 <= scan_x < screenshot.width and 0 <= scan_y < screenshot.height):
                    continue
                try:
                    pixel_color = screenshot.getpixel((scan_x, scan_y))
                    
                    if sum(pixel_color) < black_color_threshold:
                        is_hole = True
                    
                    if sum(pixel_color) >= 50:
                        for tac_color in self.tactical_colors:
                            if all(abs(pixel_color[i] - tac_color[i]) <= color_tolerance for i in range(3)):
                                is_potentially_walkable = True
                                break
                except IndexError:
                    pass
            
            if is_hole:
                self.los_transparent_cells.add(cell_coord)
            elif is_potentially_walkable:
                self.walkable_cells.add(cell_coord) # Une case marchable est forcément transparente
                self.los_transparent_cells.add(cell_coord)

        log(f"[Grille] Cartographie terminée : {len(self.walkable_cells)} cases marchables trouvées.")

    def get_neighbors(self, cell):
        q, r = cell
        neighbors = [
            (q + 1, r), (q - 1, r), (q, r + 1), (q, r - 1),
            (q + 1, r - 1), (q - 1, r + 1)
        ]
        return [n for n in neighbors if n in self.walkable_cells]

    def get_distance(self, cell1, cell2):
        if cell1 == cell2:
            return 0
        q1, r1 = cell1
        q2, r2 = cell2
        return abs(q1 - q2) + abs(r1 - r2)

    def get_path_distance(self, start, end):
        path = self.find_path(start, end)
        if path and len(path) > 1:
            return len(path) - 1
        elif path and len(path) == 1:
            return 0
        return float('inf')

    def get_move_cost(self, cell1, cell2):
        q1, r1 = cell1
        q2, r2 = cell2
        return abs(q1 - q2) + abs(r1 - r2)

    def get_farthest_walkable_cell(self, path, max_cost):
        if not path or len(path) < 2:
            return path[0] if path else None

        current_cost = 0
        for i in range(len(path) - 1):
            cost_to_next = self.get_move_cost(path[i], path[i+1])
            if current_cost + cost_to_next > max_cost:
                return path[i]
            current_cost += cost_to_next
        
        return path[-1]

    # --- Calculs pour la Grille Hexagonale ---
    def _axial_to_cube(self, cell):
        q, r = cell
        return (q, r, -q - r)

    def _cube_round(self, cube):
        rx, ry, rz = round(cube[0]), round(cube[1]), round(cube[2])
        x_diff, y_diff, z_diff = abs(rx - cube[0]), abs(ry - cube[1]), abs(rz - cube[2])
        if x_diff > y_diff and x_diff > z_diff:
            rx = -ry - rz
        elif y_diff > z_diff:
            ry = -rx - rz
        else:
            rz = -rx - ry
        return (int(rx), int(ry), int(rz))

    def _cube_to_axial(self, cube):
        return (cube[0], cube[1])

    def has_line_of_sight(self, start, end):
        if start == end:
            return True
            
        n = self.get_distance(start, end)
        if n == 0: return True

        start_cube = self._axial_to_cube(start)
        end_cube = self._axial_to_cube(end)
        
        line_cells = []
        for i in range(1, n):
            interp_cube = tuple(start_cube[j] + (end_cube[j] - start_cube[j]) * i / n for j in range(3))
            line_cells.append(self._cube_to_axial(self._cube_round(interp_cube)))
            
        for cell in line_cells:
            if cell != end and cell not in self.los_transparent_cells:
                log(f"[Debug LdV] Ligne de vue de {start} à {end} bloquée par {cell}.")
                return False
        return True

    def find_path(self, start, end):
        if start not in self.walkable_cells:
            return None

        frontier = [(0, start)]
        came_from = {start: None}
        cost_so_far = {start: 0}

        while frontier:
            current_priority, current = heapq.heappop(frontier)

            if current == end and current in self.walkable_cells:
                break
            
            for next_cell in self.get_neighbors(current):
                new_cost = cost_so_far[current] + self.get_move_cost(current, next_cell)
                if next_cell not in cost_so_far or new_cost < cost_so_far[next_cell]:
                    cost_so_far[next_cell] = new_cost
                    priority = new_cost + self.get_distance(end, next_cell)
                    heapq.heappush(frontier, (priority, next_cell))
                    came_from[next_cell] = current

        closest_cell_to_target = start
        min_dist_to_target = self.get_distance(start, end)

        for cell in cost_so_far:
            dist = self.get_distance(cell, end)
            if dist < min_dist_to_target:
                min_dist_to_target = dist
                closest_cell_to_target = cell

        if closest_cell_to_target is None:
            return None

        path = []
        current = closest_cell_to_target
        while current is not None:
            path.append(current)
            current = came_from.get(current)
        
        return path[::-1] if path else None

grid_instance = Grid()