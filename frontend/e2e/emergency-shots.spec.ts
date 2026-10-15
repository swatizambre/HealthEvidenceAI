import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";

const API = process.env.HE_API_BASE || "http://127.0.0.1:8010";

test.use({ viewport: { width: 390, height: 844 } });

test("emergency card flow screenshots", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.addInitScript(() => {
    window.localStorage.setItem("he.ai.deskRole", "patient");
    window.localStorage.setItem("he.ai.myPatientId", "PAT-000001");
  });
  await page.goto("/emergency");
  await page.waitForTimeout(4000);
  await page.screenshot({ path: "shots/0-landing.png", fullPage: true });
  await expect(page.getByRole("heading", { name: "Emergency card" })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("svg.qr-code")).toBeVisible();
  await page.getByText("Keep on this phone").click();
  await page.screenshot({ path: "shots/1-card.png", fullPage: true });

  const tok = await request.post(`${API}/api/v1/auth/dev-token`, {
    data: { subject: "PAT-000001", roles: ["patient"], patient_id: "PAT-000001" },
  });
  const access = (await tok.json()).access_token;
  const card = await (
    await request.get(`${API}/api/v1/me/emergency-card`, { headers: { Authorization: `Bearer ${access}` } })
  ).json();
  const token = String(card.emergency_url).split("/e/")[1];

  const pub = await page.context().newPage();
  await pub.setViewportSize({ width: 390, height: 844 });
  await pub.goto(`/e/${token}`);
  await expect(pub.getByRole("heading", { name: "Emergency medical card" })).toBeVisible();
  await pub.screenshot({ path: "shots/2-public.png", fullPage: true });
  await pub.getByRole("button", { name: "हिंदी" }).click();
  await pub.screenshot({ path: "shots/3-public-hi.png", fullPage: true });
  await pub.getByRole("button", { name: "English" }).click();
  await pub.getByLabel("Hospital or place").fill("City Hospital, emergency ward");
  await pub.getByRole("button", { name: "Send to family" }).click();
  await expect(pub.getByText("Sent. The family")).toBeVisible();
  await pub.screenshot({ path: "shots/4-public-sent.png", fullPage: true });

  await page.reload();
  await expect(page.getByText("Who opened it")).toBeVisible();
  await expect(page.getByText("City Hospital, emergency ward")).toBeVisible();
  await page.screenshot({ path: "shots/5-alerts.png", fullPage: true });

  await page.route("**/api/v1/me/emergency-card", (route) => route.abort());
  await page.reload();
  await expect(page.getByText("No connection")).toBeVisible();
  await page.screenshot({ path: "shots/6-offline.png", fullPage: true });

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  const pubOverflow = await pub.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  writeFileSync("shots/report.txt", JSON.stringify({ errors, overflow, pubOverflow }, null, 2));
});
