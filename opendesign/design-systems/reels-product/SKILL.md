---
name: reels-product
description: Product UI system for Reels — dark editorial studio for local VOD→clip workflows. Use when designing or iterating on the Reels web app shell, home, watch, jobs, or publish surfaces.
---

# Reels product design system

Extracted from `web/src/v2/` (v2.css, AppHeader, HomePage, WatchPage).

## Tokens

Load `tokens/colors_and_type.css`. Prefer semantic vars (`--surface-primary`, `--action-primary`, `--h1`) over raw hex.

## Posture

- Dark studio, warm amber accent, teal for healthy status.
- Display: Fraunces (logo, section titles). Body: Instrument Sans.
- Density mid: one primary action cluster per viewport; secondary actions collapse to buttons/modals.
- Brand mark: `Reels.` with amber period.
- Portuguese UI copy, sentence case.
- No purple gradients, no emoji-as-icons, no left-border accent cards.

## Surfaces in scope

Home feed (carousel + horizontal rows + library grid), Watch (player + action bar + related sidebar), Jobs, Publish wallet, System dock.
