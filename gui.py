import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, font
from ctypes import windll, byref, c_int 
import pyautogui
import threading
import queue
import time
import json
import keyboard
from PIL import Image, ImageTk
import os, sys, traceback
from main import main_bot_logic, load_map_data, create_map_interactively, find_exit_with_fallback, wait_for_map_change, get_next_map_coords 
from utils import log, set_pause_state, set_stop_state, is_stop_requested, is_fight_started, get_map_coordinates, image_file_lock
from grid import grid_instance
from fight import combat_state

class GuiApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Goofy Assistant")
        self.geometry("565x650")
        # --- Association de l'icône à l'application dans la barre des tâches Windows ---
        myappid = 'goofy.assistant.bot'
        windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        
        try:
            self.iconbitmap('icon.ico')
        except tk.TclError:
            print("[GUI] Fichier 'icon.ico' introuvable. L'icône par défaut est utilisée.")
        self.resizable(True, True)
        self.attributes('-topmost', True)

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
        self.style.configure('TCheckbutton', background=dark_bg, foreground=text_color, indicatorcolor=button_bg)
        self.style.map('TCheckbutton', background=[('active', dark_bg)], indicatorcolor=[('selected', text_color)])
        self.style.map('TNotebook.Tab', background=[('selected', dark_bg)], padding=[('selected', [10, 5])])

        self.update_idletasks()
        windll.dwmapi.DwmSetWindowAttribute(windll.user32.GetParent(self.winfo_id()), 20, byref(c_int(2)), 4)

        # --- Onglets ---
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        self.bot_tab = ttk.Frame(self.notebook, style='TFrame')
        self.settings_tab = ttk.Frame(self.notebook, style='TFrame')
        self.combat_tab = ttk.Frame(self.notebook, style='TFrame')

        self.notebook.add(self.bot_tab, text='Bot')
        self.notebook.add(self.combat_tab, text='Combat')
        self.notebook.add(self.settings_tab, text='Configuration')

        # --- Onglet: Bot ---        
        self.info_label = ttk.Label(self.bot_tab, text="Coordonnées: N/A", anchor='w', font=("Consolas", 10))
        self.info_label.pack(pady=(5,0), padx=5, fill='x')

        self.map_canvas = tk.Canvas(self.bot_tab, bg=light_grey_bg, highlightthickness=0)
        self.map_canvas.pack(pady=5, padx=5, fill='both', expand=True)
        self.map_canvas.bind("<KeyPress-Delete>", self.delete_selected_map_item)
        self.map_canvas.bind("<Button-3>", self.show_map_context_menu)

        map_controls_frame = ttk.Frame(self.bot_tab)
        map_controls_frame.pack(pady=(2, 5), fill=tk.X, padx=5)
        map_controls_frame.columnconfigure(4, weight=1)
        self.add_edit_map_button = ttk.Button(map_controls_frame, text="Créer/Éditer Map", command=self.add_or_edit_map)
        self.add_edit_map_button.grid(row=0, column=0, padx=5)
        ttk.Button(map_controls_frame, text="Rafraîchir", command=self.draw_map).grid(row=0, column=1, padx=5)
        self.toggle_grid_view_button = ttk.Button(map_controls_frame, text="Afficher Grille Combat", command=self.toggle_grid_view)
        self.toggle_grid_view_button.grid(row=0, column=2, padx=5)

        self.log_widget = scrolledtext.ScrolledText(self.bot_tab, state='disabled', height=10, bg=light_grey_bg, fg=text_color, font=("Consolas", 9), relief='flat', spacing1=0, spacing2=0, spacing3=0)
        self.log_widget.pack(pady=5, padx=5, fill=tk.BOTH, expand=True)

        control_frame = ttk.Frame(self.bot_tab)
        control_frame.pack(side=tk.BOTTOM, pady=(4, 10), fill=tk.X, padx=5)
        control_frame.columnconfigure(5, weight=1)

        self.start_button = ttk.Button(control_frame, text="Démarrer", command=self.start_bot)
        self.start_button.grid(row=0, column=0, padx=5)

        self.pause_button = ttk.Button(control_frame, text="Pause/Reprise", command=self.toggle_pause_bot, state='disabled')
        self.pause_button.grid(row=0, column=1, padx=5)
        
        self.reload_button = ttk.Button(control_frame, text="Recharger", command=self.reload_bot, state='disabled')
        self.reload_button.grid(row=0, column=2, padx=(5, 15))

        self.combat_only_var = tk.BooleanVar()
        self.combat_only_check = ttk.Checkbutton(control_frame, text="Mode Combat", variable=self.combat_only_var)
        self.combat_only_check.grid(row=0, column=3, padx=(5,0))
        
        self.auto_combat_var = tk.BooleanVar(value=True)
        self.auto_combat_check = ttk.Checkbutton(control_frame, text="Auto", variable=self.auto_combat_var)
        
        self.status_label = ttk.Label(control_frame, text="Statut : Prêt", anchor='e')
        self.status_label.grid(row=0, column=6, sticky='e', padx=5)

        # --- Widgets de l'onglet Configuration ---
        self.key_vars = {}
        hotkey_definitions = [
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
        ]
        position_definitions = [
            ("TACTICAL_MODE_POS", "Pos. Mode Tactique"),
            ("LOCK_MODE_POS", "Pos. Verrouillage Combat"),
            ("CREATURE_MODE_POS", "Pos. Mode Créature"),
            ("READY_BUTTON_POS", "Pos. Bouton Prêt"),
            ("END_TURN_BUTTON_POS", "Pos. Bouton Fin de Tour"),
            ("FIGHT_END_CLOSE_POS", "Pos. Fermeture Fin Combat"),
            ("LEVEL_UP_OK_POS", "Pos. OK Métier/Niveau"),
            ("PA_OCR_POS", "Pos. OCR PA"),
            ("PM_OCR_POS", "Pos. OCR PM"),
        ]
        grid_definitions = [
            ("origin", "Point d'ancrage (x,y)"),
            ("CELL_WIDTH", "Largeur Cellule"), 
            ("CELL_HEIGHT", "Hauteur Cellule")
        ]


        canvas = tk.Canvas(self.settings_tab, bg=dark_bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.settings_tab, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # --- Section Hotkeys ---
        ttk.Label(scrollable_frame, text="--- Hotkeys ---", font=('calibri', 10, 'bold')).pack(fill='x', padx=5, pady=(10,2))

        for key_id, label_text in hotkey_definitions:
            frame = ttk.Frame(scrollable_frame)
            frame.pack(fill='x', padx=5, pady=2)
            ttk.Label(frame, text=f"{label_text}:", width=25).pack(side=tk.LEFT)
            var = tk.StringVar()
            ttk.Entry(frame, textvariable=var, state='readonly', width=15).pack(side=tk.LEFT, padx=5)
            
            capture_text = "Capturer Touche"
            capture_func = self.capture_key
            capture_button = ttk.Button(frame, text=capture_text, command=lambda v=var, b=None, f=capture_func: f(v, b))
            capture_button.pack(side=tk.LEFT, padx=5)
            self.key_vars[key_id] = (var, capture_button)

        # --- Section Positions ---
        ttk.Label(scrollable_frame, text="--- Positions ---", font=('calibri', 10, 'bold')).pack(fill='x', padx=5, pady=(10,2))
        for key_id, label_text in position_definitions:
            frame = ttk.Frame(scrollable_frame)
            frame.pack(fill='x', padx=5, pady=2)
            ttk.Label(frame, text=f"{label_text}:", width=25).pack(side=tk.LEFT)
            var = tk.StringVar()
            ttk.Entry(frame, textvariable=var, state='readonly', width=15).pack(side=tk.LEFT, padx=5)
            capture_button = ttk.Button(frame, text="Capturer Pos", command=lambda v=var, b=None: self.capture_position(v, b))
            capture_button.pack(side=tk.LEFT, padx=5)
            self.key_vars[key_id] = (var, capture_button)

        # --- Section Grille ---
        ttk.Label(scrollable_frame, text="--- Grille ---", font=('calibri', 10, 'bold')).pack(fill='x', padx=5, pady=(10,2))
        for key_id, label_text in grid_definitions:
            frame = ttk.Frame(scrollable_frame)
            frame.pack(fill='x', padx=5, pady=2)
            ttk.Label(frame, text=f"{label_text}:", width=25).pack(side=tk.LEFT)
            var = tk.StringVar()
            entry_state = 'normal'
            ttk.Entry(frame, textvariable=var, width=15, state=entry_state).pack(side=tk.LEFT, padx=5)
            self.key_vars[key_id] = (var, None)

        # --- Section Divers ---
        ttk.Label(scrollable_frame, text="--- Combat ---", font=('calibri', 10, 'bold')).pack(fill='x', padx=5, pady=(10,2))
        frame = ttk.Frame(scrollable_frame)
        frame.pack(fill='x', padx=5, pady=2)
        ttk.Label(frame, text="Couleurs Marchables (Hex):", width=25).pack(side=tk.LEFT)
        var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=var, width=30)
        entry.pack(side=tk.LEFT, padx=5, fill='x', expand=True)
        self.key_vars["WALKABLE_COLORS_HEX"] = (var, None)
        
        frame = ttk.Frame(scrollable_frame)
        frame.pack(fill='x', padx=5, pady=2)
        ttk.Label(frame, text="Couleurs Monstres (Hex):", width=25).pack(side=tk.LEFT)
        var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=var, width=30)
        entry.pack(side=tk.LEFT, padx=5, fill='x', expand=True)
        self.key_vars["MONSTER_COLORS_HEX"] = (var, None)

        ttk.Label(scrollable_frame, text="--- Divers ---", font=('calibri', 10, 'bold')).pack(fill='x', padx=5, pady=(10,2))
        self.debug_click_var = tk.BooleanVar()
        self.debug_click_check = ttk.Checkbutton(scrollable_frame, text="Debug Clic sur la carte", variable=self.debug_click_var)
        self.debug_click_check.pack(fill='x', padx=10, pady=2)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        config_control_frame = ttk.Frame(self.settings_tab)
        config_control_frame.pack(side=tk.BOTTOM, pady=(4, 10), fill=tk.X, padx=5)
        self.status_label_config = ttk.Label(config_control_frame, text="Statut : Prêt", anchor='w')
        self.status_label_config.pack(side=tk.TOP, fill='x', padx=5)
        
        self.save_settings_button = ttk.Button(config_control_frame, text="Sauvegarder", command=self.save_settings)
        self.save_settings_button.pack(side=tk.TOP, pady=2, fill=tk.X)

        # --- Onglet: Combat ---
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

        self.spells_tree = ttk.Treeview(self.combat_tab, columns=('name', 'key', 'cost', 'priority', 'range_min', 'range_max', 'casts_per_turn', 'movement', 'los'), show='headings')
        self.spells_tree.heading('name', text='Nom')
        self.spells_tree.heading('key', text='Touche')
        self.spells_tree.heading('cost', text='PA')
        self.spells_tree.heading('priority', text='Priorité')
        self.spells_tree.heading('range_min', text='PO Min')
        self.spells_tree.heading('range_max', text='PO Max')
        self.spells_tree.heading('casts_per_turn', text='Lancers')
        self.spells_tree.heading('movement', text='Mouv.')
        self.spells_tree.heading('los', text='LoS')
        self.spells_tree.column('name', width=115)
        self.spells_tree.column('key', width=50, anchor='center')
        self.spells_tree.column('cost', width=25, anchor='center')
        self.spells_tree.column('priority', width=50, anchor='center')
        self.spells_tree.column('range_min', width=50, anchor='center')
        self.spells_tree.column('range_max', width=50, anchor='center')
        self.spells_tree.column('casts_per_turn', width=50, anchor='center')
        self.spells_tree.column('movement', width=50, anchor='center')
        self.spells_tree.column('los', width=50, anchor='center')
        self.spells_tree.pack(padx=5, pady=5, fill='both', expand=True)

        # --- Initialisation de l'état de l'application ---
        self.bot_thread = None
        self.keyboard_listener_thread = None
        self.is_paused = False
        self.log_queue = queue.Queue()
        self.load_settings()
        self.log_widgets = [self.log_widget]
        self.selected_map_item = None
        self.closing_on_stop = False
        self.reloading = False
        self.in_combat_view = False
        self.in_placement_phase = False
        self.is_bot_running = False

        self.show_combat_grid = False
        self.combat_screenshot = None

        self.setup_global_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(100, self.process_log_queue)
        self.redirect_stdout()

    def log_to_widget(self, msg):
        if not isinstance(msg, str):
            msg = str(msg)
        msg = ''.join(c for c in msg if c.isprintable() or c in '\n\t')
        self.log_queue.put(msg)

    def process_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()

            self.log_widget.config(state='normal')
            self.log_widget.insert(tk.END, msg)
            self.log_widget.config(state='disabled')
            self.log_widget.see(tk.END)

        self.after(100, self.process_log_queue)

    def redirect_stdout(self):
        class StdoutRedirector:
            def __init__(self, widget_log_func):
                self.widget_log_func = widget_log_func
                self.buffer = ''

            def write(self, text):
                self.widget_log_func(text)

            def flush(self):
                pass

        sys.stdout = StdoutRedirector(self.log_to_widget)
        sys.stderr = StdoutRedirector(self.log_to_widget)
    def start_bot(self):
        self.start_button.config(state='disabled')
        self.pause_button.config(state='normal', text="Pause")
        self.reload_button.config(state='normal')
        self.update_status_labels("Statut : En cours...")
        set_stop_state(False)
        set_pause_state(False)
        self.is_bot_running = True
        self.is_paused = False

        self.draw_map()

        def bot_thread_wrapper():
            try:
                main_bot_logic(self, self.on_bot_finished)
            except Exception as e:
                sys.__stderr__.write(f"ERREUR CRITIQUE INATTENDUE: {e}\n{traceback.format_exc()}\n")
                self.log_to_widget(f"ERREUR CRITIQUE INATTENDUE: {e}")
        self.bot_thread = threading.Thread(target=bot_thread_wrapper, daemon=True)
        self.bot_thread.start()

    def update_status_labels(self, text):
        self.status_label.config(text=text)
        self.status_label_config.config(text=text)
        self.status_label_combat.config(text=text)

    def toggle_pause_bot(self):
        self.is_paused = not self.is_paused
        set_pause_state(self.is_paused)
        self.after(100, self.release_modifier_keys_after_hotkey)
        if self.is_paused:
            self.pause_button.config(text="Reprendre")
            self.update_status_labels("Statut : En pause")
            self.log_to_widget("[GUI] Script mis en pause.")
        else:
            self.pause_button.config(text="Pause")
            self.log_to_widget("[GUI] Reprise du script.")

    def reload_bot(self):
        if self.bot_thread and self.bot_thread.is_alive():
            self.log_to_widget("[GUI] Rechargement du bot demandé...")
            self.reloading = True
            self.stop_bot(close_app=False)

    def stop_bot(self, close_app=False):
        def release_modifier_keys():
            keyboard.release('ctrl')
            keyboard.release('alt')
            keyboard.release('shift')

        if self.bot_thread and self.bot_thread.is_alive():
            self.log_to_widget("[GUI] Demande d'arrêt du bot...")
            if self.is_paused:
                self.toggle_pause_bot()

            set_stop_state(True)
            self.pause_button.config(state='disabled')
            self.reload_button.config(state='disabled')
            self.after(100, release_modifier_keys)
            if close_app:
                self.closing_on_stop = True
        elif close_app:
            self.destroy()

    def on_bot_finished(self):
        self.start_button.config(state='normal')
        self.pause_button.config(text="Pause/Reprise")
        self.pause_button.config(state='disabled')
        self.reload_button.config(state='disabled')
        self.log_to_widget("[GUI] Le bot est arrêté.")
        self.keyboard_listener_thread = None
        self.is_bot_running = False
        if self.closing_on_stop:
            self.after(100, self.destroy)
        elif self.reloading:
            self.reloading = False
            self.log_to_widget("[GUI] Redémarrage du bot...")
            self.after(500, self.start_bot)

    def capture_key(self, var_to_set, _):
        def do_capture():
            for _, (_, btn) in self.key_vars.items():
                if btn:
                    btn.config(text="...", state='disabled')
            
            self.log_to_widget("[GUI] En attente d'un raccourci clavier...")
            
            pressed_keys = set()
            while True:
                event = keyboard.read_event(suppress=True)
                if event.event_type == keyboard.KEY_DOWN:
                    pressed_keys.add(event.name)
                elif event.event_type == keyboard.KEY_UP:
                    break
            
            key_map = {
                'right ctrl': 'Ctrl D', 'left ctrl': 'Ctrl G',
                'alt': 'Alt', 'alt gr': 'AltGr', 'shift': 'Maj',
                'delete': 'Suppr', 'enter': 'Entrée', 'esc': 'Échap',
                'up': 'Haut', 'down': 'Bas', 'left': 'Gauche', 'right': 'Droite'
            }
            
            key_names = {key_map.get(k, k.capitalize()) for k in pressed_keys}
            
            modifiers_order = ['Ctrl G', 'Ctrl D', 'Alt', 'AltGr', 'Maj']
            mods = sorted(
                [k for k in key_names if k in modifiers_order],
                key=lambda m: modifiers_order.index(m)
            )
            keys = sorted([k for k in key_names if k not in mods])
            
            final_keys = mods + keys
            key_name = "+".join(final_keys)
            
            self.after(0, var_to_set.set, key_name)
            self.log_to_widget(f"[GUI] Touche capturée : {key_name}")

            for key_id, (_, btn) in self.key_vars.items():
                if btn:
                    is_pos_capture = "POS" in key_id
                    capture_text = "Capturer Pos" if is_pos_capture else "Capturer Touche"
                    btn.config(text=capture_text, state='normal')

        threading.Thread(target=do_capture, daemon=True).start()

    def capture_position(self, var_to_set, _):
        def do_capture():
            for _, (_, btn) in self.key_vars.items():
                if btn:
                    btn.config(text="...", state='disabled')
            
            self.log_to_widget("[GUI] Capture de position dans 2s...")
            time.sleep(2)
            x, y = pyautogui.position()
            pos_str = f"{x},{y}"
            
            self.after(0, var_to_set.set, pos_str)
            self.log_to_widget(f"[GUI] Position capturée : {pos_str}")

            for key_id, (_, btn) in self.key_vars.items():
                if btn:
                    is_pos_capture = "POS" in key_id
                    capture_text = "Capturer Pos" if is_pos_capture else "Capturer Touche"
                    btn.config(text=capture_text, state='normal')
        threading.Thread(target=do_capture, daemon=True).start()

    def setup_global_hotkeys(self):
        try:
            keyboard.remove_all_hotkeys()
        except AttributeError:
            pass
        
        pause_key = self.key_vars["PAUSE_RESUME"][0].get()
        if pause_key:
            keyboard.add_hotkey(pause_key, self.toggle_pause_bot_hotkey, suppress=True)

    def toggle_pause_bot_hotkey(self):
        if self.bot_thread and self.bot_thread.is_alive():
            self.toggle_pause_bot()
            self.after(100, self.release_modifier_keys_after_hotkey)

    def release_modifier_keys_after_hotkey(self):
        keyboard.release('ctrl')
        keyboard.release('alt')
        keyboard.release('shift')

    def add_or_edit_map(self):
        coords = get_map_coordinates()
        if not coords:
            messagebox.showerror("Erreur", "Impossible de lire les coordonnées de la carte actuelle.")
            return
        
        map_exists = os.path.exists(f"Maps/{coords}.json")
        mode_text = "modifier" if map_exists else "créer"
        
        if messagebox.askyesno(f"{mode_text.capitalize()} la carte", f"Voulez-vous {mode_text} les données de la carte {coords} ?"):
            threading.Thread(target=create_map_interactively, args=(coords, None, map_exists), daemon=True).start()

    def update_map_button_text(self):
        coords = get_map_coordinates()
        map_exists = os.path.exists(f"Maps/{coords}.json") if coords else False
        button_text = "Éditer la Map" if map_exists else "Créer la Map"
        self.add_edit_map_button.config(text=button_text)

    def draw_map(self, in_combat=None):
        self.map_canvas.delete("all")

        if in_combat is not None:
            self.in_combat_view = in_combat

        canvas_width, canvas_height = self.map_canvas.winfo_width(), self.map_canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            self.after(100, self.draw_map)
            return
        
        if not grid_instance.is_calibrated:
            messagebox.showerror("Erreur", "La grille n'est pas étalonnée. Veuillez l'étalonner depuis l'onglet 'Debug'.")
            self.update_map_button_text()
            return
        
        coords = get_map_coordinates()
        game_area = (0, 24, 1348, 808)
        game_screenshot = None

        image_dir = os.path.join("Maps", "Images")
        os.makedirs(image_dir, exist_ok=True)

        if coords:
            if self.in_combat_view or self.show_combat_grid:
                tactic_path = os.path.join(image_dir, f"{coords}Tactic.png")
                with image_file_lock:
                    if os.path.exists(tactic_path):
                        game_screenshot = Image.open(tactic_path)
            else:
                normal_path = os.path.join(image_dir, f"{coords}Normal.png")
                if not os.path.exists(normal_path):
                    # Si l'image normale n'existe pas, on la crée
                    log(f"[GUI] Le fichier {normal_path} n'existe pas. Création automatique...")
                    temp_screenshot = pyautogui.screenshot().crop(game_area)
                    with image_file_lock:
                        temp_screenshot.save(normal_path)
                    game_screenshot = temp_screenshot
                
                with image_file_lock:
                    if os.path.exists(normal_path):
                        game_screenshot = Image.open(normal_path)

        if game_screenshot is None:
            full_screenshot = pyautogui.screenshot()
            game_screenshot = full_screenshot.crop(game_area)
        
        scale = min(canvas_width / game_screenshot.width, canvas_height / game_screenshot.height)
        scaled_w, scaled_h = int(game_screenshot.width * scale), int(game_screenshot.height * scale)
        
        img_resized = game_screenshot.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
        self.map_bg_photo = ImageTk.PhotoImage(img_resized)
        self.map_canvas.create_image(canvas_width/2, canvas_height/2, image=self.map_bg_photo, anchor='center')
        
        info_text = f"Coordonnées: {coords if coords else 'N/A'}"
        if self.in_combat_view:
            pa = combat_state.current_pa if combat_state.current_pa is not None else '?'
            pm = combat_state.current_pm if combat_state.current_pm is not None else '?'
            info_text += f"  |  PA: {pa}  |  PM: {pm}"
        self.info_label.config(text=info_text)

        self.update_map_button_text()
        map_data = {}
        fishing_spots_coords = set()
        exit_spots_coords = set()
        
        if not self.in_combat_view:
            coords = get_map_coordinates()
            if coords:
                try:
                    map_data = load_map_data(coords)
                    for cell_data in map_data.get("cells", []):
                        grid_cell = grid_instance.get_cell_from_screen_coords(cell_data['x'], cell_data['y'])
                        if grid_cell:
                            fishing_spots_coords.add(grid_cell)

                    for direction, pos_data in map_data.get("exits", {}).items():
                        grid_cell = grid_instance.get_cell_from_screen_coords(pos_data['x'], pos_data['y'])
                        if grid_cell:
                            exit_spots_coords.add(grid_cell)

                except FileNotFoundError:
                    pass
        
        coords = get_map_coordinates()
        combat_overrides = {}
        if coords:
            try:
                map_data_for_overrides = load_map_data(coords)
                combat_overrides = map_data_for_overrides.get("combat_overrides", {})
            except FileNotFoundError:
                pass

        for cell_coord, screen_pos in grid_instance.cells.items():
            if game_area[0] <= screen_pos[0] < game_area[2] and game_area[1] <= screen_pos[1] < game_area[3]:
                relative_x = screen_pos[0] - game_area[0]
                relative_y = screen_pos[1] - game_area[1]
                canvas_x = (relative_x * scale) + (canvas_width - scaled_w) / 2
                canvas_y = (relative_y * scale) + (canvas_height - scaled_h) / 2

                fill_color = ""
                stipple_pattern = ""
                outline_color = "grey"
                item_tags = ("cell", str(cell_coord))

                if cell_coord in exit_spots_coords and not (self.in_combat_view or self.show_combat_grid):
                    fill_color = "yellow"
                    stipple_pattern = "gray50"
                elif cell_coord in fishing_spots_coords and not (self.in_combat_view or self.show_combat_grid):
                    fill_color = "orange"
                    stipple_pattern = "gray50"
                if self.in_placement_phase:
                    if cell_coord in combat_state.possible_player_starts:
                        fill_color = "white"
                        outline_color = "white"
                    elif cell_coord in combat_state.possible_monster_starts:
                        fill_color = "black"
                        outline_color = "black" 
                    if cell_coord in combat_state.monster_positions:
                        fill_color = "darkred"
                        stipple_pattern = "gray50"
                elif self.in_combat_view or self.show_combat_grid:
                    override_state = combat_overrides.get(str(cell_coord))
                    if override_state == "walkable":
                        fill_color = "green"
                        stipple_pattern = "gray50"
                    elif override_state == "obstacle": # Changement de couleur ici
                        fill_color = "red"
                        stipple_pattern = "gray50"
                    elif override_state == "los_transparent":
                        fill_color = "orange"
                        stipple_pattern = "gray50"
                    elif cell_coord in grid_instance.walkable_cells:
                        outline_color = "lime"
                    elif cell_coord in grid_instance.los_transparent_cells:
                        outline_color = "orange"
                    else:
                        outline_color = "red"
                    if cell_coord in combat_state.monster_positions:
                        fill_color = "darkred"
                        stipple_pattern = "gray50"
                    elif cell_coord in combat_state.player_positions:
                        fill_color = "blue"
                        stipple_pattern = "gray50"

                width = 2 if self.in_placement_phase and (cell_coord in combat_state.possible_player_starts or cell_coord in combat_state.possible_monster_starts) else 1
                cell_w, cell_h = 97 * scale, 50 * scale
                points = [
                    canvas_x, canvas_y - cell_h / 2,
                    canvas_x + cell_w / 2, canvas_y,
                    canvas_x, canvas_y + cell_h / 2,
                    canvas_x - cell_w / 2, canvas_y
                ]
                item_type_tag = "cell"
                if cell_coord in exit_spots_coords and not (self.in_combat_view or self.show_combat_grid):
                    item_type_tag = "exit"

                self.map_canvas.create_polygon(points, outline=outline_color, fill=fill_color, width=width, stipple=stipple_pattern, tags=(item_type_tag, str(cell_coord))) 
                
                self.map_canvas.tag_bind(str(cell_coord), "<Button-1>", lambda event, tags=(item_type_tag, str(cell_coord)): self.on_map_item_click(event, tags))

    def highlight_spot(self, cell, color):
        grid_cell = grid_instance.get_cell_from_screen_coords(cell['x'], cell['y'])
        if grid_cell:
            tag_expression = f"cell && \"{str(grid_cell)}\""
            items = self.map_canvas.find_withtag(tag_expression)
            for item_id in items:
                if self.map_canvas.itemcget(item_id, "fill") != "":
                    self.map_canvas.itemconfig(item_id, fill=color)

    def on_map_item_click(self, event, tags):
        item_type, item_data_str = tags
        item_data = tuple(map(int, item_data_str.strip('()').split(',')))
        if self.debug_click_var.get():
            self.log_to_widget(f"[Debug Clic] Case cliquée : {item_data}")
            return

        if self.selected_map_item:
            if self.selected_map_item != (item_type, item_data):
                self.draw_map() 

        self.selected_map_item = (item_type, item_data)
        self.log_to_widget(f"[GUI] Sélectionné : {item_type} à la case {item_data}. Appuyez sur 'Suppr' pour effacer.")
        self.map_canvas.focus_set()

        tag_expression = f"{item_type} && \"{str(item_data)}\""
        items = self.map_canvas.find_withtag(tag_expression)
        for item_id in items:
            if self.map_canvas.itemcget(item_id, "fill") != "":
                self.map_canvas.itemconfig(item_id, fill="cyan")

    def show_map_context_menu(self, event):
        clicked_items = self.map_canvas.find_overlapping(event.x, event.y, event.x, event.y)
        cell_coord_str = None
        for item in clicked_items:
            tags = self.map_canvas.gettags(item)
            for tag in tags:
                if tag.startswith('('):
                    cell_coord_str = tag
                    break
            if cell_coord_str:
                break
        
        if not cell_coord_str:
            return

        grid_coord = tuple(map(int, cell_coord_str.strip('()').split(',')))

        context_menu = tk.Menu(self, tearoff=0)
        if self.in_combat_view or self.show_combat_grid:
            context_menu.add_command(label="Forcer Marchable", command=lambda: self.set_combat_override(grid_coord, "walkable"))
            context_menu.add_command(label="Forcer Obstacle", command=lambda: self.set_combat_override(grid_coord, "obstacle"))
            context_menu.add_command(label="Forcer Ligne de Vue", command=lambda: self.set_combat_override(grid_coord, "los_transparent"))
            context_menu.add_separator()
            context_menu.add_command(label="Réinitialiser Case", command=lambda: self.set_combat_override(grid_coord, None))
        else:
            context_menu.add_command(label="Ajouter Ressource", command=lambda: self.add_resource_at_cell(grid_coord))
            context_menu.add_command(label="Supprimer Ressource", command=lambda: self.remove_resource_at_cell(grid_coord))

        context_menu.post(event.x_root, event.y_root)

    def add_resource_at_cell(self, grid_coord):
        map_coords = get_map_coordinates()
        if not map_coords: return
        try:
            map_data = load_map_data(map_coords)
        except FileNotFoundError:
            map_data = {"map": map_coords, "cells": [], "exits": {}}
        screen_pos = grid_instance.cells.get(grid_coord)
        if not screen_pos: return
        map_data.setdefault("cells", []).append({"x": screen_pos[0], "y": screen_pos[1]})
        with open(f"Maps/{map_coords}.json", "w") as f:
            json.dump(map_data, f, indent=4)
        self.log_to_widget(f"[GUI] Point de ressource ajouté à la case {grid_coord} sur la carte {map_coords}.")
        self.draw_map()

    def remove_resource_at_cell(self, grid_coord):
        map_coords = get_map_coordinates()
        if not map_coords: return
        try:
            map_data = load_map_data(map_coords)
            cells_to_keep = [c for c in map_data.get("cells", []) if grid_instance.get_cell_from_screen_coords(c['x'], c['y']) != grid_coord]
            if len(cells_to_keep) < len(map_data.get("cells", [])):
                map_data["cells"] = cells_to_keep
                with open(f"Maps/{map_coords}.json", "w") as f:
                    json.dump(map_data, f, indent=4)
                self.log_to_widget(f"[GUI] Point de ressource retiré de la case {grid_coord} sur la carte {map_coords}.")
                self.draw_map()
        except FileNotFoundError:
            pass

    def set_combat_override(self, grid_coord, state):
        map_coords = get_map_coordinates()
        if not map_coords: return
        try:
            map_data = load_map_data(map_coords)
        except FileNotFoundError:
            map_data = {"map": map_coords, "cells": [], "exits": {}}
        
        overrides = map_data.setdefault("combat_overrides", {})
        if state is None:
            if str(grid_coord) in overrides:
                del overrides[str(grid_coord)]
                self.log_to_widget(f"[Grille] Remplacement pour la case {grid_coord} retiré.")
        else:
            overrides[str(grid_coord)] = state
            self.log_to_widget(f"[Grille] Case {grid_coord} forcée à l'état '{state}'.")

        with open(f"Maps/{map_coords}.json", "w") as f:
            json.dump(map_data, f, indent=4)
        self.draw_map()

    def toggle_grid_view(self):
        self.show_combat_grid = not self.show_combat_grid
        if self.show_combat_grid:
            self.toggle_grid_view_button.config(text="Afficher Grille Pêche")
        else:
            self.toggle_grid_view_button.config(text="Afficher Grille Combat")
        self.draw_map()

    def calibrate_grid(self):
        def calibration_thread_target():
            grid_instance.calibrate()
            self.after(0, self.update_origin_field)

        threading.Thread(target=calibration_thread_target, daemon=True).start()

    def update_origin_field(self):
        new_origin = grid_instance.origin
        self.key_vars["origin"][0].set(f"{new_origin[0]},{new_origin[1]}")
        self.log_to_widget("[GUI] Point d'ancrage mis à jour dans l'interface.")
        self.draw_map()

    def delete_selected_map_item(self, event):
        if not self.selected_map_item: return
        item_type, item_data = self.selected_map_item

        coords = get_map_coordinates()
        if not coords: return

        msg = f"Voulez-vous vraiment supprimer ce point ({item_data}) de la carte {coords} ?"
        if messagebox.askyesno("Confirmation de suppression", msg):
            try:
                map_data = load_map_data(coords)
                if item_type == "cell":
                    cells_to_keep = [c for c in map_data.get("cells", []) if grid_instance.get_cell_from_screen_coords(c['x'], c['y']) != item_data]
                    map_data["cells"] = cells_to_keep
                elif item_type == "exit":
                    exit_to_delete = None
                    for direction, pos_data in map_data.get("exits", {}).items():
                        if grid_instance.get_cell_from_screen_coords(pos_data['x'], pos_data['y']) == item_data:
                            exit_to_delete = direction
                            break
                    if exit_to_delete:
                        del map_data["exits"][exit_to_delete]
                
                with open(f"Maps/{coords}.json", "w") as f:
                    json.dump(map_data, f, indent=4)
                
                self.log_to_widget(f"[GUI] Point {item_data} supprimé de la carte {coords}.")
                self.selected_map_item = None
                self.draw_map()
            except Exception as e:
                self.log_to_widget(f"[GUI] Erreur lors de la suppression : {e}")

    def load_settings(self):
        with open("config.json", "r") as f:
            config = json.load(f)
        keybinds_config = config.get("KEYBINDS", {})
        map_keys_config = config.get("MAP_CREATION_KEYS", {})
        pos_config = config.get("POSITIONS", {})
        grid_config = config.get("GRID", {})
        combat_config = config.get("COMBAT", {})

        for key_id, (var, _) in self.key_vars.items():
            if "POS" in key_id:
                pos_value = pos_config.get(key_id, [])
                var.set(','.join(map(str, pos_value)) if pos_value else '')
            elif key_id == "origin":
                pos_value = grid_config.get(key_id, [])
                var.set(','.join(map(str, pos_value)) if pos_value else '')
            elif key_id == "WALKABLE_COLORS_HEX":
                hex_colors = combat_config.get("WALKABLE_COLORS_HEX", [])
                var.set(', '.join(hex_colors))
            elif key_id == "MONSTER_COLORS_HEX":
                hex_colors = combat_config.get("MONSTER_COLORS_HEX", [])
                var.set(', '.join(hex_colors))
            else:
                var.set(keybinds_config.get(key_id) or map_keys_config.get(key_id, ''))

        self.pa_var.set(combat_config.get("ACTION_POINTS", 6))
        self.pm_var.set(combat_config.get("MOVEMENT_POINTS", 3))
        
        self.key_vars["CELL_WIDTH"][0].set(grid_config.get("CELL_WIDTH", 96.5))
        self.key_vars["CELL_HEIGHT"][0].set(grid_config.get("CELL_HEIGHT", 49.5))
        for item in self.spells_tree.get_children():
            self.spells_tree.delete(item)
        for spell in combat_config.get("SPELLS", []):
            is_movement_str = "Oui" if spell.get('is_movement', False) else "Non"
            requires_los_str = "Oui" if spell.get('requires_los', True) else "Non"
            self.spells_tree.insert('', 'end', values=(
                spell.get('name', ''), 
                spell.get('key', ''), 
                spell.get('cost', 0), 
                spell.get('priority', 99),
                spell.get('range_min', 1),
                spell.get('range_max', 8),
                spell.get('casts_per_turn', 99),
                is_movement_str,
                requires_los_str
            ))

    def save_settings(self):
        with open("config.json", "r+") as f:
            config = json.load(f)
            
            keybinds_config = {}
            map_keys_config = {}
            pos_config = {}
            grid_config = config.get("GRID", {})
            combat_config = config.get("COMBAT", {})

            for key_id, (var, _) in self.key_vars.items():
                value = var.get()
                if "POS" in key_id or key_id == "origin":
                    try:
                        pos_config[key_id] = [int(v.strip()) for v in value.split(',')] if value else []
                    except ValueError:
                        pos_config[key_id] = []
                elif key_id in ["CELL_WIDTH", "CELL_HEIGHT"]:
                    try:
                        grid_config[key_id] = float(value)
                    except ValueError:
                        pass
                elif key_id == "WALKABLE_COLORS_HEX":
                    hex_colors = [c.strip().upper().replace('#', '') for c in value.split(',') if c.strip()]
                    combat_config["WALKABLE_COLORS_HEX"] = hex_colors
                elif key_id == "MONSTER_COLORS_HEX":
                    hex_colors = [c.strip().upper().replace('#', '') for c in value.split(',') if c.strip()]
                    combat_config["MONSTER_COLORS_HEX"] = hex_colors
                elif key_id in self.key_vars and self.key_vars[key_id][1] and "Pos" not in self.key_vars[key_id][1].cget("text"):
                    keybinds_config[key_id] = self._format_hotkey_for_save(value) 
                else:
                    map_keys_config[key_id] = self._format_hotkey_for_save(value)
            config["KEYBINDS"] = keybinds_config
            grid_config["origin"] = pos_config.pop("origin", grid_config.get("origin"))
            config["COMBAT"] = combat_config

            config["MAP_CREATION_KEYS"] = map_keys_config

            self.setup_global_hotkeys()
            config["POSITIONS"] = pos_config
            config["GRID"] = grid_config

            try:
                combat_config["ACTION_POINTS"] = int(self.pa_var.get())
                combat_config["MOVEMENT_POINTS"] = int(self.pm_var.get())
            except ValueError:
                messagebox.showerror("Erreur", "Les PA et PM doivent être des nombres entiers.")
                return
            
            spells = []
            for item_id in self.spells_tree.get_children():
                values = self.spells_tree.item(item_id, 'values')
                is_movement = True if values[7] == "Oui" else False
                requires_los = True if values[8] == "Oui" else False
                spells.append({
                    "name": values[0], 
                    "key": values[1], 
                    "cost": int(values[2]), 
                    "priority": int(values[3]),
                    "range_min": int(values[4]),
                    "range_max": int(values[5]),
                    "casts_per_turn": int(values[6]),
                    "is_movement": is_movement,
                    "requires_los": requires_los
                })
            combat_config["SPELLS"] = spells
            config["COMBAT"] = combat_config

            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
        self.log_to_widget("[GUI] Paramètres sauvegardés.")
        grid_instance.load_config()
        self.draw_map()

    def _format_hotkey_for_save(self, hotkey_str):
        if not hotkey_str:
            return ""
        
        parts = [p.strip().lower() for p in hotkey_str.split('+')]
        
        key_map = {
            'ctrl d': 'Ctrl D', 'right ctrl': 'Ctrl D',
            'ctrl g': 'Ctrl G', 'left ctrl': 'Ctrl G',
            'alt': 'Alt', 'alt gr': 'AltGr', 'shift': 'Maj',
            'suppr': 'Suppr', 'delete': 'Suppr',
            'entrée': 'Entrée', 'enter': 'Entrée',
            'échap': 'Échap', 'esc': 'Échap',
            'haut': 'Haut', 'up': 'Haut',
            'bas': 'Bas', 'down': 'Bas',
            'gauche': 'Gauche', 'left': 'Gauche',
            'droite': 'Droite', 'right': 'Droite'
        }
        
        normalized_parts = set()
        for p in parts:
            normalized_parts.add(key_map.get(p, p.capitalize()))

        modifiers_order = ['Ctrl G', 'Ctrl D', 'Alt', 'AltGr', 'Maj']
        mods = sorted([p for p in normalized_parts if p in modifiers_order], key=lambda m: modifiers_order.index(m))
        keys = sorted([k for k in normalized_parts if k not in mods])
        
        final_keys = mods + keys
        return "+".join(final_keys)

    def add_spell(self):
        win = tk.Toplevel(self)
        win.title("Ajouter un sort")
        try:
            win.iconbitmap('icon.ico')
        except tk.TclError:
            pass
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

        ttk.Label(win, text="Lancers/tour:").grid(row=6, column=0, padx=5, pady=5, sticky='w')
        casts_per_turn_entry = ttk.Entry(win)
        casts_per_turn_entry.grid(row=6, column=1, padx=5, pady=5)
        casts_per_turn_entry.insert(0, "99")
        
        is_movement_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text="Sort de Mouvement", variable=is_movement_var).grid(row=7, columnspan=2, padx=5, pady=2, sticky='w')

        requires_los_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(win, text="Nécessite LoS", variable=requires_los_var).grid(row=8, columnspan=2, padx=5, pady=2, sticky='w')

        def on_add():
            name = name_entry.get()
            key = key_entry.get()
            cost = cost_entry.get()
            priority = priority_entry.get()
            range_min = range_min_entry.get()
            range_max = range_max_entry.get()
            casts_per_turn = casts_per_turn_entry.get()
            is_movement = "Oui" if is_movement_var.get() else "Non"
            requires_los = "Oui" if requires_los_var.get() else "Non"

            if name and key and cost and priority:
                try:
                    values = (name, key, int(cost), int(priority), int(range_min), int(range_max), int(casts_per_turn), is_movement, requires_los)
                    self.spells_tree.insert('', 'end', values=values)
                    win.destroy()
                except ValueError:
                    messagebox.showerror("Erreur", "Les champs numériques (PA, priorité, etc.) doivent être des nombres.", parent=win)
            else:
                messagebox.showwarning("Attention", "Veuillez remplir tous les champs.", parent=win)

        ttk.Button(win, text="Ajouter", command=on_add).grid(row=9, columnspan=2, pady=10)

    def edit_spell(self):
        selected_item = self.spells_tree.selection()
        if not selected_item:
            messagebox.showwarning("Attention", "Veuillez sélectionner un sort à modifier.")
            return

        item_id = selected_item[0]
        current_values = self.spells_tree.item(item_id, 'values')

        win = tk.Toplevel(self)
        win.title("Modifier un sort")
        try:
            win.iconbitmap('icon.ico')
        except tk.TclError:
            pass
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

        ttk.Label(win, text="Lancers/tour:").grid(row=6, column=0, padx=5, pady=5, sticky='w')
        casts_per_turn_entry = ttk.Entry(win)
        casts_per_turn_entry.grid(row=6, column=1, padx=5, pady=5)
        casts_per_turn_entry.insert(0, current_values[6])
        
        is_movement_var = tk.BooleanVar(value=(current_values[7] == "Oui"))
        ttk.Checkbutton(win, text="Sort de Mouvement", variable=is_movement_var).grid(row=7, columnspan=2, padx=5, pady=2, sticky='w')

        requires_los_var = tk.BooleanVar(value=(current_values[8] == "Oui"))
        ttk.Checkbutton(win, text="Nécessite LoS", variable=requires_los_var).grid(row=8, columnspan=2, padx=5, pady=2, sticky='w')

        def on_save():
            try:
                is_movement_str = "Oui" if is_movement_var.get() else "Non"
                requires_los_str = "Oui" if requires_los_var.get() else "Non"
                new_values = (
                    name_entry.get(), key_entry.get(), int(cost_entry.get()), int(priority_entry.get()),
                    int(range_min_entry.get()), int(range_max_entry.get()), int(casts_per_turn_entry.get()),
                    is_movement_str, requires_los_str
                )
                self.spells_tree.item(item_id, values=new_values)
                win.destroy()
            except ValueError:
                messagebox.showerror("Erreur", "Les champs numériques (PA, priorité, etc.) doivent être des nombres.", parent=win)

        ttk.Button(win, text="Sauvegarder", command=on_save).grid(row=9, columnspan=2, pady=10)


    def remove_spell(self):
        selected_item = self.spells_tree.selection()
        if selected_item:
            self.spells_tree.delete(selected_item)

    def on_closing(self):
        if self.bot_thread and self.bot_thread.is_alive():
            set_stop_state(True)
        self.destroy()

if __name__ == "__main__":
    app = GuiApp()
    app.mainloop()