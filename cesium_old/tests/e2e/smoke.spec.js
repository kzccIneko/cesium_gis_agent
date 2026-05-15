const { test, expect } = require('@playwright/test');

test('主页可打开并显示标题', async ({ page }) => {
  await page.goto('/Cesium_coordinate_copy_czDebugging.html');
  await expect(page).toHaveTitle(/三维地理信息分析系统/);
});
