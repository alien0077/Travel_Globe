# Travel Globe Agent Notes

## Conversation
- 全程使用繁體中文討論。
- 使用者偏好端到端完成：實作、驗證、commit/push/deploy 狀態都要交代清楚。
- 禁止批量刪除如 `rm -rf *`；真的需要破壞性操作時必須先取得明確允許。

## Background Pipeline Rules
- 長時間 raw／解析／建圖工作必須使用可觀測的 detached worker，並保留 `status.json`、`done.json`、固定 log 與 PID/lock。
- `launchctl submit` 的 worker 完成後必須在寫入 `done.json` 後移除自身 label；wrapper 啟動前與 `__worker` 入口都必須先檢查完成標記，禁止 keepalive 重新掃描已完成日期。
- worker 非零失敗或被中止時必須原子寫入 `failed.json` 並移除自身 label；wrapper 與 `__worker` 看到失敗標記只能回報阻擋，不得由 keepalive 自動重跑或從頭掃描。
- 發現 `done.json` 已是 `complete` 時只能回報已完成，不得自動重跑；若確實需要重跑，必須使用新的版本化 job/output root 與新 label。
- 每次背景工作啟動後只做一次 startup sanity check；後續由使用者要求時查 status，不以前景輪詢浪費算力。
- raw 修復或重新下載後，所有下游步驟都必須使用同一份修復後 raw 重新產出版本化結果，禁止只重跑最後一層。
- 若只修復或重新下載單一日期，raw observation 只能重解析該日期；其餘未受影響日期必須核對 0.25 度輸出後重用既有 daily-derived，再從 merge 重新產出全部下游版本化結果，禁止無條件重掃全部 raw 日期。
- 若只修復或重新下載單一日期，raw observation 只能重解析該日期；其餘未受影響日期應核對 checksum 後重用既有 daily-derived，再從 merge 重新產出全部下游版本化結果，禁止無條件重掃全部 raw 日期。

## Memory And CodeGraph
- 本專案使用本機 `agent-recall` 作為跨 session 記憶入口。進入專案時先呼叫 `session_start(project="Travel_Globe", mode="lite")`，需要細節再用 `recall()`。
- 若本 session 產生部署、架構、測試、帳號限制、重大 bug/fix 等可復用知識，結束前用 `session_end(project="Travel_Globe", ...)` 保存摘要。
- 本機已初始化 CodeGraph：`.codegraph/` 是本機 sqlite 索引快取，不提交 Git。程式碼大改後執行 `codegraph sync .`，需要快速理解架構時用 `codegraph status .`、`codegraph files`、`codegraph explore <query>`。

## Project Shape
- Monorepo root 是 `/Users/alien/Desktop/Travel_Globe`，不要再包一層 `travel-globe/`。
- Web Replay Engine 在 `replay-engine/`，使用 Vite + TypeScript + Three.js，不使用 React。
- iOS shell 在 `ios/TravelGlobe/`，Replay Engine static build 由 `scripts/copy-replay-to-ios.sh` 複製到 `ios/TravelGlobe/Resources/ReplayEngine`。
- `replay-engine/public/readme.html` 是繁體中文使用手冊，Web UI 應可點進去閱讀；iOS bundle 也要包含該檔。

## Hosting And Deploy
- 目前主要 Web hosting 改用 GitHub Pages，正式 URL：
  `https://alien0077.github.io/Travel_Globe/`
- 使用手冊 URL：
  `https://alien0077.github.io/Travel_Globe/readme.html`
- GitHub Pages site 已用 GitHub API 建立，設定為 `build_type: workflow`；`.github/workflows/web-static.yml` 會 build 並用 `actions/deploy-pages@v4` 發布。
- Netlify 目前不可作為主要部署驗證來源，因為 `alien0077` team credits 已用完，production deploys 會被停用或跳過。除非使用者明確要求處理 Netlify 帳務/額度，否則以 GitHub Pages 驗證為準。
- 若 GitHub Pages workflow 在 `actions/configure-pages@v5` 失敗並出現 `Get Pages site failed ... Not Found`，代表 Pages site 尚未建立。
- 若出現 `Create Pages site failed ... Resource not accessible by integration`，不要反覆 rerun；用已登入的 GitHub 使用者權限建立 Pages：
  `gh api --method POST repos/alien0077/Travel_Globe/pages -f build_type=workflow`
- Pages 發布後用 `curl -I` 驗證首頁、`readme.html`、`index.js`、`index.css` 都回 `200`，不要只看 workflow 綠燈。

## Verification Commands
- Web:
  - `npm --prefix replay-engine run typecheck`
  - `npm --prefix replay-engine run test`
  - `npm --prefix replay-engine run build`
  - `npm --prefix replay-engine run preview`
  - `npm --prefix replay-engine run verify:preview`
- iOS static resource sync:
  - `./scripts/copy-replay-to-ios.sh`
- iOS build smoke:
  - `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild build -project TravelGlobe.xcodeproj -scheme TravelGlobe -destination 'generic/platform=iOS Simulator' -derivedDataPath /private/tmp/TravelGlobeDerived CODE_SIGNING_ALLOWED=NO`

## Known Issues
- GitHub Actions 可能顯示 Node 20 deprecation warning；目前不影響成功部署，但若 action 版本升級造成失敗，再更新 workflow action versions。
- Vite build 可能提示單一 bundle 超過 500 kB；目前是 warning，不是 deploy blocker。若後續素材/圖層變大，再做 code-splitting 或資產分層。
- 本機完整 `xcodebuild test` 曾卡在 simulator workers / `TEST INTERRUPTED`；不要把它當已通過。可先用 simulator generic build 作 smoke verification。
- Web/iOS 若出現白畫面，優先檢查 `replay-engine/dist/index.html` 的相對路徑、`vite.config.ts` 的 `base: './'`、以及 iOS bundle 是否已重新執行 `copy-replay-to-ios.sh`。
- iOS WKWebView 不要直接用本機 `file://` URL 作為 WebGL texture / GLB / JSON 等資源來源；常見狀況是網頁看似載入成功，但 GPU 實際不上貼圖或模型。Replay Engine 內嵌 iOS 時應使用自訂 scheme handler（目前為 `travelglobe://replay/`）或等效的 HTTP-like 來源，並在 build 後重新執行 `copy-replay-to-ios.sh`。
