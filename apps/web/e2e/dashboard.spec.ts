import { test, expect, type Page } from "@playwright/test";

test("profile with bad salinity shows reasons instead of empty axes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1818, height: 1000 });
  await page.goto(
    "/explore/profiles?region=Indian+Ocean&start=2025-01-01&end=2025-04-01&qc=science_ready&platform=5906257&profile=f85f411b-9a3f-4de7-a073-e2ca8818f2be",
  );
  const charts = page.getByTestId("profile-charts");
  await expect(charts.getByText("No readings", { exact: true })).toHaveCount(2);
  const salinity = charts
    .getByRole("heading", { name: "Practical salinity versus pressure" })
    .locator("../..");
  const ts = charts
    .getByRole("heading", { name: "Temperature-salinity diagram" })
    .locator("../..");
  await expect(salinity).toContainText(
    "Salinity readings are marked as bad quality.",
  );
  await expect(ts).toContainText(
    "No usable salinity readings to pair with temperature.",
  );
  await expect(salinity.locator(".chart")).toHaveCount(0);
  await expect(ts.locator(".chart")).toHaveCount(0);
  await expect(charts.getByRole("button", { name: "Reset view" })).toHaveCount(
    1,
  );
  const cards = await charts.locator(".chart-panel").all();
  const heights = await Promise.all(
    cards.map(async (card) => (await card.boundingBox())?.height),
  );
  expect(heights[1]).toBe(heights[0]);
  expect(heights[2]).toBe(heights[0]);
});

// scripts/stage3_acceptance.py sets STAGE3_SHOTS_DIR to keep screenshots of the checkpoints.
async function checkpoint(page: Page, name: string) {
  const directory = process.env.STAGE3_SHOTS_DIR;
  if (!directory) return;
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${directory}/${name}.png`, fullPage: true });
}

// The Stage 3 scenario (build prompt, tests): open the dashboard, filter to the Arabian Sea,
// January 2025, 0-100 dbar, and see map points and a profile chart. Filters are driven through
// the controls and asserted in the URL (PRD 14.3); the map count is read from its live region
// and the profile is selected through the list (ADR-0062), never through canvas pixels.
test("dashboard: Arabian Sea, January 2025, 0-100 dbar shows map points and a profile chart", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "An ocean of data.A deeper understanding.",
  );
  await expect(page.getByText("Local services ready")).toBeVisible();

  const filters = page.getByRole("form", { name: "Filters" });
  await filters.getByLabel("Region").selectOption("Arabian Sea");
  await filters.getByLabel("Start (UTC day, inclusive)").fill("2025-01-01");
  await filters.getByLabel("End (UTC day, exclusive)").fill("2025-02-01");
  await filters.locator(".advanced-filters > summary").click();
  await filters.getByLabel("Pressure from (dbar)").fill("0");
  await filters.getByLabel("Pressure to (dbar)").fill("100");
  await expect(page).toHaveURL(/region=Arabian\+Sea/);
  await expect(page).toHaveURL(/start=2025-01-01/);
  await expect(page).toHaveURL(/end=2025-02-01/);
  await expect(page).toHaveURL(/depth_min=0/);
  await expect(page).toHaveURL(/depth_max=100/);

  await expect(page.getByRole("heading", { name: /Coverage/ })).toBeVisible();
  await expect(page.locator(".coverage-scope")).toContainText("Arabian Sea");
  const mapStatus = page.getByTestId("map-status");
  await expect(mapStatus).toHaveText(/[1-9]\d* profiles plotted/, {
    timeout: 60_000,
  });
  const mapBounds = await page.locator(".map-canvas").boundingBox();
  expect(mapBounds?.height).toBeGreaterThan(250);
  await expect(
    page.getByRole("heading", { name: "Temperature mean (°C)" }),
  ).toBeVisible({ timeout: 60_000 });
  const coverageCard = await page.locator(".coverage").boundingBox();
  const locationsCard = await page.locator(".locations-panel").boundingBox();
  expect(coverageCard?.y).toBe(locationsCard?.y);
  expect(coverageCard?.height).toBeCloseTo(locationsCard?.height ?? 0, 0);
  expect(coverageCard?.width).toBeCloseTo(locationsCard?.width ?? 0, 0);
  await expect(page.locator(".coverage-scope")).toContainText(
    "1 Jan 2025 to 1 Feb 2025",
  );

  await page
    .getByRole("button", { name: "Coverage & ingestion details" })
    .click();
  const coverageDialog = page.getByRole("dialog", {
    name: "Coverage & ingestion details",
  });
  await expect(coverageDialog).toBeVisible();
  await expect(coverageDialog).toContainText("Arabian Sea (iho-v3");
  await expect(
    coverageDialog.getByText("FloatChat ingestion", { exact: true }),
  ).toBeVisible();
  const coverageAfterOpen = await page.locator(".coverage").boundingBox();
  expect(coverageAfterOpen?.height).toBe(coverageCard?.height);
  expect((await page.locator(".locations-panel").boundingBox())?.height).toBe(
    locationsCard?.height,
  );
  await page.keyboard.press("Escape");
  await expect(coverageDialog).not.toBeVisible();
  await page
    .locator(".locations-panel")
    .getByRole("button", { name: "Data source & processing details" })
    .click();
  const sourceDialog = page.getByRole("dialog", {
    name: "Data source & processing details",
  });
  await expect(sourceDialog).toBeVisible();
  await expect(
    sourceDialog.getByText("Result SHA-256", { exact: true }),
  ).toBeVisible();
  await sourceDialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(sourceDialog).not.toBeVisible();
  await checkpoint(page, "01-dashboard");
  await page.getByRole("link", { name: "Open the map" }).click();
  await expect(page).toHaveURL(/\/explore\/map\?.*region=Arabian\+Sea/);
  await expect(page.getByTestId("map-status")).toHaveText(
    /[1-9]\d* profiles plotted/,
    { timeout: 60_000 },
  );
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  const list = page.getByTestId("profile-list");
  await list.getByRole("button", { name: "Show profile" }).first().click();
  await expect(page).toHaveURL(/profile=[0-9a-f-]{36}/);
  await expect(page).toHaveURL(/platform=\d+/);
  await expect(page.getByTestId("map-status")).toHaveText(
    /trajectory of \d+ positions/,
    { timeout: 60_000 },
  );

  await checkpoint(page, "02-map");
  await page
    .getByRole("link", { name: "Open the selected profile's charts" })
    .click();
  await expect(page).toHaveURL(/\/explore\/profiles\?.*profile=/);
  const charts = page.getByTestId("profile-charts");
  await expect(
    charts.getByRole("heading", { name: "Temperature versus pressure" }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(
    charts.getByRole("heading", { name: "Temperature-salinity diagram" }),
  ).toBeVisible();
  const listCard = await page.locator(".profiles-list-panel").boundingBox();
  const summaryCard = await page.locator(".profile-summary").boundingBox();
  expect(listCard?.y).toBe(summaryCard?.y);
  expect(listCard?.height).toBeCloseTo(summaryCard?.height ?? 0, 0);
  await charts.getByText("How these charts are built", { exact: true }).click();
  await expect(charts.getByText("Recorded at", { exact: true })).toBeVisible();
  await expect(charts.getByText(/paired readings shown/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Temperature-salinity diagram" }),
  ).toHaveCount(1);
  await expect(charts.getByRole("button", { name: "Reset view" })).toHaveCount(
    3,
  );
  const tsChart = charts
    .getByRole("heading", { name: "Temperature-salinity diagram" })
    .locator("../..");
  await expect(tsChart.locator(".chart")).toContainText("Pressure", {
    timeout: 30_000,
  });
  const first = charts.locator("section").first();
  await expect(first.locator(".chart")).toBeVisible();
  await expect(first.locator(".chart")).toContainText("Pressure (dbar)", {
    timeout: 30_000,
  });
  const ticks = first.locator(".ytick");
  const originalTicks = await ticks.allTextContents();
  await first.locator(".nsewdrag").scrollIntoViewIfNeeded();
  const plotArea = await first.locator(".nsewdrag").boundingBox();
  expect(plotArea).not.toBeNull();
  if (plotArea) {
    await page.mouse.move(
      plotArea.x + plotArea.width * 0.2,
      plotArea.y + plotArea.height * 0.2,
    );
    await page.mouse.down();
    await page.mouse.move(
      plotArea.x + plotArea.width * 0.8,
      plotArea.y + plotArea.height * 0.7,
      { steps: 8 },
    );
    await page.mouse.up();
    await expect.poll(() => ticks.allTextContents()).not.toEqual(originalTicks);
    await first.getByRole("button", { name: "Reset view" }).click();
    await expect.poll(() => ticks.allTextContents()).toEqual(originalTicks);
  }
  await first.getByRole("tab", { name: "Table" }).click();
  await expect(
    first.getByRole("columnheader", { name: "Temperature (°C)" }),
  ).toBeVisible();
  expect(await first.locator("tbody tr").count()).toBeGreaterThan(0);
  await charts
    .getByText("Quality & processing details", { exact: true })
    .click();
  await expect(charts.getByTestId("provenance").first()).toBeVisible();
  await checkpoint(page, "03-profiles");
});
