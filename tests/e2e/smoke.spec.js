// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('三维地理信息分析系统 - 冒烟测试', () => {

  test('页面正常加载', async ({ page }) => {
    await page.goto('/Cesium_coordinate_copy_czDebugging.html');

    // 标题正确
    await expect(page).toHaveTitle('三维地理信息分析系统');

    // Cesium 容器存在
    const cesiumContainer = page.locator('#cesiumContainer');
    await expect(cesiumContainer).toBeVisible({ timeout: 30_000 });

    // Cesium canvas 渲染成功
    const canvas = page.locator('canvas');
    await expect(canvas.first()).toBeAttached({ timeout: 30_000 });
  });

  test('导航栏功能正常', async ({ page }) => {
    await page.goto('/Cesium_coordinate_copy_czDebugging.html');

    // 导航栏品牌文字
    await expect(page.locator('.navbar-brand span')).toContainText('三维地理信息分析');

    // 数据管理下拉菜单可见
    const dropdowns = page.locator('.dropdown-toggle');
    await expect(dropdowns.first()).toBeVisible();
  });

  test('左侧工具栏存在', async ({ page }) => {
    await page.goto('/Cesium_coordinate_copy_czDebugging.html');

    // 侧边栏容器 (ID 为 sidebar)
    const sidebar = page.locator('#sidebar');
    await expect(sidebar).toBeAttached({ timeout: 20_000 });
  });

});
