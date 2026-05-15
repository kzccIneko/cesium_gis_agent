# Copilot instructions for this repository

## Build, run, and verification commands

### Backend (FastAPI, Python)

- Start backend (recommended, from repo root):
  - `powershell -ExecutionPolicy Bypass -File .\backend\run_backend.ps1`
- What the script does:
  - creates/uses `backend\.venv`
  - installs `backend\requirements.txt`
  - runs `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

### Frontend (Cesium static app)

- Install frontend dependencies used by `Cesium_coordinate_copy_czDebugging.html`:
  - `cd .\cesium_old`
  - `npm install`
- Serve frontend:
  - use VS Code Live Server (workspace is configured for port `5501`), and open `cesium_old\Cesium_coordinate_copy_czDebugging.html`

### Tests / lint

- There is no project-level automated test/lint command configured in the root, `backend`, or `cesium_old` package scripts.
- For a single targeted backend check, call one endpoint directly (after backend is running), for example:
  - `curl -X POST "http://127.0.0.1:8000/api/v1/analyze/terrain" -H "Content-Type: application/json" -d "{\"bbox\":{\"west\":110.9,\"south\":30.7,\"east\":111.1,\"north\":30.9},\"resolution\":64,\"analysis_type\":\"slope\",\"output_formats\":[\"geojson\"]}"`

## High-level architecture

- This repo is a **static Cesium frontend** (`cesium_old`) plus a **FastAPI analysis backend** (`backend`).
- Main frontend entry page is `cesium_old\Cesium_coordinate_copy_czDebugging.html`; it wires a large set of legacy global scripts and UI panels.
- `features\earthOpera.js` initializes `viewer` and shared UI shell, and `features\SidebarManager.js` manages search/layer groups and visibility.
- Terrain/path backend integration is orchestrated in `features\slope\TerrainBackendIntegration.js`:
  - requests `/api/v1/analyze/terrain`, `/api/v1/analyze/path`, `/api/v1/dem/meta`, and cache-clear endpoints
  - manages request tiling + dynamic LOD + layer lifecycle
  - registers loaded results into sidebar layers and numeric hover tips
- Backend API entry is `backend\app\main.py`; computation is in `backend\app\services\analysis_service.py`; artifact export is in `backend\app\services\export_service.py`.
- Backend returns artifact URLs (`/outputs/...` or `/tile-cache/...`) that frontend loads into Cesium as GeoJSON/CZML/KML.

## Key conventions specific to this codebase

- **Script load order matters.** This app is not module-bundled; many files depend on globals. Preserve script order in `Cesium_coordinate_copy_czDebugging.html`.
- **Global-state pattern is intentional.** Files share `window`/`global` symbols (`viewer`, `SlopeAnalysis`, `_terrainBackend*`, `sidebarManager`). Avoid refactors that isolate modules unless all dependents are updated.
- **Backend/Frontend visual parity is deliberate.** In `analysis_service.py` and `export_service.py`, formulas/color bins are written to match existing frontend slope/aspect behavior. Keep parity when changing metrics or color mapping.
- **Use atomic file writes for generated artifacts.** Backend writes output/cache JSON via temp-file replace; preserve this behavior for new backend outputs.
- **Cache lifecycle is part of UX.** Frontend triggers backend cache clear on init/pagehide; backend exposes `/api/v1/cache/outputs/clear` and `/api/v1/cache/tiles/clear`.
- **Current active app page is `Cesium_coordinate_copy_czDebugging.html`**, while `test\` contains experimental/demo HTML pages.
- **Repo docs context:** `cesium_old\README.md` tracks ongoing feature evolution; notably the 2026 updates emphasize backend-linked terrain/path analysis, cache robustness, and moving feature code under `features\`.
