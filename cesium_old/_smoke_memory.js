/* 冒烟脚本：验证「对话记忆 + 跳转不再抢跑采样」这两件事。
 *
 * 用法： node cesium_old/_smoke_memory.js
 * 前置： 后端在 8000，静态服务在 8081。
 */
const { chromium } = require('playwright');

const CHROME_EXE = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PAGE_URL = 'http://127.0.0.1:8081/Cesium_coordinate_copy_czDebugging.html';
const OUT = 'bench/_smoke_mem';

function ok(b) { return b ? '✅' : '❌'; }

(async () => {
  const errors = [];
  const browser = await chromium.launch({
    headless: true,
    executablePath: CHROME_EXE,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text().slice(0, 200)); });
  page.on('pageerror', (e) => errors.push('[pageerror] ' + String(e).slice(0, 200)));

  console.log('→ 打开主页面…');
  await page.goto(PAGE_URL, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForFunction(() => !!window.AgentPanel, null, { timeout: 60000 });

  // ---- 入口：顶部菜单图标（用户要求：顶部图标，右下角悬浮按钮已删）----
  const entry = await page.evaluate(() => {
    const nav = document.getElementById('agentChat');
    return {
      navExists: !!nav,
      // 应为纯图标：没有可见文字
      navText: nav ? nav.textContent.trim() : '(无)',
      floatGone: !document.getElementById('agentFloatBtn')
    };
  });
  console.log(ok(entry.navExists && entry.navText === ''), '顶部入口为纯图标（无文字）:', JSON.stringify(entry.navText));
  console.log(ok(entry.floatGone), '右下角悬浮按钮已移除');

  await page.click('#agentChat', { force: true });
  await page.waitForTimeout(1500);
  const opened = await page.evaluate(() => {
    const w = document.getElementById('agentAssistantWin');
    return !!w && getComputedStyle(w).display !== 'none';
  });
  console.log(ok(opened), '顶部图标可打开面板');

  // ---- session_id 应持久化到 localStorage ----
  // 注意：ID 是在**首次发消息时**才生成的，所以这里先记下基线，等第一句发完再查。
  const sidBefore = await page.evaluate(() => localStorage.getItem('geoagent.session_id'));
  console.log(ok(sidBefore === null), '初始尚无会话 ID（首次发送时才生成）:', String(sidBefore));

  // 放大到一块山区，让视野成为有效分析范围
  await page.evaluate(() => {
    if (window.viewer) {
      window.viewer.camera.flyTo({
        destination: Cesium.Rectangle.fromDegrees(109.0, 18.49, 111.0, 19.50),
        duration: 0
      });
    }
  });
  await page.waitForTimeout(2500);

  /** 发一句话，返回过程里出现过的等待文案（用来判断有没有偷跑地形采样） */
  async function ask(text) {
    const seen = [];
    await page.evaluate(() => {
      const el = document.getElementById('agentpInput');
      el.value = '';
    });
    // 监听等待文案变化
    await page.evaluate(() => {
      window.__seenWaiting = [];
      const chat = document.getElementById('agentpChat');
      window.__mo = new MutationObserver(() => {
        const w = chat.querySelector('.agentp-waiting');
        if (w && w.textContent) {
          const t = w.textContent.trim();
          const arr = window.__seenWaiting;
          if (!arr.length || arr[arr.length - 1] !== t) arr.push(t);
        }
      });
      window.__mo.observe(chat, { childList: true, subtree: true, characterData: true });
    });

    await page.fill('#agentpInput', text);
    await page.click('#agentpSendBtn');
    // 等这一轮结束（发送按钮恢复可用）
    await page.waitForFunction(
      () => !document.getElementById('agentpSendBtn').disabled,
      null, { timeout: 600000 }
    );
    await page.waitForTimeout(600);
    const seenWaiting = await page.evaluate(() => {
      window.__mo.disconnect();
      return window.__seenWaiting;
    });
    const last = await page.evaluate(() => {
      const msgs = Array.from(document.querySelectorAll('#agentpChat .agentp-msg'));
      const m = msgs[msgs.length - 1];
      if (!m) return {};
      const mem = m.querySelector('.agentp-memory-line');
      const act = m.querySelector('.agentp-source');
      return {
        bubble: (m.querySelector('.bubble') || {}).textContent || '',
        memory: mem ? mem.textContent.trim() : '',
        action: act ? act.textContent.trim() : ''
      };
    });
    console.log(`  「${text}」`);
    console.log(`     等待文案: ${JSON.stringify(seenWaiting)}`);
    if (last.memory) console.log(`     记忆: ${last.memory}`);
    if (last.action) console.log(`     ${last.action}`);
    console.log(`     回答: ${String(last.bubble).replace(/\n/g, ' ').slice(0, 110)}`);
    return { seenWaiting, ...last };
  }

  console.log('\n→ 第 1 句：看某个地方（应为跳转，不采样）');
  const r1 = await ask('我想看看五指山');
  console.log(ok(!r1.seenWaiting.some((t) => t.includes('采样')),
    '未触发地形采样（这就是之前那几分钟的来源）'));

  const sid1 = await page.evaluate(() => localStorage.getItem('geoagent.session_id'));
  console.log(ok(!!sid1), '会话 ID 已持久化（首次发送时生成）:', String(sid1));

  console.log('\n→ 第 2 句：用代词回指（应能理解成五指山）');
  const r2 = await ask('跳转到这个地方');
  console.log(ok(/五指山/.test(r2.memory || ''),
    '记忆生效：' + (r2.memory || '(无记忆提示)')));

  console.log('\n→ 第 3 句：换个地名（应同样秒级跳转，不采样）');
  const r3 = await ask('跳转到阿尔卑斯山');
  console.log(ok(!r3.seenWaiting.some((t) => t.includes('采样')),
    '换地名后也没触发采样'));

  console.log('\n→ 第 4 句：再回指一次（应指向新的地方）');
  const r4 = await ask('跳转到这个地方');
  console.log(ok(/阿尔卑斯/.test(r4.memory || ''),
    '记忆跟上最新一轮：' + (r4.memory || '(无记忆提示)')));

  await page.screenshot({ path: `${OUT}_chat.png` });

  // ---- 新会话按钮 ----
  const beforeLen = await page.evaluate(() =>
    document.querySelectorAll('#agentpChat > *').length);
  await page.click('#agentpNewSessionBtn');
  await page.waitForTimeout(600);
  const after = await page.evaluate(() => ({
    len: document.querySelectorAll('#agentpChat > *').length,
    sid: localStorage.getItem('geoagent.session_id')
  }));
  console.log('\n' + ok(after.len < beforeLen && after.sid === null),
    `新会话：对话区 ${beforeLen} → ${after.len} 条，旧会话 ID 已清除（下一条消息会用新会话）`);
  await page.screenshot({ path: `${OUT}_newsession.png` });

  const realErrors = errors.filter((e) =>
    !e.includes('tiff-imagery-provider') && !e.includes('favicon') &&
    !e.includes('Bing') && !e.includes('tile'));
  if (realErrors.length) {
    console.log('\n控制台报错（已过滤历史遗留项）:');
    realErrors.slice(0, 6).forEach((e) => console.log('  ' + e));
  } else {
    console.log('\n✅ 无新增控制台报错');
  }

  await browser.close();
})().catch((e) => { console.error('冒烟失败:', e); process.exit(1); });
