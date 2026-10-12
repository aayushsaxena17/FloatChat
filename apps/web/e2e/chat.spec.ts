import { test, expect } from "@playwright/test";

// The integration stack runs the API with LLM_PROVIDER=offline (ADR-0069): the rule-based
// planner answers, the interpretation panel names it, and the seeded science rows execute.
test("chat turns a question into a validated plan with an interpretation panel", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/chat");
  const input = page.getByLabel("Your question");
  await input.fill(
    "Monthly mean temperature in the Arabian Sea from January to March 2025 in the upper 100 dbar",
  );
  await page.getByRole("button", { name: "Send" }).click();
  const thread = page.getByTestId("chat-thread");
  await expect(thread.locator('[data-kind="answer"]')).toBeVisible({
    timeout: 120000,
  });
  const toggle = page.getByRole("button", {
    name: /How FloatChat interpreted your request/,
  });
  await expect(toggle).toContainText("offline-rules-v1");
  await toggle.click();
  const panel = page.getByTestId("interpretation");
  await expect(panel).toContainText("Arabian Sea");
  await expect(panel).toContainText("0 to 100 dbar");
  await expect(panel).toContainText("aggregate mean by month");
  await expect(page.getByTestId("chat-result")).toBeVisible();
  await expect(page.getByTestId("provenance")).toBeVisible();
  // A follow-up without a period is a clarification, not a guess.
  await input.fill("salinity in the Bay of Bengal");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(thread.locator('[data-kind="clarification"]')).toBeVisible({
    timeout: 60000,
  });
  await page.screenshot({ path: "test-results/chat.png", fullPage: true });
});
