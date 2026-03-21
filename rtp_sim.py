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

import random
import sys
import time
from collections import deque, defaultdict


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG  —  mirrors JS constants exactly
# ═══════════════════════════════════════════════════════════════════════

HEIGHTS     = [3, 5, 5, 5, 5, 3]
MAX_H       = max(HEIGHTS)
REELS       = len(HEIGHTS)
MIN_CLUSTER = 5
TOTAL_CELLS = sum(HEIGHTS)   # 26

# Symbol weights (base game)
SYM_WEIGHTS: dict[str, float] = {
    "DOG_TAGS":    18.0,
    "BOOTS":       16.0,
    "PISTOL":      14.0,
    "RIFLE":       12.0,
    "GRENADE":     10.0,
    "HELICOPTER":   7.0,
    "TANK":         5.0,
    "WILD":         3.0,
    "SCATTER":      2.0,
    "BOMB":         1.0,
    "SUPER_BOMB":   0.5,
}

# Paytable: symbol → {cluster_size: multiplier_of_bet}
PAY: dict[str, dict[int, float]] = {
    "DOG_TAGS":   {5: 0.3,  7: 0.6,  9: 1.0,  12: 2.0,  15: 4.0 },
    "BOOTS":      {5: 0.4,  7: 0.8,  9: 1.5,  12: 3.0,  15: 6.0 },
    "PISTOL":     {5: 0.6,  7: 1.0,  9: 2.0,  12: 4.0,  15: 8.0 },
    "RIFLE":      {5: 0.8,  7: 1.5,  9: 3.0,  12: 6.0,  15: 12.0},
    "GRENADE":    {5: 1.0,  7: 2.0,  9: 4.0,  12: 8.0,  15: 16.0},
    "HELICOPTER": {5: 1.5,  7: 3.0,  9: 6.0,  12: 12.0, 15: 25.0},
    "TANK":       {5: 2.0,  7: 5.0,  9: 10.0, 12: 20.0, 15: 50.0},
    "WILD":       {5: 1.0,  7: 2.0,  9: 4.0,  12: 8.0,  15: 20.0},
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
        eff = 3.0 if (is_fs and key == "SUPER_BOMB") else w
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

    any_action = True
    while any_action:
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

            # Clear cells, increment multipliers
            for cl in clusters:
                for r, row in cl["cells"]:
                    mults[r][row] += 1
                    if mults[r][row] > max_mult:
                        max_mult = mults[r][row]
                    grid[r][row] = None

            cascade_down(grid, mults, is_fs)

        # ── 2. Bombs (sequential — leftmost / topmost first) ───────
        active_bombs = find_bombs(grid)
        while active_bombs:
            any_action = True
            b_type, b_reel, b_row = active_bombs[0]
            bombs_det += 1

            for r, row in get_blast_cells(b_type, b_reel, b_row, grid):
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
#  FULL SIMULATION
# ═══════════════════════════════════════════════════════════════════════

def run_simulation(n_spins: int = 10_000_000) -> None:
    total_wagered   = 0.0
    total_won       = 0.0
    spins_with_win  = 0
    max_win_mult    = 0.0   # highest single-session win / bet

    fs_triggers     = 0
    total_fs_spins  = 0

    cascade_dist:   dict[int, int] = defaultdict(int)
    mult_dist:      dict[int, int] = defaultdict(int)

    total_bombs_det = 0
    spins_with_bomb = 0

    tier_counts: dict[str, int] = {
        "<2x": 0, "2-9x": 0, "10-24x": 0,
        "25-49x": 0, "50-99x": 0, "100x+": 0,
    }

    start = time.perf_counter()
    report_every = max(1, n_spins // 20)

    for spin_num in range(1, n_spins + 1):
        total_wagered += 1.0   # normalised to 1× bet

        # ── Base spin ──────────────────────────────────────────────
        result     = simulate_spin(is_fs=False)
        session_win = result["win"]
        max_mult_spin = result["max_mult"]

        cascade_dist[result["cascade_depth"]] += 1
        if result["bombs_det"] > 0:
            spins_with_bomb += 1
            total_bombs_det += result["bombs_det"]

        # ── Free spins trigger ─────────────────────────────────────
        if result["scatters"] >= 3:
            fs_triggers += 1
            sc = min(result["scatters"], 5)
            spins_left = FS_TABLE[sc]
            fs_mults   = result["mults"]   # carry over from triggering spin

            while spins_left > 0:
                spins_left  -= 1
                total_fs_spins += 1

                fs_res      = simulate_spin(is_fs=True, mults=fs_mults)
                session_win += fs_res["win"]
                fs_mults     = fs_res["mults"]   # carry mults forward

                if fs_res["max_mult"] > max_mult_spin:
                    max_mult_spin = fs_res["max_mult"]
                if fs_res["bombs_det"] > 0:
                    total_bombs_det += fs_res["bombs_det"]

                # Retrigger
                if fs_res["scatters"] >= 3:
                    spins_left += FS_TABLE[min(fs_res["scatters"], 5)]

        # ── Accumulate ─────────────────────────────────────────────
        total_won     += session_win
        mult_dist[max_mult_spin] += 1

        if session_win > 0:
            spins_with_win += 1
        if session_win > max_win_mult:
            max_win_mult = session_win

        w = session_win   # already in bet-units
        if   w >= 100: tier_counts["100x+"]  += 1
        elif w >= 50:  tier_counts["50-99x"] += 1
        elif w >= 25:  tier_counts["25-49x"] += 1
        elif w >= 10:  tier_counts["10-24x"] += 1
        elif w >= 2:   tier_counts["2-9x"]   += 1
        else:          tier_counts["<2x"]    += 1

        # ── Progress report ────────────────────────────────────────
        if spin_num % report_every == 0:
            elapsed = time.perf_counter() - start
            pct     = spin_num / n_spins * 100
            rate    = spin_num / elapsed if elapsed > 0 else 0
            eta     = (n_spins - spin_num) / rate if rate > 0 else 0
            rtp_now = total_won / total_wagered * 100
            print(
                f"  {pct:5.1f}%  spins={spin_num:>10,}  "
                f"RTP={rtp_now:.2f}%  rate={rate:,.0f}/s  ETA={eta:.0f}s"
            )

    elapsed = time.perf_counter() - start

    # ═══════════════════════════════════════════════════════════════
    #  REPORT
    # ═══════════════════════════════════════════════════════════════

    rtp          = total_won / total_wagered * 100
    hit_freq     = spins_with_win / n_spins * 100
    avg_win      = total_won / n_spins
    fs_rate      = fs_triggers / n_spins * 100
    avg_fs       = total_fs_spins / fs_triggers if fs_triggers > 0 else 0.0
    bomb_freq    = spins_with_bomb / n_spins * 100

    D = "═" * 58

    print()
    print(D)
    print("  OPERATION JACKPOT — RTP SIMULATION RESULTS")
    print(D)
    print(f"  Spins simulated   : {n_spins:>16,}")
    print(f"  Elapsed           : {elapsed:>15.1f}s")
    print(f"  Throughput        : {n_spins / elapsed:>15,.0f} spins/s")
    print()
    print(f"  RTP               : {rtp:>15.3f}%")
    print(f"  Hit frequency     : {hit_freq:>15.3f}%  (1 in {100/hit_freq:.1f})")
    print(f"  Avg win / spin    : {avg_win:>15.4f}× bet")
    print(f"  Max win           : {max_win_mult:>15.1f}× bet")
    print()
    print(f"  Free spins rate   : {fs_rate:>15.3f}%  (1 in {100/fs_rate:.0f} spins)")
    print(f"  FS triggers       : {fs_triggers:>16,}")
    print(f"  Total FS played   : {total_fs_spins:>16,}")
    print(f"  Avg FS per trig   : {avg_fs:>15.1f}")
    print()
    print(f"  Spins with bomb   : {bomb_freq:>15.3f}%")
    print(f"  Total detonations : {total_bombs_det:>16,}")

    # Win tier distribution
    print()
    print("  ── Win tier distribution ──────────────────────────")
    for label, count in tier_counts.items():
        pct = count / n_spins * 100
        bar = "█" * int(pct / 2)
        print(f"  {label:>8}  {count:>11,}  ({pct:5.2f}%)  {bar}")

    # Cascade depth distribution
    print()
    print("  ── Cascade depth distribution ─────────────────────")
    max_depth = max(cascade_dist.keys()) if cascade_dist else 0
    for depth in range(min(max_depth + 1, 16)):
        count = cascade_dist.get(depth, 0)
        pct   = count / n_spins * 100
        if depth == 0:
            label = "  no cascade"
        elif depth == 1:
            label = "   1 cascade"
        else:
            label = f"  {depth} cascades"
        bar = "█" * int(pct / 2)
        print(f"  {label}  {count:>11,}  ({pct:5.2f}%)  {bar}")
    if max_depth >= 16:
        overflow = sum(v for k, v in cascade_dist.items() if k >= 16)
        print(f"   16+ cascades  {overflow:>11,}  ({overflow / n_spins * 100:5.2f}%)")

    # Multiplier peak distribution
    print()
    print("  ── Multiplier peak distribution ───────────────────")
    max_m = max(mult_dist.keys()) if mult_dist else 1
    buckets = [
        (1,  1),  (2,  2),  (3,  4),   (5,   9),
        (10, 19), (20, 49), (50, 99),  (100, max(max_m, 100)),
    ]
    for lo, hi in buckets:
        count = sum(mult_dist.get(m, 0) for m in range(lo, hi + 1))
        if count == 0:
            continue
        pct   = count / n_spins * 100
        label = f"{lo}×" if lo == hi else f"{lo}–{hi}×"
        bar   = "█" * int(pct / 2)
        print(f"  {label:>8}  {count:>11,}  ({pct:5.2f}%)  {bar}")

    print()
    print(D)


# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args = sys.argv[1:]
    n    = 10_000_000
    seed = None

    i = 0
    while i < len(args):
        if args[i] == "--seed" and i + 1 < len(args):
            seed = int(args[i + 1])
            i += 2
        elif args[i].lstrip("-").lstrip("+").isdigit():
            n = int(args[i])
            i += 1
        else:
            i += 1

    if seed is not None:
        random.seed(seed)
        print(f"Seed: {seed}")

    print(f"Running {n:,} spins…")
    print()
    run_simulation(n)
