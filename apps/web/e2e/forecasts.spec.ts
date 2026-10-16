import { test, expect } from "@playwright/test";

// Stage 6 (ADR-0085): a forecast request from the workspace becomes a job; over the three
// seeded months the run is refused with its reason, and the boundary text is still shown.
test("a forecast request runs as a job and a short history is refused honestly", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/forecasts");
  await page.getByLabel("Variable").selectOption("salinity");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/, { timeout: 30000 });
  await expect(page.getByText("Completed", { exact: true })).toBeVisible({
    timeout: 180000,
  });
  await page.goto("/forecasts");
  const link = page.getByRole("link", { name: /3-month forecast/ }).first();
  await expect(link).toBeVisible({ timeout: 30000 });
  await link.click();
  await expect(page.getByRole("alert")).toContainText("history_too_short", {
    timeout: 30000,
  });
  await expect(page.getByTestId("boundary")).toContainText(
    "not a physics-based ocean forecast",
  );
  await page.screenshot({ path: "test-results/forecast.png", fullPage: true });
});
