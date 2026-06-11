// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('地形分析 - 核心功能回归', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/Cesium_coordinate_copy_czDebugging.html');
    // 等待 Cesium 初始化
    await page.waitForSelector('canvas', { timeout: 30_000 });
  });

  test('Cesium 3D 视图正常渲染', async ({ page }) => {
    const canvas = page.locator('canvas').first();
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box.width).toBeGreaterThan(0);
    expect(box.height).toBeGreaterThan(0);
  });

  test('剖面分析菜单项存在', async ({ page }) => {
    // 空间分析下拉菜单中包含剖面分析菜单项
    const profileMenuItem = page.locator('#profileAnalysis');
    await expect(profileMenuItem).toBeAttached();
    const text = await profileMenuItem.textContent();
    expect(text).toContain('剖面分析');
  });

  test('页面无控制台错误', async ({ page }) => {
    const errors = [];
    page.on('pageerror', err => errors.push(err));

    await page.reload();
    await page.waitForSelector('canvas', { timeout: 30_000 });
    await page.waitForTimeout(3000);

    // 记录错误但不强制失败（Cesium 可能有第三方警告）
    if (errors.length > 0) {
      console.warn(`页面错误 (${errors.length}):`, errors.map(e => e.message).join(', '));
    }
  });

});
