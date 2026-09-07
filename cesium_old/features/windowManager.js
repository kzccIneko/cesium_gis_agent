/* WindowManager 第一期：点击置顶 + 单例注册表
 * 对应 FRONTEND_AUDIT.md 第五节 —— 14 个 functionWin 悬浮窗此前无统一管理者：
 *   - 无 z-index 管理，多窗叠加时点不到被遮住的窗口
 *   - 显示/隐藏各自为政，直接改 style.display
 * 本期只做「管理层」，不改任何窗口内部业务逻辑；第二期（层叠定位/位置记忆）另行迭代。
 *
 * 设计要点：
 *   1. 原生 document 捕获阶段监听，不依赖 jQuery、不依赖加载顺序；
 *   2. 委托 + closest：静态 14 窗与运行时动态创建的分析面板（RoughAnalysis 等）自动生效；
 *   3. zCounter 从 100000 起步（动态分析面板现用 99999，置顶后始终在其上）。
 */
(function () {
    'use strict';

    var topZ = 100000;

    function bringToFront(win) {
        if (!win || win.nodeType !== 1) return;
        var z = parseInt(win.style.zIndex, 10) || 0;
        if (z < topZ) {
            win.style.zIndex = ++topZ;
        }
    }

    // 点击任意窗口任意位置 → 置顶（capture：先于窗口自身 handler，且不阻塞默认行为）
    document.addEventListener('mousedown', function (e) {
        var win = e.target.closest && e.target.closest('.functionWin');
        if (win) bringToFront(win);
    }, true);

    // 单例注册表：静态窗口按 id 惰性登记，动态面板可主动 register
    var registry = {};

    function byId(id) {
        if (!registry[id] || !registry[id].isConnected) {
            var el = document.getElementById(id);
            if (el) registry[id] = el;
        }
        return registry[id] || null;
    }

    window.WindowMgr = {
        /** 手动登记动态面板（如 RoughAnalysis 创建的图表面板） */
        register: function (id, el) { registry[id] = el; return el; },

        bringToFront: bringToFront,

        isOpen: function (id) {
            var w = byId(id);
            return !!w && w.style.display !== 'none';
        },

        /** 单例打开：显示 + 置顶；已开则仅置顶 */
        open: function (id) {
            var w = byId(id);
            if (!w) return null;
            w.style.display = 'block';
            bringToFront(w);
            return w;
        },

        close: function (id) {
            var w = byId(id);
            if (w) w.style.display = 'none';
            return w;
        },

        /** 开-关切换 */
        toggle: function (id) {
            return this.isOpen(id) ? (this.close(id), null) : this.open(id);
        }
    };
})();
