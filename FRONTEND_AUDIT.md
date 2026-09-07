# 前端结构与逻辑审计报告

审计对象：`cesium_old/`，入口 `Cesium_coordinate_copy_czDebugging.html`（1378 行 / 71 KB，共 90 个 `<script>`）。

自研 JS 约 **15.8k 行**（不含 `libs/`、`node_modules/`）。本报告只做只读调查，未修改任何文件。
`Cesium_coordinate_copy_czDebugging.html`、`features/slope/TerrainBackendIntegration.js`、
`features/slope/TerrainClassification.js` 目前有未提交的工作区修改，报告中已单独标注。

---

## 一、结论：最该先动的 4 处

按「收益 / 风险」排序。

| # | 问题 | 位置 | 收益 | 风险 |
|---|---|---|---|---|
| 1 | 同一库重复加载（jQuery ×3、turf ×2、echarts ×2、layui ×2） | HTML:1268/1321/1326 等 | 高：直接消除插件丢失隐患、省 ~1.5 MB | **中**，需实测 |
| 2 | 拖拽逻辑 4 份重复实现 | `eventBindInit.js:232`、`RoughAnalysis.js:175/401/669`、`TerrainProfileAnalysis.js:429` | 高：行为统一，动态面板自动生效 | 低 |
| 3 | 「SlopeAspect copy debug.js」是实际生效文件 | HTML:1353 | 高：消除"改了没反应"的陷阱 | 低（改名） |
| 4 | 无统一窗口管理器，14 个悬浮窗各自为政 | 全局 | 中：层级/位置/单例可控 | 中 |

---

## 二、依赖加载：3 份 jQuery，2 份 turf

### 事实

```
1268:  libs/jquery/jquery.js           （非 defer，立即执行）
1272:  easyui                          （已注释）
1279:  libs/echarts/echarts.js         （第 16 行还有 CDN 版 echarts）
1281:  libs/jqueryui/jquery-ui.js      （非 defer，挂在 1268 的 jQuery 上）
1321:  measure/jquery/jquery.min.js    （defer，jQuery 第 2 份）
1323:  measure/layui-v2.6.8/.../layui.js
1326:  libs/jquery/jquery.min.js       （defer，jQuery 第 3 份）
1327:  libs/turf/turf.min.js
1328:  libs/layui/layui.all.js         （layui 第 2 份）
1349:  ./libs/turf/turf.js             （turf 第 2 份）
```

### 为什么这是问题

jQuery 每加载一次就覆盖 `window.$` / `window.jQuery`。加载顺序决定：

1. `jquery-ui`（1281）把 `.draggable()` 等插件挂到 **1268 那份** jQuery 上；
2. 1321、1326 随后把 `window.$` 换成**新的、没有插件的** jQuery；
3. 1326 之后执行的所有代码（`js/index.js`、`features/**`、SlopeAspect 各模块）拿到的 `$`
   是**不带 jQuery UI 的干净实例**。

也就是说，任何 `.draggable()` / `.slider()` 调用在 1326 之后都会抛
`TypeError: $(...).draggable is not a function`。目前没炸，多半是因为拖拽实际是
自己用 `.mousedown` 实现的（见第三节），jQuery UI 的拖拽根本没被用上——
**等于白加载 250 KB 的 jQuery UI**。

turf 与 echarts 同理：最终 `window.turf` 是 1349 的 `turf.js`（1327 的 min 版被覆盖），
最终 `echarts` 是 1279 的本地版（第 16 行 CDN 版被覆盖）。**两份都下载，只用最后一份。**

### 建议

- jQuery 只留一份。推荐保留 1268 那份并删除 1321、1326 ——
  这样 jQuery UI 的插件能挂住，`$` 全程唯一。
- 删除 1327（`turf.min.js`），保留 1349；删除第 16 行的 CDN echarts 或 1279 的本地版，二选一。
- 删 1323 或 1328 的 layui，保留一份。

**风险提示**：需要先确认 `measure/cesium-measure.js` 是否依赖 measure 目录下的 jQuery 副本。
建议改完后在浏览器里跑一遍量算功能。

---

## 三、拖拽：同一段逻辑写了 4 遍

### 事实

中心实现只有一处，绑在静态元素上：

```js
// features/eventBindInit.js:232
$('.move').mousedown(function () { toolbarMove(this); });
$('.close').click(function () {
    $(this.parentNode.parentNode).css('display', 'none');   // 236
});
$('.toggle_win').click(function () {
    $(".content", this.parentNode.parentNode).slideToggle(); // 239
});
```

但另有 4 处**内联重复实现**：

- `features/slope/RoughAnalysis.js:175`
- `features/slope/RoughAnalysis.js:401`
- `features/slope/RoughAnalysis.js:669`
- `features/slope/TerrainProfileAnalysis.js:429`

（均为 `(function makeDraggable(...) {...})(...)` 的 IIFE 形式）

### 为什么会重复

`$('.move').mousedown(...)` 在 `$(document).ready()` 里执行，只覆盖**当时已存在**的元素。
而 RoughAnalysis、TerrainProfileAnalysis 的面板是**运行时动态创建**的，
静态绑定抓不到，于是每个文件各自复制了一份拖拽代码。

这是典型的「静态绑定 + 动态元素」不匹配，靠复制粘贴绕过。

### 建议

改成事件委托，一处搞定，动态面板自动生效：

```js
$(document).on('mousedown', '.move', function () { toolbarMove(this); });
$(document).on('click', '.close', function () {
    $(this).closest('.functionWin').hide();
});
$(document).on('click', '.toggle_win', function () {
    $('.content', $(this).closest('.functionWin')).slideToggle();
});
```

顺带把 236 行的 `this.parentNode.parentNode` 换成 `.closest('.functionWin')` ——
现在这种写法对 DOM 层级是硬编码假设，往标题栏里多套一层 div 就会静默失效。

**风险**：低。委托与直接绑定行为一致，只影响新增元素。

---

## 四、命名陷阱：线上文件叫 "copy debug"

```
1353: <script src="./features/slope/SlopeAspect copy debug.js" defer></script>
```

实际加载的是 `SlopeAspect copy debug.js`（1324 行），
而 `features/slope/SlopeAspect.js`（1013 行）**没有被任何入口引用**。

两份已经分叉（1324 vs 1013 行）。这意味着：
改 `SlopeAspect.js` 不会有任何效果，而文件名又在暗示它是调试副本。
后续接手的人（包括面试时看你代码的人）极易改错文件。

同目录下还有 9 个 `modules/SlopeAspect*Module.js`，看起来是正在做的模块化拆分——
即当前处于"原始文件 → 复制出 debug 副本 → 拆模块"的中途状态。

**建议**：确认 `copy debug` 版是最新后，把它重命名为 `SlopeAspect.js`（先备份旧的），
入口改指向规范文件名。文件名里不要留 "copy debug"。

---

## 五、窗口管理：14 个悬浮窗，没有管理者

### 事实

HTML 里有 **14 个** `class="functionWin"` 的悬浮窗口和 **14 个** `class="head move"` 拖拽头：

`alert_download`(276)、`rec_search`(295)、`slopeWindow`(322)、`contourWindow`(543)、
`modelWindow`(609)、`loadLayerWin`(717)、`gaochengshuju`(760)、`spatialMeasureWin`(798)、
`avoidanceAreaAnalysisWin`(828)、`loadDataWin`(933)、`loadCzmlWin`(994)、
`saveSceneWin`(1030)、`displaySettingWin`(1048)、`markWin`(1220)

但没有 `WindowManager` 之类的统一抽象（全仓库搜索无结果）。每个窗口的：

- **显示/隐藏**：各处直接改 `style.display`，没有统一入口
- **层级**：无 z-index 管理，后开的窗口不一定在最上层
- **位置**：硬编码在 HTML 的 `style="left:400px; top:64px"` 里（如 276 行），
  全 HTML 共 **133 处 inline style**

### 后果

- 多个窗口叠加时点不到被遮住的那个（没有"点击置顶"）
- 同一功能可开出多个实例（无单例约束）
- 窗口位置写死在 HTML，无法记忆、无法做"层叠排列"
- 改样式要翻 HTML 找 inline style，无法用 CSS 统一控制

### 建议

抽一个 `WindowManager`，统一管：注册 / 打开 / 关闭 / 置顶 / 层叠定位。
把 inline 的 `left/top` 收进 CSS 变量或 JS 配置。

**风险**：中。涉及全部 14 个窗口的调用点，建议分期做——
先只做"点击置顶 + 单例"，不动各窗口内部的业务逻辑。

---

## 六、次要问题

| 问题 | 位置 | 说明 |
|---|---|---|
| `EventModel` 对象过大 | `eventBindInit.js:255` 起 | 该文件共 2840 行，`EventModel` 一个字面量对象承载了等高线、坡度、路径、量算等全部业务入口，是事实上的"上帝对象" |
| 顶层隐式全局 | `eventBindInit.js:6-15` | `center` / `tracker` / `layerId` / `shapeDic` / `flag` / `bxmap` / `area_alpha` 直接 `var` 在顶层，无命名空间，与第三方库冲突风险高 |
| 实例挂 window | `eventBindInit.js:278/297/637/650/662` | `window._profileAnalysisInstance`、`window.SlopeAnalysis`、`window._RoughAnalysisInstance` 等；637/650/662 三处重复 `window._RoughAnalysisInstance \|\| new RoughAnalysis()` 的懒加载写法 |
| 副本目录 | `Cesium_tests/`、`test/` | 各有一批 HTML 副本，含 `Cesium_coordinate_copy_副本.html`。与 `cesium_old/` 主入口内容重叠，改一处忘一处 |
| CDN 依赖 | HTML:16/87/89/90 | echarts、onnxruntime-web、vue、element-plus 走 CDN。离线或校园网受限时直接白屏 |

---

## 七、建议的推进顺序

1. **先做第三节（拖拽委托）** —— 改动小、收益明确、几乎无回归风险，可立刻删掉 4 份重复代码。
2. **再做第四节（文件改名）** —— 纯重命名，先备份，消除后续踩坑。
3. **然后第二节（依赖去重）** —— 需要浏览器实测一遍量算与坡度功能。
4. **最后第五节（WindowManager）** —— 最大的一块，建议拆成"置顶 + 单例"两期，
   不要一次重写 14 个窗口。

第 1、2 步可以马上做且不影响你正在写的 WIP；
第 3、4 步建议在你当前这轮 WIP 提交之后再做，避免和未提交改动打架。
