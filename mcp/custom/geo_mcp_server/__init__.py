"""GeoMCP —— 地理空间分析 MCP Server。

目录结构::

    geo_mcp_server/
      __init__.py   版本与导出
      server.py     FastMCP 入口（工具 + 资源 + 提示词 + Agent 工具）
      tools.py      把 backend/app/tools/ 的 11 个工具适配成 MCP 工具
      config/       Claude Desktop / Cursor 的接入配置示例
      tests/        测试（不需要真实 MCP 客户端即可运行）
      README.md     5 分钟接入指南

对外暴露：
- 11 个细粒度工具：DEM、坡度/坡向/曲率/成本表面、路径规划、
  三种地貌分类、分区统计
- 1 个 Agent 工具 geo_agent_query：一个问题走完「计划-执行-反思」
- 2 个资源：geo://tools、geo://capabilities
- 1 个提示词：geo_site_selection
"""

from __future__ import annotations

__version__ = "0.3.0"

__all__ = ["__version__"]
