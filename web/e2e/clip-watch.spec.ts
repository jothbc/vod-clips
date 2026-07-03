import { expect, test } from "@playwright/test";

const CLIP_ID = "2026-06-22_17-11-29::clip_04";
const PARENT_ID = "2026-06-22_17-11-29";
const CLIP_URL = `http://localhost:5173/watch/${CLIP_ID}`;
const API_BASE = "http://localhost:8000";

test.describe("Clip watch page e2e", () => {
  test.beforeEach(async ({ request }) => {
    const ready = await request.get(`${API_BASE}/api/ready`);
    expect(ready.ok()).toBeTruthy();
  });

  test("API returns clip detail with stream URL", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/v2/videos/${CLIP_ID}`);
    expect(res.ok()).toBeTruthy();
    const data = await res.json();
    expect(data.kind).toBe("clip");
    expect(data.stream_url).toContain(`clips/clip_04`);
    expect(data.parent_slug).toBe(PARENT_ID);
  });

  test("API related returns parent VOD", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/v2/videos/${CLIP_ID}/related`);
    expect(res.ok()).toBeTruthy();
    const items = (await res.json()).items;
    expect(items.length).toBeGreaterThan(0);
    expect(items[0].kind).toBe("original");
    expect(items[0].id).toBe(PARENT_ID);
  });

  test("clip page loads player and shows parent in sidebar", async ({ page }) => {
    await page.goto(CLIP_URL);
    await expect(page.locator(".v2-watch-title")).toBeVisible({ timeout: 15000 });
    await expect(page.locator(".v2-sidebar-title")).toContainText(/VOD original/i);
    await expect(page.locator(".v2-related-card")).toHaveCount(1);
    await expect(page.locator(".v2-related-card")).toContainText(PARENT_ID.replace(/_/g, " ").slice(0, 10));
    await expect(page.locator(".v2-player-wrap video")).toBeVisible();
  });
});
