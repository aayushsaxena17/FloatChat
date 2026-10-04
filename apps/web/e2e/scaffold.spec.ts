import { test, expect } from "@playwright/test";

test("browser loads scaffold and reaches the local API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading")).toContainText("Explore the ocean");
  await expect(page.getByRole("status")).toHaveText("Local services ready");
});
