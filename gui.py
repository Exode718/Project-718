import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk
from ctypes import windll, byref, c_int
import pyautogui
import threading
import queue
import time
import json
import keyboard
from PIL import Image, ImageTk
import os
from main import main_bot_logic, request_map_change, get_map_coordinates, load_map_data, create_map_interactively, find_exit_with_fallback, wait_for_map_change, get_next_map_coords
from utils import set_pause_state, set_stop_state, is_stop_requested
from grid import grid_instance


class GuiApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Dofus Assistant")
        self.geometry("565x375")
        try:
            self.iconbitmap('icon.ico')
        except tk.TclError:
            print("[GUI] Fichier 'icon.ico' introuvable. L'icône par défaut est utilisée.")
        self.resizable(False, False)
        self.attributes('-topmost', True)

        # --- Thème sombre amélioré ---
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        dark_bg = '#2E2E2E'
        light_grey_bg = '#424242'
        button_bg = '#000000'
        button_active_bg = '#333333'
        text_color = 'white'

        self.configure(bg=dark_bg)
        self.style.configure('TFrame', background=dark_bg)
        self.style.configure('TButton', background=button_bg, foreground=text_color, borderwidth=1, font=('calibri', 10, 'bold'))
        self.style.map('TButton', background=[('active', button_active_bg)])
        self.style.configure('TLabel', background=dark_bg, foreground=text_color)
        self.style.configure('TNotebook', background=dark_bg, borderwidth=0)
        self.style.configure('TNotebook.Tab', background=light_grey_bg, foreground=text_color, padding=[10, 5])
        self.style.map('TNotebook.Tab', background=[('selected', dark_bg)], padding=[('selected', [10, 5])])

        # On force la barre de titre de Windows en mode sombre pour le style
        self.update_idletasks()
        windll.dwmapi.DwmSetWindowAttribute(windll.user32.GetParent(self.winfo_id()), 20, byref(c_int(2)), 4)

        # --- Onglets ---
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        self.bot_tab = ttk.Frame(self.notebook, style='TFrame')
        self.settings_tab = ttk.Frame(self.notebook, style='TFrame')
        self.combat_tab = ttk.Frame(self.notebook, style='TFrame')
        self.path_tab = ttk.Frame(self.notebook, style='TFrame')
        self.map_tab = ttk.Frame(self.notebook, style='TFrame')
        self.debug_tab = ttk.Frame(self.notebook, style='TFrame')

        self.notebook.add(self.bot_tab, text='Bot')
        self.notebook.add(self.map_tab, text='Map')
        self.notebook.add(self.path_tab, text='Déplacement')
        self.notebook.add(self.combat_tab, text='Combat')
        self.notebook.add(self.debug_tab, text='Debug')
        self.notebook.add(self.settings_tab, text='Configuration')

        # --- Widgets ---
        control_frame = ttk.Frame(self.bot_tab)
        control_frame.pack(side=tk.BOTTOM, pady=(4, 10), fill=tk.X, padx=5)
        control_frame.columnconfigure(3, weight=1)

        self.start_button = ttk.Button(control_frame, text="Démarrer", command=self.start_bot)
        self.start_button.grid(row=0, column=0, padx=5)

        self.pause_button = ttk.Button(control_frame, text="Pause/Reprise", command=self.toggle_pause_bot, state='disabled')
        self.pause_button.grid(row=0, column=1, padx=5)

        self.reload_button = ttk.Button(control_frame, text="Recharger", command=self.reload_bot, state='disabled')
        self.reload_button.grid(row=0, column=2, padx=(5, 15))

        # --- Case à cocher pour le combat auto ---
        self.auto_combat_var = tk.BooleanVar()
        self.auto_combat_check = ttk.Checkbutton(control_frame, text="Combat Auto", variable=self.auto_combat_var)
        self.auto_combat_check.grid(row=0, column=3, padx=5)
        
        control_frame.columnconfigure(4, weight=1)
        self.status_label = ttk.Label(control_frame, text="Statut : Prêt", anchor='e')
        self.status_label.grid(row=0, column=4, sticky='e', padx=5)


        self.log_widget = scrolledtext.ScrolledText(self.bot_tab, state='disabled', bg=light_grey_bg, fg=text_color, font=("Consolas", 9), relief='flat')
        self.log_widget.pack(pady=5, padx=5, fill=tk.BOTH, expand=True)

        # --- Widgets de l'onglet Configuration ---
        self.key_vars = {}
        keybind_definitions = [
            ("PAUSE_RESUME", "Touche Pause/Reprise"),
            ("ADD_SPOT", "Ajouter Spot Pêche"),
            ("EXIT_UP_LEFT", "Sortie Haut-Gauche"),
            ("EXIT_UP", "Sortie Haut"),
            ("EXIT_UP_RIGHT", "Sortie Haut-Droite"),
            ("EXIT_LEFT", "Sortie Gauche"),
            ("EXIT_RIGHT", "Sortie Droite"),
            ("EXIT_DOWN_LEFT", "Sortie Bas-Gauche"),
            ("EXIT_DOWN", "Sortie Bas"),
            ("EXIT_DOWN_RIGHT", "Sortie Bas-Droite"),
            ("MOVE_UP", "Déplacement Haut"),
            ("MOVE_DOWN", "Déplacement Bas"),
            ("MOVE_LEFT", "Déplacement Gauche"),
            ("MOVE_RIGHT", "Déplacement Droite")
        ]

        # On met les raccourcis dans une zone qui peut défiler si ça dépasse
        canvas = tk.Canvas(self.settings_tab, bg=dark_bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.settings_tab, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        for key_id, label_text in keybind_definitions:
            frame = ttk.Frame(scrollable_frame)
            frame.pack(fill='x', padx=5, pady=2)
            ttk.Label(frame, text=f"{label_text}:", width=25).pack(side=tk.LEFT)
            var = tk.StringVar()
            ttk.Entry(frame, textvariable=var, state='readonly', width=15).pack(side=tk.LEFT, padx=5)
            capture_button = ttk.Button(frame, text="Capturer", command=lambda v=var, b=None: self.capture_key(v, b))
            capture_button.pack(side=tk.LEFT, padx=5)
            self.key_vars[key_id] = (var, capture_button)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        config_control_frame = ttk.Frame(self.settings_tab)
        config_control_frame.pack(side=tk.BOTTOM, pady=(4, 10), fill=tk.X, padx=5)
        self.status_label_config = ttk.Label(config_control_frame, text="Statut : Prêt", anchor='w')
        self.status_label_config.pack(side=tk.TOP, fill='x', padx=5)
        self.save_settings_button = ttk.Button(config_control_frame, text="Sauvegarder", command=self.save_settings)
        self.save_settings_button.pack(side=tk.LEFT, padx=5)

        # --- Widgets de l'onglet Déplacement ---
        self.path_log_widget = scrolledtext.ScrolledText(self.path_tab, state='disabled', bg=light_grey_bg, fg=text_color, font=("Consolas", 9), relief='flat', height=12)
        self.path_log_widget.pack(pady=(5,0), padx=5, fill='x', expand=False)

        path_buttons_frame = ttk.Frame(self.path_tab)

        # Création des boutons directionnels
        buttons = {
            'haut-gauche': (0, 0), 'haut': (0, 1), 'haut-droite': (0, 2),
            'gauche': (1, 0), 'droite': (1, 2),
            'bas-gauche': (2, 0), 'bas': (2, 1), 'bas-droite': (2, 2)
        }
        arrow_symbols = {
            'haut-gauche': '↖', 'haut': '↑', 'haut-droite': '↗',
            'gauche': '←', 'droite': '→',
            'bas-gauche': '↙', 'bas': '↓', 'bas-droite': '↘'
        }

        for direction, pos in buttons.items():
            btn = ttk.Button(path_buttons_frame, text=arrow_symbols[direction], width=4,
                             command=lambda d=direction: self.trigger_map_change(d))
            btn.grid(row=pos[0], column=pos[1], padx=5, pady=2)
        path_buttons_frame.pack(side=tk.BOTTOM, pady=(4, 10))

        # --- Widgets de l'onglet Map ---
        self.map_canvas = tk.Canvas(self.map_tab, bg=light_grey_bg, highlightthickness=0)
        self.map_canvas.pack(pady=5, padx=5, fill='both', expand=True)

        map_controls_frame = ttk.Frame(self.map_tab)
        map_controls_frame.pack(side=tk.BOTTOM, pady=(4, 10), fill=tk.X, padx=5)
        map_controls_frame.columnconfigure(2, weight=1)

        ttk.Button(map_controls_frame, text="Ajouter/Éditer", command=self.add_or_edit_map).grid(row=0, column=0, padx=5)
        ttk.Button(map_controls_frame, text="Rafraîchir", command=self.draw_map).grid(row=0, column=1, padx=5)

        self.map_status_label = ttk.Label(map_controls_frame, text="Statut : Prêt", anchor='e')
        self.map_status_label.grid(row=0, column=2, sticky='e', padx=5)

        # --- Widgets de l'onglet Combat ---
        combat_stats_frame = ttk.Frame(self.combat_tab)
        combat_stats_frame.pack(padx=10, pady=10, fill='x')
        
        ttk.Label(combat_stats_frame, text="Points d'Action (PA):").pack(side=tk.LEFT, padx=5)
        self.pa_var = tk.StringVar()
        ttk.Entry(combat_stats_frame, textvariable=self.pa_var, width=5).pack(side=tk.LEFT, padx=5)

        ttk.Label(combat_stats_frame, text="Points de Mouvement (PM):").pack(side=tk.LEFT, padx=15)
        self.pm_var = tk.StringVar()
        ttk.Entry(combat_stats_frame, textvariable=self.pm_var, width=5).pack(side=tk.LEFT, padx=5)

        combat_control_frame = ttk.Frame(self.combat_tab)
        combat_control_frame.pack(side=tk.BOTTOM, pady=(4, 10), fill=tk.X, padx=5)
        self.status_label_combat = ttk.Label(combat_control_frame, text="Statut : Prêt", anchor='w')
        self.status_label_combat.pack(side=tk.TOP, fill='x', padx=5)
        self.save_combat_settings_button = ttk.Button(combat_control_frame, text="Sauvegarder", command=self.save_settings)
        self.save_combat_settings_button.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(combat_control_frame, text="Supprimer Sort", command=self.remove_spell).pack(side=tk.RIGHT, padx=5)
        ttk.Button(combat_control_frame, text="Modifier Sort", command=self.edit_spell).pack(side=tk.RIGHT, padx=5)
        ttk.Button(combat_control_frame, text="Ajouter Sort", command=self.add_spell).pack(side=tk.RIGHT, padx=5)

        spells_frame = ttk.LabelFrame(self.combat_tab, text="Sorts", style='TFrame')
        spells_frame.pack(padx=10, pady=10, fill='both', expand=True)

        self.spells_tree = ttk.Treeview(spells_frame, columns=('name', 'key', 'cost', 'priority', 'range_min', 'range_max'), show='headings')
        self.spells_tree.heading('name', text='Nom')
        self.spells_tree.heading('key', text='Touche')
        self.spells_tree.heading('cost', text='PA')
        self.spells_tree.heading('priority', text='Priorité')
        self.spells_tree.heading('range_min', text='Portée Min')
        self.spells_tree.heading('range_max', text='Portée Max')
        self.spells_tree.column('name', width=150)
        self.spells_tree.column('key', width=50, anchor='center')
        self.spells_tree.column('cost', width=50, anchor='center')
        self.spells_tree.column('priority', width=60, anchor='center')
        self.spells_tree.column('range_min', width=70, anchor='center')
        self.spells_tree.column('range_max', width=70, anchor='center')
        self.spells_tree.pack(side=tk.LEFT, fill='both', expand=True)

        spells_scrollbar = ttk.Scrollbar(spells_frame, orient="vertical", command=self.spells_tree.yview)
        spells_scrollbar.pack(side=tk.RIGHT, fill='y')
        self.spells_tree.configure(yscrollcommand=spells_scrollbar.set)

        # --- Widgets de l'onglet Debug ---
        self.debug_canvas = tk.Canvas(self.debug_tab, bg=light_grey_bg, highlightthickness=0)
        self.debug_canvas.pack(pady=5, padx=5, fill='both', expand=True)

        debug_controls_frame = ttk.Frame(self.debug_tab)
        debug_controls_frame.pack(side=tk.BOTTOM, pady=(4, 10), fill=tk.X, padx=5)
        ttk.Button(debug_controls_frame, text="Afficher la Grille", command=self.draw_debug_grid).pack(side=tk.LEFT, padx=5)
        self.calibrate_grid_button = ttk.Button(debug_controls_frame, text="Étalonner Grille", command=self.calibrate_grid)
        self.calibrate_grid_button.pack(side=tk.LEFT, padx=10)


        # --- Bot state ---
        self.bot_thread = None
        self.keyboard_listener_thread = None
        self.is_paused = False
        self.log_queue = queue.Queue()
        self.load_settings()
        self.log_widgets = [self.log_widget]
        self.selected_map_item = None
        self.closing_on_stop = False
        self.reloading = False
        self.map_items = {} # Pour garder en mémoire les éléments dessinés sur la carte (points, sorties)

        self.setup_global_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(100, self.process_log_queue)

    def log_to_widget(self, msg):
        """Ajoute un message à la file d'attente pour l'affichage dans le widget de log."""
        self.log_queue.put(msg)

    def process_log_queue(self):
        """Traite les messages de la file d'attente et les affiche."""
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()

            self.log_widget.config(state='normal')
            self.log_widget.insert(tk.END, msg + '\n')
            self.log_widget.config(state='disabled')
            self.log_widget.see(tk.END)

            if msg.startswith("[Trajet]"):
                self.path_log_widget.config(state='normal')
                self.path_log_widget.insert(tk.END, msg + '\n')
                self.path_log_widget.config(state='disabled')
                self.path_log_widget.see(tk.END)

        self.after(100, self.process_log_queue)

    def start_bot(self):
        self.start_button.config(state='disabled')
        self.pause_button.config(state='normal')
        self.reload_button.config(state='normal')
        self.update_status_labels("Statut : En cours...")
        set_stop_state(False)
        set_pause_state(False)
        self.is_paused = False

        # On affiche la carte une première fois au lancement
        self.draw_map()

        # On lance le bot dans son propre "thread" pour que l'interface ne freeze pas
        self.bot_thread = threading.Thread(target=main_bot_logic, args=(self.log_to_widget, self.on_bot_finished), daemon=True)
        self.bot_thread.start()

    def update_status_labels(self, text):
        """Met à jour le texte de tous les labels de statut."""
        self.status_label.config(text=text)
        self.status_label_config.config(text=text)
        self.status_label_combat.config(text=text)
        self.map_status_label.config(text=text)

    def toggle_pause_bot(self):
        self.is_paused = not self.is_paused
        set_pause_state(self.is_paused)
        if self.is_paused:
            self.update_status_labels("Statut : En pause")
            self.log_to_widget("[GUI] Script mis en pause.")
        else:
            self.update_status_labels("Statut : En cours...")
            self.log_to_widget("[GUI] Reprise du script.")

    def reload_bot(self):
        if self.bot_thread and self.bot_thread.is_alive():
            self.log_to_widget("[GUI] Rechargement du bot demandé...")
            self.reloading = True
            self.stop_bot(close_app=False)

    def trigger_map_change(self, direction):
        if self.bot_thread and self.bot_thread.is_alive():
            self.log_to_widget(f"[Trajet] Déplacement demandé vers : {direction.capitalize()}")
            request_map_change(direction)
        else:
            self.log_to_widget("[Trajet] Déplacement manuel initié (bot à l'arrêt).")
            threading.Thread(target=self.manual_move, args=(direction,), daemon=True).start()

    def manual_move(self, direction):
        """Gère un déplacement unique lorsque le bot principal n'est pas en cours d'exécution."""
        coords = get_map_coordinates()
        if not coords:
            self.log_to_widget("[Trajet] Impossible de lire les coordonnées de la carte actuelle.")
            return

        self.log_to_widget(f"[Trajet] Position actuelle : {coords}.")
        try:
            map_data = load_map_data(coords)
            
            # Chercher une sortie valide (directe ou en fallback)
            target_direction = find_exit_with_fallback(map_data, direction)
            
            if target_direction:
                # Vérifier que la carte de destination existe dans la base de données
                next_coords = get_next_map_coords(coords, target_direction)
                if os.path.exists(os.path.join("Maps", f"{next_coords}.json")):
                    self.log_to_widget(f"[Trajet] Déplacement vers '{target_direction}' (carte {next_coords} connue).")
                    self.perform_move(coords, map_data, target_direction)
                else:
                    self.log_to_widget(f"[Trajet] La carte de destination {next_coords} n'est pas dans la base de données. Déplacement annulé.")
            else:
                self.log_to_widget(f"[Trajet] Aucune sortie directe '{direction}'. Recherche d'une alternative...")
        except FileNotFoundError:
            self.log_to_widget(f"[Trajet] Fichier de map introuvable pour {coords}.")
        except Exception as e:
            self.log_to_widget(f"[Trajet] Erreur lors du déplacement manuel : {e}")

    def perform_move(self, current_coords, map_data, direction):
        """Effectue le clic et attend le changement de map."""
        exit_pos = map_data["exits"][direction]
        pyautogui.click(exit_pos["x"], exit_pos["y"])
        self.log_to_widget(f"[Trajet] Clic sur la sortie '{direction}'. Attente du changement de map...")
        
        # Utilise la fonction de main.py dans un thread pour ne pas geler la GUI
        if wait_for_map_change(current_coords):
            # Rafraîchir la carte après un court délai
            self.after(500, self.draw_map) 
            
    def stop_bot(self, close_app=False):
        if self.bot_thread and self.bot_thread.is_alive():
            self.log_to_widget("[GUI] Demande d'arrêt du bot...")
            # Si le bot est en pause, on le réveille pour qu'il puisse voir qu'on veut l'arrêter
            if self.is_paused:
                self.toggle_pause_bot()

            set_stop_state(True) # type: ignore
            self.pause_button.config(state='disabled')
            self.reload_button.config(state='disabled')
            if close_app:
                self.closing_on_stop = True
        elif close_app:
            self.destroy()

    def on_bot_finished(self):
        """Callback appelé à la fin du thread du bot."""
        self.update_status_labels("Statut : Arrêté")
        self.start_button.config(state='normal')
        self.pause_button.config(state='disabled')
        self.reload_button.config(state='disabled')
        self.log_to_widget("[GUI] Le bot est arrêté.")
        self.keyboard_listener_thread = None
        if self.closing_on_stop:
            self.after(100, self.destroy)
        elif self.reloading:
            self.reloading = False
            self.log_to_widget("[GUI] Redémarrage du bot...")
            self.after(500, self.start_bot)

    def capture_key(self, var_to_set, _):
        """Capture la prochaine touche pressée dans un thread séparé pour ne pas bloquer la GUI."""
        def do_capture():
            # On désactive tous les boutons "Capturer" pour éviter les clics multiples
            for _, (_, btn) in self.key_vars.items():
                btn.config(text="...", state='disabled')
            
            key_name = keyboard.read_key(suppress=True)
            
            self.after(0, var_to_set.set, key_name)
            self.log_to_widget(f"[GUI] Touche capturée : {key_name}")

            # On réactive tout, c'est bon !
            for _, (_, btn) in self.key_vars.items():
                btn.config(text="Capturer", state='normal')

        threading.Thread(target=do_capture, daemon=True).start()

    def setup_global_hotkeys(self):
        """Met en place les raccourcis clavier globaux."""
        try:
            keyboard.remove_all_hotkeys()
        except AttributeError:
            pass
        
        pause_key = self.key_vars["PAUSE_RESUME"][0].get()
        if pause_key and pause_key != 'esc':
            hotkey = f"ctrl+{pause_key}"
            keyboard.add_hotkey(hotkey, self.toggle_pause_bot_hotkey, suppress=True)
            self.log_to_widget(f"[Clavier] Touche Pause/Reprise configurée sur '{hotkey}'.")

        move_keys = {
            "MOVE_UP": "haut", "MOVE_DOWN": "bas",
            "MOVE_LEFT": "gauche", "MOVE_RIGHT": "droite"
        }
        for key_id, direction in move_keys.items():
            key = self.key_vars[key_id][0].get()
            if key:
                hotkey = f"ctrl+{key}"
                keyboard.add_hotkey(hotkey, lambda d=direction: self.trigger_map_change(d), suppress=True)
                self.log_to_widget(f"[Clavier] Touche de déplacement '{direction.capitalize()}' configurée sur '{hotkey}'.")

    def toggle_pause_bot_hotkey(self):
        """Gère la pause/reprise via raccourci, uniquement si le bot est en cours."""
        if self.bot_thread and self.bot_thread.is_alive():
            self.toggle_pause_bot()

    def add_or_edit_map(self):
        """Lance l'outil de création ou de modification pour la carte actuelle."""
        coords = get_map_coordinates()
        if not coords:
            messagebox.showerror("Erreur", "Impossible de lire les coordonnées de la carte actuelle.")
            return
        
        map_exists = os.path.exists(f"Maps/{coords}.json")
        mode_text = "modifier" if map_exists else "créer"
        
        if messagebox.askyesno(f"{mode_text.capitalize()} la carte", f"Voulez-vous {mode_text} les données de la carte {coords} ?"):
            threading.Thread(target=create_map_interactively, args=(coords, None, map_exists), daemon=True).start()

    def draw_map(self):
        """Dessine la carte sur le canevas, avec l'image de fond et capture auto."""
        self.map_canvas.delete("all")
        self.map_items.clear()
        canvas_width, canvas_height = self.map_canvas.winfo_width(), self.map_canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            self.after(100, self.draw_map)
            return
        self.map_canvas.unbind("<Button-1>")

        coords = get_map_coordinates()
        if not coords:
            self.map_canvas.create_text(canvas_width/2, canvas_height/2, text="Impossible de lire la carte.", fill="white", font=("Calibri", 12))
            return

        self.map_canvas.create_text(10, 10, text=f"Carte: {coords}", fill="white", font=("Calibri", 12, "bold"), anchor="nw", tags="map_text")

        try:
            map_data = load_map_data(coords)
            
            bg_path = f"Maps/{coords}.png"
            if not os.path.exists(bg_path):
                self.log_to_widget(f"[GUI] Aucune image de fond pour {coords}. Capture automatique...")
                game_area = (0, 24, 1348, 808)
                screenshot = pyautogui.screenshot(region=game_area)
                screenshot.save(bg_path)
                self.log_to_widget(f"[GUI] Fond de carte sauvegardé : {bg_path}")

            img = Image.open(bg_path)
            
            scale = min(canvas_width / img.width, canvas_height / img.height)
            
            if img.width <= 0 or img.height <= 0:
                raise ValueError("Les dimensions de l'image de fond sont invalides.")

            scaled_w, scaled_h = int(img.width * scale), int(img.height * scale)
            img_resized = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
            self.map_bg_photo = ImageTk.PhotoImage(img_resized)
            
            offset_x = (canvas_width - scaled_w) / 2
            offset_y = (canvas_height - scaled_h) / 2
            self.map_canvas.create_image(offset_x, offset_y, image=self.map_bg_photo, anchor='nw')

            for cell in map_data.get("cells", []):
                x = (cell['x'] * scale) + offset_x
                y = ((cell['y'] - 24) * scale) + offset_y
                item_id = self.map_canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="cyan", outline="cyan", tags="map_item")
                self.map_canvas.tag_bind(item_id, "<Button-1>", lambda e, t="cell", c=cell: self.on_map_item_click(e, t, c))
                self.map_items[f"cell_{cell['x']}_{cell['y']}"] = item_id

            for direction, pos in map_data.get("exits", {}).items():
                x = (pos['x'] * scale) + offset_x
                y = ((pos['y'] - 24) * scale) + offset_y
                item_id = self.map_canvas.create_rectangle(x - 6, y - 6, x + 6, y + 6, fill="orange", outline="orange", tags="map_item")
                self.map_canvas.tag_bind(item_id, "<Button-1>", lambda e, t="exit", c=direction: self.on_map_item_click(e, t, c))
                text_id = self.map_canvas.create_text(x, y + 10, text=direction, fill="white", font=("Calibri", 7))
                self.map_canvas.tag_bind(text_id, "<Button-1>", lambda e, t="exit", c=direction: self.on_map_item_click(e, t, c))

        except FileNotFoundError:
            self.map_canvas.create_text(canvas_width/2, canvas_height/2, text=f"Aucune donnée pour la carte {coords}.", fill="white", font=("Calibri", 12))
        except Exception as e:
            self.log_to_widget(f"[Erreur GUI] Erreur inattendue lors du dessin de la carte : {e}")
            self.map_canvas.create_text(canvas_width/2, canvas_height/2, text=f"Erreur d'affichage pour {coords}.", fill="red", font=("Calibri", 12))
        
        self.map_canvas.tag_raise("map_text")

    def highlight_spot(self, cell, color):
        """Change la couleur d'un point de pêche sur la carte."""
        item_key = f"cell_{cell['x']}_{cell['y']}"
        item_id = self.map_items.get(item_key)
        if item_id:
            self.map_canvas.itemconfig(item_id, fill=color, outline=color)

    def on_map_item_click(self, event, item_type, item_data):
        """Gère le clic sur un élément de la carte."""
        canvas = event.widget
        if self.selected_map_item:
            canvas.itemconfig(self.selected_map_item, outline="cyan" if canvas.type(self.selected_map_item) == "oval" else "orange")

        self.selected_map_item = canvas.find_closest(event.x, event.y)[0]
        canvas.itemconfig(self.selected_map_item, outline="yellow")
        
        canvas.focus_set()
        canvas.bind("<Delete>", lambda e, t=item_type, d=item_data: self.delete_map_item(t, d))

    def calibrate_grid(self):
        """Lance le processus d'étalonnage de la grille dans un thread séparé."""
        threading.Thread(target=grid_instance.calibrate, daemon=True).start()

    def draw_debug_grid(self):
        """Affiche la grille de combat et les obstacles sur le canevas de débogage."""
        self.debug_canvas.delete("all")
        
        if not grid_instance.is_calibrated:
            messagebox.showerror("Erreur", "La grille n'est pas étalonnée. Veuillez l'étalonner depuis l'onglet 'Debug'.")
            return
        
        full_screenshot = pyautogui.screenshot()
        grid_instance.map_obstacles(screenshot=full_screenshot)

        game_area = (0, 24, 1348, 808)
        game_screenshot = full_screenshot.crop(game_area)
        
        canvas_width = self.debug_canvas.winfo_width()
        canvas_height = self.debug_canvas.winfo_height()
        
        scale = min(canvas_width / game_screenshot.width, canvas_height / game_screenshot.height)
        scaled_w, scaled_h = int(game_screenshot.width * scale), int(game_screenshot.height * scale)
        
        img_resized = game_screenshot.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
        self.debug_bg_photo = ImageTk.PhotoImage(img_resized)
        self.debug_canvas.create_image(0, 0, image=self.debug_bg_photo, anchor='nw')

        for cell_coord, screen_pos in grid_instance.cells.items():
            if game_area[0] <= screen_pos[0] < game_area[2] and game_area[1] <= screen_pos[1] < game_area[3]:
                relative_x = screen_pos[0] - game_area[0]
                relative_y = screen_pos[1] - game_area[1]
                canvas_x = relative_x * scale
                canvas_y = relative_y * scale
                color = "lime" if cell_coord in grid_instance.walkable_cells else "red"
                self.debug_canvas.create_oval(canvas_x - 2, canvas_y - 2, canvas_x + 2, canvas_y + 2, fill=color, outline=color)

    def delete_map_item(self, item_type, item_data):
        """Supprime un élément de la carte après confirmation."""
        coords = get_map_coordinates()
        if not coords: return

        msg = f"Voulez-vous vraiment supprimer ce point ({item_data}) de la carte {coords} ?"
        if messagebox.askyesno("Confirmation de suppression", msg):
            try:
                map_data = load_map_data(coords)
                if item_type == "cell" and item_data in map_data.get("cells", []):
                    map_data["cells"].remove(item_data)
                elif item_type == "exit" and item_data in map_data.get("exits", {}):
                    del map_data["exits"][item_data]

                with open(f"Maps/{coords}.json", "w") as f:
                    json.dump(map_data, f, indent=4)
                
                self.log_to_widget(f"[GUI] Point {item_data} supprimé de la carte {coords}.")
                self.draw_map()
            except Exception as e:
                self.log_to_widget(f"[GUI] Erreur lors de la suppression : {e}")

    def load_settings(self):
        with open("config.json", "r") as f:
            config = json.load(f)
        keybinds_config = config.get("KEYBINDS", {})
        map_keys_config = config.get("MAP_CREATION_KEYS", {})
        all_keys = {**keybinds_config, **map_keys_config}
        for key_id, (var, _) in self.key_vars.items():
            var.set(all_keys.get(key_id, ''))

        combat_config = config.get("COMBAT", {})
        self.pa_var.set(combat_config.get("ACTION_POINTS", 6))
        self.pm_var.set(combat_config.get("MOVEMENT_POINTS", 3))
        
        for item in self.spells_tree.get_children():
            self.spells_tree.delete(item)
        for spell in combat_config.get("SPELLS", []):
            self.spells_tree.insert('', 'end', values=(
                spell.get('name', ''), 
                spell.get('key', ''), 
                spell.get('cost', 0), 
                spell.get('priority', 99),
                spell.get('range_min', 1),
                spell.get('range_max', 8)
            ))

    def save_settings(self):
        with open("config.json", "r+") as f:
            config = json.load(f)
            
            keybinds_config = {}
            map_keys_config = {}
            for key_id, (var, _) in self.key_vars.items():
                if key_id in ["PAUSE_RESUME", "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"]:
                    keybinds_config[key_id] = var.get()
                else:
                    map_keys_config[key_id] = var.get()
            config["KEYBINDS"] = keybinds_config
            config["MAP_CREATION_KEYS"] = map_keys_config

            self.setup_global_hotkeys()

            combat_config = config.get("COMBAT", {})
            try:
                combat_config["ACTION_POINTS"] = int(self.pa_var.get())
                combat_config["MOVEMENT_POINTS"] = int(self.pm_var.get())
            except ValueError:
                messagebox.showerror("Erreur", "Les PA et PM doivent être des nombres entiers.")
                return
            
            spells = []
            for item_id in self.spells_tree.get_children():
                values = self.spells_tree.item(item_id, 'values')
                spells.append({
                    "name": values[0], 
                    "key": values[1], 
                    "cost": int(values[2]), 
                    "priority": int(values[3]),
                    "range_min": int(values[4]),
                    "range_max": int(values[5])})
            combat_config["SPELLS"] = spells
            config["COMBAT"] = combat_config

            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
        self.log_to_widget("[GUI] Paramètres sauvegardés.")

    def add_spell(self):
        """Ouvre une fenêtre pour ajouter un nouveau sort."""
        win = tk.Toplevel(self)
        win.title("Ajouter un sort")
        win.configure(bg='#2E2E2E')
        
        ttk.Label(win, text="Nom:").grid(row=0, column=0, padx=5, pady=5, sticky='w')
        name_entry = ttk.Entry(win)
        name_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(win, text="Touche:").grid(row=1, column=0, padx=5, pady=5, sticky='w')
        key_entry = ttk.Entry(win)
        key_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(win, text="Coût PA:").grid(row=2, column=0, padx=5, pady=5, sticky='w')
        cost_entry = ttk.Entry(win)
        cost_entry.grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(win, text="Priorité:").grid(row=3, column=0, padx=5, pady=5, sticky='w')
        priority_entry = ttk.Entry(win)
        priority_entry.grid(row=3, column=1, padx=5, pady=5)
        priority_entry.insert(0, "1")
        
        ttk.Label(win, text="Portée Min:").grid(row=4, column=0, padx=5, pady=5, sticky='w')
        range_min_entry = ttk.Entry(win)
        range_min_entry.grid(row=4, column=1, padx=5, pady=5)
        range_min_entry.insert(0, "1")

        ttk.Label(win, text="Portée Max:").grid(row=5, column=0, padx=5, pady=5, sticky='w')
        range_max_entry = ttk.Entry(win)
        range_max_entry.grid(row=5, column=1, padx=5, pady=5)
        range_max_entry.insert(0, "8")

        def on_add():
            name = name_entry.get()
            key = key_entry.get()
            cost = cost_entry.get()
            priority = priority_entry.get()
            range_min = range_min_entry.get()
            range_max = range_max_entry.get()

            if name and key and cost and priority:
                try:
                    values = (name, key, int(cost), int(priority), int(range_min), int(range_max))
                    self.spells_tree.insert('', 'end', values=values)
                    win.destroy()
                except ValueError:
                    messagebox.showerror("Erreur", "Le coût en PA et la priorité doivent être des nombres.", parent=win)
            else:
                messagebox.showwarning("Attention", "Veuillez remplir tous les champs.", parent=win)

        ttk.Button(win, text="Ajouter", command=on_add).grid(row=6, columnspan=2, pady=10)

    def edit_spell(self):
        """Ouvre une fenêtre pour modifier le sort sélectionné."""
        selected_item = self.spells_tree.selection()
        if not selected_item:
            messagebox.showwarning("Attention", "Veuillez sélectionner un sort à modifier.")
            return

        item_id = selected_item[0]
        current_values = self.spells_tree.item(item_id, 'values')

        win = tk.Toplevel(self)
        win.title("Modifier un sort")
        win.configure(bg='#2E2E2E')

        ttk.Label(win, text="Nom:").grid(row=0, column=0, padx=5, pady=5, sticky='w')
        name_entry = ttk.Entry(win)
        name_entry.grid(row=0, column=1, padx=5, pady=5)
        name_entry.insert(0, current_values[0])

        ttk.Label(win, text="Touche:").grid(row=1, column=0, padx=5, pady=5, sticky='w')
        key_entry = ttk.Entry(win)
        key_entry.grid(row=1, column=1, padx=5, pady=5)
        key_entry.insert(0, current_values[1])

        ttk.Label(win, text="Coût PA:").grid(row=2, column=0, padx=5, pady=5, sticky='w')
        cost_entry = ttk.Entry(win)
        cost_entry.grid(row=2, column=1, padx=5, pady=5)
        cost_entry.insert(0, current_values[2])

        ttk.Label(win, text="Priorité:").grid(row=3, column=0, padx=5, pady=5, sticky='w')
        priority_entry = ttk.Entry(win)
        priority_entry.grid(row=3, column=1, padx=5, pady=5)
        priority_entry.insert(0, current_values[3])

        ttk.Label(win, text="Portée Min:").grid(row=4, column=0, padx=5, pady=5, sticky='w')
        range_min_entry = ttk.Entry(win)
        range_min_entry.grid(row=4, column=1, padx=5, pady=5)
        range_min_entry.insert(0, current_values[4])

        ttk.Label(win, text="Portée Max:").grid(row=5, column=0, padx=5, pady=5, sticky='w')
        range_max_entry = ttk.Entry(win)
        range_max_entry.grid(row=5, column=1, padx=5, pady=5)
        range_max_entry.insert(0, current_values[5])

        def on_save():
            try:
                new_values = (
                    name_entry.get(), key_entry.get(), int(cost_entry.get()), int(priority_entry.get()),
                    int(range_min_entry.get()), int(range_max_entry.get())
                )
                self.spells_tree.item(item_id, values=new_values)
                win.destroy()
            except ValueError:
                messagebox.showerror("Erreur", "Le coût en PA et la priorité doivent être des nombres.", parent=win)

        ttk.Button(win, text="Sauvegarder", command=on_save).grid(row=6, columnspan=2, pady=10)


    def remove_spell(self):
        """Supprime le sort sélectionné."""
        selected_item = self.spells_tree.selection()
        if selected_item:
            self.spells_tree.delete(selected_item)

    def on_closing(self):
        if self.bot_thread and self.bot_thread.is_alive():
            if messagebox.askokcancel("Quitter", "Voulez-vous vraiment quitter ?"):
                self.stop_bot(close_app=True)
        else:
            self.destroy()

if __name__ == "__main__":
    app = GuiApp()
    app.mainloop()