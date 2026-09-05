# MCP 工具目录

本目录存放项目相关的 MCP (Model Context Protocol) 工具配置与自定义服务器。

## 当前 MCP 工具

### Playwright MCP (`@playwright/mcp`)

浏览器自动化测试工具，配置在 `.claude/settings.local.json` 的 `mcpServers` 中：

```json
"mcpServers": {
  "playwright": {
    "command": "npx",
    "args": ["-y", "@playwright/mcp"]
  }
}
```

用途：
- e2e 浏览器测试自动化
- 页面截图与交互验证
- Cesium 3D 场景的自动化回归测试

相关文件：
- `playwright.config.js` — Playwright 测试配置
- `tests/e2e/` — 测试用例目录
- `package.json` → `npm run test:e2e` — 运行测试命令

### 自定义 MCP 服务器

已实现：**[GeoMCP](custom/geo_mcp_server/README.md)** —— 地理空间分析服务器，
把 `backend/app/tools/` 的 11 个分析工具 + 1 个 Agent 工具以 MCP 协议对外暴露。

- 入口：`custom/geo_mcp_server/server.py`
- 接入指南、可用工具、排障表：`custom/geo_mcp_server/README.md`
- 客户端配置示例：`custom/geo_mcp_server/config/`

快速验证：

```bash
# 必须用 backend 虚拟环境（工具依赖 numpy / rasterio / onnxruntime）
backend/.venv/Scripts/python.exe mcp/custom/geo_mcp_server/tests/test_mcp_server.py
```

---

新增自定义服务器放在 `mcp/custom/` 目录下，每个服务器应包含：
- `server.py` 或 `server.js` — 服务器入口
- `README.md` — 使用说明
- `tests/` — 测试

两个本项目特有的坑，写新服务器时同样适用：

1. **必须用 `backend/.venv` 的 Python 启动**，否则调用时缺 GIS 依赖。
2. **必须用脚本绝对路径启动，不能用 `-m`**：项目根目录下的 `mcp/` 目录
   与官方 SDK 包同名，以 `-m mcp.xxx` 方式启动会遮蔽 SDK，
   报含糊的 `No module named 'mcp.server'`。
   以 `python <绝对路径>/server.py` 启动时 `sys.path[0]` 是脚本所在目录，不受影响。

> 注：`.gitignore` 忽略 `mcp/` 下的运行产物（`playwright-report/`、`test-results/`），
> 但放行 `mcp/README.md` 与 `mcp/custom/`。
