# Operation Jackpot 🎰

A military-themed browser slot game built as a single, self-contained HTML file. Features a cluster pays mechanic, cascading symbols, multiplier grids, bombs, and a free spins mode — all playable with no build step or dependencies.

---

## Features

- **Cluster Pays** — wins require 5 or more connected matching symbols (horizontal/vertical)
- **Cascading Symbols** — winning clusters are cleared and new symbols fall in, enabling chain reactions
- **Multiplier Grid** — each cleared cell increments its multiplier; multipliers persist across cascades and carry into free spins
- **Bomb Symbols** — `💣` clears an entire row + column; `☢️ Super Bomb` clears the entire grid
- **Free Spins Mode** — triggered by 3–5 scatter symbols; multipliers accumulate for the full session
- **Asymmetric 6-Reel Grid** — diamond-shaped layout with reel heights `[4, 5, 6, 6, 5, 4]`
- **Military Aesthetic** — dark terminal UI with scanline overlay, amber accents, and tactical theming

---

## Gameplay

### Grid & Symbols

| Symbol | Emoji | Rarity |
|---|---|---|
| Helmet | 🪖 | Most common |
| Dog Tags | 🏅 | Common |
| Boots | 👟 | Common |
| Pistol | 🔫 | Moderate |
| Rifle | 🎯 | Moderate |
| Grenade | 🧨 | Uncommon |
| Helicopter | 🚁 | Rare |
| Tank | ⚙️ | Rarest regular |
| Wild | ⭐ | Substitutes for any regular symbol |
| Scatter | 🚩 | Triggers free spins (reels 2–5 only) |
| Bomb | 💣 | Clears row + column |
| Super Bomb | ☢️ | Clears entire grid |

### Winning

Clusters of **5 or more** connected matching symbols pay out based on the paytable. Wilds substitute for any regular symbol and can also form their own pure-wild clusters.

**Win = paytable multiplier × bet × sum of cell multipliers in the cluster**

### Cascade System

1. All bombs detonate first
2. Winning clusters are paid out and cleared
3. Remaining symbols fall down; new symbols fill from the top
4. Repeats until no bombs and no clusters remain

### Free Spins

| Scatters | Spins Awarded |
|---|---|
| 3 | 8 |
| 4 | 12 |
| 5 | 20 |

- Multipliers carry over from the triggering spin and **accumulate** throughout the session
- Bombs are replaced by Super Bombs (increased frequency)
- Additional scatters during free spins retrigger the same awards

### Bet Steps

`$0.20 · $0.50 · $1.00 · $2.00 · $5.00 · $10.00 · $20.00 · $50.00`

---

## Getting Started

No installation or build step required.

1. Clone or download the repository
2. Open `operation-jackpot.html` in any modern browser
3. Play

```bash
git clone https://github.com/kcw36/Operation-Jackpot.git
cd Operation-Jackpot
# Open operation-jackpot.html in your browser
```

---

## Project Structure

```
operation-jackpot.html   # Entire game — markup, CSS, and JS in one file
CLAUDE.md                # Developer spec and architecture notes
README.md                # This file
```

The game is intentionally kept as a single self-contained file for maximum portability.

---

## Roadmap

- [ ] **Scatter Polish** — scatter symbol to use identical block-drop animation and multiplier display as regular symbols
- [ ] **Free Spins Mode** — 3/4/5 scatters trigger 8/12/20 free spins; multipliers accumulate; bombs replaced by super bombs
- [ ] **Win Messages** — thematic overlay text scaled to win size ("GOOD HIT" → "TOTAL ANNIHILATION")
- [ ] **Python RTP Simulation** — simulate 10M+ spins to verify return-to-player, hit frequency, and cascade depth distribution
- [ ] **RTP Fine-Tuning** — adjust symbol weights and paytable values to hit target RTP (~95%)
- [ ] **Buy Bonus** — purchase direct free spins entry at a fixed cost multiplier
- [ ] **Mobile Layout** — responsive scaling for smaller screens

---

## License

This project is a prototype. No license has been applied yet.
