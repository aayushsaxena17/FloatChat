# Ocean observatory frontend

The frontend uses an oceanic editorial identity while retaining the React/Vite application and existing API contracts.

- The dashboard opens with an original SVG current study and a typographic hero. The illustration is labelled and is not presented as observed current data.
- Explore the ocean carries the dashboard's filters into the map. View observations jumps to the working controls; keyboard focus follows the anchor.
- Navy surfaces and sea-glass accents extend through the dashboard, maps, profile views, chart/table tabs, errors, and native controls. Plotly and MapLibre use the corresponding dark palette.
- All metrics still come from the existing API. Coverage, truncation, provenance, units, and unavailable features retain their existing semantics.
- The layout adapts to phone screens, and reduced-motion preferences disable the hero pulse and smooth scrolling. The artwork, fonts, and favicon require no third-party requests.

## Files

`apps/web/src/dashboard/OceanHero.tsx` owns the hero and SVG. `apps/web/src/ocean.css` owns editorial layout and responsive styling. Shared control/data styles remain in `style.css`, with chart and map colours in `charts/palette.ts`.

## Preview and validation

From the repository root, with the existing API available on port 8000:

```sh
pnpm --filter @floatchat/web dev --port 5174
```

Port 5174 allows preview alongside the Docker frontend on port 5173.

Validated: 53 Vitest tests, both existing Playwright scenarios against the local API, TypeScript, ESLint, Prettier, and the production build. The hero link is checked against the full selected filter set. Desktop (1440px) and mobile (390px) layouts were inspected in the browser, including the observation anchor and horizontal overflow.

```sh
pnpm --filter @floatchat/web exec vitest run --maxWorkers=1
BASE_URL=http://127.0.0.1:5174 pnpm --filter @floatchat/web test:e2e
pnpm --filter @floatchat/web typecheck
pnpm --filter @floatchat/web lint
pnpm --filter @floatchat/web format:check
pnpm --filter @floatchat/web build
```
