import { test, expect } from "@playwright/test";

test("browser loads the shell and reaches the local API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "An ocean of data.A deeper understanding.",
  );
  await expect(page.getByText("Local services ready")).toBeVisible();
});
