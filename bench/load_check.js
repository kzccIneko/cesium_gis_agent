// 浏览器加载验证脚本：采集控制台错误 + 关键全局对象状态
// 用法: node load_check.js <url> <输出json路径>
const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
  const url = process.argv[2] || 'http://127.0.0.1:8765/Cesium_coordinate_copy_czDebugging.html';
  const outPath = process.argv[3] || 'load_check_out.json';
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });

  const consoleErrors = [];
  const consoleWarnings = [];
  const pageErrors = [];
  const failedRequests = [];

  page.on('console', (msg) => {
    const text = msg.text();
    if (msg.type() === 'error') consoleErrors.push(text.slice(0, 300));
    if (msg.type() === 'warning') consoleWarnings.push(text.slice(0, 200));
  });
  page.on('pageerror', (err) => pageErrors.push(String(err).slice(0, 300)));
  page.on('requestfailed', (req) => {
    const failure = req.failure() ? req.failure().errorText : '';
    // 忽略外部 CDN（离线环境必然失败）与中止请求
    if (/ERR_ABORTED|net::ERR_NAME_NOT_RESOLVED|net::ERR_INTERNET_DISCONNECTED/.test(failure) === false || req.url().includes('127.0.0.1')) {
      failedRequests.push((req.url() + ' | ' + failure).slice(0, 250));
    }
  });

  try {
    await page.goto(url, { waitUntil: 'load', timeout: 60000 });
  } catch (e) {
    pageErrors.push('GOTO_FAIL: ' + String(e).slice(0, 200));
  }
  // 等 Cesium/延迟脚本/异步初始化跑完
  await page.waitForTimeout(15000);

  const globals = await page.evaluate(() => {
    const t = (v) => typeof v;
    return {
      jquery: t(window.jQuery),
      jqueryVersion: window.jQuery ? window.jQuery.fn.jquery : null,
      hasDraggable: window.jQuery ? t(window.jQuery.fn.draggable) : 'no-jquery',
      turf: t(window.turf),
      echarts: t(window.echarts),
      layui: t(window.layui),
      cesium: t(window.Cesium),
      toolbarMove: t(window.toolbarMove),
      RoughAnalysis: t(window.RoughAnalysis),
      TerrainProfileAnalysis: t(window.TerrainProfileAnalysis),
      TerrainClassification: t(window.TerrainClassification),
      viewer: t(window.viewer),
    };
  });

  const result = {
    url,
    consoleErrors: [...new Set(consoleErrors)],
    consoleErrorCount: consoleErrors.length,
    pageErrors: [...new Set(pageErrors)],
    pageErrorCount: pageErrors.length,
    failedLocalRequests: failedRequests.filter((r) => r.includes('127.0.0.1')),
    otherFailedRequests: [...new Set(failedRequests.filter((r) => !r.includes('127.0.0.1')))],
    globals,
  };
  fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
  console.log('errors:', result.consoleErrorCount, 'pageErrors:', result.pageErrorCount, 'globals:', JSON.stringify(result.globals));
  await browser.close();
})();
