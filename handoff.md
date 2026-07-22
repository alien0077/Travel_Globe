# Handoff — Travel Globe 航路圖 Session

**Session Tag**: `20260719-airgraph-global`
**日期**: 2026-07-19 23:30
**專案路徑**: `/Users/alien/Desktop/Travel_Globe`

## Session 摘要

將 AviationDB 從多來源（各國 eAIP、EAD、AIXM）**統一為 FlightGear GPL-only 資料源**，並整合進 Replay Engine 讓航班航線從 great circle 改為**真實航路路由**。

### 已完成變更

| 檔案 | 變更 |
|:----|:----|
| `AviationDB/scripts/export_airgraph.py` | **新增**：從 `awy.dat` 直接匯出主連通分量航路圖（26,742 航路點、8,541 航路、57,217 航段），跳過 SQLite 中繼層 |
| `shared/offline-packs/aviation/regions/global.airgraph.json` | **新增**：全球航路圖 JSON（3.3 MB，gzip 0.9 MB） |
| `shared/offline-packs/aviation/regions/global.airgraph.json.gz` | **新增**：gzip 壓縮版 |
| `FLIGHTGEAR_LICENSE.txt` | **新增**：GPL v2 版權宣告（Robin A. Peel / FlightGear） |
| `AviationDB/.gitignore` | **新增/修正**：排除 `data/raw/`、`data/processed/`、`data/releases/`、`data/reports/` |
| `replay-engine/src/flight-preload/airgraphIndex.ts` | **新增**：全域 `global.airgraph.json` 載入、空間網格索引（5° cells）、主圖連通分量濾波、Dijkstra 最短路徑 |
| `replay-engine/src/flight-preload/buildPreloadedFlightJourney.ts` | **修改**：整合 `findAirgraphRoute`，改用 `airgraphRoute.method === 'airway_graph'` 判斷而非 truthy/falsy；fallback 時走原本多點 great circle 插值 |
| `replay-engine/src/test/flightPreload.test.ts` | **修改**：航路點預期值從舊 asia-east 區域包（TONGA/MAKOT/...）更新為全球圖（KUDOS/LEKOS/...） |
| `replay-engine/src/test/flightAnalytics.test.ts` | **修改**：預期 `routeFallbackSource` → `routeMethod` + `routeSource` |
| `ios/TravelGlobe/Resources/ReplayEngine/index.html` | **修改**：iOS bundle 更新 |
| `ios/TravelGlobe/Resources/ReplayEngine/index.js` | **修改**：iOS bundle 更新（含 inline airgraph 資料） |
| `AviationDB/` (source code) | **新增**：完整的 AviationDB 模組（src/tests/scripts/config/docs） |

### 已刪除

| 檔案 | 原因 |
|:----|:----|
| `shared/offline-packs/aviation/regions/asia-east.airgraph.json` | 舊區域包，已被 global 取代 |
| `shared/offline-packs/aviation/regions/asia-east.airgraph.json.gz` | 同上 |

## 進行中工作

- **iOS 信任 profile**：手機上需去 設定→一般→VPN 與裝置管理→信任開發者描述檔，才能啟動 app

## 關鍵發現

### 航路圖架構
- FlightGear `awy.dat` 有 57,822 航段、8,609 條航路
- 連通分量分析：150 個分量，**主分量 26,742 點（98%）**
- 匯出腳本只保留主分量 → pack 從 139K 點降為 26K 點，JSON 從 10MB 降為 3.3MB
- 2-letter/3-letter waypoint 在全球各地重複出現（如 "N" 在 29 個不同位置），但每個 instance 有自己的座標，export 時用 `(ident, round_lat, round_lon)` 做 dedup key

### 路由引擎
- `airgraphIndex.ts` 使用 5° 空間網格加速最近點查找（~1ms per lookup）
- Dijkstra 實作在 26K 點圖上約需數十 ms
- 測試航線：TPE→NRT（19 WP, 1,258 NM）、JFK→LHR（80 WP, 7,628 NM）
- **Important**：great circle 保留為 fallback（`hasAirwayRoute` 檢查 method）

### 授權
- 專案本身 MIT License
- 航路資料源自 FlightGear `awy.dat`（Robin A. Peel, **GPL v2**）
- `FLIGHTGEAR_LICENSE.txt` 附有完整版權宣告
- `AviationDB/.gitignore` 排除了所有原始資料（`data/raw/`、`data/processed/`）
- `AviationDB/data/` 目錄完全不在 git 中

### 部署
- GitHub Pages CI 已驗證：typecheck → test (68/68) → build → deploy → URL 200
- Web: `https://alien0077.github.io/Travel_Globe/`
- iOS build for device 成功（xcodebuild + devicectl install & launch）

## 剩餘待辦

1. **手機信任 profile**：
   ```
   設定 → 一般 → VPN 與裝置管理 → 點一下開發者描述檔 → 信任
   ```

## 技術脈絡

### 常用指令
```bash
# AviationDB 匯出航路圖
python3 AviationDB/scripts/export_airgraph.py

# Web build & 測試
npm --prefix replay-engine run typecheck
npm --prefix replay-engine run test
npm --prefix replay-engine run build
npm --prefix replay-engine run preview

# iOS
bash scripts/copy-replay-to-ios.sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build -quiet -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO
bash deploy.sh ios-device
```

### 關鍵路徑
- 航路圖資料：`shared/offline-packs/aviation/regions/global.airgraph.json`（git tracked）
- 路由引擎：`replay-engine/src/flight-preload/airgraphIndex.ts`
- 航班 preload：`replay-engine/src/flight-preload/buildPreloadedFlightJourney.ts`
- 路由測試：`replay-engine/src/test/flightPreload.test.ts`
- 匯出腳本：`AviationDB/scripts/export_airgraph.py`

### commit
```
83a6c72 feat(aviation): FlightGear GPL 全球航路圖取代 great circle
```

## 恢復指令

```bash
# 1. 確認 handoff
test -f /Users/alien/Desktop/Travel_Globe/handoff.md && echo "HANDOFF_DETECTED"

# 2. 檢查 git 狀態
cd /Users/alien/Desktop/Travel_Globe && git log --oneline -5

# 3. 啟用記憶
# 執行 agent-recall session_start(project="Travel_Globe", mode="lite")
```
