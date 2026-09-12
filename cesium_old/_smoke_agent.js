/* 冒烟脚本：验证 GeoAgent 面板已嵌入主系统、能出表/图/图层，并且用的是真实地形。
 *
 * 用法： node cesium_old/_smoke_agent.js
 * 前置： 后端在 8000，静态服务在 8081。
 */
const { chromium } = require('playwright');

const CHROME_EXE = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PAGE_URL = 'http://127.0.0.1:8081/Cesium_coordinate_copy_czDebugging.html';
const OUT = 'bench/_smoke';

function ok(b) { return b ? '✅' : '❌'; }

(async () => {
  const errors = [];
  const browser = await chromium.launch({
    headless: true,
    executablePath: CHROME_EXE,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });

  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text().slice(0, 240)); });
  page.on('pageerror', (e) => errors.push('[pageerror] ' + String(e).slice(0, 240)));

  console.log('→ 打开主页面…');
  await page.goto(PAGE_URL, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForFunction(() => !!window.AgentPanel, null, { timeout: 60000 });

  // ---- 1. 入口：常驻悬浮按钮 + 顶部独立菜单项 ----
  const entries = await page.evaluate(() => {
    const floatBtn = document.getElementById('agentFloatBtn');
    const nav = document.getElementById('agentChat');
    const navParent = nav ? nav.parentElement : null;
    return {
      floatExists: !!floatBtn,
      floatVisible: !!floatBtn && getComputedStyle(floatBtn).display !== 'none',
      navExists: !!nav,
      // 关键：不能再挂在「空间分析」那个下拉里
      navIsTopLevel: !!navParent && navParent.classList.contains('navbar-nav'),
      navText: nav ? nav.textContent.trim() : ''
    };
  });
  console.log(ok(entries.floatExists && entries.floatVisible), '常驻悬浮按钮存在且可见');
  console.log(ok(entries.navExists && entries.navIsTopLevel),
    '顶部独立菜单项（不在任何分组里）:', entries.navText);

  // 点悬浮按钮开面板
  await page.click('#agentFloatBtn');
  await page.waitForTimeout(1000);
  const opened = await page.evaluate(() => {
    const w = document.getElementById('agentAssistantWin');
    return w && getComputedStyle(w).display !== 'none';
  });
  const btnActive = await page.evaluate(() =>
    document.getElementById('agentFloatBtn').classList.contains('is-active'));
  console.log(ok(opened), '悬浮按钮可打开面板');
  console.log(ok(btnActive), '按钮进入高亮（开/关状态可见）');

  // ---- 2. 元问题：问"看的是哪"不该触发任何计算 ----
  console.log('\n→ 问「现在的视野是什么区域范围」（元问题）…');
  await page.fill('#agentpInput', '现在的视野是什么区域范围');
  await page.click('#agentpSendBtn');
  await page.waitForTimeout(2500);
  const viewAns = await page.evaluate(() => {
    const bots = document.querySelectorAll('#agentpChat .agentp-msg-bot');
    const last = bots[bots.length - 1];
    if (!last) return null;
    return {
      text: (last.querySelector('.bubble') || {}).textContent || '',
      steps: last.querySelectorAll('.agentp-step').length,
      results: last.querySelectorAll('.agentp-result').length
    };
  });
  console.log('  回答:', (viewAns.text || '').replace(/\n/g, ' ').slice(0, 120));
  console.log(ok(viewAns.steps === 0 && viewAns.results === 0),
    '没有调用任何工具、没有出结果卡（期待 0 步）');

  // ---- 3. 视野过大 + 没点地名 → 应该被拦下 ----
  console.log('\n→ 视野还在全球时问「算一下坡度」…');
  await page.fill('#agentpInput', '算一下坡度');
  await page.click('#agentpSendBtn');
  await page.waitForTimeout(2000);
  const guarded = await page.evaluate(() => {
    const bots = document.querySelectorAll('#agentpChat .agentp-msg-bot');
    const last = bots[bots.length - 1];
    const t = last ? (last.querySelector('.bubble') || {}).textContent || '' : '';
    return { text: t, hasStep: !!last && last.querySelectorAll('.agentp-step').length > 0 };
  });
  console.log('  回答:', guarded.text.replace(/\n/g, ' ').slice(0, 110));
  console.log(ok(guarded.text.indexOf('太大') >= 0 && !guarded.hasStep),
    '被拦下并给出放大/报地名的指引，未擅自选区域计算');

  // ---- 4. 飞到具体区域，做真实地形分析 ----
  console.log('\n→ 相机飞到贡嘎山…');
  await page.evaluate(() => {
    if (window.viewer) {
      window.viewer.camera.flyTo({
        destination: Cesium.Rectangle.fromDegrees(101.72, 29.52, 102.02, 29.80)
      });
    }
  });
  await page.waitForTimeout(5000);
  console.log('  视野标签：', await page.textContent('#agentpCtxValue'));

  console.log('→ 发送「算一下当前视野的坡度」…');
  await page.fill('#agentpInput', '算一下当前视野的坡度');
  await page.click('#agentpSendBtn');

  let gotResult = false;
  try {
    await page.waitForSelector('#agentpChat .agentp-result', { timeout: 240000 });
    gotResult = true;
  } catch (e) { /* 下面统一报告 */ }

  const res = await page.evaluate(() => {
    const all = document.querySelectorAll('#agentpChat .agentp-msg-bot');
    const last = all[all.length - 1];
    const src = last ? last.querySelector('.agentp-source') : null;
    const cards = last ? Array.from(last.querySelectorAll('.agentp-metric')) : [];
    return {
      sourceTag: src ? src.textContent : '(无)',
      cards: cards.map((m) => (m.querySelector('.k') || {}).textContent + '=' +
                               (m.querySelector('.v') || {}).textContent),
      steps: last ? last.querySelectorAll('.agentp-step').length : 0,
      answer: last ? ((last.querySelector('.bubble') || {}).textContent || '').slice(0, 200) : ''
    };
  });
  console.log(ok(gotResult), '产出结果卡片');
  console.log('  数据来源标签:', res.sourceTag);
  console.log('  执行链路步数:', res.steps);
  console.log('  指标卡:', JSON.stringify(res.cards));
  console.log('  回答:', res.answer.replace(/\n/g, ' ').slice(0, 150));
  await page.screenshot({ path: `${OUT}_terrain.png` });

  // ---- 5. 叠加图层 ----
  const overlayBtn = await page.$('#agentpChat .agentp-btn.primary');
  if (overlayBtn) {
    console.log('\n→ 点击「叠加到地图」…');
    const before = await page.evaluate(() =>
      window.sidebarManager ? window.sidebarManager.getAllLayers().length : -1);
    await overlayBtn.click();
    await page.waitForTimeout(8000);
    const layers = await page.evaluate(() => window.sidebarManager
      ? window.sidebarManager.getAllLayers().map((l) => l.name + ' [' + l.type + ']') : null);
    console.log('  图层数:', before, '→', JSON.stringify(layers));
    await page.screenshot({ path: `${OUT}_overlay.png` });
  } else {
    console.log('  （没有可叠加的矢量产物）');
  }

  console.log('\n=== 控制台错误 ===');
  const uniq = [...new Set(errors)];
  if (!uniq.length) console.log('无');
  else uniq.slice(0, 8).forEach((e) => console.log(e));

  await browser.close();
})();
