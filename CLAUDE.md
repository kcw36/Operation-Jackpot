# Operation Jackpot — Claude Code Project Guide

## Project Overview

**Operation Jackpot** is a military-themed HTML/JS slot game prototype built as a single self-contained file (`operation-jackpot.html`). It uses a cluster pays mechanic with cascading symbols on a 6-reel asymmetric diamond grid. The current build is a fully browser-playable prototype with free spins, bombs, a multiplier grid, win popups, and a bonus buy feature. A Python RTP simulation (`rtp_sim.py`) mirrors the JS logic and has been used to tune the game to a target RTP of ~95%.

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

| Key | Display | Weight | Notes |
|---|---|---|---|
| BOOTS | 👟 | 16 | Most common |
| PISTOL | 🔫 | 14 | |
| RIFLE | 🎯 | 12 | |
| GRENADE | 🧨 | 10 | |
| HELICOPTER | 🚁 | 7 | |
| TANK | ⚙️ | 5 | Rarest regular symbol |
| WILD | W | 2 | Substitutes for regular symbols; can also form its own pure-wild clusters |
| SCATTER | 🚩 | 2 | Only spawns on reels 2–5 (index 1–4); weight=0 on reels 1 & 6 |
| BOMB | 💣 | 0.3 | Explodes entire row + column of its position; replaced by SUPER_BOMB in free spins |
| SUPER_BOMB | ☢️ | 0.3 | Clears entire grid; weight increases to 1.0 in free spins |

### Wild Behaviour
- Wilds join clusters of matching regular symbols (acts as that symbol)
- Wilds also form their own pure-wild clusters independently
- Both behaviours apply simultaneously
- Rendered as a bold amber **W** glyph (`Russo One` font, `.cell.is-wild .sym` CSS rule)

### Paytable (× bet multiplier, interpolated smoothly between tiers)

Values tuned to target ~95% RTP with the majority of return delivered through free spins.

| Symbol | ×5 | ×7 | ×9 | ×12 | ×15+ |
|---|---|---|---|---|---|
| BOOTS | 0.05 | 0.10 | 0.20 | 0.40 | 0.80 |
| PISTOL | 0.08 | 0.13 | 0.25 | 0.50 | 1.00 |
| RIFLE | 0.10 | 0.20 | 0.40 | 0.75 | 1.50 |
| GRENADE | 0.13 | 0.25 | 0.50 | 1.00 | 2.00 |
| HELICOPTER | 0.20 | 0.40 | 0.75 | 1.50 | 3.00 |
| TANK | 0.25 | 0.65 | 1.25 | 2.50 | 6.25 |
| WILD (pure cluster) | 0.13 | 0.25 | 0.50 | 1.00 | 2.50 |

**Interpolation rule:** For cluster sizes between tier breakpoints, linearly interpolate between the two surrounding tiers. Cap at the ×15 value for clusters of 15+.

**Win formula:** `paytable_value × bet × sum_of_multipliers_in_cluster`

### Multiplier Grid
- Every cell starts at `1×`
- **Base game:** each time a cell is cleared, its multiplier increments by `+1` (linear: 1→2→3→4…)
- **Free spins:** each time a cell is cleared, its multiplier **doubles** (exponential: 1→2→4→8→16…); capped at `1024×`
- Multipliers persist across all cascades within a spin
- **Base game:** multipliers reset to `1×` at the start of each new spin
- **Free spins:** multipliers persist and accumulate for the entire free spins session; they carry over from the triggering spin
- Multipliers reset to `1×` when free spins end

### Bomb Mechanics
- **BOMB** (`💣`): on detonation, clears all cells in the bomb's row AND the bomb's column; increments multiplier on every cleared cell; explosion radiates outward from the epicentre with staggered delay
- **SUPER_BOMB** (`☢️`): clears the entire grid simultaneously; increments multiplier on every cell
- Bombs are immune to each other's blasts (like SCATTER); they survive and detonate in a subsequent pass
- In free spins, BOMB does not spawn — SUPER_BOMB takes its slot with increased weight (1.0)

### Cascade Order (per round, repeats until no action)
1. Find all qualifying clusters (5+), highlight and pay them
2. Clear cluster cells, increment their multipliers
3. Cascade down — existing symbols fall, new symbols roll in from top
4. Detonate all bombs present (one at a time, leftmost/topmost first)
5. After each bomb detonation, immediately cascade (fill gaps, roll in new symbols)
6. Repeat from step 1 until a full round produces no clusters and no bombs

### Free Spins
- **Trigger:** 3, 4, or 5 SCATTER symbols present on reels 2–5 after all cascades complete
- **Awards:** 3=8 spins, 4=12 spins, 5=20 spins
- **Retrigger:** 3+ scatters during free spins adds the same amounts above
- **Multiplier carry-over:** grid multiplier state from the triggering spin carries into free spins
- **Bombs become Super Bombs:** BOMB is removed from the draw pool; SUPER_BOMB weight increases to 3
- **Auto-play:** free spins run automatically with a short delay between each spin
- **End:** total win popup shown; multipliers reset to `1×` when the session concludes
- **Tension sound:** `sfxScatterTension()` plays when exactly 2 scatters are visible on the initial drop

### Bonus Buy
- Cost: `80 × current bet`
- Guarantees at least 3 SCATTER symbols on reels 2–5 on the next spin using a Fisher-Yates shuffle
- Button is disabled during free spins, while busy, and when balance is insufficient for `cost + bet`
- Triggers the spin immediately on click; button reactivates after free spins session ends

### Win Popup Messages
Displayed after each spin (or after a free spins session ends) based on win as a multiple of bet:

| Win / Bet | Message |
|---|---|
| < 2× | Silent (no popup) |
| 2–9× | Low tier |
| 10–24× | DIRECT HIT |
| 25–49× | CRITICAL STRIKE |
| 50–99× | DEVASTATING BLOW |
| 100×+ | TOTAL ANNIHILATION |

- During free spins, per-spin popups are suppressed; a single total-win popup fires at session end
- `pointer-events: none` on the overlay — never blocks the spin button

---

## Code Architecture

### Key Constants
```js
const HEIGHTS         = [3, 5, 5, 5, 5, 3];  // rows per reel
const REELS           = 6;
const MIN_CLUSTER     = 5;
const STEP            = 70;                    // cell(68px) + gap(2px) — must match CSS --step
const BET_STEPS       = [0.20, 0.50, 1.00, 2.00, 5.00, 10.00, 20.00, 50.00];
const BONUS_BUY_MULT  = 80;                    // cost = 80 × current bet
const FS_TABLE        = {3:8, 4:12, 5:20};    // scatters → free spins awarded
```

### State Object `G`
```js
G = {
  balance, bet, betIdx,
  grid,             // [reel][row] = symKey | null
  mults,            // [reel][row] = int ≥ 1
  freeSpins, inFS,
  spinWin, sessionWin, fsWin,
  busy,
  bonusBuyPending,
}
```

### DOM Structure
```
.reel#reel-{r}          ← viewport/window with mask-image edge fade
  .reel-strip#strip-{r} ← the scrolling drum band
    .cell#c-{r}-{row}   ← individual symbol slot
      .sym              ← emoji or glyph
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

**Bomb explosion**:
- Regular BOMB: `anim-bomb` class with `--bomb-delay` CSS var; delay = `Math.abs(dist) × STAGGER` radiating outward from epicentre
- SUPER_BOMB: all cells receive `--bomb-delay: 0` — simultaneous full-grid flash

**CSS vars per cell for roll-in:** `--roll-delay`, `--roll-dur`
**CSS vars per reel for spin:** `--spin-delay`, `--spin-dur`
**CSS vars per cell for bomb:** `--bomb-delay`

### Important Implementation Notes
- `STEP = 70` must always match `.cell` height (68px) + `.gap` (2px) in CSS; if you change cell size update both
- Reel height is set inline: `reelEl.style.height = HEIGHTS[r] * STEP - 2 + 'px'` — the `-2` drops the trailing gap
- The `-webkit-mask-image` / `mask-image` on `.reel` creates the drum-curve edge fade; do not remove
- `void el.offsetWidth` reflow triggers before re-adding animation classes — required for CSS animation restart
- `G.grid[r][row] = null` marks a cell as empty/cleared; cascade compacts non-null entries to the bottom
- Scatter check runs **after** the cascade loop, not before — scatters that drop in as cascade replacements must be counted
- `justTriggeredFS` flag prevents the triggering spin from consuming a free spin (off-by-one guard)
- `G.busy = false` must be set before the tail-recursive `spin()` call in the free spins path; the spin button stays physically disabled to block manual clicks during the inter-spin gap

---

## Visual / Aesthetic Rules

- **Theme:** military tactical / night-ops terminal. Dark greens, amber accents, scanline overlay.
- **Fonts:** `Russo One` (headings, labels, values) + `Share Tech Mono` (body, log, paytable)
- **Do not** introduce new colour families without strong justification. The palette is intentionally restricted.
- **Do not** replace the scanline `body::after` pseudo-element — it is part of the aesthetic
- Multiplier tier border colours: `1×` default, `2×` dark green, `3×` mid green, `4×` bright green, `5×+` amber — keep this progression
- Wild **W** glyph: `Russo One`, `2rem`, `#f0a500` with `text-shadow` glow (`.cell.is-wild .sym`)

---

## Planned Next Steps (in priority order)

1. **RTP Verification** — run `python rtp_sim.py 10000000` with the current tuned values and confirm RTP is in the 93–97% range. Fine-tune paytable if needed: reduce BOOTS/PISTOL/RIFLE ×5 values by ~10% if RTP > 97%; increase HELICOPTER/TANK ×15 values by ~15% if RTP < 93%.

2. **Mobile layout** — responsive scaling so the grid fits smaller screens without scrolling.

---

## Development Notes

- Scatter check runs **after** the full cascade loop — do not move it back before. Scatters can land as cascade replacement symbols and must be counted in the final board state.
- Bomb detonation is **sequential**: fire leftmost/topmost bomb, cascade, re-scan, repeat. Do not revert to simultaneous union-blast — the sequential model allows bombs to survive each other's blasts and detonate independently.
- When modifying `cascadeDown`, verify that the `clearedCells` argument contains every nulled-out cell for that round — missing cells will skip their roll-out animation.
- Free spins auto-play uses tail recursion (`spin()` calls itself) — do not introduce `await` loops that could stack; keep the pattern as-is.
- The paytable interpolation function `getPay(sym, size)` assumes tiers are ordered `[5,7,9,12,15]` — do not reorder.
- If adding new symbols, update: `SYM`, `PAY` (if payable), `drawSym` exclusion logic, the legend HTML, and the paytable HTML table.
- Bomb immunity filter: `SCATTER`, `BOMB`, and `SUPER_BOMB` are excluded from any bomb's blast cells — except the firing bomb's own cell which is always included for self-destruction.

---

## File Layout

```
operation-jackpot.html    ← entire game (markup + CSS + JS)
rtp_sim.py                ← Python RTP simulation (mirrors JS logic; multiprocessing)
CLAUDE.md                 ← this file
README.md                 ← player-facing description
```
