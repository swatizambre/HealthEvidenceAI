import { expect, test } from "@playwright/test";

/**
 * FAANG pilot smoke: Today → patients → chart evidence pack → Reviews → disclaimer.
 * Uses demo sign-in (local dig-jwt).
 */
test.describe("desk smoke", () => {
  test("today, patients, reviews show professional evidence-pack chrome", async ({ page }) => {
    // The insurance desk is opt-in (Settings); the smoke covers it switched on.
    await page.addInitScript(() => window.localStorage.setItem("he.insuranceDesk", "1"));
    await page.goto("/");
    await expect(page.getByRole("link", { name: "HealthEvidence AI" })).toBeVisible();
    await expect(page.locator(".app-footer")).toContainText(/not a medical device/i);

    const demo = page.getByLabel("Demo sign-in");
    if (await demo.count()) {
      await demo.selectOption("staff");
    }

    await expect(page.getByTestId("heading-today")).toBeVisible({ timeout: 30_000 });

    const nav = page.getByRole("navigation", { name: "Application" });
    await nav.getByRole("link", { name: "Patients", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Patients" })).toBeVisible({ timeout: 30_000 });

    // Open first patient from the table (prefer PAT- links in tbody).
    const rowLink = page.locator("table a[href^='/patients/PAT-']").first();
    if (await rowLink.count()) {
      await rowLink.click();
    } else {
      await page.locator('a[href^="/patients/PAT-"]').first().click();
    }

    await expect(page.locator("#evidence-packet, .packet-panel, .chart-name").first()).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByText(/Evidence pack/i).first()).toBeVisible();

    await nav.getByRole("link", { name: "Reviews", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Reviews" })).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".app-footer")).toContainText(/does not diagnose|approve|deny/i);
  });
});
