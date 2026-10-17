# Brand mark redesign — evidence

Renders for the pull request that replaced the Lemely mark (concept a3, the
hairline `L` with a tick across it) with an open spiral notebook that riffles
its pages. Every image here is generated from the committed sources, not drawn
by hand.

| File | What it shows | How it was made |
|---|---|---|
| `before-after.png` | The previous mark beside the new one, both at 300px | `mark.svg` at `origin/develop` and at this branch, rasterised with sharp |
| `cuts.png` | The three standalone cuts at the sizes they actually ship at | the three files in `web/public/brand/` |
| `riffle.gif` | One full 6s cycle of the page turn | `BrandMark` plus `index.css`'s keyframes, rendered in Chromium |
| `in-context.png` | The header lockup, the pre-mount shell's draw-on, the PWA icon and the favicon | the built app under `vite preview`, and `dist/index.html` |

Two notes on how the animations were captured, because the naive method is
wrong in both cases:

- **`riffle.gif` scrubs rather than samples.** Screenshotting takes longer than
  the frame interval, so a `waitForTimeout` loop drifts — an early attempt at 12
  fps covered well over one cycle and neither matched the real speed nor looped.
  The frames come from pausing every animation and setting `currentTime`, which
  gives exact, evenly spaced phases and still honours each sheet's own
  `animation-delay`.
- **The shell's draw-on scrubs only its own animations.** `lm-shell-appear` is
  what reveals the slow-load tier after a 5s delay; winding that back to sample
  the draw puts it before its own delay, the tier returns to
  `visibility: hidden`, and there is nothing left to photograph.
