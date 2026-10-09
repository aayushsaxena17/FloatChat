import { test, expect, type Page } from "@playwright/test";

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
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Dashboard");
  await expect(page.getByText("Local services ready")).toBeVisible();

  const filters = page.getByRole("form", { name: "Filters" });
  await filters.getByLabel("Region").selectOption("Arabian Sea");
  await filters.getByLabel("Start (UTC day, inclusive)").fill("2025-01-01");
  await filters.getByLabel("End (UTC day, exclusive)").fill("2025-02-01");
  await filters.getByLabel("Pressure from (dbar)").fill("0");
  await filters.getByLabel("Pressure to (dbar)").fill("100");
  await expect(page).toHaveURL(/region=Arabian\+Sea/);
  await expect(page).toHaveURL(/start=2025-01-01/);
  await expect(page).toHaveURL(/end=2025-02-01/);
  await expect(page).toHaveURL(/depth_min=0/);
  await expect(page).toHaveURL(/depth_max=100/);

  await expect(page.getByRole("heading", { name: /Coverage/ })).toBeVisible();
  await expect(
    page
      .getByRole("heading", { name: /Coverage/ })
      .locator("..")
      .locator(".."),
  ).toContainText("Arabian Sea (iho-v3");
  const mapStatus = page.getByTestId("map-status");
  await expect(mapStatus).toHaveText(/[1-9]\d* profiles plotted/, {
    timeout: 60_000,
  });
  await expect(
    page.getByRole("heading", { name: "Temperature mean (°C)" }),
  ).toBeVisible({ timeout: 60_000 });

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
  const first = charts.locator("section").first();
  await expect(first.locator(".chart")).toBeVisible();
  await expect(first.locator(".chart")).toContainText("Pressure (dbar)", {
    timeout: 30_000,
  });
  await first.getByRole("button", { name: "Table" }).click();
  await expect(
    first.getByRole("columnheader", { name: "Temperature (°C)" }),
  ).toBeVisible();
  expect(await first.locator("tbody tr").count()).toBeGreaterThan(0);
  await expect(charts.getByTestId("provenance").first()).toBeVisible();
  await checkpoint(page, "03-profiles");
});
