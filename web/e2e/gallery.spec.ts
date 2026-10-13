import { expect, test } from "@playwright/test";

const HOME_URL = "http://localhost:5173/";
const API_BASE = "http://localhost:8000";

test.describe("Gallery modal e2e", () => {
  test.beforeEach(async ({ request }) => {
    const ready = await request.get(`${API_BASE}/api/ready`);
    expect(ready.ok()).toBeTruthy();
  });

  test("biblioteca does not flicker loading state while open", async ({ page }) => {
    await page.goto(HOME_URL);
    await page.getByRole("button", { name: /Abrir galeria/i }).click();
    await expect(page.getByRole("heading", { name: /Galeria/i })).toBeVisible();

    const loading = page.getByText("Carregando…", { exact: true });
    await expect(loading).toBeHidden({ timeout: 15000 });

    // Wait longer than the old 3s poll interval — loading must not reappear
    await page.waitForTimeout(6500);
    await expect(loading).toBeHidden();

    const modal = page.locator(".v2-modal");
    await expect(modal.getByRole("heading", { name: "Biblioteca", level: 3 })).toBeVisible();
    await expect(modal.locator(".v2-gallery-item")).not.toHaveCount(0);
  });
});
