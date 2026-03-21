#!/usr/bin/env python3
"""
rtp_sim.py  —  Operation Jackpot RTP Simulation

Mirrors the JavaScript logic in operation-jackpot.html exactly:
  same HEIGHTS, symbol weights, paytable, cluster BFS, bomb mechanics,
  cascade order (clusters first, then bombs), multiplier system, and
  free spins rules including multiplier carry-over and retriggers.

Usage
-----
  python rtp_sim.py                       # 10 million spins
  python rtp_sim.py 1000000               # custom spin count
  python rtp_sim.py 10000000 --seed 42    # reproducible run

Output
------
  RTP, hit frequency, average win, max win, free spins trigger rate,
  cascade depth distribution, multiplier peak distribution, bomb stats.
"""

from __future__ import annotations

import multiprocessing
import os
import random
import sys
import time
from collections import deque

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError for box chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG  —  mirrors JS constants exactly
# ═══════════════════════════════════════════════════════════════════════

HEIGHTS     = [3, 5, 5, 5, 5, 3]
MAX_H       = max(HEIGHTS)
REELS       = len(HEIGHTS)
MIN_CLUSTER = 5
TOTAL_CELLS = sum(HEIGHTS)   # 26

# Symbol weights (base game)
# DOG_TAGS removed — shifts cluster frequency toward higher-paying symbols
SYM_WEIGHTS: dict[str, float] = {
    "BOOTS":       16.0,
    "PISTOL":      14.0,
    "RIFLE":       12.0,
    "GRENADE":     10.0,
    "HELICOPTER":   7.0,
    "TANK":         5.0,
    "WILD":         2.0,   # reduced from 3 to lower base hit frequency
    "SCATTER":      2.0,
    "BOMB":         0.3,
    "SUPER_BOMB":   0.3,
}

# Paytable: symbol → {cluster_size: multiplier_of_bet}
# Values reduced ~÷8 from original to target ~95% RTP.
# Base game multipliers are +1 per clear (linear); FS multipliers double
# per clear (exponential) — see simulate_spin() for gating logic.
PAY: dict[str, dict[int, float]] = {
    "BOOTS":      {5: 0.05, 7: 0.10, 9: 0.20, 12: 0.40, 15: 0.80},
    "PISTOL":     {5: 0.08, 7: 0.13, 9: 0.25, 12: 0.50, 15: 1.00},
    "RIFLE":      {5: 0.10, 7: 0.20, 9: 0.40, 12: 0.75, 15: 1.50},
    "GRENADE":    {5: 0.13, 7: 0.25, 9: 0.50, 12: 1.00, 15: 2.00},
    "HELICOPTER": {5: 0.20, 7: 0.40, 9: 0.75, 12: 1.50, 15: 3.00},
    "TANK":       {5: 0.25, 7: 0.65, 9: 1.25, 12: 2.50, 15: 6.25},
    "WILD":       {5: 0.13, 7: 0.25, 9: 0.50, 12: 1.00, 15: 2.50},
}

PAY_TIERS = [5, 7, 9, 12, 15]

FS_TABLE: dict[int, int] = {3: 8, 4: 12, 5: 20}

# Symbols that cannot join or form clusters
SPECIALS = frozenset({"WILD", "SCATTER", "BOMB", "SUPER_BOMB"})

# Symbols that survive another bomb's blast (plus SCATTER)
BOMB_IMMUNE = frozenset({"SCATTER", "BOMB", "SUPER_BOMB"})


# ═══════════════════════════════════════════════════════════════════════
#  PRE-BUILT DRAW POOLS
#  Normalised cumulative-weight tables — built once, sampled with a
#  single random.random() call per draw (no dict iteration in hot path).
# ═══════════════════════════════════════════════════════════════════════

def _build_pool(reel: int, is_fs: bool) -> tuple[list[str], list[float]]:
    keys: list[str] = []
    cumulative: list[float] = []
    total = 0.0
    for key, w in SYM_WEIGHTS.items():
        if key == "SCATTER" and (reel < 1 or reel > 4):
            continue
        if key == "BOMB" and is_fs:
            continue
        eff = 1.0 if (is_fs and key == "SUPER_BOMB") else w
        total += eff
        keys.append(key)
        cumulative.append(total)
    # Normalise to [0, 1]
    for i in range(len(cumulative)):
        cumulative[i] /= total
    return keys, cumulative


# Keyed by (reel_index, is_fs)
_POOLS: dict[tuple[int, bool], tuple[list[str], list[float]]] = {
    (r, fs): _build_pool(r, fs)
    for r in range(REELS)
    for fs in (False, True)
}


def draw_sym(reel: int, is_fs: bool) -> str:
    keys, cum = _POOLS[(reel, is_fs)]
    r = random.random()
    for i, c in enumerate(cum):
        if r <= c:
            return keys[i]
    return keys[-1]


# ═══════════════════════════════════════════════════════════════════════
#  PAYTABLE INTERPOLATION  —  mirrors getPay() in JS
# ═══════════════════════════════════════════════════════════════════════

def get_pay(sym: str, size: int) -> float:
    t = PAY.get(sym)
    if t is None or size < 5:
        return 0.0
    if size >= 15:
        return t[15]
    for i in range(len(PAY_TIERS) - 1):
        s0, s1 = PAY_TIERS[i], PAY_TIERS[i + 1]
        if s0 <= size <= s1:
            p0, p1 = t[s0], t[s1]
            return p0 + (size - s0) / (s1 - s0) * (p1 - p0)
    return 0.0


# ═══════════════════════════════════════════════════════════════════════
#  GRID GEOMETRY  —  pre-computed for performance
# ═══════════════════════════════════════════════════════════════════════

# Neighbour list for every (reel, row) cell.
# Mirrors the neighbors() function in JS: same-reel vertical + cross-reel
# horizontal using center-aligned visual-row arithmetic.
_NEIGHBORS: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {}
for _r in range(REELS):
    for _row in range(HEIGHTS[_r]):
        _nb: list[tuple[int, int]] = []
        if _row > 0:
            _nb.append((_r, _row - 1))
        if _row < HEIGHTS[_r] - 1:
            _nb.append((_r, _row + 1))
        _vy = (MAX_H - HEIGHTS[_r]) / 2 + _row
        if _r > 0:
            _nr = _vy - (MAX_H - HEIGHTS[_r - 1]) / 2
            if _nr == int(_nr) and 0 <= int(_nr) < HEIGHTS[_r - 1]:
                _nb.append((_r - 1, int(_nr)))
        if _r < REELS - 1:
            _nr = _vy - (MAX_H - HEIGHTS[_r + 1]) / 2
            if _nr == int(_nr) and 0 <= int(_nr) < HEIGHTS[_r + 1]:
                _nb.append((_r + 1, int(_nr)))
        _NEIGHBORS[(_r, _row)] = tuple(_nb)


# Bomb blast cell lists for every (reel, row) position (regular BOMB only).
# Mirrors bombCells() in JS: visual-row horizontal + full column.
_BOMB_CELLS: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {}
for _r in range(REELS):
    for _row in range(HEIGHTS[_r]):
        _cells: set[tuple[int, int]] = set()
        _vy = (MAX_H - HEIGHTS[_r]) / 2 + _row
        for _br in range(REELS):
            _brow = round(_vy - (MAX_H - HEIGHTS[_br]) / 2)
            if 0 <= _brow < HEIGHTS[_br]:
                _cells.add((_br, _brow))
        for _brow in range(HEIGHTS[_r]):
            _cells.add((_r, _brow))
        _BOMB_CELLS[(_r, _row)] = tuple(_cells)

_SUPERBOMB_CELLS: tuple[tuple[int, int], ...] = tuple(
    (r, row) for r in range(REELS) for row in range(HEIGHTS[r])
)


# ═══════════════════════════════════════════════════════════════════════
#  CLUSTER DETECTION  —  mirrors findClusters() in JS (BFS)
# ═══════════════════════════════════════════════════════════════════════

def find_clusters(grid: list[list[str | None]]) -> list[dict]:
    """
    Returns list of {sym, cells} dicts for every qualifying cluster (≥5).
    Pass 1: regular symbols (wilds act as connectors).
    Pass 2: pure-wild clusters from any unvisited WILD cells.
    """
    visited: list[list[bool]] = [[False] * HEIGHTS[r] for r in range(REELS)]
    clusters: list[dict] = []

    # ── Pass 1: regular symbol clusters (WILD attaches) ──
    for r in range(REELS):
        for row in range(HEIGHTS[r]):
            if visited[r][row]:
                continue
            sym = grid[r][row]
            if sym is None or sym in SPECIALS:
                continue
            q: deque[tuple[int, int]] = deque()
            q.append((r, row))
            visited[r][row] = True
            cells: list[tuple[int, int]] = []
            while q:
                cr, cro = q.popleft()
                cells.append((cr, cro))
                for nr, nro in _NEIGHBORS[(cr, cro)]:
                    if visited[nr][nro]:
                        continue
                    ns = grid[nr][nro]
                    if ns == sym or ns == "WILD":
                        visited[nr][nro] = True
                        q.append((nr, nro))
            if len(cells) >= MIN_CLUSTER:
                clusters.append({"sym": sym, "cells": cells})

    # ── Pass 2: pure-wild clusters ──
    for r in range(REELS):
        for row in range(HEIGHTS[r]):
            if visited[r][row] or grid[r][row] != "WILD":
                continue
            q = deque()
            q.append((r, row))
            visited[r][row] = True
            cells = []
            while q:
                cr, cro = q.popleft()
                cells.append((cr, cro))
                for nr, nro in _NEIGHBORS[(cr, cro)]:
                    if not visited[nr][nro] and grid[nr][nro] == "WILD":
                        visited[nr][nro] = True
                        q.append((nr, nro))
            if len(cells) >= MIN_CLUSTER:
                clusters.append({"sym": "WILD", "cells": cells})

    return clusters


# ═══════════════════════════════════════════════════════════════════════
#  BOMB HELPERS  —  mirror findBombs() / bombCells() in JS
# ═══════════════════════════════════════════════════════════════════════

def find_bombs(grid: list[list[str | None]]) -> list[tuple[str, int, int]]:
    """Returns (type, reel, row) tuples in left→right, top→bottom order."""
    return [
        (grid[r][row], r, row)          # type: ignore[misc]
        for r in range(REELS)
        for row in range(HEIGHTS[r])
        if grid[r][row] in ("BOMB", "SUPER_BOMB")
    ]


def get_blast_cells(
    b_type: str, b_reel: int, b_row: int,
    grid: list[list[str | None]],
) -> list[tuple[int, int]]:
    """
    Cells this bomb actually clears, applying immunity rules:
      - SCATTER survives any blast
      - BOMB / SUPER_BOMB survive another bomb's blast
      - The firing bomb's own cell always self-destructs
    """
    raw = _SUPERBOMB_CELLS if b_type == "SUPER_BOMB" else _BOMB_CELLS[(b_reel, b_row)]
    result: list[tuple[int, int]] = []
    for r, row in raw:
        s = grid[r][row]
        if s is None:
            continue
        if s == "SCATTER":
            continue
        if s in ("BOMB", "SUPER_BOMB") and not (r == b_reel and row == b_row):
            continue    # other bombs immune — they'll fire later
        result.append((r, row))
    return result


# ═══════════════════════════════════════════════════════════════════════
#  CASCADE  —  mirrors cascadeDown() state-update in JS
#
#  JS logic:
#    const all     = G.grid[r].map((s,i) => [s, G.mults[r][i]]);
#    const cleared = all.filter(([s]) => s === null);
#    const kept    = all.filter(([s]) => s !== null);
#    fresh         = Array.from({length:dropped}, () => drawSym(r, G.inFS));
#    G.grid[r]  = [...fresh,               ...kept.map(([s]) => s)];
#    G.mults[r] = [...cleared.map(([,m])=>m), ...kept.map(([,m])=>m)];
#
#  Cleared-cell multipliers (already incremented before nulling) move to
#  the TOP of the column; new symbols inherit those incremented values.
# ═══════════════════════════════════════════════════════════════════════

def cascade_down(
    grid:  list[list[str | None]],
    mults: list[list[int]],
    is_fs: bool,
) -> None:
    """
    Compact surviving symbols to the bottom of each reel; fill the top
    with freshly drawn symbols. Mutates grid and mults in place.
    """
    for r in range(REELS):
        h = HEIGHTS[r]
        col_s = grid[r]
        col_m = mults[r]

        # Gather cleared (null) and kept (non-null) pairs in column order
        cleared_m: list[int] = []
        kept_sm:   list[tuple[str, int]] = []
        for i in range(h):
            if col_s[i] is None:
                cleared_m.append(col_m[i])
            else:
                kept_sm.append((col_s[i], col_m[i]))   # type: ignore[arg-type]

        dropped = len(cleared_m)
        if dropped == 0:
            continue

        # Fresh symbols fill the top; cleared-cell mults transfer with them
        for i in range(dropped):
            col_s[i] = draw_sym(r, is_fs)
            col_m[i] = cleared_m[i]

        # Surviving symbols settle to the bottom
        for i, (s, m) in enumerate(kept_sm):
            col_s[dropped + i] = s
            col_m[dropped + i] = m


def count_scatters(grid: list[list[str | None]]) -> int:
    return sum(
        1 for r in range(REELS) for row in range(HEIGHTS[r])
        if grid[r][row] == "SCATTER"
    )


# ═══════════════════════════════════════════════════════════════════════
#  SINGLE SPIN  —  base game or free spin
# ═══════════════════════════════════════════════════════════════════════

def simulate_spin(
    is_fs: bool,
    mults: list[list[int]] | None = None,
) -> dict:
    """
    Simulate one spin and return a result dict.

    Parameters
    ----------
    is_fs  : True if this is a free spin (BOMB excluded; SUPER_BOMB w=3)
    mults  : multiplier grid to use; None → initialise all to 1
             (passed by reference — mutated in place for FS carry-over)

    Returns
    -------
    {
      win           : float   total win in bet-units
      cascade_depth : int     cascade rounds beyond the first (0 = no cascade)
      max_mult      : int     highest multiplier seen on any cell this spin
      scatters      : int     scatter count on the final board
      bombs_det     : int     bomb detonations this spin
      mults         : list    final multiplier grid (same object as input)
    }
    """
    # Draw initial grid
    grid: list[list[str | None]] = [
        [draw_sym(r, is_fs) for _ in range(HEIGHTS[r])]
        for r in range(REELS)
    ]

    # Multiplier grid: start fresh or inherit carry-over
    if mults is None:
        mults = [[1] * HEIGHTS[r] for r in range(REELS)]

    spin_win  = 0.0
    round_num = 0
    bombs_det = 0
    max_mult  = max(m for col in mults for m in col)

    # Safety caps — prevent runaway chains.
    # In free spins, SUPER_BOMB weight=3 gives ~0.9 expected new bombs per
    # 26-cell refill (close to 1), so chain lengths can be arbitrarily long
    # with non-zero probability. Cap detonations per spin at 200 and outer
    # cascade rounds at 100 to bound simulation time while still capturing
    # all practically reachable states.
    MAX_BOMB_DET   = 200
    MAX_ROUNDS     = 100
    MULT_CAP       = 1024   # FS doubling cap — prevents extreme outliers

    any_action = True
    while any_action and round_num < MAX_ROUNDS:
        any_action = False
        round_num += 1

        # ── 1. Clusters (resolve before bombs each round) ──────────
        clusters = find_clusters(grid)
        if clusters:
            any_action = True

            for cl in clusters:
                sz       = len(cl["cells"])
                base_pay = get_pay(cl["sym"], sz)
                mult_sum = sum(mults[r][row] for r, row in cl["cells"])
                spin_win += base_pay * mult_sum   # bet-units

            # Clear cells, increment/double multipliers
            for cl in clusters:
                for r, row in cl["cells"]:
                    if is_fs:
                        mults[r][row] = min(mults[r][row] * 2, MULT_CAP)
                    else:
                        mults[r][row] += 1
                    if mults[r][row] > max_mult:
                        max_mult = mults[r][row]
                    grid[r][row] = None

            cascade_down(grid, mults, is_fs)

        # ── 2. Bombs (sequential — leftmost / topmost first) ───────
        active_bombs = find_bombs(grid)
        while active_bombs and bombs_det < MAX_BOMB_DET:
            any_action = True
            b_type, b_reel, b_row = active_bombs[0]
            bombs_det += 1

            for r, row in get_blast_cells(b_type, b_reel, b_row, grid):
                if is_fs:
                    mults[r][row] = min(mults[r][row] * 2, MULT_CAP)
                else:
                    mults[r][row] += 1
                if mults[r][row] > max_mult:
                    max_mult = mults[r][row]
                grid[r][row] = None

            cascade_down(grid, mults, is_fs)
            active_bombs = find_bombs(grid)

    # Scatter check runs after all cascades (mirrors post-cascade JS logic)
    scatters = count_scatters(grid)

    return {
        "win":           spin_win,
        "cascade_depth": round_num - 1,
        "max_mult":      max_mult,
        "scatters":      scatters,
        "bombs_det":     bombs_det,
        "mults":         mults,
    }


# ═══════════════════════════════════════════════════════════════════════
#  MULTIPROCESSING WORKER
#  Must be a top-level function so it is picklable on all platforms
#  (Windows uses spawn, not fork, so nested/lambda functions fail).
# ═══════════════════════════════════════════════════════════════════════

def _worker(args: tuple) -> dict:
    """Run a batch of spins and return aggregated stats as a plain dict."""
    batch_size, seed = args
    random.seed(seed)

    total_won      = 0.0
    wins           = 0
    max_win        = 0.0
    fs_triggers    = 0
    total_fs_spins = 0
    cascade_dist: dict[int, int] = {}
    mult_dist:    dict[int, int] = {}
    bombs_det_tot  = 0
    spins_w_bomb   = 0
    tiers: dict[str, int] = {
        "<2x": 0, "2-9x": 0, "10-24x": 0,
        "25-49x": 0, "50-99x": 0, "100x+": 0,
    }

    for _ in range(batch_size):
        result      = simulate_spin(is_fs=False)
        session_win = result["win"]
        mx          = result["max_mult"]

        cd = result["cascade_depth"]
        cascade_dist[cd] = cascade_dist.get(cd, 0) + 1

        if result["bombs_det"] > 0:
            spins_w_bomb  += 1
            bombs_det_tot += result["bombs_det"]

        # ── Free spins trigger ──────────────────────────────────────
        if result["scatters"] >= 3:
            fs_triggers += 1
            spins_left   = FS_TABLE[min(result["scatters"], 5)]
            fs_mults     = result["mults"]

            while spins_left > 0:
                spins_left     -= 1
                total_fs_spins += 1

                fs_res       = simulate_spin(is_fs=True, mults=fs_mults)
                session_win += fs_res["win"]
                fs_mults     = fs_res["mults"]

                if fs_res["max_mult"] > mx:
                    mx = fs_res["max_mult"]
                if fs_res["bombs_det"] > 0:
                    bombs_det_tot += fs_res["bombs_det"]
                if fs_res["scatters"] >= 3:
                    spins_left += FS_TABLE[min(fs_res["scatters"], 5)]

        # ── Accumulate ──────────────────────────────────────────────
        total_won += session_win
        if session_win > 0:
            wins += 1
        if session_win > max_win:
            max_win = session_win

        mult_dist[mx] = mult_dist.get(mx, 0) + 1

        w = session_win
        if   w >= 100: tiers["100x+"]  += 1
        elif w >= 50:  tiers["50-99x"] += 1
        elif w >= 25:  tiers["25-49x"] += 1
        elif w >= 10:  tiers["10-24x"] += 1
        elif w >= 2:   tiers["2-9x"]   += 1
        else:          tiers["<2x"]    += 1

    return {
        "n":           batch_size,
        "total_won":   total_won,
        "wins":        wins,
        "max_win":     max_win,
        "fs_triggers": fs_triggers,
        "fs_spins":    total_fs_spins,
        "cascade":     cascade_dist,
        "mults":       mult_dist,
        "bombs_det":   bombs_det_tot,
        "bombs_spins": spins_w_bomb,
        "tiers":       tiers,
    }


def _merge(total: dict, r: dict) -> None:
    """Merge a worker result dict into the running total in place."""
    total["n"]           += r["n"]
    total["total_won"]   += r["total_won"]
    total["wins"]        += r["wins"]
    total["max_win"]      = max(total["max_win"], r["max_win"])
    total["fs_triggers"] += r["fs_triggers"]
    total["fs_spins"]    += r["fs_spins"]
    total["bombs_det"]   += r["bombs_det"]
    total["bombs_spins"] += r["bombs_spins"]
    for k, v in r["cascade"].items():
        total["cascade"][k] = total["cascade"].get(k, 0) + v
    for k, v in r["mults"].items():
        total["mults"][k] = total["mults"].get(k, 0) + v
    for k, v in r["tiers"].items():
        total["tiers"][k] += v


def _print_report(total: dict, elapsed: float) -> None:
    """Print the final results table (same layout as run_simulation)."""
    n            = total["n"]
    total_won    = total["total_won"]
    rtp          = total_won / n * 100
    hit_freq     = total["wins"] / n * 100
    avg_win      = total_won / n
    fs_triggers  = total["fs_triggers"]
    fs_rate      = fs_triggers / n * 100
    avg_fs       = total["fs_spins"] / fs_triggers if fs_triggers > 0 else 0.0
    bomb_freq    = total["bombs_spins"] / n * 100
    cascade_dist = total["cascade"]
    mult_dist    = total["mults"]
    tier_counts  = total["tiers"]

    D = "═" * 58

    print()
    print(D)
    print("  OPERATION JACKPOT — RTP SIMULATION RESULTS")
    print(D)
    print(f"  Spins simulated   : {n:>16,}")
    print(f"  Elapsed           : {elapsed:>15.1f}s")
    print(f"  Throughput        : {n / elapsed:>15,.0f} spins/s")
    print()
    print(f"  RTP               : {rtp:>15.3f}%")
    print(f"  Hit frequency     : {hit_freq:>15.3f}%  (1 in {100/hit_freq:.1f})")
    print(f"  Avg win / spin    : {avg_win:>15.4f}× bet")
    print(f"  Max win           : {total['max_win']:>15.1f}× bet")
    print()
    print(f"  Free spins rate   : {fs_rate:>15.3f}%  (1 in {100/fs_rate:.0f} spins)")
    print(f"  FS triggers       : {fs_triggers:>16,}")
    print(f"  Total FS played   : {total['fs_spins']:>16,}")
    print(f"  Avg FS per trig   : {avg_fs:>15.1f}")
    print()
    print(f"  Spins with bomb   : {bomb_freq:>15.3f}%")
    print(f"  Total detonations : {total['bombs_det']:>16,}")

    print()
    print("  ── Win tier distribution ──────────────────────────")
    for label, count in tier_counts.items():
        pct = count / n * 100
        bar = "█" * int(pct / 2)
        print(f"  {label:>8}  {count:>11,}  ({pct:5.2f}%)  {bar}")

    print()
    print("  ── Cascade depth distribution ─────────────────────")
    max_depth = max(cascade_dist.keys()) if cascade_dist else 0
    for depth in range(min(max_depth + 1, 16)):
        count = cascade_dist.get(depth, 0)
        pct   = count / n * 100
        label = "  no cascade" if depth == 0 else f"  {depth} cascade{'s' if depth > 1 else ' '}"
        bar   = "█" * int(pct / 2)
        print(f"  {label}  {count:>11,}  ({pct:5.2f}%)  {bar}")
    if max_depth >= 16:
        overflow = sum(v for k, v in cascade_dist.items() if k >= 16)
        print(f"   16+ cascades  {overflow:>11,}  ({overflow / n * 100:5.2f}%)")

    print()
    print("  ── Multiplier peak distribution ───────────────────")
    max_m   = max(mult_dist.keys()) if mult_dist else 1
    buckets = [
        (1,  1),  (2,  2),  (3,  4),   (5,   9),
        (10, 19), (20, 49), (50, 99),  (100, max(max_m, 100)),
    ]
    for lo, hi in buckets:
        count = sum(mult_dist.get(m, 0) for m in range(lo, hi + 1))
        if count == 0:
            continue
        pct   = count / n * 100
        label = f"{lo}×" if lo == hi else f"{lo}–{hi}×"
        bar   = "█" * int(pct / 2)
        print(f"  {label:>8}  {count:>11,}  ({pct:5.2f}%)  {bar}")

    print()
    print(D)


def run_parallel(n_spins: int = 10_000_000, n_workers: int = 0, base_seed: int | None = None) -> None:
    """
    Distribute n_spins across n_workers processes using multiprocessing.Pool.

    Strategy
    --------
    Split work into (n_workers × 10) chunks so that:
      - Progress updates arrive frequently (every ~10% of a single worker's load)
      - Load is balanced even if individual spins vary in duration (FS retriggers)
      - imap_unordered streams results back as each chunk finishes

    Seeds
    -----
    Each chunk gets a unique seed derived from base_seed + chunk_index × large_prime,
    ensuring statistically independent draws across workers.
    """
    if n_workers <= 0:
        n_workers = os.cpu_count() or 1

    # Build chunk list
    n_chunks   = n_workers * 10
    chunk_base = n_spins // n_chunks
    remainder  = n_spins % n_chunks
    chunks: list[tuple[int, int]] = []
    prime = 1_000_003   # large prime to spread seeds
    for i in range(n_chunks):
        size = chunk_base + (1 if i < remainder else 0)
        seed = ((base_seed or 0) + i * prime) & 0xFFFF_FFFF
        chunks.append((size, seed))

    total: dict = {
        "n": 0, "total_won": 0.0, "wins": 0, "max_win": 0.0,
        "fs_triggers": 0, "fs_spins": 0,
        "cascade": {}, "mults": {},
        "bombs_det": 0, "bombs_spins": 0,
        "tiers": {"<2x": 0, "2-9x": 0, "10-24x": 0,
                  "25-49x": 0, "50-99x": 0, "100x+": 0},
    }

    print(f"Workers : {n_workers}  (across {n_chunks} chunks)")
    if base_seed is not None:
        print(f"Seed    : {base_seed}")
    print()

    start     = time.perf_counter()
    completed = 0

    if n_workers == 1:
        # Skip pool overhead for single-worker runs
        for chunk_args in chunks:
            _merge(total, _worker(chunk_args))
            completed += chunk_args[0]
            pct  = completed / n_spins * 100
            rate = completed / (time.perf_counter() - start) if (time.perf_counter() - start) > 0 else 0
            eta  = (n_spins - completed) / rate if rate > 0 else 0
            rtp  = total["total_won"] / completed * 100 if completed else 0
            print(
                f"\r  {pct:5.1f}%  spins={completed:>10,}"
                f"  RTP={rtp:.2f}%  rate={rate:,.0f}/s  ETA={eta:.0f}s   ",
                end="", flush=True,
            )
        print()
    else:
        with multiprocessing.Pool(processes=n_workers) as pool:
            for result in pool.imap_unordered(_worker, chunks):
                _merge(total, result)
                completed += result["n"]
                pct  = completed / n_spins * 100
                rate = completed / (time.perf_counter() - start) if (time.perf_counter() - start) > 0 else 0
                eta  = (n_spins - completed) / rate if rate > 0 else 0
                rtp  = total["total_won"] / completed * 100 if completed else 0
                print(
                    f"\r  {pct:5.1f}%  spins={completed:>10,}"
                    f"  RTP={rtp:.2f}%  rate={rate:,.0f}/s  ETA={eta:.0f}s   ",
                    end="", flush=True,
                )
        print()

    elapsed = time.perf_counter() - start
    _print_report(total, elapsed)


# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ── Required on Windows: multiprocessing uses spawn (not fork),
    #    so worker processes re-import this module. Without this guard
    #    each worker would spawn more workers recursively. ──────────
    multiprocessing.freeze_support()

    args     = sys.argv[1:]
    n        = 10_000_000
    seed     = None
    workers  = 0   # 0 → auto-detect cpu_count()

    i = 0
    while i < len(args):
        if args[i] == "--seed" and i + 1 < len(args):
            seed = int(args[i + 1])
            i += 2
        elif args[i] == "--workers" and i + 1 < len(args):
            val = args[i + 1]
            workers = 0 if val == "auto" else int(val)
            i += 2
        elif args[i].lstrip("-").lstrip("+").isdigit():
            n = int(args[i])
            i += 1
        else:
            i += 1

    n_cpu = os.cpu_count() or 1
    eff_workers = workers if workers > 0 else n_cpu
    print(f"Running {n:,} spins across {eff_workers} worker(s)…")
    print()
    run_parallel(n_spins=n, n_workers=workers, base_seed=seed)
