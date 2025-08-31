import os
import sys
import math
import time
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import filedialog
from tkinter import font as tkfont
from typing import Optional, Tuple, List

from game import Game, RIGHT_PANE_W, HUD_LOG_LINES, visible_enemies_list, _dir_to_compass, _inspect_info_lines, build_help_frame
import patchloader


def enable_dpi_awareness():
    # Best-effort DPI awareness for Windows to avoid blurry scaling
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
            return
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # System DPI aware
        except Exception:
            pass
    except Exception:
        pass


def default_save_path() -> str:
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = os.path.join(appdata, "TextCrawler2")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "savegame.json")
    return os.path.join(os.getcwd(), "savegame.json")


class NewGameDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, game: Game):
        super().__init__(master)
        self.title("New Game")
        self.resizable(False, False)
        self.game = game
        self.result = False

        frm = ttk.Frame(self, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")

        self.var_random = tk.BooleanVar(value=game.menu_seed_random)
        self.var_seed = tk.StringVar(value=str(game.menu_seed_value if game.menu_seed_value >= 0 else 1337))
        self.var_w = tk.IntVar(value=game.menu_width)
        self.var_h = tk.IntVar(value=game.menu_height)
        self.var_enemies = tk.IntVar(value=game.menu_enemies)
        self.var_tier = tk.IntVar(value=getattr(game, 'menu_tier', 1))
        self.var_rooms = tk.BooleanVar(value=getattr(game, 'menu_use_rooms', True))

        ttk.Label(frm, text="Seed:").grid(row=0, column=0, sticky="w")
        se = ttk.Entry(frm, textvariable=self.var_seed, width=12)
        se.grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(frm, text="Random", variable=self.var_random, command=lambda: se.configure(state=("disabled" if self.var_random.get() else "normal"))).grid(row=0, column=2, sticky="w")
        if self.var_random.get():
            se.configure(state="disabled")

        ttk.Label(frm, text="Width:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_w, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(frm, text="Height:").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_h, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text="Enemies:").grid(row=3, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_enemies, width=8).grid(row=3, column=1, sticky="w")
        ttk.Label(frm, text="Tier:").grid(row=4, column=0, sticky="w")
        tier_box = ttk.Combobox(frm, state="readonly", values=(1,2,3), width=6, textvariable=self.var_tier)
        tier_box.grid(row=4, column=1, sticky="w")
        ttk.Checkbutton(frm, text="Use rooms/corridors", variable=self.var_rooms).grid(row=5, column=0, columnspan=2, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="OK", command=self.on_ok).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Cancel", command=self.on_cancel).grid(row=0, column=1)

        self.bind("<Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.on_cancel())

        self.grab_set()
        self.transient(master)
        self.wait_visibility()
        self.focus()

    def on_ok(self):
        try:
            w = max(20, min(120, int(self.var_w.get())))
            h = max(10, min(60, int(self.var_h.get())))
            en = max(0, min(99, int(self.var_enemies.get())))
        except Exception:
            messagebox.showerror("Invalid", "Width/Height/Enemies must be integers")
            return
        self.game.menu_seed_random = bool(self.var_random.get())
        if not self.game.menu_seed_random:
            try:
                self.game.menu_seed_value = max(0, int(self.var_seed.get()))
            except Exception:
                messagebox.showerror("Invalid", "Seed must be a non-negative integer")
                return
        else:
            self.game.menu_seed_value = -1
        self.game.menu_width = w
        self.game.menu_height = h
        self.game.menu_enemies = en
        try:
            self.game.menu_tier = int(self.var_tier.get())
        except Exception:
            self.game.menu_tier = 1
        self.game.menu_use_rooms = bool(self.var_rooms.get())
        self.result = True
        self.destroy()

    def on_cancel(self):
        self.result = False
        self.destroy()


class SeriesDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.title("Auto Series")
        self.resizable(False, False)
        self.result: Optional[Tuple[int, bool, int, int, bool]] = None
        frm = ttk.Frame(self, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frm, text="Runs:").grid(row=0, column=0, sticky="w")
        self.var_runs = tk.IntVar(value=50)
        ttk.Entry(frm, textvariable=self.var_runs, width=10).grid(row=0, column=1, sticky="w")
        self.var_fixed = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Fixed Seed", variable=self.var_fixed).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(frm, text="Show frames every K ticks (0=hidden):").grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.var_show = tk.IntVar(value=0)
        ttk.Entry(frm, textvariable=self.var_show, width=10).grid(row=3, column=0, sticky="w")
        ttk.Label(frm, text="Tier:").grid(row=3, column=1, sticky="w")
        self.var_tier = tk.IntVar(value=1)
        ttk.Combobox(frm, state="readonly", values=(1,2,3), width=6, textvariable=self.var_tier).grid(row=3, column=1, sticky="e")
        self.var_rooms = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Use rooms/corridors", variable=self.var_rooms).grid(row=4, column=0, columnspan=2, sticky="w")
        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="Start", command=self.on_start).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Cancel", command=self.on_cancel).grid(row=0, column=1)
        self.bind("<Return>", lambda e: self.on_start())
        self.bind("<Escape>", lambda e: self.on_cancel())
        self.grab_set()
        self.transient(master)
        self.wait_visibility()
        self.focus()

    def on_start(self):
        try:
            runs = max(1, int(self.var_runs.get()))
            fixed = bool(self.var_fixed.get())
            show = max(0, int(self.var_show.get()))
            tier = int(self.var_tier.get())
            use_rooms = bool(self.var_rooms.get())
        except Exception:
            messagebox.showerror("Invalid", "Please enter valid integers")
            return
        self.result = (runs, fixed, show, tier, use_rooms)
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


class SeriesResultsDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, lines: List[str]):
        super().__init__(master)
        self.title("Auto Series Results")
        self.resizable(False, False)
        frm = ttk.Frame(self, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        text = "Results:\n" + "\n".join(lines)
        lbl = tk.Text(frm, width=48, height=min(18, max(8, len(lines) + 4)))
        lbl.insert("1.0", text)
        lbl.configure(state="disabled")
        lbl.grid(row=0, column=0, columnspan=3, sticky="nsew")
        btns = ttk.Frame(frm)
        btns.grid(row=1, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="Copy", command=lambda: self._copy(lines)).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Save...", command=lambda: self._save(lines)).grid(row=0, column=1, padx=5)
        ttk.Button(btns, text="Close", command=self.destroy).grid(row=0, column=2)
        self.grab_set()
        self.transient(master)
        self.wait_visibility()
        self.focus()

    def _copy(self, lines: List[str]):
        try:
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))
        except Exception:
            pass

    def _save(self, lines: List[str]):
        try:
            appdata = os.environ.get("APPDATA")
            base = os.path.join(appdata or os.getcwd(), "TextCrawler2", "reports")
            os.makedirs(base, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(base, f"series_{ts}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("Results\n")
                for s in lines:
                    f.write(s + "\n")
            messagebox.showinfo("Saved", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))


class RunResultDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, rows: List[Tuple[str, str]], on_close=None, on_new=None, on_quit=None):
        super().__init__(master)
        self.title("Run Results")
        self.resizable(False, False)
        frm = ttk.Frame(self, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        for i, (k, v) in enumerate(rows):
            ttk.Label(frm, text=f"{k}:").grid(row=i, column=0, sticky="w", padx=(0, 8))
            ttk.Label(frm, text=v).grid(row=i, column=1, sticky="w")
        btns = ttk.Frame(frm)
        btns.grid(row=len(rows), column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="New Run (R)", command=lambda: self._do(on_new)).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Quit (Q)", command=lambda: self._do(on_quit)).grid(row=0, column=1, padx=5)
        ttk.Button(btns, text="Close", command=lambda: self._do(on_close)).grid(row=0, column=2)
        self.bind("<Escape>", lambda e: self._do(on_close))
        self.bind("<KeyPress-r>", lambda e: self._do(on_new))
        self.bind("<KeyPress-q>", lambda e: self._do(on_quit))
        self.grab_set()
        self.transient(master)
        self.wait_visibility()
        self.focus()

    def _do(self, fn):
        try:
            if fn:
                fn()
        finally:
            try:
                self.destroy()
            except Exception:
                pass
class GuiApp:
    def __init__(self, game: Game):
        enable_dpi_awareness()
        self.game = game
        self.root = tk.Tk()
        self.root.title("Text Crawler II")
        self.root.geometry("960x600")
        self.root.minsize(640, 400)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Canvas fills window
        self.canvas = tk.Canvas(self.root, bg="#000000", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Tile and HUD layout
        self.tile_size: int = 32  # default tile size in px (scales with window)
        self.gap_px: int = 8      # gap between map and HUD
        # HUD font
        self.font_family = "Consolas"
        self.hud_font_size = 14
        self.hud_font = tkfont.Font(family=self.font_family, size=self.hud_font_size)

        # Status toast
        self._status_text: Optional[str] = None
        self._status_after_id: Optional[str] = None

        # Damage popups managed in GUI for short lifetime
        self._active_popups: List[dict] = []

        # Auto-play scheduler state
        self._auto_after_id: Optional[str] = None
        self._auto_counter: int = 0
        # Series/batch state
        self._series_active: bool = False
        self._series_total: int = 0
        self._series_done: int = 0
        self._series_wins: int = 0
        self._series_losses: int = 0
        self._series_sum_turns: int = 0
        self._series_sum_kills: int = 0
        self._series_sum_dmg_taken: int = 0
        self._series_sum_dmg_dealt: int = 0
        self._series_sum_items_used: int = 0
        # Extra series metrics
        self._series_sum_times_hexed: int = 0
        self._series_sum_shots_dodged: int = 0
        self._series_kills_by_role: dict = {}
        self._series_fixed_seed: bool = False
        self._series_base_seed: int = 1337
        self._series_show_every: int = 0
        self._series_report_lines: Optional[List[str]] = None
        self._series_tier: int = 1
        self._series_use_rooms: bool = True
        # Modal/dialog guard
        self._modal_open: bool = False

        # Input bindings
        self.root.bind("<KeyPress>", self.on_key)
        self.root.bind("<Configure>", self.on_resize)
        self.root.bind("<Button-1>", self.on_click)

        # Menu bar
        self._build_menu()
        # Live watcher
        try:
            patchloader.start_watcher()
        except Exception:
            pass
        # Periodic live-reload check
        self._live_after_id = None
        self._schedule_live_check()

        # Start a game immediately
        self.game.new_game(is_restart=False)
        # Initial layout compute and draw
        self._compute_layout()
        self.redraw()

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Game…", command=self.menu_new_game)
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self.menu_save)
        file_menu.add_command(label="Load", command=self.menu_load)
        # Patches / Mods
        file_menu.add_separator()
        file_menu.add_command(label="Import Patch…", command=self.menu_import_patch)
        file_menu.add_command(label="Reload Patches && Config (F10)", command=self.menu_reload)
        file_menu.add_command(label="Manage Patches…", command=self.menu_manage_patches)
        file_menu.add_separator()
        # Auto-Play controls
        self.var_auto = tk.BooleanVar(value=self.game.auto_play)
        file_menu.add_checkbutton(label="Auto-Play", variable=self.var_auto, command=self.menu_toggle_auto)
        speed_menu = tk.Menu(file_menu, tearoff=False)
        self.var_speed = tk.IntVar(value=int(self.game.auto_ticks_per_sec))
        for v in (4, 8, 16, 32, 64):
            speed_menu.add_radiobutton(label=f"{v} tps", value=v, variable=self.var_speed, command=self.menu_speed_change)
        file_menu.add_cascade(label="Speed", menu=speed_menu)
        self.var_fast = tk.BooleanVar(value=self.game.auto_fast)
        file_menu.add_checkbutton(label="Fast Mode (skip draws)", variable=self.var_fast, command=self.menu_toggle_fast)
        # Auto-Restart flags
        self.var_ar_death = tk.BooleanVar(value=self.game.auto_restart_on_death)
        self.var_ar_victory = tk.BooleanVar(value=self.game.auto_restart_on_victory)
        file_menu.add_checkbutton(label="Auto-Restart on Death", variable=self.var_ar_death, command=self.menu_toggle_ar_death)
        file_menu.add_checkbutton(label="Auto-Restart on Victory", variable=self.var_ar_victory, command=self.menu_toggle_ar_victory)
        file_menu.add_separator()
        file_menu.add_command(label="Auto Series...", command=self.menu_series)
        file_menu.add_command(label="Start Demo", command=self.menu_start_demo)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        settings_menu = tk.Menu(menubar, tearoff=False)
        settings_menu.add_command(label="Open Config Folder", command=self.menu_open_config)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Controls & Legend", command=self.menu_help)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        # Hot reload hotkey
        self.root.bind("<F10>", lambda e: self.menu_reload())

    # ---------- Event Handlers ----------
    def on_resize(self, event):
        # Recompute tile size and HUD font based on available space
        self._compute_layout()
        self.redraw()

    def on_close(self):
        self.root.destroy()

    def on_key(self, event: tk.Event):
        key = self._normalize_key(event)
        if key is None:
            return

        g = self.game

        # Global exits from overlays
        if key in ("ESC", "Q"):
            if g.help_mode:
                g.help_mode = False
                self._ensure_auto()
                self.redraw()
                return
            if g.inspect_mode:
                g.inspect_mode = False
                self._ensure_auto()
                self.redraw()
                return
            if key == "Q":
                self.on_close()
                return

        if key == "H":
            g.help_mode = not g.help_mode
            # Auto-play pauses while help is open
            self._ensure_auto()
            self.redraw()
            return

        # When help is open: ignore all except H/Esc/Q and A (toggle auto)
        if g.help_mode:
            if key == "A":
                g.auto_play = not g.auto_play
                try:
                    self.var_auto.set(g.auto_play)
                except Exception:
                    pass
                if g.auto_play:
                    self._toast(f"Auto: ON ({max(1,int(g.auto_ticks_per_sec))} tps)")
                else:
                    self._toast("Auto: OFF")
                self._ensure_auto()
                self.redraw()
            return

        # Pause toggle
        if key == "P":
            if g.state == "paused":
                g.state = "playing"
                g.logger.log("Unpaused.")
            elif g.state in ("playing", "game_over"):
                g.state = "paused"
                g.logger.log("Paused.")
            self._ensure_auto()
            self.redraw()
            return

        # F9 toggles auto-restart both
        if key == "F9":
            v = not (g.auto_restart_on_death and g.auto_restart_on_victory)
            g.auto_restart_on_death = v
            g.auto_restart_on_victory = v
            self._toast(f"Auto-Restart: {'ON' if v else 'OFF'}")
            self._ensure_auto()
            self.redraw()
            return

        # In paused mode: Save/Load/Restart
        if g.state == "paused":
            if key == "S":
                g.save_game()
                self._toast("Saved")
                self.redraw()
                return
            if key == "L":
                if g.load_game():
                    self._toast("Loaded")
                self.redraw()
                return
            if key == "R":
                g.new_game(is_restart=True)
                self.redraw()
                return
            return

        # Restart
        if key == "R":
            g.new_game(is_restart=True)
            self._ensure_auto()
            self.redraw()
            return

        # Inspect toggle
        if key == "I":
            if g.inspect_mode:
                g.inspect_mode = False
            else:
                g.inspect_mode = True
                g.inspect_x, g.inspect_y = g.player.x, g.player.y
            self.redraw()
            return

        # Inspect cursor movement without consuming turn
        if g.inspect_mode:
            move = self._dir_from_key(key)
            if move:
                dx, dy = move
                g.inspect_x = max(0, min(g.map.w - 1, g.inspect_x + dx))
                g.inspect_y = max(0, min(g.map.h - 1, g.inspect_y + dy))
                g.recompute_fov()
                self.redraw()
            return

        # Auto-Play hotkeys
        if key == "A":
            g.auto_play = not g.auto_play
            try:
                self.var_auto.set(g.auto_play)
            except Exception:
                pass
            if g.auto_play:
                self._toast(f"Auto: ON ({max(1,int(g.auto_ticks_per_sec))} tps)")
            else:
                self._toast("Auto: OFF")
            self._ensure_auto()
            self.redraw()
            return
        if key == "U":
            used = g.use_potion(manual=True)
            if used and g.state == "playing":
                g.enemy_turns()
                g.turn += 1
                g.recompute_fov()
                self._ingest_damage_events()
                self._ensure_tick()
                self._ensure_auto()
                self.redraw()
            return
        if key in ("[", "]"):
            speeds = [4, 8, 16, 32, 64]
            try:
                i = speeds.index(max(1, int(g.auto_ticks_per_sec)))
            except Exception:
                i = 2
            if key == "[" and i > 0:
                g.auto_ticks_per_sec = speeds[i - 1]
            if key == "]" and i < len(speeds) - 1:
                g.auto_ticks_per_sec = speeds[i + 1]
            try:
                self.var_speed.set(int(g.auto_ticks_per_sec))
            except Exception:
                pass
            self._toast(f"Speed: {g.auto_ticks_per_sec} tps")
            self._ensure_auto()
            self.redraw()
            return
        if key == "}":
            g.auto_fast = not g.auto_fast
            g._set_auto_fast_params()
            try:
                self.var_fast.set(g.auto_fast)
            except Exception:
                pass
            self._toast("Fast mode: " + ("ON" if g.auto_fast else "OFF"))
            self._ensure_auto()
            self.redraw()
            return

        # Gameplay input
        turn_taken = False
        if key == ".":
            from game import TurnDigest
            g._digest = TurnDigest()
            if g.auto_play:
                g.auto_play = False
                try:
                    self.var_auto.set(False)
                except Exception:
                    pass
                self._ensure_auto()
            turn_taken = True
        else:
            move = self._dir_from_key(key)
            if move:
                dx, dy = move
                # Turn digest
                from game import TurnDigest
                g._digest = TurnDigest()
                if g.auto_play:
                    g.auto_play = False
                    try:
                        self.var_auto.set(False)
                    except Exception:
                        pass
                    self._ensure_auto()
                old = (g.player.x, g.player.y)
                g.move_entity(g.player, dx, dy)
                turn_taken = True
        if turn_taken and g.state == "playing":
            # Enemies move and digest log
            g.enemy_turns()
            g.turn += 1
            # Tick player effects after turn
            try:
                g._decay_effects(g.player)
            except Exception:
                pass
            if getattr(g, "_digest", None) is not None:
                for line in g._digest.summarize():
                    g.logger.log(line)
                g._digest = None
            g.recompute_fov()
            # Capture fresh damage events for popups
            self._ingest_damage_events()
            self._ensure_tick()
            self._ensure_auto()
            self.redraw()

    # ---------- Rendering ----------
    def _compute_layout(self):
        # Compute tile size and HUD font so that map + HUD fits canvas
        W = max(1, self.canvas.winfo_width())
        H = max(1, self.canvas.winfo_height())
        map_w = max(1, int(self.game.map.w))
        map_h = max(1, int(self.game.map.h))
        gap = self.gap_px

        # Try tile sizes from a reasonable max down to min
        best_tile = 24
        # Prefer 32 if it fits
        for tile in list(range(48, 15, -1)):
            # HUD font attempts to match tile height roughly
            hud_size = max(8, int(tile * 0.62))
            f = tkfont.Font(family=self.font_family, size=hud_size)
            ch_w = max(1, f.measure("M"))
            # content sizes
            content_w = map_w * tile + gap + RIGHT_PANE_W * ch_w
            content_h = map_h * tile
            if content_w <= W and content_h <= H:
                best_tile = tile
                self.hud_font_size = hud_size
                self.hud_font = f
                break
        self.tile_size = best_tile
        # Ensure hud font exists
        if not hasattr(self, "hud_font") or self.hud_font is None:
            self.hud_font = tkfont.Font(family=self.font_family, size=self.hud_font_size)

    def redraw(self):
        g = self.game
        g.recompute_fov()
        # Consume flash positions for this frame
        flash_set = set(getattr(g, 'flash_positions', []))
        g.flash_positions = []
        # Ingest any new damage events if not yet captured
        self._ingest_damage_events()

        self.canvas.delete("all")
        W = max(1, self.canvas.winfo_width())
        H = max(1, self.canvas.winfo_height())
        tile = max(8, int(self.tile_size))
        map_cols = g.map.w
        map_rows = g.map.h
        # HUD text metrics
        hud_ch_w = max(1, self.hud_font.measure("M"))
        hud_ch_h = max(1, self.hud_font.metrics("linespace"))

        # Compute content area and offsets to center content
        content_w = map_cols * tile + self.gap_px + RIGHT_PANE_W * hud_ch_w
        content_h = map_rows * tile
        ox = max(0, (W - content_w) // 2)
        oy = max(0, (H - content_h) // 2)

        # Background
        self.canvas.create_rectangle(ox, oy, ox + content_w, oy + content_h, fill="#000000", outline="")

        # Draw map tiles as rectangles
        for y in range(map_rows):
            for x in range(map_cols):
                explored = g.map.explored[y][x]
                visible = g.visible[y][x]
                t = g.map.tiles[y][x]
                x0 = ox + x * tile
                y0 = oy + y * tile
                x1 = x0 + tile
                y1 = y0 + tile
                if not explored and not visible:
                    # Unknown: leave black
                    continue
                if t.walkable:
                    fill = "#1a1a1a" if visible else "#0c0c0c"  # dark floor
                else:
                    fill = "#b0b0b0" if visible else "#404040"  # walls
                self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")

        # Doors overlay
        try:
            for (dx, dy), d in getattr(g.map, 'doors', {}).items():
                if not g.map.explored[dy][dx]:
                    continue
                x0 = ox + dx * tile
                y0 = oy + dy * tile
                # Draw a vertical bar for door
                color = "#ffd700" if (g.visible[dy][dx]) else "#808080"
                if d.open:
                    # Slightly open: two small lines
                    self.canvas.create_line(x0 + tile*0.3, y0 + tile*0.2, x0 + tile*0.7, y0 + tile*0.2, fill=color, width=2)
                    self.canvas.create_line(x0 + tile*0.3, y0 + tile*0.8, x0 + tile*0.7, y0 + tile*0.8, fill=color, width=2)
                else:
                    self.canvas.create_rectangle(x0 + tile*0.4, y0 + tile*0.2, x0 + tile*0.6, y0 + tile*0.8, outline=color, width=2)
                    if d.locked:
                        self.canvas.create_oval(x0 + tile*0.47, y0 + tile*0.45, x0 + tile*0.53, y0 + tile*0.55, fill=color, outline=color)
        except Exception:
            pass

        # Draw Exit portal tile (glow)
        ex, ey = getattr(g, 'exit_x', None), getattr(g, 'exit_y', None)
        if isinstance(ex, int) and isinstance(ey, int):
            if 0 <= ex < map_cols and 0 <= ey < map_rows and g.map.explored[ey][ex]:
                x0 = ox + ex * tile
                y0 = oy + ey * tile
                pad = max(2, tile // 8)
                self.canvas.create_oval(x0 + pad//2, y0 + pad//2, x0 + tile - pad//2, y0 + tile - pad//2, outline="#ffd700", width=2)
                self.canvas.create_oval(x0 + pad, y0 + pad, x0 + tile - pad, y0 + tile - pad, outline="#80c0ff", width=2)

        # Draw corpses silhouettes (explored and visible or explored only?)
        for (cx, cy, kind) in getattr(g, 'corpses', []):
            if 0 <= cx < map_cols and 0 <= cy < map_rows and g.map.explored[cy][cx]:
                x0 = ox + cx * tile
                y0 = oy + cy * tile
                pad = max(2, tile // 8)
                self.canvas.create_oval(x0 + pad, y0 + pad, x0 + tile - pad, y0 + tile - pad, fill="#606060", outline="")

        # Draw items (visible)
        try:
            for it in list(getattr(g, 'items', []) or []):
                if 0 <= it.x < map_cols and 0 <= it.y < map_rows and g.visible[it.y][it.x]:
                    x0 = ox + it.x * tile
                    y0 = oy + it.y * tile
                    kind = getattr(it, 'kind', 'potion')
                    if kind == 'potion':
                        # Small bottle icon
                        self.canvas.create_rectangle(x0 + tile*0.35, y0 + tile*0.25, x0 + tile*0.65, y0 + tile*0.65, fill="#40c0ff", outline="#a0e0ff")
                        self.canvas.create_rectangle(x0 + tile*0.45, y0 + tile*0.15, x0 + tile*0.55, y0 + tile*0.25, fill="#a0e0ff", outline="")
                    else:
                        # Key icon
                        pad = max(2, tile // 8)
                        self.canvas.create_oval(x0 + pad, y0 + pad, x0 + tile//2, y0 + tile//2, fill="#ffd700", outline="#e0b000")
                        self.canvas.create_rectangle(x0 + tile*0.55, y0 + tile*0.40, x0 + tile*0.80, y0 + tile*0.50, fill="#ffd700", outline="#e0b000")
        except Exception:
            pass

        # Draw entities (only if visible)
        for y in range(map_rows):
            for x in range(map_cols):
                if not g.visible[y][x]:
                    continue
                ent_here = None
                if g.player.is_alive() and g.player.x == x and g.player.y == y:
                    ent_here = g.player
                else:
                    for e in g.enemies:
                        if e.is_alive() and e.x == x and e.y == y:
                            ent_here = e
                            break
                if ent_here is None:
                    continue
                px = ox + x * tile
                py = oy + y * tile
                pad = max(2, tile // 8)
                color = self._color_for_entity(ent_here)
                outline = "#ffd700" if (ent_here is g.player) else "#101010"
                # Flash overlay on hit
                if (x, y) in flash_set:
                    self.canvas.create_rectangle(px, py, px + tile, py + tile, fill="#ff0000", outline="", stipple="gray25")
                # Draw a circle for the unit
                self.canvas.create_oval(px + pad, py + pad, px + tile - pad, py + tile - pad, fill=color, outline=outline, width=2 if ent_here is g.player else 1)

        # Auto path preview (next few steps)
        try:
            path_preview: List[Tuple[int, int]] = list(getattr(g, '_auto_path', []) or [])
        except Exception:
            path_preview = []
        if path_preview:
            max_steps = min(6, len(path_preview))
            for (sx, sy) in path_preview[:max_steps]:
                if not (0 <= sx < map_cols and 0 <= sy < map_rows):
                    continue
                x0 = ox + sx * tile
                y0 = oy + sy * tile
                self.canvas.create_rectangle(x0, y0, x0 + tile, y0 + tile, outline="#80c0ff", width=1, fill="#80c0ff", stipple="gray50")

        # Damage popups overlay
        now = time.time()
        for ev in list(self._active_popups):
            if ev.get("until", 0) <= now:
                continue
            x = int(ev.get("x", 0))
            y = int(ev.get("y", 0))
            dmg = int(ev.get("dmg", 0))
            px = ox + x * tile + tile // 2
            py = oy + y * tile + tile // 2
            self.canvas.create_text(px, py, text=f"-{dmg}", fill="#ff4040", font=self.hud_font, anchor="c")

        # Inspect cursor overlay
        if g.inspect_mode:
            px = ox + g.inspect_x * tile
            py = oy + g.inspect_y * tile
            self.canvas.create_rectangle(px + 1, py + 1, px + tile - 1, py + tile - 1, outline="#ffffff")

        # Right pane
        pane_x0 = ox + map_cols * tile + self.gap_px
        pane_y0 = oy
        # Status
        if g.state in ("playing", "paused", "game_over", "victory"):
            gen = 'rooms' if getattr(g.map, 'gen_type', 'caves') == 'rooms' else 'caves'
            status_line = f"HP {g.player.hp}/{g.player.max_hp}  ATK {g.player.power}  Turn {g.turn}  Tier {getattr(g, 'menu_tier', 1)}  Gen {gen}  Seed {g.seed}"
        else:
            seed_str = (str(g.menu_seed_value) if not g.menu_seed_random else "random")
            status_line = f"HP -/-  ATK -  Turn -  Seed {seed_str}"
        controls_line = "WASD/Arrows: move  .: wait  P: pause  I: inspect  H: help"
        auto_speed = max(1, int(g.auto_ticks_per_sec))
        auto_on = "ON" if g.auto_play else "OFF"
        fast_suffix = f"  Fast: {'ON' if g.auto_fast else 'OFF'}"
        auto_line = f"AUTO: {auto_on}  Speed: {auto_speed} tps{fast_suffix}  (A toggle, [ ] speed, }} fast)"
        goal_line = ""
        inv_line = ""
        try:
            goal_line = g._goal_status_line()
            inv_line = g._inventory_line()
        except Exception:
            goal_line = goal_line or ""
            inv_line = inv_line or ""
        ar_line = f"Auto-Restart: {'ON' if (g.auto_restart_on_death and g.auto_restart_on_victory) else 'OFF'}"
        # Live status
        try:
            st = patchloader.get_live_status()
            ts = st.get("last_time")
            ts_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "N/A"
            live_line = None
            if st.get("enabled"):
                ok = st.get("last_ok")
                live_line = f"Live Patches: ON — last apply {'OK' if (ok is None or ok) else 'FAILED'} at {ts_str}"
            pane_lines: List[str] = [status_line, controls_line, auto_line]
            if live_line:
                pane_lines.append(live_line)
        except Exception:
            pane_lines: List[str] = [status_line, controls_line, auto_line]
        if goal_line:
            pane_lines.append(goal_line)
        if inv_line:
            pane_lines.append(inv_line)
        # Player Effects line
        try:
            effs = []
            for name, data in getattr(g.player, 'effects', {}).items():
                d = int(data.get('dur', 0))
                if name == 'Shield':
                    effs.append(f"Shield ({d})")
                elif name == 'Hex':
                    effs.append(f"Hex ({d})")
                elif name == 'Frenzy':
                    effs.append(f"Frenzy ({d})")
                elif name == 'Aim':
                    effs.append(f"Aim ({d})")
            if effs:
                pane_lines.append("Effects: " + ", ".join(effs))
        except Exception:
            pass
        pane_lines.append(ar_line)
        if g.state in ("playing", "paused", "game_over"):
            if g.inspect_mode:
                pane_lines.extend(["[Inspect]"] + _inspect_info_lines(g))
            else:
                pane_lines.extend(visible_enemies_list(g))
        # Fit top area
        top_max = max(0, g.map.h - HUD_LOG_LINES)
        top_lines = []
        # Use game's wrapper
        for s in pane_lines:
            top_lines.extend(g._wrap(s, RIGHT_PANE_W))
        top_lines = (top_lines + [""] * top_max)[:top_max]
        # Log bottom area
        log_wrapped: List[str] = []
        for s in g.logger.lines:
            log_wrapped.extend(g._wrap(s, RIGHT_PANE_W))
        bottom_lines = (log_wrapped + [""] * HUD_LOG_LINES)[-HUD_LOG_LINES:]
        final_lines = top_lines + bottom_lines
        for i, line in enumerate(final_lines[:g.map.h]):
            fill = "#c0c0c0"
            s = line.strip()
            if s.startswith("AUTO:") and g.auto_play:
                fill = "#d8ffb0"  # light green
            elif s.startswith("Live Patches:"):
                # Colorize by status keywords
                if "FAILED" in s:
                    fill = "#ffb0b0"  # light red
                else:
                    fill = "#b0ffb0"  # light green
            self.canvas.create_text(pane_x0, pane_y0 + i * tile, text=line.ljust(RIGHT_PANE_W), fill=fill, font=self.hud_font, anchor="nw")

        # Overlays (draw after HUD)
        if g.help_mode:
            self._draw_help_overlay(ox, oy, content_w, content_h, hud_ch_w, hud_ch_h)
        elif g.state == "paused":
            self._draw_paused_overlay(ox, oy, content_w, content_h)

        # Auto toggle button in top-right of content area
        btn_margin = 8
        btn_w = max(60, int(hud_ch_w * 6))
        btn_h = max(24, int(hud_ch_h * 1.2))
        bx1 = ox + content_w - btn_margin
        by1 = oy + btn_margin
        bx0 = bx1 - btn_w
        by0 = by1 - btn_h
        btn_fill = "#2c2c2c" if not g.auto_play else "#245c24"
        self.canvas.create_rectangle(bx0, by0, bx1, by1, fill=btn_fill, outline="#909090")
        label = "Auto: ON" if g.auto_play else "Auto: OFF"
        self.canvas.create_text((bx0 + bx1) // 2, (by0 + by1) // 2, text=label, fill="#ffffff", font=self.hud_font, anchor="c")
        self._auto_btn_bbox = (bx0, by0, bx1, by1)

        # Status toast
        if self._status_text:
            self.canvas.create_text(ox + content_w - 10, oy + content_h - 10, text=self._status_text, fill="#ffff80", font=self.hud_font, anchor="se")

        self.canvas.update_idletasks()

        # Show victory/defeat modal if ended and no auto-restart/series
        if not self._series_active and g.state in ("victory", "game_over") and not self._modal_open:
            should = not ((g.state == "victory" and g.auto_restart_on_victory) or (g.state == "game_over" and g.auto_restart_on_death))
            if should:
                self._modal_open = True
                summary = [
                    ("Result", "Victory!" if g.state == "victory" else "Defeat"),
                    ("Turns", str(g.turn)),
                    ("Kills", str(g.run_kills)),
                    ("Items used", str(g.run_items_used)),
                    ("Dmg dealt", str(g.run_dmg_dealt)),
                    ("Dmg taken", str(g.run_dmg_taken)),
                    ("Seed", str(g.seed)),
                ]
                RunResultDialog(self.root, summary, on_close=self._on_modal_close, on_new=self._on_modal_new, on_quit=self.on_close)

    def _on_modal_close(self):
        self._modal_open = False
        self.redraw()

    def _on_modal_new(self):
        self._modal_open = False
        self.game.new_game(is_restart=True)
        self.redraw()

    def _draw_paused_overlay(self, ox: int, oy: int, w: int, h: int):
        # Dim background
        self.canvas.create_rectangle(ox, oy, ox + w, oy + h, fill="#000000", outline="", stipple="gray50")
        # Centered panel
        cx, cy = ox + w // 2, oy + h // 2
        pw, ph = max(260, w // 3), max(120, h // 6)
        x0, y0 = cx - pw // 2, cy - ph // 2
        x1, y1 = cx + pw // 2, cy + ph // 2
        self.canvas.create_rectangle(x0, y0, x1, y1, fill="#101010", outline="#e0e000")
        self.canvas.create_text(cx, cy, text="Paused\nS: Save   L: Load\nP: Unpause", fill="#ffff80", font=self.hud_font, anchor="c")

    def _draw_help_overlay(self, ox: int, oy: int, w: int, h: int, ch_w: int, ch_h: int):
        # Modal matte + centered panel with legend
        self.canvas.create_rectangle(ox, oy, ox + w, oy + h, fill="#000000", outline="", stipple="gray50")
        g = self.game
        help_lines = []
        legend = [
            "Help (H to close):",
            "",
            "Legend:",
            f"Walls: █",
            f"Floor: '·' in FOV, space outside",
            "Unknown: space",
            "Player: @ bright white/yellow",
            "Enemies: g Goblin green, a Archer cyan, p Priest magenta, T Troll green, s Shaman yellow",
            "> Exit, ! Potion",
            "",
            "Controls:",
            "WASD/Arrows move; . wait; P pause; I inspect; H help; R restart; Q quit",
            "Paused: S save, L load",
            "",
            "Turn order: You -> Enemies -> Log fold",
        ]
        for s in legend:
            help_lines.extend(g._wrap(s, RIGHT_PANE_W))
        # Compose modal content
        panel_chars = 46
        pad_px = max(8, int(ch_h * 0.8))
        lines: List[str] = []
        lines.extend(g._wrap("Controls & Legend", panel_chars))
        lines.append("")
        lines.extend(g._wrap("Legend:", panel_chars))
        lines.extend(g._wrap("Walls: #", panel_chars))
        lines.extend(g._wrap("Floor: '.' in FOV, space outside", panel_chars))
        lines.extend(g._wrap("Unknown: space", panel_chars))
        lines.extend(g._wrap("Player: @ bright", panel_chars))
        lines.extend(g._wrap("Enemies: g Goblin, a Archer, p Priest, T Troll, s Shaman", panel_chars))
        lines.append("")
        lines.extend(g._wrap("Gameplay:", panel_chars))
        lines.extend(g._wrap("WASD/Arrows move; . wait; P pause; I inspect; H help; R restart; Q quit", panel_chars))
        lines.append("")
        lines.extend(g._wrap("Auto-Play controls:", panel_chars))
        lines.extend(g._wrap("A — toggle, [ / ] — speed, } — fast, P — pause", panel_chars))
        lines.append("")
        lines.extend(g._wrap("H/Esc — close", panel_chars))
        # Extra: doors and abilities
        lines.append("")
        lines.extend(g._wrap("Doors: '+' closed, '*' locked (need Key), '/' open", panel_chars))
        lines.extend(g._wrap("Abilities:", panel_chars))
        lines.extend(g._wrap("Archer: Aim then Shot (2-5 tiles, +100% next shot)", panel_chars))
        lines.extend(g._wrap("Priest: Shield (+temp HP, 3 turns)", panel_chars))
        lines.extend(g._wrap("Troll: Regen (+1 HP/turn; Tier 3: +2)", panel_chars))
        lines.extend(g._wrap("Shaman: Frenzy ally (+1 ATK, 3) or Hex player (-1 ATK, 3)", panel_chars))
        lines.append("")
        lines.extend(g._wrap("Bot: avoids Archer LOS; opens doors; uses keys", panel_chars))
        # Measure and draw panel
        text_w = panel_chars * max(1, ch_w)
        text_h = len(lines) * max(1, ch_h)
        panel_w = text_w + pad_px * 2
        panel_h = text_h + pad_px * 2
        cx, cy = ox + w // 2, oy + h // 2
        x0, y0 = cx - panel_w // 2, cy - panel_h // 2
        x1, y1 = cx + panel_w // 2, cy + panel_h // 2
        self.canvas.create_rectangle(x0, y0, x1, y1, fill="#101010", outline="#80c080")
        tx, ty = x0 + pad_px, y0 + pad_px
        for i, s in enumerate(lines):
            self.canvas.create_text(tx, ty + i * ch_h, text=s, fill="#c0ffc0", font=self.hud_font, anchor="nw")

    def _toast(self, text: str, ms: int = 1200):
        self._status_text = text
        if self._status_after_id:
            try:
                self.root.after_cancel(self._status_after_id)
            except Exception:
                pass
        self._status_after_id = self.root.after(ms, self._clear_toast)

    def _clear_toast(self):
        self._status_text = None
        self._status_after_id = None
        self.redraw()

    # ---------- Menu actions ----------
    def menu_new_game(self):
        dlg = NewGameDialog(self.root, self.game)
        self.root.wait_window(dlg)
        if dlg.result:
            self.game.new_game(is_restart=False)
            self.redraw()

    def menu_save(self):
        self.game.save_game()
        self._toast("Saved")
        self.redraw()

    def menu_open_config(self):
        p = patchloader.open_config_folder()
        if p:
            self._toast(f"Opened: {p}")
        else:
            self._toast("Open failed")

    def menu_import_patch(self):
        path = filedialog.askopenfilename(title="Import Patch", filetypes=[("Patch Zip", "*.zip"), ("All files", "*.*")])
        if not path:
            return
        dst = patchloader.import_patch_zip(path)
        if not dst:
            messagebox.showerror("Import failed", "Could not import patch zip. See logs/loader.log")
            return
        # Show info from manifest if any
        try:
            # Rescan so get_patches sees the new file
            patchloader.reload_all()
            info = None
            for p in patchloader.get_patches():
                if os.path.basename(p.path) == os.path.basename(dst):
                    info = p
                    break
            if info is not None:
                self._toast(f"Installed patch {info.id} v{info.version} (priority {info.priority})")
            else:
                self._toast("Patch installed")
        except Exception:
            self._toast("Patch installed")

    def menu_manage_patches(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Manage Patches")
        dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        rows = []
        ttk.Label(frm, text="Enabled").grid(row=0, column=0)
        ttk.Label(frm, text="Priority").grid(row=0, column=1)
        ttk.Label(frm, text="ID / File").grid(row=0, column=2)
        patches = patchloader.get_patches()
        for i, p in enumerate(patches, start=1):
            var_en = tk.BooleanVar(value=p.enabled)
            var_pr = tk.IntVar(value=p.priority)
            ttk.Checkbutton(frm, variable=var_en).grid(row=i, column=0, padx=4)
            sp = ttk.Spinbox(frm, from_=-999, to=999, textvariable=var_pr, width=6)
            sp.grid(row=i, column=1, padx=4)
            ttk.Label(frm, text=f"{p.id} v{p.version}  ({os.path.basename(p.path)})").grid(row=i, column=2, padx=6, sticky="w")
            rows.append((p, var_en, var_pr))
        btns = ttk.Frame(frm)
        btns.grid(row=len(rows)+1, column=0, columnspan=3, pady=(10,0), sticky="e")
        def apply_and_close():
            for p, ven, vpr in rows:
                try:
                    patchloader.set_patch_enabled(p.id, bool(ven.get()))
                    patchloader.adjust_patch_priority(p.id, int(vpr.get()))
                except Exception:
                    pass
            dlg.destroy()
            self.menu_reload()
        ttk.Button(btns, text="OK", command=apply_and_close).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Cancel", command=dlg.destroy).grid(row=0, column=1)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.wait_visibility()
        dlg.focus()

    def menu_reload(self):
        # Stop auto timers first
        self.game.auto_play = False
        try:
            self.var_auto.set(False)
        except Exception:
            pass
        self._ensure_auto()
        ok, msg = patchloader.reload_all()
        # Apply config overrides to game module
        try:
            import game as game_mod
            # Update ENEMY_TYPES and FOV
            base_defaults = list(getattr(game_mod, "_ENEMY_TYPES_DEFAULT", list(game_mod.ENEMY_TYPES)))
            game_mod.ENEMY_TYPES[:] = patchloader.finalize_enemy_types(base_defaults)
            cfg = patchloader.get_config()
            fov = int(((cfg.get("map") or {}).get("fov_radius") or game_mod.FOV_RADIUS))
            game_mod.FOV_RADIUS = max(1, fov)
        except Exception:
            pass
        self._toast(msg)
        # Redraw HUD/help/legend
        self.game.recompute_fov()
        self.redraw()

    # ---------- Live Watcher ----------
    def _schedule_live_check(self):
        try:
            if self._live_after_id:
                self.root.after_cancel(self._live_after_id)
        except Exception:
            pass
        # Poll every ~350ms
        self._live_after_id = self.root.after(350, self._check_live_reload)

    def _check_live_reload(self):
        try:
            if patchloader.has_pending_reload():
                reasons = patchloader.consume_reload_reasons()
                before = [p.id for p in patchloader.get_patches() if getattr(p, 'enabled', True)]
                ok, _ = patchloader.reload_all()
                # Apply config overrides to game module
                try:
                    import game as game_mod
                    base_defaults = list(getattr(game_mod, "_ENEMY_TYPES_DEFAULT", list(game_mod.ENEMY_TYPES)))
                    game_mod.ENEMY_TYPES[:] = patchloader.finalize_enemy_types(base_defaults)
                    cfg = patchloader.get_config()
                    fov = int(((cfg.get("map") or {}).get("fov_radius") or game_mod.FOV_RADIUS))
                    game_mod.FOV_RADIUS = max(1, fov)
                except Exception:
                    pass
                # Toasts according to reasons and diff
                after = [p.id for p in patchloader.get_patches() if getattr(p, 'enabled', True)]
                new = [x for x in after if x not in before]
                removed = [x for x in before if x not in after]
                if ok:
                    if ("config" in reasons) and (len(reasons) == 1):
                        self._toast("Config updated — reloaded")
                    elif ("assets" in reasons) and (len(reasons) == 1):
                        self._toast("Assets updated — reloaded")
                    elif "patches" in reasons:
                        if new:
                            self._toast(f"New patch: {new[0]} — applied")
                        elif removed:
                            self._toast("Patch removed — reloaded")
                        else:
                            self._toast("Patches updated — applied")
                    elif "mods" in reasons:
                        self._toast("Bot AI updated — next tick uses new logic")
                    else:
                        self._toast("Reloaded patches: OK")
                else:
                    self._toast("Patch apply FAILED — reverted")
                # Redraw HUD/help/legend
                self.game.recompute_fov()
                self.redraw()
        except Exception:
            pass
        finally:
            self._schedule_live_check()

    def menu_load(self):
        if self.game.load_game():
            self._toast("Loaded")
        self.redraw()

    def menu_help(self):
        self.game.help_mode = True
        self.redraw()

    def menu_toggle_auto(self):
        self.game.auto_play = bool(self.var_auto.get())
        self._toast(f"Auto: {'ON' if self.game.auto_play else 'OFF'}")
        self._ensure_auto()
        self.redraw()

    def menu_speed_change(self):
        v = int(self.var_speed.get())
        self.game.auto_ticks_per_sec = v
        self._toast(f"Speed: {v} tps")
        self._ensure_auto()
        self.redraw()

    def menu_toggle_fast(self):
        self.game.auto_fast = bool(self.var_fast.get())
        self.game._set_auto_fast_params()
        self._toast("Fast mode: " + ("ON" if self.game.auto_fast else "OFF"))
        self._ensure_auto()
        self.redraw()

    def menu_toggle_ar_death(self):
        self.game.auto_restart_on_death = bool(self.var_ar_death.get())
        self._toast("Auto-Restart on Death: " + ("ON" if self.game.auto_restart_on_death else "OFF"))
        self._ensure_auto()
        self.redraw()

    def menu_toggle_ar_victory(self):
        self.game.auto_restart_on_victory = bool(self.var_ar_victory.get())
        self._toast("Auto-Restart on Victory: " + ("ON" if self.game.auto_restart_on_victory else "OFF"))
        self._ensure_auto()
        self.redraw()

    def menu_start_demo(self):
        # New random game + enable auto at 16 tps
        self.game.menu_seed_random = True
        self.game.menu_seed_value = -1
        self.game.new_game(is_restart=False)
        self.game.auto_ticks_per_sec = 16
        try:
            self.var_speed.set(16)
        except Exception:
            pass
        self.game.auto_play = True
        try:
            self.var_auto.set(True)
        except Exception:
            pass
        self._toast("Demo started: Auto 16 tps")
        self._ensure_auto()
        self.redraw()

    def menu_series(self):
        dlg = SeriesDialog(self.root)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        runs, fixed, show_every, tier, use_rooms = dlg.result
        self.start_series(runs, fixed, show_every, tier=tier, use_rooms=use_rooms)

    def start_series(self, runs: int, fixed_seed: bool, show_every: int, tier: int = 1, use_rooms: bool = True):
        # Initialize counters
        self._series_active = True
        self._series_total = max(1, int(runs))
        self._series_done = 0
        self._series_wins = 0
        self._series_losses = 0
        self._series_sum_turns = 0
        self._series_sum_kills = 0
        self._series_sum_dmg_taken = 0
        self._series_sum_dmg_dealt = 0
        self._series_sum_items_used = 0
        self._series_fixed_seed = bool(fixed_seed)
        self._series_show_every = max(0, int(show_every))
        self._series_base_seed = int(self.game.menu_seed_value if not self.game.menu_seed_random else int(time.time() * 1000))
        self._series_tier = int(tier)
        self._series_use_rooms = bool(use_rooms)
        # Configure game
        self.game.auto_play = True
        try:
            self.var_auto.set(True)
        except Exception:
            pass
        self.game.auto_fast = True
        try:
            self.var_fast.set(True)
        except Exception:
            pass
        if self._series_show_every <= 0:
            self.game.auto_render_every_n_ticks = 10**9
        else:
            self.game.auto_render_every_n_ticks = max(1, int(self._series_show_every))
        # Start first run
        self._series_next_run()
        self._ensure_auto()

    def _series_next_run(self):
        if self._series_done >= self._series_total:
            self._series_finish()
            return
        # Seed setup
        if self._series_fixed_seed:
            self.game.menu_seed_random = False
            self.game.menu_seed_value = self._series_base_seed
        else:
            self.game.menu_seed_random = True
            self.game.menu_seed_value = -1
        # Apply series-tier and generator
        self.game.menu_tier = int(getattr(self, '_series_tier', 1))
        self.game.menu_use_rooms = bool(getattr(self, '_series_use_rooms', True))
        self.game.new_game(is_restart=False)
        self.game._series_mode = True
        self._series_done += 1
        self._toast(f"Series: run {self._series_done}/{self._series_total}")
        self.redraw()

    def _series_finish(self):
        self.game._series_mode = False
        self._series_active = False
        N = max(1, int(self._series_total))
        winrate = (self._series_wins / N) * 100.0
        lines = [
            f"Runs: {N}",
            f"Wins: {self._series_wins}",
            f"Losses: {self._series_losses}",
            f"Winrate: {winrate:.1f}%",
            f"Avg Turns: {self._series_sum_turns / N:.1f}",
            f"Avg Kills: {self._series_sum_kills / N:.1f}",
            f"Avg Damage Taken: {self._series_sum_dmg_taken / N:.1f}",
            f"Avg Damage Dealt: {self._series_sum_dmg_dealt / N:.1f}",
            f"Avg Items Used: {self._series_sum_items_used / N:.2f}",
            f"Tier: {getattr(self, '_series_tier', 1)}",
        ]
        # Extra metrics
        try:
            lines.append(f"Times Hexed: {int(self._series_sum_times_hexed)}")
            lines.append(f"Shots dodged (Aim): {int(self._series_sum_shots_dodged)}")
            if self._series_kills_by_role:
                parts = [f"{k} {v}" for k, v in self._series_kills_by_role.items()]
                lines.append("Kills by role: " + ", ".join(parts))
        except Exception:
            pass
        self._series_report_lines = lines
        SeriesResultsDialog(self.root, lines)
        self.redraw()

    # ---------- Helpers ----------
    def _normalize_key(self, event: tk.Event) -> Optional[str]:
        keysym = event.keysym or ""
        ks = keysym
        low = ks.lower()
        # Arrows
        if ks in ("Up", "Down", "Left", "Right"):
            return ks.upper()
        if ks == "F9":
            return "F9"
        # Escape/Enter
        if ks == "Escape":
            return "ESC"
        if ks == "Return":
            return "ENTER"
        # Period
        if low in ("period", "kp_decimal") or event.char == ".":
            return "."
        # Brackets/speed and brace fast by keysym
        if low in ("bracketleft", "minus"):
            return "["
        if low in ("bracketright", "equal", "plus"):
            return "]"
        if low == "braceright":
            return "}"
        # Auto toggle: A and Cyrillic ef (ф/Ф)
        if low == "a" or event.char in ("a", "A", "ф", "Ф") or low in ("ф", "cyrillic_ef"):
            return "A"
        # Letters fallback
        ch = event.char or ""
        if len(ch) == 1 and ch.isalpha():
            return ch.upper()
        return None

    def _dir_from_key(self, key: str) -> Optional[Tuple[int, int]]:
        dir_map = {
            "UP": (0, -1),
            "DOWN": (0, 1),
            "LEFT": (-1, 0),
            "RIGHT": (1, 0),
            "W": (0, -1),
            "S": (0, 1),
            "A": (-1, 0),
            "D": (1, 0),
        }
        return dir_map.get(key)

    def _color_for_entity(self, e) -> str:
        name = (e.name or "").lower()
        ch = e.ch
        if name == "goblin" or ch == "g":
            return "#00cc00"
        if name == "archer" or ch == "a":
            return "#00ffff"
        if name == "priest" or ch == "p":
            return "#a060ff"
        if name == "troll" or ch in ("t", "T"):
            return "#006600"
        if name == "shaman" or ch == "s":
            return "#ff8800"
        if name == "player" or ch == "@":
            return "#ffffff"
        return "#ffffff"

    def _ingest_damage_events(self):
        # Pull new damage events from game and register popups for ~600ms
        g = self.game
        events = getattr(g, 'damage_events', None)
        if not events:
            return
        now = time.time()
        for ev in events:
            try:
                ex = int(ev.get("x", 0))
                ey = int(ev.get("y", 0))
                dmg = int(ev.get("dmg", 0))
                self._active_popups.append({
                    "x": ex,
                    "y": ey,
                    "dmg": dmg,
                    "until": now + 0.6,
                })
            except Exception:
                pass
        # Clear events from game after ingestion
        g.damage_events = []

    def _ensure_tick(self):
        # Schedule a short-lived animation loop to refresh popups
        if not getattr(self, "_tick_scheduled", False):
            self._tick_scheduled = True
            self.root.after(80, self._tick)

    def _tick(self):
        # Prune expired popups and redraw if any remain
        now = time.time()
        before = len(self._active_popups)
        self._active_popups = [ev for ev in self._active_popups if ev.get("until", 0) > now]
        if self._active_popups:
            self.redraw()
            self.root.after(80, self._tick)
        else:
            self._tick_scheduled = False

    # ---------- Auto-play scheduling ----------
    def _ensure_auto(self):
        # Cancel any previous
        if self._auto_after_id:
            try:
                self.root.after_cancel(self._auto_after_id)
            except Exception:
                pass
            self._auto_after_id = None
        if not self.game.auto_play:
            return
        # Schedule next tick
        tps = max(1, int(self.game.auto_ticks_per_sec))
        delay = max(1, int(1000 // tps))
        self._auto_after_id = self.root.after(delay, self._auto_tick)

    def _auto_tick(self):
        self._auto_after_id = None
        g = self.game
        if not g.auto_play:
            return
        # Pause auto when modal overlays are open
        if g.help_mode or g.inspect_mode:
            self.redraw()
            self._ensure_auto()
            return
        # Perform one tick only if playing
        if g.state == "playing":
            g.auto_tick()
            self._auto_counter += 1
        else:
            # End of run handling for series
            if self._series_active and g.state in ("victory", "game_over"):
                if g.state == "victory":
                    self._series_wins += 1
                else:
                    self._series_losses += 1
                self._series_sum_turns += int(g.turn)
                self._series_sum_kills += int(g.run_kills)
                self._series_sum_dmg_taken += int(g.run_dmg_taken)
                self._series_sum_dmg_dealt += int(g.run_dmg_dealt)
                self._series_sum_items_used += int(g.run_items_used)
                # Extra metrics from run
                try:
                    self._series_sum_times_hexed += int(getattr(g, 'run_times_hexed', 0))
                    self._series_sum_shots_dodged += int(getattr(g, 'run_shots_dodged', 0))
                    kb = dict(getattr(g, 'run_kills_by_role', {}) or {})
                    for k, v in kb.items():
                        self._series_kills_by_role[k] = self._series_kills_by_role.get(k, 0) + int(v)
                except Exception:
                    pass
                # Next run after short delay
                self.root.after(max(1, int(g.auto_restart_delay_ms)), self._series_next_run)
            elif (g.state in ("victory", "game_over")):
                should = (g.state == "victory" and g.auto_restart_on_victory) or (g.state == "game_over" and g.auto_restart_on_death)
                if should:
                    self.root.after(max(1, int(g.auto_restart_delay_ms)), lambda: (g.new_game(is_restart=True), self.redraw()))
        # Redraw per fast mode (skip if hidden during series)
        should_draw = (not g.auto_fast) or (self._auto_counter % max(1, g.auto_render_every_n_ticks) == 0)
        if self._series_active and self._series_show_every == 0:
            should_draw = False
        if should_draw:
            self.redraw()
        self._ensure_auto()

    # ---------- Mouse handlers ----------
    def on_click(self, event: tk.Event):
        bbox = getattr(self, "_auto_btn_bbox", None)
        if bbox:
            x0, y0, x1, y1 = bbox
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.game.auto_play = not self.game.auto_play
                try:
                    self.var_auto.set(self.game.auto_play)
                except Exception:
                    pass
                if self.game.auto_play:
                    self._toast(f"Auto: ON ({max(1,int(self.game.auto_ticks_per_sec))} tps)")
                else:
                    self._toast("Auto: OFF")
                self._ensure_auto()
                self.redraw()


__all__ = ["GuiApp", "enable_dpi_awareness"]
