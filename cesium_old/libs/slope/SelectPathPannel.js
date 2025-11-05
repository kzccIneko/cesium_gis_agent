(function(){
    const toggleBtn = document.getElementById('pathListToggleBtn');
    const panel = document.getElementById('pathListPanel');
    // const select = document.getElementById('pathListSelect');// 在SlopeAspect  pickPath()中已处理
    const closeBtn = document.getElementById('pathCloseBtn');

    function showPanelAtButton() {
      if (!toggleBtn || !panel) return;
      const rect = toggleBtn.getBoundingClientRect();
      panel.style.top = (rect.bottom + window.scrollY + 6) + 'px';
      panel.style.left = (rect.left + window.scrollX) + 'px';
      panel.style.display = 'block';
      // 打开面板时刷新路径列表（如果实例已创建）
     if (window.SlopeAnalysis && typeof window.SlopeAnalysis.pickPath === 'function') {
       try { window.SlopeAnalysis.pickPath(); } catch (e) { console.error(e); }
     }
    }
    function hidePanel() {
      if (panel) panel.style.display = 'none';
    }

    if (toggleBtn) {
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (panel.style.display === 'block') hidePanel();
        else showPanelAtButton();
      });
    }
    if (closeBtn) closeBtn.addEventListener('click', hidePanel);

    // 点击面板外部关闭
    document.addEventListener('click', (e) => {
      if (!panel) return;
      if (panel.style.display !== 'block') return;
      if (panel.contains(e.target) || (toggleBtn && toggleBtn.contains(e.target))) return;
      hidePanel();
    });

    // 当窗口大小或滚动时自动定位/隐藏
    window.addEventListener('scroll', hidePanel);
    window.addEventListener('resize', hidePanel);

    // Optional: 当路径列表更新时，自动展开面板（由 SlopeAspect.refreshPathListControl 调用即可）
    window.showPathListPanel = showPanelAtButton;
    window.hidePathListPanel = hidePanel;
  })();

  


  (function(){
  const btn = document.getElementById('usePotentialToggle');
  if (!btn) return;

  function updateButtonState() {
    const sa = window.SlopeAnalysis;
    if (!sa) {
      btn.textContent = ' 反向搜索：未初始化';
      btn.className = 'btn';
      return;
    }
    const on = Boolean(sa.usePotentialFieldFlag);
    btn.textContent = ' 反向搜索：' + (on ? '开启' : '关闭');
    btn.className = on ? 'btn btn--primary' : 'btn';
  }

  // 切换处理：切换标志
  btn.addEventListener('click', () => {
    if (!window.SlopeAnalysis) {
      alert('SlopeAnalysis 未就绪，请稍后重试');
      return;
    }
    const sa = window.SlopeAnalysis;
    sa.usePotentialFieldFlag = !Boolean(sa.usePotentialFieldFlag);
    updateButtonState();
    
  });

  // 等待 SlopeAnalysis 就绪，最多尝试若干次后停止
  let tries = 0;
  const maxTries = 40;
  const interval = setInterval(() => {
    if (window.SlopeAnalysis) {
      updateButtonState();
      clearInterval(interval);
      return;
    }
    if (++tries >= maxTries) {
      updateButtonState();
      clearInterval(interval);
    }
  }, 200);

  // 在窗口/面板显示时也同步状态
  window.addEventListener('focus', updateButtonState);
})();