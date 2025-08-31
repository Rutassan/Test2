import os
import sys
import math
import time
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import font as tkfont
from typing import Optional, Tuple, List

from game import Game, RIGHT_PANE_W, HUD_LOG_LINES, visible_enemies_list, _dir_to_compass, _inspect_info_lines, build_help_frame


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

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=3, pady=(10, 0), sticky="e")
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
        self.result = True
        self.destroy()

    def on_cancel(self):
        self.result = False
        self.destroy()


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

        # Input bindings
        self.root.bind("<KeyPress>", self.on_key)
        self.root.bind("<Configure>", self.on_resize)
        self.root.bind("<Button-1>", self.on_click)

        # Menu bar
        self._build_menu()

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
        file_menu.add_separator()
        file_menu.add_command(label="Start Demo", command=self.menu_start_demo)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Controls & Legend", command=self.menu_help)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

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

        # Draw corpses silhouettes (explored and visible or explored only?)
        for (cx, cy, kind) in getattr(g, 'corpses', []):
            if 0 <= cx < map_cols and 0 <= cy < map_rows and g.map.explored[cy][cx]:
                x0 = ox + cx * tile
                y0 = oy + cy * tile
                pad = max(2, tile // 8)
                self.canvas.create_oval(x0 + pad, y0 + pad, x0 + tile - pad, y0 + tile - pad, fill="#606060", outline="")

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
        if g.state in ("playing", "paused", "game_over"):
            status_line = f"HP {g.player.hp}/{g.player.max_hp}  ATK {g.player.power}  Turn {g.turn}  Seed {g.seed}"
        else:
            seed_str = (str(g.menu_seed_value) if not g.menu_seed_random else "random")
            status_line = f"HP -/-  ATK -  Turn -  Seed {seed_str}"
        controls_line = "WASD/Arrows: move  .: wait  P: pause  I: inspect  H: help"
        auto_speed = max(1, int(g.auto_ticks_per_sec))
        auto_on = "ON" if g.auto_play else "OFF"
        fast_suffix = f"  Fast: {'ON' if g.auto_fast else 'OFF'}"
        auto_line = f"AUTO: {auto_on}  Speed: {auto_speed} tps{fast_suffix}  (A toggle, [ ] speed, }} fast)"
        pane_lines: List[str] = [status_line, controls_line, auto_line]
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
            if line.strip().startswith("AUTO:") and g.auto_play:
                fill = "#d8ffb0"
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
            "> exit (if present)",
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

    # ---------- Helpers ----------
    def _normalize_key(self, event: tk.Event) -> Optional[str]:
        keysym = event.keysym or ""
        ks = keysym
        low = ks.lower()
        # Arrows
        if ks in ("Up", "Down", "Left", "Right"):
            return ks.upper()
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
        # Redraw per fast mode
        if (not g.auto_fast) or (self._auto_counter % max(1, g.auto_render_every_n_ticks) == 0):
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
