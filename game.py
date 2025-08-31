import os
import sys
import json
import math
import random
import time
from typing import List, Tuple, Optional, Dict, Any

# Windows-specific imports
import msvcrt
import ctypes


# Console helpers
STD_OUTPUT_HANDLE = -11
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def enable_ansi() -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        hOut = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(hOut, ctypes.byref(mode)) == 0:
            return False
        new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if kernel32.SetConsoleMode(hOut, new_mode) == 0:
            return False
        return True
    except Exception:
        return False


def hide_cursor(ansi: bool):
    if ansi:
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()


def show_cursor(ansi: bool):
    if ansi:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


RESET = "\x1b[0m"
FG_WHITE = "\x1b[37m"
FG_BRIGHT_WHITE = "\x1b[97m"
FG_GRAY = "\x1b[90m"
FG_GREEN = "\x1b[32m"
FG_BRIGHT_GREEN = "\x1b[92m"
FG_RED = "\x1b[31m"
FG_YELLOW = "\x1b[33m"
FG_CYAN = "\x1b[36m"
FG_MAGENTA = "\x1b[35m"
FG_ORANGE = "\x1b[38;5;208m"


DEFAULT_W = 40
DEFAULT_H = 20
FOV_RADIUS = 8
RIGHT_PANE_W = 38
HUD_LOG_LINES = 7  # reserve 6–8 lines for folded log

WALL_CHAR = "█"
FLOOR_CHAR = "·"
UNKNOWN_CHAR = " "
WALL_CHAR = "\u2588"  # full block
FLOOR_CHAR = "\u00B7"  # middle dot

# Centralized enemy type definitions for both console and GUI paths
# Each entry: (name, ch, color_visible, color_dim, hp, power, weight)
ENEMY_TYPES: List[Tuple[str, str, str, str, int, int, int]] = [
    ("Goblin", "g", FG_BRIGHT_GREEN, FG_GREEN, 8, 3, 4),
    ("Archer", "a", FG_CYAN, FG_CYAN, 6, 2, 2),
    ("Priest", "p", FG_MAGENTA, FG_MAGENTA, 7, 2, 2),
    ("Troll", "T", FG_GREEN, FG_GREEN, 14, 5, 2),
    ("Shaman", "s", FG_ORANGE, FG_YELLOW, 9, 3, 2),
]


class Logger:
    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self.lines: List[str] = []

    def log(self, msg: str):
        self.lines.append(msg)
        if len(self.lines) > self.capacity:
            self.lines = self.lines[-self.capacity :]

    def serialize(self) -> List[str]:
        return list(self.lines)

    def deserialize(self, data: List[str]):
        self.lines = list(data)[-self.capacity :]


class Tile:
    def __init__(self, walkable: bool):
        self.walkable = walkable


class Map:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.tiles: List[List[Tile]] = [[Tile(False) for _ in range(w)] for _ in range(h)]
        self.explored: List[List[bool]] = [[False for _ in range(w)] for _ in range(h)]

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def is_walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return self.tiles[y][x].walkable

    def carve(self, x: int, y: int):
        if self.in_bounds(x, y):
            self.tiles[y][x].walkable = True

    def generate(self, rng: random.Random):
        # Drunkard walk generation ensuring connectivity
        # Start from center
        self.tiles = [[Tile(False) for _ in range(self.w)] for _ in range(self.h)]
        self.explored = [[False for _ in range(self.w)] for _ in range(self.h)]
        start_x = self.w // 2
        start_y = self.h // 2
        x, y = start_x, start_y
        self.carve(x, y)
        target_floor = int(self.w * self.h * 0.45)
        carved = 1
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        attempts = 0
        max_attempts = self.w * self.h * 50
        while carved < target_floor and attempts < max_attempts:
            dx, dy = rng.choice(directions)
            nx, ny = x + dx, y + dy
            if 1 <= nx < self.w - 1 and 1 <= ny < self.h - 1:
                if not self.tiles[ny][nx].walkable:
                    self.tiles[ny][nx].walkable = True
                    carved += 1
                x, y = nx, ny
            attempts += 1
        # Add some random room carves for openness, but ensure adjacency to existing floor
        for _ in range(20):
            rx = rng.randrange(1, self.w - 2)
            ry = rng.randrange(1, self.h - 2)
            rw = rng.randrange(2, 6)
            rh = rng.randrange(2, 5)
            has_adjacent = False
            for yy in range(max(1, ry - 1), min(self.h - 1, ry + rh + 1)):
                for xx in range(max(1, rx - 1), min(self.w - 1, rx + rw + 1)):
                    if self.tiles[yy][xx].walkable:
                        has_adjacent = True
                        break
                if has_adjacent:
                    break
            if not has_adjacent:
                continue
            for yy in range(ry, min(self.h - 1, ry + rh)):
                for xx in range(rx, min(self.w - 1, rx + rw)):
                    self.tiles[yy][xx].walkable = True

        # Enforce single connected component: flood fill from start, wall off unreachable floors
        reachable = [[False for _ in range(self.w)] for _ in range(self.h)]
        stack = [(start_x, start_y)]
        while stack:
            cx, cy = stack.pop()
            if not (0 <= cx < self.w and 0 <= cy < self.h):
                continue
            if reachable[cy][cx] or not self.tiles[cy][cx].walkable:
                continue
            reachable[cy][cx] = True
            for dx, dy in directions:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < self.w and 0 <= ny < self.h and not reachable[ny][nx] and self.tiles[ny][nx].walkable:
                    stack.append((nx, ny))
        for y in range(self.h):
            for x in range(self.w):
                if self.tiles[y][x].walkable and not reachable[y][x]:
                    self.tiles[y][x].walkable = False

    def serialize(self) -> Dict[str, Any]:
        return {
            "w": self.w,
            "h": self.h,
            "tiles": [[1 if self.tiles[y][x].walkable else 0 for x in range(self.w)] for y in range(self.h)],
            "explored": self.explored,
        }

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "Map":
        m = Map(data["w"], data["h"])
        for y in range(m.h):
            for x in range(m.w):
                m.tiles[y][x].walkable = bool(data["tiles"][y][x])
        m.explored = data.get("explored", [[False for _ in range(m.w)] for _ in range(m.h)])
        return m


class Entity:
    def __init__(self, x: int, y: int, ch: str, color_visible: str, color_dim: str, name: str, hp: int, power: int):
        self.x = x
        self.y = y
        self.ch = ch
        self.color_visible = color_visible
        self.color_dim = color_dim
        self.name = name
        self.hp = hp
        self.max_hp = hp
        self.power = power

    def pos(self) -> Tuple[int, int]:
        return self.x, self.y

    def is_alive(self) -> bool:
        return self.hp > 0

    def serialize(self) -> Dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "ch": self.ch,
            "name": self.name,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "power": self.power,
        }

    @staticmethod
    def deserialize(data: Dict[str, Any], color_visible: str, color_dim: str) -> "Entity":
        e = Entity(data["x"], data["y"], data["ch"], color_visible, color_dim, data["name"], data["hp"], data["power"])
        e.max_hp = data.get("max_hp", e.hp)
        return e


class Game:
    def __init__(self):
        self.state: str = "menu"  # menu, playing, paused, game_over
        self.turn: int = 0
        self.seed: int = 1337
        self.rng = random.Random(self.seed)
        self.map = Map(DEFAULT_W, DEFAULT_H)
        self.player = Entity(0, 0, "@", FG_BRIGHT_WHITE, FG_BRIGHT_WHITE, "Player", 20, 5)
        self.enemies: List[Entity] = []
        self.visible: List[List[bool]] = [[False for _ in range(self.map.w)] for _ in range(self.map.h)]
        self.logger = Logger()
        # Menu settings
        self.menu_seed_value: int = 1337
        self.menu_seed_random: bool = False
        self.menu_width: int = DEFAULT_W
        self.menu_height: int = DEFAULT_H
        self.menu_enemies: int = 8
        self.menu_sel: int = 0  # 0=Seed,1=Width,2=Height,3=Enemies
        # Terminal capabilities
        self.ansi: bool = enable_ansi()
        hide_cursor(self.ansi)
        # Turn digest/flash and overlays
        self._digest: Optional[TurnDigest] = None
        self.flash_positions: List[Tuple[int, int]] = []
        # Damage popup events (for GUI renderer): list of dicts {x,y,dmg,time}
        self.damage_events: List[Dict[str, Any]] = []
        # Corpses to render (for GUI renderer): list of tuples (x, y, kind)
        self.corpses: List[Tuple[int, int, str]] = []
        self.inspect_mode: bool = False
        self.inspect_x: int = 0
        self.inspect_y: int = 0
        self.help_mode: bool = False

        # Auto-play/bot state
        self.auto_play: bool = False
        # Allowed speeds: 4, 8, 16, 32, 64 tps
        self.auto_ticks_per_sec: int = 16
        # Fast mode: redraw every N ticks instead of each
        self.auto_fast: bool = False
        self.auto_render_every_n_ticks: int = 1  # computed from fast flag
        self._auto_tick_counter: int = 0
        self._auto_last_pos: Tuple[int, int] = (0, 0)
        self._auto_no_progress_ticks: int = 0
        self._auto_target_desc: Optional[str] = None
        self._auto_path: Optional[List[Tuple[int, int]]] = None  # full path including next cells
        # Optional behaviors
        self.auto_restart_on_death: bool = False
        self.auto_restart_on_victory: bool = False

    def random_enemy(self) -> Entity:
        """Return a newly created random enemy Entity using internal RNG.

        Selection uses weighted probabilities defined in ENEMY_TYPES.
        No rendering or logging here; caller is responsible for placement.
        """
        # Prepare a flat population according to weights to keep compatibility
        # across Python versions/environments without relying on random.choices
        pop: List[Tuple[str, str, str, str, int, int]] = []
        for name, ch, cv, cd, hp, pow_, weight in ENEMY_TYPES:
            if weight > 0:
                pop.extend([(name, ch, cv, cd, hp, pow_)] * int(weight))
        if not pop:
            # Fallback: ensure at least a goblin if misconfigured
            name, ch, cv, cd, hp, pow_ = ("Goblin", "g", FG_BRIGHT_GREEN, FG_GREEN, 8, 3)
        else:
            name, ch, cv, cd, hp, pow_ = self.rng.choice(pop)
        return Entity(0, 0, ch, cv, cd, name, hp, pow_)

    def new_game(self, is_restart: bool = False):
        # Determine seed
        if self.menu_seed_random:
            self.seed = int(time.time() * 1000) & 0xFFFFFFFF
        else:
            self.seed = int(self.menu_seed_value) & 0xFFFFFFFF
        self.rng = random.Random(self.seed)
        # Resize map if needed
        self.map = Map(self.menu_width, self.menu_height)
        self.visible = [[False for _ in range(self.map.w)] for _ in range(self.map.h)]
        self.map.generate(self.rng)
        self.turn = 1
        # Place player
        self.player = Entity(0, 0, "@", FG_BRIGHT_WHITE, FG_BRIGHT_WHITE, "Player", 20, 5)
        self.player.max_hp = 20
        self.place_entity_random_floor(self.player)
        # Place enemies
        self.enemies = []
        # Clear ephemeral/visual-only state
        self.damage_events = []
        self.corpses = []
        for _ in range(max(0, self.menu_enemies)):
            e = self.random_enemy()
            self.place_entity_random_floor(e, avoid=[self.player] + self.enemies)
            self.enemies.append(e)
        if is_restart:
            self.logger.log("Restarted.")
        else:
            self.logger.log(f"New game. Seed={self.seed}")
        self.state = "playing"
        self.recompute_fov()

    def place_entity_random_floor(self, ent: Entity, avoid: Optional[List[Entity]] = None):
        if avoid is None:
            avoid = []
        max_tries = 1000
        for _ in range(max_tries):
            x = self.rng.randrange(1, self.map.w - 1)
            y = self.rng.randrange(1, self.map.h - 1)
            if self.map.is_walkable(x, y) and all((x, y) != a.pos() for a in avoid):
                ent.x, ent.y = x, y
                return
        # fallback
        for y in range(self.map.h):
            for x in range(self.map.w):
                if self.map.is_walkable(x, y) and all((x, y) != a.pos() for a in avoid):
                    ent.x, ent.y = x, y
                    return

    def bresenham_line(self, x0: int, y0: int, x1: int, y1: int) -> List[Tuple[int, int]]:
        points = []
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            points.append((x, y))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy
        return points

    def has_los(self, x0: int, y0: int, x1: int, y1: int, radius: int) -> bool:
        if (x1 - x0) ** 2 + (y1 - y0) ** 2 > radius * radius:
            return False
        for i, (x, y) in enumerate(self.bresenham_line(x0, y0, x1, y1)):
            if i == 0:
                continue
            if x == x1 and y == y1:
                return True
            if not self.map.is_walkable(x, y):
                return False
        return True

    def recompute_fov(self):
        self.visible = [[False for _ in range(self.map.w)] for _ in range(self.map.h)]
        px, py = self.player.x, self.player.y
        for y in range(self.map.h):
            for x in range(self.map.w):
                if self.has_los(px, py, x, y, FOV_RADIUS):
                    self.visible[y][x] = True
                    self.map.explored[y][x] = True

    def entity_at(self, x: int, y: int) -> Optional[Entity]:
        if self.player.x == x and self.player.y == y and self.player.is_alive():
            return self.player
        for e in self.enemies:
            if e.x == x and e.y == y and e.is_alive():
                return e
        return None

    def is_blocked(self, x: int, y: int) -> bool:
        if not self.map.is_walkable(x, y):
            return True
        if self.player.x == x and self.player.y == y and self.player.is_alive():
            return True
        for e in self.enemies:
            if e.x == x and e.y == y and e.is_alive():
                return True
        return False

    def move_entity(self, ent: Entity, dx: int, dy: int, attack_on_block: bool = True):
        nx, ny = ent.x + dx, ent.y + dy
        if not self.map.in_bounds(nx, ny):
            return
        if self.map.is_walkable(nx, ny):
            target = None
            if ent is self.player:
                target = next((e for e in self.enemies if e.x == nx and e.y == ny and e.is_alive()), None)
            else:
                if self.player.x == nx and self.player.y == ny and self.player.is_alive():
                    target = self.player
            if target is None:
                ent.x, ent.y = nx, ny
            else:
                if attack_on_block:
                    self.attack(ent, target)

    def attack(self, attacker: Entity, defender: Entity):
        dmg = attacker.power
        defender.hp -= dmg
        # One-frame flash at defender location
        self.flash_positions.append((defender.x, defender.y))
        # GUI damage popup event (store raw event; GUI will expire it)
        try:
            self.damage_events.append({
                "x": defender.x,
                "y": defender.y,
                "dmg": int(dmg),
                "time": time.time(),
                "attacker": attacker.name,
                "defender": defender.name,
            })
        except Exception:
            # In non-GUI/older runs just ignore
            pass
        # Fold into digest if present
        if hasattr(self, "_digest") and self._digest is not None:
            self._digest.record_attack(attacker, defender, dmg)
        else:
            if attacker is self.player:
                self.logger.log(f"You hit {defender.name} for {dmg}.")
            elif defender is self.player:
                self.logger.log(f"{attacker.name} hits you for {dmg}.")
            else:
                self.logger.log(f"{attacker.name} hits {defender.name} for {dmg}.")
        if defender.hp <= 0:
            if defender is self.player:
                self.logger.log("You died!")
                self.state = "game_over"
            else:
                if hasattr(self, "_digest") and self._digest is not None:
                    self._digest.record_kill(attacker, defender)
                else:
                    self.logger.log(f"{defender.name} dies.")
                # Record corpse for GUI rendering (silhouette)
                try:
                    self.corpses.append((defender.x, defender.y, defender.name or defender.ch))
                except Exception:
                    pass

    def enemy_turns(self):
        for e in self.enemies:
            if not e.is_alive():
                continue
            if not self.player.is_alive():
                break
            # If adjacent to player, attack
            if abs(e.x - self.player.x) + abs(e.y - self.player.y) == 1:
                self.attack(e, self.player)
                continue
            # If has line of sight, move towards player
            if self.has_los(e.x, e.y, self.player.x, self.player.y, radius=12):
                dx = 0 if e.x == self.player.x else (1 if self.player.x > e.x else -1)
                dy = 0 if e.y == self.player.y else (1 if self.player.y > e.y else -1)
                # Try axis that is farther first
                if abs(self.player.x - e.x) >= abs(self.player.y - e.y):
                    if not self.is_blocked(e.x + dx, e.y):
                        e.x += dx
                    elif not self.is_blocked(e.x, e.y + dy):
                        e.y += dy
                else:
                    if not self.is_blocked(e.x, e.y + dy):
                        e.y += dy
                    elif not self.is_blocked(e.x + dx, e.y):
                        e.x += dx
            else:
                # Wander randomly 30% of the time
                if self.rng.random() < 0.3:
                    dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (0, 0)]
                    dx, dy = self.rng.choice(dirs)
                    if not self.is_blocked(e.x + dx, e.y + dy):
                        e.x += dx
                        e.y += dy

    def handle_player_action(self, key: str) -> bool:
        # Returns True if turn consumed
        if key == ".":
            return True
        dir_map = {
            "UP": (0, -1),
            "DOWN": (0, 1),
            "LEFT": (-1, 0),
            "RIGHT": (1, 0),
            "w": (0, -1),
            "s": (0, 1),
            "a": (-1, 0),
            "d": (1, 0),
            "W": (0, -1),
            "S": (0, 1),
            "A": (-1, 0),
            "D": (1, 0),
        }
        if key in dir_map:
            dx, dy = dir_map[key]
            old_pos = (self.player.x, self.player.y)
            self.move_entity(self.player, dx, dy)
            if (self.player.x, self.player.y) != old_pos:
                return True
            # If didn't move, maybe attacked
            return True
        return False

    # ---------- Auto-play helpers ----------
    def _set_auto_fast_params(self):
        if self.auto_fast:
            # Render every N ticks in fast mode
            # Default to 4; can tweak if needed
            self.auto_render_every_n_ticks = 4
        else:
            self.auto_render_every_n_ticks = 1

    def _neighbors4(self, x: int, y: int) -> List[Tuple[int, int]]:
        cand = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        out: List[Tuple[int, int]] = []
        for nx, ny in cand:
            if self.map.in_bounds(nx, ny) and self.map.is_walkable(nx, ny):
                out.append((nx, ny))
        return out

    def _is_occupied(self, x: int, y: int) -> bool:
        if self.player.is_alive() and (x, y) == (self.player.x, self.player.y):
            return True
        for e in self.enemies:
            if e.is_alive() and (e.x, e.y) == (x, y):
                return True
        return False

    def _bfs_path(self, start: Tuple[int, int], goals: List[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
        """BFS on walkable cells avoiding occupied tiles, except allowing entering the goal tile.
        Returns full path list from start to goal inclusive; None if unreachable.
        """
        if not goals:
            return None
        W, H = self.map.w, self.map.h
        goal_set = set(goals)
        from collections import deque
        q = deque([start])
        came: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}
        while q:
            cur = q.popleft()
            if cur in goal_set:
                # reconstruct
                path: List[Tuple[int, int]] = []
                at = cur
                while at is not None:
                    path.append(at)
                    at = came[at]
                path.reverse()
                return path
            cx, cy = cur
            for nx, ny in self._neighbors4(cx, cy):
                nxt = (nx, ny)
                if nxt in came:
                    continue
                # allow stepping onto goal even if occupied; otherwise avoid occupied
                if nxt not in goal_set and self._is_occupied(nx, ny):
                    continue
                came[nxt] = cur
                q.append(nxt)
        return None

    def _frontier_targets(self) -> List[Tuple[int, int]]:
        """Tiles we know and that border unexplored space to encourage exploration without map cheating."""
        t: List[Tuple[int, int]] = []
        for y in range(self.map.h):
            for x in range(self.map.w):
                if not self.map.is_walkable(x, y):
                    continue
                if not (self.map.explored[y][x] or self.visible[y][x]):
                    continue
                # frontier if at least one neighbor is not explored
                for nx, ny in self._neighbors4(x, y):
                    if not self.map.explored[ny][nx]:
                        t.append((x, y))
                        break
        return t

    def _visible_enemies(self) -> List[Entity]:
        out: List[Entity] = []
        for e in self.enemies:
            if not e.is_alive():
                continue
            if 0 <= e.x < self.map.w and 0 <= e.y < self.map.h and self.visible[e.y][e.x]:
                out.append(e)
        return out

    def _nearest(self, src: Tuple[int, int], points: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        if not points:
            return None
        sx, sy = src
        points.sort(key=lambda p: abs(p[0] - sx) + abs(p[1] - sy))
        return points[0]

    def _estimate_risk_should_flee(self) -> bool:
        # Very simple: flee if HP < 40% or many enemies are adjacent/nearby with higher combined power.
        if self.player.hp <= max(1, int(self.player.max_hp * 0.4)):
            return True
        # Count enemies in radius 1 (Chebyshev 1)
        near_count = 0
        total_power = 0
        px, py = self.player.x, self.player.y
        for e in self._visible_enemies():
            if max(abs(e.x - px), abs(e.y - py)) <= 1:
                near_count += 1
                total_power += max(1, int(e.power))
        if near_count >= 2 and total_power >= self.player.hp // 2:
            return True
        return False

    def bot_choose_action(self) -> Tuple[str, Optional[Tuple[int, int]], Optional[List[Tuple[int, int]]], str]:
        """Plan one action.
        Returns: (kind, (dx,dy) or None, path or None, desc)
        kind in {"wait", "move"}
        desc is a short log message.
        """
        if self.state != "playing" or not self.player.is_alive():
            return ("wait", None, None, "idle")
        px, py = self.player.x, self.player.y

        # 1) Low HP: flee (no inventory system here)
        if self._estimate_risk_should_flee():
            # choose step that maximizes distance to nearest visible enemy
            vis = self._visible_enemies()
            if vis:
                best: Optional[Tuple[int, int]] = None
                best_score = -1
                for nx, ny in self._neighbors4(px, py) + [(px, py)]:
                    if (nx, ny) != (px, py) and self._is_occupied(nx, ny):
                        continue
                    score = min(abs(nx - e.x) + abs(ny - e.y) for e in vis)
                    if score > best_score:
                        best_score = score
                        best = (nx, ny)
                if best is not None and best != (px, py):
                    dx, dy = best[0] - px, best[1] - py
                    return ("move", (dx, dy), None, "flee (low HP)")
                return ("wait", None, None, "hold (corner)")

        # 2) Adjacent enemy: attack
        adj = [(e, abs(e.x - px) + abs(e.y - py)) for e in self._visible_enemies()]
        adj = [(e, d) for (e, d) in adj if d == 1]
        if adj:
            # Target priority: Shaman -> Priest -> Archer -> Troll -> Goblin
            def pri(name: str) -> int:
                n = name.lower()
                order = {"shaman": 0, "priest": 1, "archer": 2, "troll": 3, "goblin": 4}
                return order.get(n, 9)
            adj.sort(key=lambda t: (pri(t[0].name), t[0].hp))
            target = adj[0][0]
            dx = 0 if target.x == px else (1 if target.x > px else -1)
            dy = 0 if target.y == py else (1 if target.y > py else -1)
            return ("move", (dx, dy), None, f"attack {target.name}")

        # 3) Visible enemy: approach via BFS to enemy tile (allow attack on arrival)
        vis = self._visible_enemies()
        if vis:
            # nearest by BFS distance approx (use Manhattan heuristic for pick)
            goals = [(e.x, e.y) for e in vis]
            path = self._bfs_path((px, py), goals)
            if path and len(path) >= 2:
                nx, ny = path[1]
                dx, dy = nx - px, ny - py
                target = self._nearest((px, py), goals)
                steps = len(path) - 1
                who = next((e for e in vis if (e.x, e.y) == target), None)
                who_name = who.name if who else "enemy"
                return ("move", (dx, dy), path[1:7], f"path → {who_name} ({steps} steps)")

        # 4) Explore: go to nearest frontier
        frontier = self._frontier_targets()
        if frontier:
            path = self._bfs_path((px, py), frontier)
            if path and len(path) >= 2:
                nx, ny = path[1]
                dx, dy = nx - px, ny - py
                steps = len(path) - 1
                return ("move", (dx, dy), path[1:7], f"explore ({steps} steps)")

        # 5) Otherwise wait
        return ("wait", None, None, "wait")

    def auto_tick(self) -> bool:
        """Perform one auto-play tick. Returns True if a turn was consumed."""
        if self.state != "playing" or not self.player.is_alive():
            return False
        from game import TurnDigest  # type: ignore  # local import to avoid circular hinting
        self._digest = TurnDigest()
        kind, move, path, desc = self.bot_choose_action()

        # Log decision changes sparsely
        if desc != self._auto_target_desc:
            if desc.startswith("path"):
                self.logger.log("Auto: " + desc)
            elif desc.startswith("flee"):
                self.logger.log("Auto: " + desc)
            elif desc.startswith("explore"):
                self.logger.log("Auto: " + desc)
            self._auto_target_desc = desc
        # Save path preview
        self._auto_path = path or []

        old = (self.player.x, self.player.y)
        consumed = False
        if kind == "wait":
            consumed = True
        elif kind == "move" and move is not None:
            dx, dy = move
            self.move_entity(self.player, dx, dy)
            consumed = True
        # Enemy turns and turn advancement
        if consumed:
            self.enemy_turns()
            self.turn += 1
            if getattr(self, "_digest", None) is not None:
                for line in self._digest.summarize():
                    self.logger.log(line)
                self._digest = None
            # progress tracking
            new = (self.player.x, self.player.y)
            if new == old:
                self._auto_no_progress_ticks += 1
            else:
                self._auto_no_progress_ticks = 0
            if self._auto_no_progress_ticks >= 12:
                # replan
                self._auto_target_desc = None
                self._auto_path = []
                self._auto_no_progress_ticks = 0
                self.logger.log("Auto: replan (no progress)")
        self.recompute_fov()
        return consumed

    def read_key_nonblocking(self, allowed: Optional[set] = None) -> Optional[str]:
        if not msvcrt.kbhit():
            return None
        try:
            ch = msvcrt.getwch()
        except Exception:
            return None
        key: Optional[str] = None
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            code = ord(ch2)
            if code == 72:
                key = "UP"
            elif code == 80:
                key = "DOWN"
            elif code == 75:
                key = "LEFT"
            elif code == 77:
                key = "RIGHT"
        elif ch == "\r":
            key = "ENTER"
        elif ch == "\x1b":
            key = "ESC"
        elif ch == "\t":
            key = "TAB"
        else:
            if len(ch) == 1:
                if ch == ".":
                    key = "."
                else:
                    key = ch.upper() if ch.isalpha() else ch
        if key is None:
            return None
        if allowed is not None and key not in allowed:
            return None
        return key

    def read_key_blocking(self, allowed: Optional[set] = None) -> str:
        # Blocking read of a single normalized key
        while True:
            ch = msvcrt.getwch()
            key: Optional[str] = None
            if ch in ("\x00", "\xe0"):
                ch2 = msvcrt.getwch()
                code = ord(ch2)
                if code == 72:
                    key = "UP"
                elif code == 80:
                    key = "DOWN"
                elif code == 75:
                    key = "LEFT"
                elif code == 77:
                    key = "RIGHT"
            elif ch == "\r":
                key = "ENTER"
            elif ch == "\x1b":
                key = "ESC"
            elif ch == "\t":
                key = "TAB"
            else:
                if len(ch) == 1:
                    if ch == ".":
                        key = "."
                    else:
                        key = ch.upper()
            if key is None:
                continue
            if allowed is not None and key not in allowed:
                continue
            return key

    def _wrap(self, text: str, width: int) -> List[str]:
        if width <= 0:
            return [""]
        out: List[str] = []
        for line in text.splitlines() or [""]:
            s = line
            while len(s) > width:
                # break at last space within width if possible
                cut = s.rfind(" ", 0, width)
                if cut <= 0:
                    cut = width
                out.append(s[:cut])
                s = s[cut:].lstrip()
            out.append(s)
        return out

    def build_frame(self) -> str:
        w, h = self.map.w, self.map.h
        pane_w = RIGHT_PANE_W
        # Build right pane content (fixed width): status, controls, visible enemies; bottom: folded log
        pane_top_max = max(0, h - HUD_LOG_LINES)
        if self.state in ("playing", "paused", "game_over"):
            status_line = f"HP {self.player.hp}/{self.player.max_hp}  ATK {self.player.power}  Turn {self.turn}  Seed {self.seed}"
        else:
            seed_str = (str(self.menu_seed_value) if not self.menu_seed_random else "random")
            status_line = f"HP -/-  ATK -  Turn -  Seed {seed_str}"
        controls_line = "WASD/↑↓←→: ход  .: ждать  P: пауза  I: осмотр  H: помощь"
        pane_top_lines: List[str] = []
        pane_top_lines.extend(self._wrap(status_line, pane_w))
        controls_line = "WASD/Arrows: move  .: wait  P: pause  I: inspect  H: help"
        pane_top_lines.extend(self._wrap(controls_line, pane_w))
        # Auto-play status
        auto_speed = max(1, int(self.auto_ticks_per_sec))
        auto_on = "ON" if self.auto_play else "OFF"
        fast_suffix = f"  Fast: {'ON' if self.auto_fast else 'OFF'}"
        auto_line = f"AUTO: {auto_on}  Speed: {auto_speed} tps{fast_suffix}  (A toggle, [ ] speed, }} fast)"
        if self.ansi and self.auto_play:
            auto_line = FG_BRIGHT_GREEN + auto_line + RESET
        pane_top_lines.extend(self._wrap(auto_line, pane_w))
        if self.state in ("playing", "paused", "game_over"):
            if self.inspect_mode:
                pane_top_lines.extend(self._wrap("[Осмотр]", pane_w))
                for s in _inspect_info_lines(self):
                    pane_top_lines.extend(self._wrap(s, pane_w))
            else:
                for s in visible_enemies_list(self):
                    pane_top_lines.extend(self._wrap(s, pane_w))
        pane_top_lines = (pane_top_lines + [""] * pane_top_max)[:pane_top_max]
        log_wrapped: List[str] = []
        for s in self.logger.lines:
            log_wrapped.extend(self._wrap(s, pane_w))
        pane_bottom_lines = (log_wrapped + [""] * HUD_LOG_LINES)[-HUD_LOG_LINES:]
        pane_lines = pane_top_lines + pane_bottom_lines

        # Build map left side
        lines: List[str] = []
        use_color = self.ansi
        flash_set = set(getattr(self, 'flash_positions', []))
        # consume flashes after rendering this frame
        self.flash_positions = []
        for y in range(h):
            row_chars: List[str] = []
            for x in range(w):
                explored = self.map.explored[y][x]
                visible = self.visible[y][x]
                tile = self.map.tiles[y][x]
                if not explored and not visible:
                    row_chars.append(UNKNOWN_CHAR)
                    continue
                if tile.walkable:
                    base_ch = FLOOR_CHAR if visible else " "
                    base_col = ""
                else:
                    base_ch = WALL_CHAR
                    base_col = FG_GRAY
                ent_here = None
                if visible:
                    if self.player.is_alive() and self.player.x == x and self.player.y == y:
                        ent_here = self.player
                    else:
                        for e in self.enemies:
                            if e.is_alive() and e.x == x and e.y == y:
                                ent_here = e
                                break
                # Inspect cursor overlay
                if self.inspect_mode and self.inspect_x == x and self.inspect_y == y:
                    cur_ch = "+"
                    if use_color:
                        row_chars.append(FG_WHITE + cur_ch + RESET)
                    else:
                        row_chars.append(cur_ch)
                    continue
                if ent_here is not None:
                    ch = ent_here.ch
                    color = ent_here.color_visible
                    if (x, y) in flash_set and use_color:
                        color = "\x1b[1m" + color
                    if use_color:
                        row_chars.append(color + ch + RESET)
                    else:
                        row_chars.append(ch)
                else:
                    if use_color and base_col:
                        row_chars.append(base_col + base_ch + RESET)
                    else:
                        row_chars.append(base_ch)
            left = "".join(row_chars)
            right = pane_lines[y] if y < len(pane_lines) else ""
            # Ensure right is exactly pane_w (trim or pad)
            if len(right) > pane_w:
                right = right[:pane_w]
            else:
                right = right.ljust(pane_w)
            lines.append(left + " " + right)
        return "\n".join(lines)

    def render_frame(self, frame: str):
        if self.ansi:
            out = "\x1b[2J\x1b[H" + frame
            sys.stdout.write(out)
            sys.stdout.flush()
        else:
            os.system("cls")
            # Single write to avoid echo issues
            sys.stdout.write(frame)
            sys.stdout.flush()

    def _default_save_path(self) -> str:
        # Default to %APPDATA%\TextCrawler2\savegame.json on Windows; fallback to local file otherwise
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = os.path.join(appdata, "TextCrawler2")
            try:
                os.makedirs(base, exist_ok=True)
            except Exception:
                pass
            return os.path.join(base, "savegame.json")
        return os.path.join(os.getcwd(), "savegame.json")

    def save_game(self, filename: Optional[str] = None):
        if not filename:
            filename = self._default_save_path()
        data = {
            "state": self.state,
            "turn": self.turn,
            "seed": self.seed,
            "map": self.map.serialize(),
            "player": self.player.serialize(),
            "enemies": [e.serialize() for e in self.enemies if e.is_alive()],
            "log": self.logger.serialize(),
        }
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
        except Exception:
            pass
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.logger.log("Saved.")

    def load_game(self, filename: Optional[str] = None) -> bool:
        if not filename:
            filename = self._default_save_path()
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.logger.log(f"Failed to load: {e}")
            return False

        self.state = data.get("state", "paused")
        self.turn = data.get("turn", 1)
        self.seed = data.get("seed", 1337)
        self.rng = random.Random(self.seed)
        self.map = Map.deserialize(data["map"]) if "map" in data else self.map
        self.player = Entity.deserialize(data["player"], FG_BRIGHT_WHITE, FG_BRIGHT_WHITE)
        loaded_enemies: List[Entity] = []
        for ed in data.get("enemies", []):
            name = ed.get("name", "?")
            ch = ed.get("ch", "?")
            cv, cd = enemy_colors_for(name, ch)
            loaded_enemies.append(Entity.deserialize(ed, cv, cd))
        self.enemies = loaded_enemies
        self.logger.deserialize(data.get("log", []))
        self.logger.log("Loaded.")
        self.recompute_fov()
        return True

    def handle_pause_key(self, key: str):
        if key in ("P", "ESC"):
            self.state = "playing"
            self.logger.log("Unpaused.")
        elif key == "S":
            self.save_game()
        elif key == "L":
            if self.load_game():
                # ensure immediate redraw by caller
                pass
        elif key == "R":
            self.new_game(is_restart=True)
        # Q handled at run loop level

    def run(self):
        try:
            # Draw initial menu
            self.render_frame(build_menu_frame(self))
            while True:
                if self.state == "menu":
                    allowed = {"UP", "DOWN", "LEFT", "RIGHT", "TAB", "ENTER", "ESC", "+", "-"}
                    key = self.read_key_blocking(allowed)
                    if key == "ESC":
                        break
                    if key in ("UP", "DOWN", "TAB"):
                        if key == "UP":
                            self.menu_sel = (self.menu_sel - 1) % 4
                        else:
                            self.menu_sel = (self.menu_sel + 1) % 4
                    elif key in ("LEFT", "RIGHT", "+", "-"):
                        inc = 1 if key in ("RIGHT", "+") else -1
                        if self.menu_sel == 0:
                            # Seed: -1 means random
                            if self.menu_seed_random and inc == 1:
                                self.menu_seed_random = False
                                if self.menu_seed_value < 0:
                                    self.menu_seed_value = 1337
                            elif not self.menu_seed_random and (self.menu_seed_value + inc) < 0:
                                self.menu_seed_random = True
                                self.menu_seed_value = -1
                            else:
                                if self.menu_seed_random and inc == -1:
                                    # stay random on further decrements
                                    pass
                                else:
                                    if self.menu_seed_random and inc == 1:
                                        self.menu_seed_random = False
                                        self.menu_seed_value = 1337
                                    else:
                                        self.menu_seed_value = max(0, self.menu_seed_value + inc)
                        elif self.menu_sel == 1:
                            self.menu_width = max(20, min(120, self.menu_width + inc))
                        elif self.menu_sel == 2:
                            self.menu_height = max(10, min(60, self.menu_height + inc))
                        elif self.menu_sel == 3:
                            self.menu_enemies = max(0, min(99, self.menu_enemies + inc))
                    elif key == "ENTER":
                        self.new_game(is_restart=False)
                    # redraw menu every interaction
                    self.render_frame(build_menu_frame(self))
                    continue

                if self.state == "playing":
                    # draw frame fresh
                    self.recompute_fov()
                    self.render_frame(self.build_frame())

                    # Auto-play loop if enabled
                    if self.auto_play:
                        # non-blocking auto loop, allow hotkeys; pause when overlays open
                        self._set_auto_fast_params()
                        tick_interval = max(0.001, 1.0 / max(1, int(self.auto_ticks_per_sec)))
                        self._auto_tick_counter = 0
                        while self.auto_play and self.state in ("playing", "paused"):
                            start = time.time()
                            # Handle hotkeys non-blocking
                            allowed_keys = {"W", "A", "S", "D", "UP", "DOWN", "LEFT", "RIGHT", ".", "P", "R", "Q", "I", "H", "[", "]", "}"}
                            k = self.read_key_nonblocking(allowed_keys)
                            # Help modal: only allow H/Esc/Q/A; pause ticks
                            if self.help_mode:
                                if k is not None:
                                    if k in ("H", "ESC"):
                                        self.help_mode = False
                                        self.recompute_fov()
                                        self.render_frame(self.build_frame())
                                    elif k == "A":
                                        self.auto_play = not self.auto_play
                                        self.logger.log(f"Auto: {'ON' if self.auto_play else 'OFF'}")
                                    elif k == "Q":
                                        return
                                else:
                                    # keep help visible
                                    self.render_frame(build_help_frame(self))
                                # Sleep and continue loop without ticking
                                spent = time.time() - start
                                remaining = tick_interval - spent
                                if remaining > 0:
                                    time.sleep(remaining)
                                continue
                            if k is not None:
                                # Movement or wait: disable auto then apply move
                                if k in {"W", "A", "S", "D", "UP", "DOWN", "LEFT", "RIGHT", "."}:
                                    self.auto_play = False
                                    # Apply as manual turn
                                    self._digest = TurnDigest()
                                    turn_taken = self.handle_player_action(k)
                                    if turn_taken and self.state == "playing":
                                        self.enemy_turns()
                                        self.turn += 1
                                        if self._digest is not None:
                                            for line in self._digest.summarize():
                                                self.logger.log(line)
                                            self._digest = None
                                    else:
                                        self._digest = None
                                    self.recompute_fov()
                                    self.render_frame(self.build_frame())
                                    break
                                if k == "Q":
                                    return
                                if k == "P":
                                    if self.state == "playing":
                                        self.state = "paused"
                                        self.logger.log("Paused.")
                                    else:
                                        self.state = "playing"
                                        self.logger.log("Unpaused.")
                                    self.recompute_fov()
                                    self.render_frame(self.build_frame())
                                elif k == "R":
                                    self.new_game(is_restart=True)
                                    self.recompute_fov()
                                    self.render_frame(self.build_frame())
                                elif k == "I":
                                    if self.inspect_mode:
                                        self.inspect_mode = False
                                    else:
                                        self.inspect_mode = True
                                        self.inspect_x, self.inspect_y = self.player.x, self.player.y
                                    self.recompute_fov()
                                    self.render_frame(self.build_frame())
                                elif k == "H":
                                    self.help_mode = not self.help_mode
                                    if self.help_mode:
                                        self.render_frame(build_help_frame(self))
                                    else:
                                        self.recompute_fov()
                                        self.render_frame(self.build_frame())
                                elif k == "[":
                                    # decrease speed
                                    speeds = [4, 8, 16, 32, 64]
                                    try:
                                        i = speeds.index(max(1, int(self.auto_ticks_per_sec)))
                                    except Exception:
                                        i = 2
                                    if i > 0:
                                        self.auto_ticks_per_sec = speeds[i - 1]
                                    self.recompute_fov()
                                    self.render_frame(self.build_frame())
                                elif k == "]":
                                    speeds = [4, 8, 16, 32, 64]
                                    try:
                                        i = speeds.index(max(1, int(self.auto_ticks_per_sec)))
                                    except Exception:
                                        i = 2
                                    if i < len(speeds) - 1:
                                        self.auto_ticks_per_sec = speeds[i + 1]
                                    self.recompute_fov()
                                    self.render_frame(self.build_frame())
                                elif k == "}":
                                    self.auto_fast = not self.auto_fast
                                    self._set_auto_fast_params()
                                    self.recompute_fov()
                                    self.render_frame(self.build_frame())

                            # Do one bot tick if not paused/overlay and still playing
                            if self.state == "playing" and not (self.help_mode or self.inspect_mode):
                                did = self.auto_tick()
                                self._auto_tick_counter += 1
                                # Render per throttling
                                if (not self.auto_fast) or (self._auto_tick_counter % max(1, self.auto_render_every_n_ticks) == 0):
                                    self.render_frame(self.build_frame())
                            # Sleep to avoid busy loop
                            spent = time.time() - start
                            remaining = tick_interval - spent
                            if remaining > 0:
                                time.sleep(remaining)
                        # Finished auto loop; continue outer loop
                        continue

                    # Manual input path
                    if self.inspect_mode:
                        allowed = {"W", "A", "S", "D", "UP", "DOWN", "LEFT", "RIGHT", "I", "ESC", "H", "P"}
                    else:
                        allowed = {"W", "A", "S", "D", "UP", "DOWN", "LEFT", "RIGHT", ".", "P", "R", "Q", "I", "H", "[", "]", "}"}
                    key = self.read_key_blocking(allowed)
                    if key == "Q":
                        break
                    if key == "H":
                        self.help_mode = not self.help_mode
                        if self.help_mode:
                            self.render_frame(build_help_frame(self))
                            hk = self.read_key_blocking({"H", "ESC", "Q", "A"})
                            if hk in ("H", "ESC"):
                                self.help_mode = False
                            elif hk == "Q":
                                break
                            elif hk == "A":
                                self.auto_play = not self.auto_play
                                self.logger.log(f"Auto: {'ON' if self.auto_play else 'OFF'}")
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    if key == "I":
                        if self.inspect_mode:
                            self.inspect_mode = False
                        else:
                            self.inspect_mode = True
                            self.inspect_x, self.inspect_y = self.player.x, self.player.y
                        continue
                    if self.inspect_mode:
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
                        if key == "ESC":
                            self.inspect_mode = False
                            continue
                        if key in dir_map:
                            dx, dy = dir_map[key]
                            self.inspect_x = max(0, min(self.map.w - 1, self.inspect_x + dx))
                            self.inspect_y = max(0, min(self.map.h - 1, self.inspect_y + dy))
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    if key == "P":
                        self.state = "paused"
                        self.logger.log("Paused.")
                        self.render_frame(self.build_frame())
                        continue
                    if key == "R":
                        self.new_game(is_restart=True)
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    if key == "[":
                        speeds = [4, 8, 16, 32, 64]
                        try:
                            i = speeds.index(max(1, int(self.auto_ticks_per_sec)))
                        except Exception:
                            i = 2
                        if i > 0:
                            self.auto_ticks_per_sec = speeds[i - 1]
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    if key == "]":
                        speeds = [4, 8, 16, 32, 64]
                        try:
                            i = speeds.index(max(1, int(self.auto_ticks_per_sec)))
                        except Exception:
                            i = 2
                        if i < len(speeds) - 1:
                            self.auto_ticks_per_sec = speeds[i + 1]
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    if key == "}":
                        self.auto_fast = not self.auto_fast
                        self._set_auto_fast_params()
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    if key == "A":
                        self.auto_play = not self.auto_play
                        self.logger.log(f"Auto: {'ON' if self.auto_play else 'OFF'}")
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    # Player action
                    self._digest = TurnDigest()
                    turn_taken = self.handle_player_action(key)
                    if turn_taken and self.state == "playing":
                        self.enemy_turns()
                        self.turn += 1
                        if self._digest is not None:
                            for line in self._digest.summarize():
                                self.logger.log(line)
                            self._digest = None
                    else:
                        # Discard digest if no turn was taken
                        self._digest = None
                    self.recompute_fov()
                    self.render_frame(self.build_frame())
                    continue

                if self.state == "paused":
                    self.recompute_fov()
                    self.render_frame(self.build_frame())
                    allowed = {"P", "S", "L", "Q", "R", "ESC", "H", "A", "[", "]", "}"}
                    key = self.read_key_blocking(allowed)
                    if key == "Q":
                        break
                    if key == "H":
                        self.help_mode = True
                        self.render_frame(build_help_frame(self))
                        hk = self.read_key_blocking({"H", "ESC", "Q", "A"})
                        if hk in ("H", "ESC"):
                            self.help_mode = False
                        elif hk == "Q":
                            break
                        elif hk == "A":
                            self.auto_play = not self.auto_play
                            self.logger.log(f"Auto: {'ON' if self.auto_play else 'OFF'}")
                        continue
                    if key == "A":
                        self.auto_play = not self.auto_play
                        self.logger.log(f"Auto: {'ON' if self.auto_play else 'OFF'}")
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    if key in ("[", "]"):
                        speeds = [4, 8, 16, 32, 64]
                        try:
                            i = speeds.index(max(1, int(self.auto_ticks_per_sec)))
                        except Exception:
                            i = 2
                        if key == "[" and i > 0:
                            self.auto_ticks_per_sec = speeds[i - 1]
                        if key == "]" and i < len(speeds) - 1:
                            self.auto_ticks_per_sec = speeds[i + 1]
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    if key == "}":
                        self.auto_fast = not self.auto_fast
                        self._set_auto_fast_params()
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
                    self.handle_pause_key(key)
                    self.recompute_fov()
                    self.render_frame(self.build_frame())
                    continue

                if self.state == "game_over":
                    self.recompute_fov()
                    self.render_frame(self.build_frame())
                    allowed = {"R", "Q"}
                    key = self.read_key_blocking(allowed)
                    if key == "Q":
                        break
                    if key == "R":
                        self.new_game(is_restart=True)
                        self.recompute_fov()
                        self.render_frame(self.build_frame())
                        continue
        finally:
            show_cursor(self.ansi)
            sys.stdout.flush()

def build_menu_frame(self) -> str:
        # Build menu in right pane; left blank area sized by current settings
        w, h = self.menu_width, self.menu_height
        lines: List[str] = []
        pane_w = RIGHT_PANE_W
        items = [
            ("Seed", ("random" if self.menu_seed_random else str(self.menu_seed_value))),
            ("Width", str(self.menu_width)),
            ("Height", str(self.menu_height)),
            ("Enemies", str(self.menu_enemies)),
        ]
        header = [
            "Rogue-like: Text Crawler",
            "Use Arrow/Tab to select field",
            "←/→ or +/- to change, Enter to start, Esc to quit",
            "",
        ]
        content: List[str] = []
        content.extend(header)
        for idx, (name, value) in enumerate(items):
            sel = ">" if idx == self.menu_sel else " "
            content.append(f"{sel} {name}: {value}")
        content.append("")
        content.append("Preview size: {}x{}".format(self.menu_width, self.menu_height))
        # Wrap and cut to h lines
        pane_lines: List[str] = []
        for s in content:
            pane_lines.extend(self._wrap(s, pane_w))
        pane_lines = (pane_lines + [""] * h)[:h]
        blank_left = " " * w
        for y in range(h):
            right = pane_lines[y] if y < len(pane_lines) else ""
            if len(right) > pane_w:
                right = right[:pane_w]
            else:
                right = right.ljust(pane_w)
            lines.append(blank_left + " " + right)
        return "\n".join(lines)

def visible_enemies_list(self: "Game") -> List[str]:
    out: List[str] = []
    px, py = self.player.x, self.player.y
    vis: List[Tuple[int, Entity]] = []
    for e in self.enemies:
        if not e.is_alive():
            continue
        if 0 <= e.x < self.map.w and 0 <= e.y < self.map.h and self.visible[e.y][e.x]:
            dist = max(abs(e.x - px), abs(e.y - py))
            vis.append((dist, e))
    vis.sort(key=lambda t: t[0])
    for dist, e in vis:
        dir_s = _dir_to_compass(e.x - px, e.y - py)
        out.append(f"{e.ch} {e.name}  {e.hp}/{e.max_hp}  dist {dist}  {dir_s}")
    return out

def _dir_to_compass(dx: int, dy: int) -> str:
    sx = "" if dx == 0 else ("E" if dx > 0 else "W")
    sy = "" if dy == 0 else ("S" if dy > 0 else "N")
    return (sy + sx) if (sy + sx) else "."

def build_help_frame(self: "Game") -> str:
    w, h = self.map.w, self.map.h
    pane_w = RIGHT_PANE_W
    lines: List[str] = []
    legend = [
        "Help (H/Esc to close):",
        "",
        "Legend:",
        f"Walls: {WALL_CHAR}",
        f"Floor: '{FLOOR_CHAR}' in FOV, space outside",
        "Unknown: space",
        "Player: @ bright white/yellow",
        "Enemies: g Goblin green, a Archer cyan, p Priest magenta, T Troll green, s Shaman yellow",
        "> exit (if present)",
        "",
        "Controls:",
        "WASD/Arrows move; . wait; P pause; I inspect; H help; R restart; Q quit",
        "Paused: S save, L load",
        "",
        "Auto-Play controls:",
        "A — toggle, [ / ] — speed, } — fast, P — pause",
        "",
        "H/Esc — close",
    ]
    pane_lines: List[str] = []
    for s in legend:
        pane_lines.extend(self._wrap(s, pane_w))
    pane_lines = (pane_lines + [""] * h)[:h]
    blank_left = " " * w
    for y in range(h):
        right = pane_lines[y] if y < len(pane_lines) else ""
        if len(right) > pane_w:
            right = right[:pane_w]
        else:
            right = right.ljust(pane_w)
        lines.append(blank_left + " " + right)
    return "\n".join(lines)

def _inspect_info_lines(self: "Game") -> List[str]:
    x, y = self.inspect_x, self.inspect_y
    lines: List[str] = []
    tile_name = "unknown"
    if self.map.in_bounds(x, y):
        tile = self.map.tiles[y][x]
        if not self.map.explored[y][x] and not self.visible[y][x]:
            tile_name = "unknown"
        else:
            tile_name = "floor" if tile.walkable else "wall"
    lines.append(f"Tile: {tile_name} @ {x},{y}")
    ent = self.entity_at(x, y)
    if ent is not None:
        who = "You (@)" if ent is self.player else f"{ent.name} ({ent.ch})"
        lines.append(f"Unit: {who}")
        lines.append(f"HP {ent.hp}/{ent.max_hp}  ATK {ent.power}")
    px, py = self.player.x, self.player.y
    dist = max(abs(x - px), abs(y - py))
    los = "yes" if self.has_los(px, py, x, y, FOV_RADIUS) else "no"
    lines.append(f"dist {dist}  LOS {los}")
    return lines

# Note: enemy selection is now a method Game.random_enemy using ENEMY_TYPES

def enemy_colors_for(name: str, ch: str) -> Tuple[str, str]:
    name_l = name.lower()
    if name_l == "goblin" or ch == "g":
        return FG_BRIGHT_GREEN, FG_GREEN
    if name_l == "archer" or ch == "a":
        return FG_CYAN, FG_CYAN
    if name_l == "priest" or ch == "p":
        return FG_MAGENTA, FG_MAGENTA
    if name_l == "troll" or ch in ("t", "T"):
        return FG_GREEN, FG_GREEN
    if name_l == "shaman" or ch == "s":
        return FG_ORANGE, FG_YELLOW
    return FG_WHITE, FG_WHITE

class TurnDigest:
    def __init__(self):
        self.enemy_hits: Dict[str, Tuple[int, int]] = {}
        self.player_hits: Dict[str, Tuple[int, int, bool]] = {}
        self.kills_by_player: Dict[str, int] = {}

    def record_attack(self, attacker: Entity, defender: Entity, dmg: int):
        if attacker.name == "Player":
            c, total, killed = self.player_hits.get(defender.name, (0, 0, False))
            self.player_hits[defender.name] = (c + 1, total + dmg, killed or defender.hp <= 0)
        elif defender.name == "Player":
            c, total = self.enemy_hits.get(attacker.name, (0, 0))
            self.enemy_hits[attacker.name] = (c + 1, total + dmg)

    def record_kill(self, attacker: Entity, defender: Entity):
        if attacker.name == "Player":
            self.kills_by_player[defender.name] = self.kills_by_player.get(defender.name, 0) + 1

    def summarize(self) -> List[str]:
        out: List[str] = []
        for name, (cnt, dmg) in self.enemy_hits.items():
            out.append(f"{name} ×{cnt} → −{dmg} HP")
        for name, (cnt, dmg, killed) in self.player_hits.items():
            suffix = " (kill)" if killed else ""
            out.append(f"You → {name} ×{cnt}: −{dmg}{suffix}")
        if len(self.kills_by_player) > 1:
            parts = [f"{name} ×{cnt}" for name, cnt in self.kills_by_player.items()]
            out.append("You killed: " + ", ".join(parts))
        if len(out) > 3:
            out = out[:3]
        return out


def main():
    game = Game()
    game.run()


if __name__ == "__main__":
    main()
