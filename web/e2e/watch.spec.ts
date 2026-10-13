import { expect, test } from "@playwright/test";

const VIDEO_ID = "untitled_video_-_made_with_clipchamp__3";
const WATCH_URL = `http://localhost:5173/watch/${VIDEO_ID}`;
const API_BASE = "http://localhost:8000";

test.describe("Watch page e2e", () => {
  test.beforeEach(async ({ request }) => {
    const ready = await request.get(`${API_BASE}/api/ready`);
    expect(ready.ok()).toBeTruthy();
  });

  test("API returns video with correct stream URL", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/v2/videos/${VIDEO_ID}`);
    expect(res.ok()).toBeTruthy();
    const data = await res.json();
    expect(data.id).toBe(VIDEO_ID);
    expect(data.title).toContain("Clipchamp");
    expect(data.stream_url).toBe(`/api/v2/media/${VIDEO_ID}/source.mp4`);
    expect(data.kind).toBe("original");
  });

  test("source video is streamable", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/v2/media/${VIDEO_ID}/source.mp4`);
    expect(res.ok()).toBeTruthy();
    const ct = res.headers()["content-type"] ?? "";
    expect(ct).toContain("video");
  });

  test("watch page loads player and title", async ({ page }) => {
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-watch-title")).toBeVisible({ timeout: 15000 });
    await expect(page.locator(".v2-watch-title")).toContainText("Clipchamp");
    await expect(page.locator(".v2-player-wrap video")).toBeVisible();
  });

  test("action bar shows pipeline buttons", async ({ page }) => {
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-actions")).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("button", { name: /Obter metadados/i })).toHaveCount(0);
    const clipBtn = page.getByRole("button", { name: /^Gerar clip$/i });
    await expect(clipBtn).toBeVisible();
    await expect(clipBtn).toBeEnabled();
    await expect(page.getByRole("button", { name: /Remover silêncios/i })).toBeEnabled();
    await expect(page.getByRole("button", { name: /Gerar legendas/i })).toBeEnabled();
    await expect(page.getByRole("button", { name: /Publicar/i }).first()).toBeEnabled();
  });

  test("video element receives valid src", async ({ page }) => {
    await page.goto(WATCH_URL);
    const video = page.locator(".v2-player-wrap video");
    await expect(video).toBeVisible({ timeout: 15000 });
    const src = await video.getAttribute("src");
    expect(src).toContain(VIDEO_ID);
    expect(src).toContain("source.mp4");
  });

  test("navigation: logo returns to home", async ({ page }) => {
    await page.goto(WATCH_URL);
    await page.locator(".v2-logo").click();
    await expect(page).toHaveURL(/localhost:5173\/?$/);
    await expect(page.locator(".v2-canvas-empty")).toBeVisible({ timeout: 10000 });
  });

  test("bay shell shows media rail and ops on desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-bay-rail")).toBeVisible({ timeout: 15000 });
    await expect(page.locator(".v2-bay-ops")).toBeVisible();
    await expect(page.locator(".v2-system-dock")).toHaveCount(0);
    await expect(page.locator(".v2-bay-ops-gauges .v2-gauge").first()).toBeVisible();
    await expect(page.locator(".v2-bay-ops .v2-health-dot").first()).toBeVisible();
  });

  test("ops drawer opens from command strip on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-bay-ops--open")).toHaveCount(0);
    await page.getByRole("button", { name: /Abrir painel de ops/i }).click();
    await expect(page.locator(".v2-bay-ops--open")).toBeVisible({ timeout: 10000 });
    await expect(page.locator(".v2-bay-ops-gauges .v2-gauge").first()).toBeVisible();
  });

  test("ops related section is present on watch page", async ({ page }) => {
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-bay-ops-title").filter({ hasText: /^Related$/i })).toBeVisible({
      timeout: 15000,
    });
  });
});

test.describe("Create clip modal", () => {
  test("opens manual timeline editor", async ({ page }) => {
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-actions")).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: /^Gerar clip$/i }).click();
    await expect(page.getByRole("heading", { name: /Criar clipe/i })).toBeVisible();
    await expect(page.locator(".v2-create-clip-preview-frame video")).toBeVisible();
    await expect(page.locator(".v2-create-clip-track")).toBeVisible();
    await expect(page.getByPlaceholder(/Adicione um título/i)).toBeVisible();
    await expect(page.getByText(/Adicionar legendas/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /Salvar clipe/i })).toBeVisible();
    await expect(page.getByText(/Analisar highlights/i)).toHaveCount(0);
  });
});
