import { test, expect } from "@playwright/test";

// Stage 5 (ADR-0081): the dashboard's export button creates a job for the filters; the job
// page follows it to completion over the seeded months and shows the downloads.
test("an export job runs from the dashboard filters to a download", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(
    "/dashboard?region=Arabian%20Sea&start=2025-01-01&end=2025-03-01&depth_min=0&depth_max=100&qc=science_ready",
  );
  const button = page.getByRole("button", { name: "Export filtered dataset" });
  await expect(button).toBeEnabled({ timeout: 60000 });
  await page.getByLabel("Export format").selectOption("csv");
  await button.click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/, { timeout: 30000 });
  await expect(
    page.getByRole("heading", { level: 1, name: "CSV export, Arabian Sea" }),
  ).toBeVisible();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible({
    timeout: 180000,
  });
  const download = page.getByRole("link", { name: /Download/ }).first();
  await expect(download).toHaveAttribute("href", /\/v1\/artefacts\/.*token=/);
  await expect(page.getByText(/measurement levels/)).toBeVisible();
  await expect(page.getByText(/doi.org\/10.17882\/42182/)).toBeVisible();
  await page.screenshot({ path: "test-results/job.png", fullPage: true });
  await page.goto("/jobs");
  await expect(
    page.getByRole("link", { name: "CSV export, Arabian Sea" }).first(),
  ).toBeVisible();
});
