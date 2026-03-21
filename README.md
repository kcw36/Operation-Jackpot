# Operation Jackpot

A military-themed browser slot game built as a single, self-contained HTML file. No install, no build step, no dependencies — open and play.

---

## Features

- **Cluster Pays** — connect 5 or more matching symbols horizontally or vertically to win
- **Cascading Symbols** — cleared clusters cause new symbols to drop in, enabling chain reactions
- **Multiplier Grid** — every cleared cell increments its multiplier; in free spins each clear **doubles** the multiplier (×2, ×4, ×8…); multipliers carry into free spins making each session exponentially more valuable
- **Bomb Symbols** — `💣` clears a full row and column; `☢️ Super Bomb` wipes the entire grid
- **Free Spins Mode** — land 3–5 scatters to trigger 8–20 free spins with persistent, accumulating multipliers
- **Bonus Buy** — skip straight to free spins for 80× your bet
- **Asymmetric 6-Reel Grid** — diamond-shaped layout (`[3, 5, 5, 5, 5, 3]` rows per reel)
- **Military Aesthetic** — dark terminal UI, scanline overlay, amber accents

---

## How to Play

### Starting Up

No installation required.

```bash
git clone https://github.com/kcw36/Operation-Jackpot.git
cd Operation-Jackpot
# Open operation-jackpot.html in any modern browser
```

### Symbols

| Symbol | Display | Notes |
|---|---|---|
| Boots | 👟 | Most common |
| Pistol | 🔫 | |
| Rifle | 🎯 | |
| Grenade | 🧨 | |
| Helicopter | 🚁 | |
| Tank | ⚙️ | Rarest regular symbol |
| Wild | **W** | Substitutes for any regular symbol; forms its own clusters |
| Scatter | 🚩 | Triggers free spins (reels 2–5 only) |
| Bomb | 💣 | Clears its entire row + column |
| Super Bomb | ☢️ | Clears the entire grid |

### Winning

Form clusters of **5 or more** connected matching symbols (horizontal or vertical connections only). The Wild (**W**) substitutes for any regular symbol and can also form pure-wild clusters.

**Win = paytable value × bet × sum of cell multipliers in the cluster**

### Paytable

| Symbol | ×5 | ×7 | ×9 | ×12 | ×15+ |
|---|---|---|---|---|---|
| Boots | 0.05× | 0.10× | 0.20× | 0.40× | 0.80× |
| Pistol | 0.08× | 0.13× | 0.25× | 0.50× | 1.00× |
| Rifle | 0.10× | 0.20× | 0.40× | 0.75× | 1.50× |
| Grenade | 0.13× | 0.25× | 0.50× | 1.00× | 2.00× |
| Helicopter | 0.20× | 0.40× | 0.75× | 1.50× | 3.00× |
| Tank | 0.25× | 0.65× | 1.25× | 2.50× | 6.25× |
| Wild cluster | 0.13× | 0.25× | 0.50× | 1.00× | 2.50× |

Values are linearly interpolated between cluster size tiers.

### Cascade System

Each round repeats until nothing happens:

1. Winning clusters are paid out and cleared; cell multipliers increment
2. Symbols fall down; new symbols drop in from the top
3. Bombs detonate (one at a time, left to right); cells cleared by bombs also increment their multipliers
4. Cascade again after each bomb

Bombs are immune to other bombs — each one detonates in sequence rather than being caught in another's blast.

### Multiplier Grid

Each cell on the grid has a multiplier that starts at `1×`. Every time a cell is cleared — by a cluster win or a bomb — its multiplier is updated. That multiplier is factored directly into any future win from that cell.

- **Base game:** each clear adds `+1` to a cell's multiplier (linear: 1→2→3→4…); resets at the start of every new spin
- **Free spins:** each clear **doubles** a cell's multiplier (exponential: 1→2→4→8→16…); carries over from the triggering spin and keeps accumulating for the entire session

### Free Spins

| Scatters Landed | Spins Awarded |
|---|---|
| 3 | 8 |
| 4 | 12 |
| 5 | 20 |

Scatter symbols count after all cascades resolve, so scatters that drop in during a cascade chain count toward the trigger.

- Multipliers carry over and **accumulate** throughout the session — a multiplier built in the base game survives into free spins
- Bombs are replaced by Super Bombs (higher spawn rate); multipliers **double** on every clear instead of +1
- Landing 3+ scatters during free spins adds another batch of free spins
- A total win popup is shown when the session ends

### Bonus Buy

Click **🎖 BUY BONUS** to guarantee at least 3 scatter symbols on the next spin, immediately triggering free spins. Cost is **80× your current bet**. The button reactivates as soon as free spins end.

### Bet Steps

`$0.20 · $0.50 · $1.00 · $2.00 · $5.00 · $10.00 · $20.00 · $50.00`

### Win Messages

| Win (relative to bet) | Message |
|---|---|
| 2–9× | Low tier |
| 10–24× | DIRECT HIT |
| 25–49× | CRITICAL STRIKE |
| 50–99× | DEVASTATING BLOW |
| 100×+ | TOTAL ANNIHILATION |

---

## Project Structure

```
operation-jackpot.html   # Entire game — markup, CSS, and JS in one file
rtp_sim.py               # Python RTP simulation (multiprocessing, mirrors JS logic)
CLAUDE.md                # Developer spec and architecture guide
README.md                # This file
```

The game is intentionally kept as a single self-contained file for maximum portability.

---

## Roadmap

- [x] Scatter symbol visual fix — identical block-drop animation and multiplier display
- [x] Free spins mode — 3/4/5 scatters trigger 8/12/20 free spins; persistent multipliers; super bombs
- [x] Win messages — thematic overlay text scaled to win size
- [x] Bonus buy — purchase direct free spins entry at 80× bet
- [x] Python RTP simulation — multiprocessing sim; 10M spins in ~3 min; full stats report
- [x] RTP tuning — paytable reduced ÷8; DOG_TAGS removed; FS multiplier doubling; target ~95%
- [ ] RTP verification — run 10M sim with current values and fine-tune if outside 93–97%
- [ ] Mobile layout — responsive scaling for smaller screens

---

## License

Prototype — no license applied.
