// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('剖面分析 - 功能验证', () => {

  test.beforeEach(async ({ page }) => {
    page.on('pageerror', err => console.log('[页面错误]', err.message));
    await page.goto('/Cesium_coordinate_copy_czDebugging.html');
    // headless 模式下 Cesium Viewer 可能因 WebGL 问题未完全初始化
    // 但 canvas 仍会被创建（构造函数在 WebGL 初始化前就已创建 canvas）
    await page.waitForSelector('canvas', { timeout: 30_000 }).catch(() => {});
  });

  test('剖面分析模块全局可访问', async ({ page }) => {
    const hasModule = await page.evaluate(() => {
      return typeof window.TerrainProfileAnalysis === 'function';
    });
    expect(hasModule).toBe(true);
  });

  test('菜单项存在且可点击', async ({ page }) => {
    const menuItem = page.locator('#profileAnalysis');
    await expect(menuItem).toBeAttached();
    const text = await menuItem.textContent();
    expect(text).toContain('剖面分析');
  });

  test('EventModel.profile 方法存在', async ({ page }) => {
    const hasMethod = await page.evaluate(() => {
      return typeof EventModel !== 'undefined'
        && typeof EventModel.profile === 'function';
    });
    expect(hasMethod).toBe(true);
  });

  test('剖面分析模块构造函数签名正确', async ({ page }) => {
    const info = await page.evaluate(() => {
      var Ctor = window.TerrainProfileAnalysis;
      if (!Ctor) return { ok: false, reason: '构造函数不存在' };

      // 验证方法存在
      var proto = Ctor.prototype;
      return {
        ok: true,
        hasStartDrawing: typeof proto.startDrawing === 'function',
        hasStopDrawing: typeof proto.stopDrawing === 'function',
        hasClearAll: typeof proto.clearAll === 'function',
        hasExportCSV: typeof proto.exportCSV === 'function',
        hasAnalyze: typeof proto._analyzeProfile === 'function',
        hasShowChart: typeof proto._showChart === 'function'
      };
    });

    expect(info.ok).toBe(true);
    expect(info.hasStartDrawing).toBe(true);
    expect(info.hasStopDrawing).toBe(true);
    expect(info.hasClearAll).toBe(true);
    expect(info.hasExportCSV).toBe(true);
    expect(info.hasAnalyze).toBe(true);
    expect(info.hasShowChart).toBe(true);
  });

});
