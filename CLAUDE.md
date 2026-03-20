# Operation Jackpot — Claude Code Project Guide

## Project Overview

**Operation Jackpot** is a military-themed HTML/JS slot game prototype built as a single self-contained file (`operation-jackpot.html`). It uses a cluster pays mechanic with cascading symbols on a 6-reel asymmetric grid. The current build is a browser-playable prototype. The next phase is a Python RTP simulation and potential refactor into a proper project structure.

---

## Current State

The project is a single file: `operation-jackpot.html`

All game logic, animation, styling, and markup live in this one file. Do not split it into separate files unless explicitly asked — it is intentionally self-contained for portability.

---

## Game Spec (Source of Truth)

### Grid
- **6 reels**, heights: `[3, 5, 5, 5, 5, 3]` (diamond/symmetric shape)
- **Cluster pays** — wins require 5 or more connected matching symbols
- **Connectivity** — horizontal and vertical only (no diagonal)
- **Cascade** — when symbols are cleared, remaining symbols fall down; new symbols are drawn randomly from a weighted pool to fill gaps from the top

### Symbols & Weights (base game)

| Key | Emoji | Weight | Notes |
|---|---|---|---|
| HELMET | 🪖 | 20 | Most common |
| DOG_TAGS | 🏅 | 18 | |
| BOOTS | 👟 | 16 | |
| PISTOL | 🔫 | 14 | |
| RIFLE | 🎯 | 12 | |
| GRENADE | 🧨 | 10 | |
| HELICOPTER | 🚁 | 7 | |
| TANK | ⚙️ | 5 | Rarest regular symbol |
| WILD | ⭐ | 3 | Substitutes for regular symbols; can also form its own pure-wild clusters |
| SCATTER | 🚩 | 2 | Only spawns on reels 2–5 (index 1–4); weight=0 on reels 1 & 6 |
| BOMB | 💣 | 2 | Explodes entire row + column of its position; replaced by SUPER_BOMB in free spins |
| SUPER_BOMB | ☢️ | 1 | Clears entire grid; weight increases to 3 in free spins |

### Wild Behaviour
- Wilds join clusters of matching regular symbols (acts as that symbol)
- Wilds also form their own pure-wild clusters independently
- Both behaviours apply simultaneously

### Paytable (× bet multiplier, interpolated smoothly between tiers)

| Symbol | ×5 | ×7 | ×9 | ×12 | ×15+ |
|---|---|---|---|---|---|
| HELMET | 0.2 | 0.4 | 0.8 | 1.5 | 3 |
| DOG_TAGS | 0.3 | 0.6 | 1.0 | 2.0 | 4 |
| BOOTS | 0.4 | 0.8 | 1.5 | 3.0 | 6 |
| PISTOL | 0.6 | 1.0 | 2.0 | 4.0 | 8 |
| RIFLE | 0.8 | 1.5 | 3.0 | 6.0 | 12 |
| GRENADE | 1.0 | 2.0 | 4.0 | 8.0 | 16 |
| HELICOPTER | 1.5 | 3.0 | 6.0 | 12 | 25 |
| TANK | 2.0 | 5.0 | 10 | 20 | 50 |
| WILD (pure cluster) | 1.0 | 2.0 | 4.0 | 8.0 | 20 |

**Interpolation rule:** For cluster sizes between tier breakpoints, linearly interpolate between the two surrounding tiers. Cap at the ×15 value for clusters of 15+.

**Win formula:** `paytable_value × bet × sum_of_multipliers_in_cluster`

### Multiplier Grid
- Every cell starts at `1×`
- Each time a cell is cleared — whether by cluster win or bomb explosion — its multiplier increments by `+1`
- Multipliers persist across all cascades within a spin
- **Base game:** multipliers reset to `1×` at the start of each new spin
- **Free spins:** multipliers persist and accumulate for the entire free spins session; they carry over from the triggering spin
- Multipliers reset to `1×` when free spins end

### Bomb Mechanics
- **BOMB** (`💣`): on detonation, clears all cells in the bomb's row AND the bomb's column; increments multiplier on every cleared cell
- **SUPER_BOMB** (`☢️`): clears the entire grid; increments multiplier on every cell
- Bombs detonate before cluster detection in each cascade round
- In free spins, BOMB does not spawn — SUPER_BOMB takes its slot with increased weight (3)

### Cascade Order (per round, repeats until no action)
1. Find all qualifying clusters (5+), highlight and pay them
2. Clear cluster cells, increment their multipliers
3. Cascade down — existing symbols fall, new symbols roll in from top
4. Detonate all bombs present (one at a time, leftmost/topmost first)
5. After each bomb detonation, immediately cascade (fill gaps, roll in new symbols)
6. Repeat from step 1 until a full round produces no clusters and no bombs

### Free Spins
- **Trigger:** 3, 4, or 5 SCATTER symbols landing simultaneously on reels 2–5
- **Awards:** 3=8 spins, 4=12 spins, 5=20 spins
- **Retrigger:** 3+ scatters during free spins adds the same amounts above
- **Multiplier carry-over:** grid multiplier state from the triggering spin carries into free spins
- **Bombs become Super Bombs:** BOMB is removed from the draw pool; SUPER_BOMB weight increases to 3
- **Auto-play:** free spins run automatically with a short delay between each spin
- **End:** multipliers reset to `1×` when the session concludes

---

## Code Architecture

### Key Constants
```js
const HEIGHTS     = [4, 5, 6, 6, 5, 4];   // rows per reel
const REELS       = 6;
const MIN_CLUSTER = 5;
const STEP        = 70;                     // cell(68px) + gap(2px) — must match CSS --step
```

### State Object `G`
```js
G = {
  balance, bet, betIdx,
  grid,       // [reel][row] = symKey | null
  mults,      // [reel][row] = int ≥1
  freeSpins, inFS,
  spinWin, sessionWin,
  busy,
}
```

### DOM Structure
```
.reel#reel-{r}          ← viewport/window with mask-image edge fade
  .reel-strip#strip-{r} ← the scrolling drum band
    .cell#c-{r}-{row}   ← individual symbol slot
      .sym              ← emoji
      .mult             ← multiplier badge (hidden when 1×)
```

### Animation System

**Drum spin** (`doSpinAnimation`):
- Animates `.reel-strip` via `drumSpin` keyframe on the `.reel.spinning` class
- All reels start together; CSS vars `--spin-delay` and `--spin-dur` stagger each reel
- Cell content is swapped at ~62% of each reel's duration (peak blur) so new symbols are already present when the drum decelerates
- After animation resolves, all cells are refreshed once more for clean state

**Roll-out** (`rollOutCells`):
- Applied to cleared cells; `rollOut` keyframe squishes symbol upward with blur as if the tape advances past it

**Roll-in** (`rollInCells`):
- Applied to newly drawn cells; `rollIn` keyframe slides symbol down from above with bounce landing
- Cells within the same reel stagger 40ms top→bottom (tape ticking forward row by row)

**CSS vars per cell for roll-in:** `--roll-delay`, `--roll-dur`
**CSS vars per reel for spin:** `--spin-delay`, `--spin-dur`

### Important Implementation Notes
- `STEP = 70` must always match `.cell` height (68px) + `.gap` (2px) in CSS; if you change cell size update both
- Reel height is set inline: `reelEl.style.height = HEIGHTS[r] * STEP - 2 + 'px'` — the `-2` drops the trailing gap
- The `-webkit-mask-image` / `mask-image` on `.reel` creates the drum-curve edge fade; do not remove
- `void el.offsetWidth` reflow triggers before re-adding animation classes — required for CSS animation restart
- `G.grid[r][row] = null` marks a cell as empty/cleared; cascade compacts non-null entries to the bottom

---

## Bet Steps
```js
const BET_STEPS = [0.20, 0.50, 1.00, 2.00, 5.00, 10.00, 20.00, 50.00];
```

---

## Visual / Aesthetic Rules

- **Theme:** military tactical / night-ops terminal. Dark greens, amber accents, scanline overlay.
- **Fonts:** `Russo One` (headings, labels, values) + `Share Tech Mono` (body, log, paytable)
- **Do not** introduce new colour families without strong justification. The palette is intentionally restricted.
- **Do not** replace the scanline `body::after` pseudo-element — it is part of the aesthetic
- Multiplier tier border colours: `1×` default, `2×` dark green, `3×` mid green, `4×` bright green, `5×+` amber — keep this progression

---

## Planned Next Steps (in priority order)

1. **Scatter Visual Fix** — SCATTER (`🚩`) currently renders differently from regular symbols (no block-drop animation, no multiplier badge). Make it behave identically to other symbols visually: same cell styling, same drop animation on spin, same multiplier display. The only scatter-specific behaviour is: it cannot be cleared by bombs; it contributes to the free spins trigger count; it does not form clusters.

2. **Free Spins Trigger** — trigger a free spins bonus game when 3, 4, or 5 scatter symbols land simultaneously on reels 2–5 (index 1–4):
   - 3 scatters → 8 free spins
   - 4 scatters → 12 free spins
   - 5 scatters → 20 free spins
   - Retrigger: 3+ scatters during free spins adds the same amounts
   - During free spins: BOMB is removed from the pool; SUPER_BOMB weight increases to 3
   - Multipliers carry over from the triggering spin and accumulate for the full session
   - Free spins run automatically with a short delay between each spin
   - Multipliers reset to `1×` when the session ends
   - Note: `sfxScatterTension()` already plays when 2 scatters are visible — keep this behaviour

3. **Win Pop-up Message** — after each spin's total win is resolved, display a thematic message overlay based on the win as a multiple of bet:
   - < 2× bet: no message (silent win, just update balance)
   - 2–9× bet: "GOOD HIT" (or similar low-tier phrase)
   - 10–24× bet: "DIRECT HIT"
   - 25–49× bet: "CRITICAL STRIKE"
   - 50–99× bet: "DEVASTATING BLOW"
   - 100×+ bet: "TOTAL ANNIHILATION"
   - Style consistently with the military terminal aesthetic; animate in/out; do not block the next spin button for longer than ~2.5 seconds

4. **Python RTP Simulation** — a separate `rtp_sim.py` script that simulates N spins (target: 10M+) and reports RTP, hit frequency, average win, max win, free spins trigger rate, cascade depth distribution, and multiplier value distribution. Should mirror the JS logic exactly (same HEIGHTS, weights, paytable, cluster detection, bomb mechanics, cascade loop, multiplier system, free spins rules).

5. **RTP Fine-Tuning** — after running the simulation, adjust symbol weights and/or paytable values to hit a target RTP (typically 94–97% for slots of this type). Document the final tuned values in this file and in the paytable HTML.

6. **Buy Bonus** — a button that lets the player purchase direct free spins entry at a fixed cost multiplier (typically 80–100× bet).

7. **Mobile layout** — responsive scaling so the grid fits smaller screens without scrolling.

---

## Development Notes

- Always test the cascade loop for edge cases: bomb clearing cells that contain another bomb (chain detonation is currently **not** implemented — bombs detonate simultaneously in a single pass, which is intentional)
- When modifying `cascadeDown`, verify that the `clearedCells` argument contains every nulled-out cell for that round — missing cells will skip their roll-out animation
- Free spins auto-play uses tail recursion (`spin()` calls itself) — do not introduce `await` loops that could stack; keep the pattern as-is
- The paytable interpolation function `getPay(sym, size)` assumes tiers are ordered `[5,7,9,12,15]` — do not reorder
- If adding new symbols, update: `SYM`, `PAY` (if payable), `drawSym` exclusion logic, the legend HTML, and the paytable HTML table

---

## File Layout (current)

```
operation-jackpot.html    ← entire game (markup + CSS + JS)
CLAUDE.md                 ← this file
```

Future files to add:
```
rtp_sim.py                ← Python math/RTP simulation
README.md                 ← player-facing description
```
