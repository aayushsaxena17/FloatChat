# Web design: light ocean theme and the float hero

The site uses one light palette, navy ink and a single action blue, with a real-time
three.js hero of an Argo float on the sea. The React/Vite application, routes, API contracts
and data semantics are unchanged (ADR-0076).

## Palette and tokens

The nine-step palette `#03045e → #023e8a → #0077b6 → #0096c7 → #00b4d8 → #48cae4 → #90e0ef →
#ade8f4 → #caf0f8` provides the surfaces (pale steps), the action colour (`#0077b6`), hover
(`#023e8a`) and the ink (`#03045e` for headings; a slightly desaturated navy for body text).
Every colour in `apps/web/src/style.css` is a token on `:root`; nothing is hard-coded in a
component. Status colours (good, warning, serious) are separate from the palette and always
ship with an icon or a label.

Chart series use the light categorical palette in `apps/web/src/charts/palette.ts` (slot 1 is
the action blue), validated with the data-viz palette checks: lightness band, chroma floor,
adjacent-pair colour-vision-deficiency separation and the normal-vision floor all pass; three
slots sit below 3:1 on white, which the table view of every chart covers. The offline MapLibre
style uses a pale sea, a light land fill and a blue point colour from the same file.

## Typography

Figtree (variable, SIL OFL) for the interface and body text; Source Serif 4 (variable, SIL OFL)
for page titles, section titles, the hero and the chat reading face. Both are served with the
app through `@fontsource-variable`; nothing is fetched from a third party.

## What was removed

Numbered mono eyebrows, kicker lines, edition and footnote captions, taglines under every
heading, "Soon" badges in the primary navigation, the brand subtitle and the labelled SVG
"current study". Functional notes stay: the truncation note on the float count, the coverage
disclaimer, the histogram bound notice, provenance and the footer attributions.

## The hero

`apps/web/src/dashboard/OceanHero.tsx` renders the copy and mounts the scene after the first
paint where WebGL is available. `apps/web/src/dashboard/oceanScene.ts` is a vanilla three.js
scene in its own async chunk: one displaced plane (150 × 110 segments) whose vertex shader sums
four directional sine waves, with a fragment shader for crest colouring, a Fresnel mix to the
sky, a tight sun glint plus a broad sheen, and distance fog into the horizon. The float is six
primitives; each frame it samples the same wave function on the CPU for its height and tilt.
The pixel ratio is capped at 1.5, the loop pauses when the hero scrolls out of view or the tab
is hidden, `prefers-reduced-motion` draws one frame, and the sky-to-water CSS gradient under
the canvas is the poster before the chunk loads and the whole hero wherever WebGL is off
(including jsdom in the unit tests). Everything is disposed on unmount.

## Preview and validation

From the repository root, with the dev stack on port 8000:

```sh
pnpm --filter @floatchat/web dev --port 5174
```

```sh
pnpm --filter @floatchat/web exec vitest run --maxWorkers=2
BASE_URL=http://127.0.0.1:5174 pnpm --filter @floatchat/web test:e2e
pnpm --filter @floatchat/web typecheck
pnpm --filter @floatchat/web lint
pnpm --filter @floatchat/web format:check
pnpm --filter @floatchat/web build
```

The build must keep `oceanScene-*.js` as its own chunk; the entry chunk must not import
`three`.
