# KHH ADS-B 端點恢復計劃

## 目的

恢復 KHH（高雄國際機場）相關航班的實際 ADS-B 航跡，尤其是
`KHH-NRT` 與 `NRT-KHH`，避免把 IFR 靜態航路誤顯示成實際飛行路線。

本計劃的原則是：不破壞已建立的路線資料；只有在 ADS-B 端點與航跡證據足夠時，才用觀測路線覆蓋 IFR 估算。

## 已確認的問題

- 目前觀測航線包約有 157,769 筆路線，但沒有任何 `KHH-*` 或 `*-KHH` 的已確認端點路線。
- `KHH-NRT` 與 `NRT-KHH` 目前都是 `directed_airway_graph`，是 IFR 靜態估算，不是 ADS-B 實際航跡。
- KHH 配對診斷有 145 條相近航路走廊候選，但嚴格的 KHH 起點／NRT 終點配對為 0 條。
- KHH 端點恢復曾看到 2,114 個相關航段，其中 1,949 個未能安全恢復為 KHH 航線。
- 失敗原因包含：第一個／最後一個收到的點離機場太遠、終點不是指定機場，以及被 RMQ、TPE、TSA 等鄰近機場競爭判定。
- 現有路線摘要與診斷檔不包含完整原始 ADS-B trace；若要重新判斷起降端點，必須取得相關原始資料。

## 來源優先順序

必須維持以下順序：

```text
observed_adsb / recovered_endpoint
  > directed_airway_graph
  > reverse_route_fallback / approximate_direct_fallback
```

說明：

- `observed_adsb`：端點已由 ADS-B 直接確認的實際航跡。
- `recovered_endpoint`：ADS-B 航跡存在，但端點透過航向、進離場航路、航班資訊與鄰近機場競爭分析恢復；必須保留 review warning。
- `directed_airway_graph`：用 IFR 航路圖產生的靜態候選，只能作為估算，不得阻擋較高可信度的觀測覆蓋。
- `reverse_route_fallback`：只有另一方向有可用路線時的反向幾何 fallback，必須註明不是獨立觀測。

## 救援流程

### 1. 保留現有資料

- 不刪除現有 `observed-routes`、route-shape selection、IFR graph 或 runtime pack。
- 將目前 KHH 的 IFR 路線保留為 fallback，並顯示「IFR estimated route」警告。
- 不因使用者看到的地理方向而手動捏造西側或東側 ADS-B 航跡。

### 2. 針對性重新取得原始 ADS-B

- 不重新下載全球資料。
- 先使用既有診斷中的日期、callsign、來源檔案與 KHH 相關航段縮小範圍。
- 若來源以每日壓縮檔提供，僅下載必要日期的原始檔，再在本機過濾 KHH 候選。
- 原始資料必須保留來源檔名、日期、callsign、trace ID 與下載／處理時間。
- 若來源資料無法重新取得，不能把未確認候選升級成實際 KHH 路線。

### 3. 建立 KHH 端點候選

不要只使用 trace 的第一點與最後一點。對每條候選航跡分析：

- 航跡前後 5–10 分鐘的連續點，而非單一端點。
- 高度變化：起飛爬升、巡航、下降與進場狀態。
- 航向與 KHH 的離場／進場方向是否一致。
- 是否進入 KHH 的 SID、STAR、進離場航路或 IFR corridor envelope。
- 與 RMQ、TPE、TSA、OGN、ISG 等鄰近或競爭機場的距離與航向。
- callsign、航班日期、航班時刻及 airport-pair 是否一致。
- 航跡是否與 IFR 路徑相近；IFR 只能作為候選走廊限制，不能單獨證明實際飛行。

### 4. 分級與人工審核

候選不得直接寫入正式觀測路線，先分級：

- `candidate_endpoint`：有走廊相似性，但端點證據不足。
- `recovered_endpoint`：至少有兩種獨立證據支持 KHH 端點，且沒有更合理的鄰近機場解釋。
- `observed_adsb_mapped`：起點與終點均通過嚴格機場配對，可直接作為實際觀測路線。
- `rejected`：保留拒絕原因，不刪除原始候選。

每條升級或拒絕結果都要保留：候選 trace、判定分數、端點距離、競爭機場、航向／高度證據、人工審核備註。

### 5. 去程與回程分開判定

- `KHH-NRT` 與 `NRT-KHH` 必須各自搜尋與驗證。
- 不可因為一個方向有 ADS-B，就自動把它反轉成另一方向的實際航跡。
- 若只能反轉使用，必須使用 `reverse_route_fallback` 並顯示明確警告。

### 6. 合併與播放驗證

- 觀測或恢復路線可以覆蓋 IFR 靜態路線。
- Replay Engine 必須識別 `observed_adsb_mapped` 與 `recovered_endpoint`，不可退回 Great Circle。
- Web、shared、iOS 三份 runtime pack 必須使用同一份輸出並做 hash 一致性檢查。
- 重新載入後確認 route method、warning、首末機場與航跡方向。

## 驗收條件

完成 KHH 救援前，不得宣稱 KHH-NRT 已恢復為實際航跡。完成後至少必須符合：

- `KHH-NRT` 有獨立端點證據，或明確標示仍為 `recovered_endpoint` review 狀態。
- `NRT-KHH` 有獨立端點證據，或明確標示為反向 fallback。
- 路徑方向、航點順序、起降機場與實際 trace 一致。
- 不再把鄰近 RMQ／TPE／TSA 航段誤標成 KHH。
- 原始 trace、診斷報告、選擇檔、runtime pack 與審核結果可互相追溯。
- Python tests、Web typecheck、Vitest、Web build 全部通過。
- 尚未確認前，UI 必須顯示 IFR estimate 或 review warning，而不是暗示為真實 ADS-B。

## 目前狀態（2026-08-07）

- 已修正全域來源優先順序，觀測路線不再被 IFR 靜態路線阻擋。
- 已修正 Replay Engine 對觀測／恢復路線的播放支援。
- 已恢復缺失的反向 fallback 路線，並保留反向警告。
- KHH-NRT 與 NRT-KHH 仍是 IFR estimate；尚未重新取得原始 KHH ADS-B trace。
- 下一個執行動作是針對性取得 KHH 相關日期／callsign 的原始資料，並執行上述端點恢復流程。

## 本次資料取得作業（2026-08-07）

- 目標日期：`2026-08-02`
- 來源：ADSB.lol `globe_history_2026` preferred release
- 背景工作：`alien.travelglobe.adsblol.20260802`
- raw 目錄：`AviationDB/data/raw/adsblol/2026-08-02/`
- 狀態檔：`AviationDB/data/raw/adsblol/2026-08-02.download-status.json`
- log：`AviationDB/data/raw/adsblol/2026-08-02.download.log`
- 規則：先只下載並保留 raw；完成後先分析與提出解法，不自動刪除、不自動覆蓋正式 route pack。

詳細結果見：`AviationDB/docs/2026-08-02-KHH-NRT-analysis-report.md`。
本次確認 `AIQ234` 屬於「航班身份可確認、幾何只有部分觀測」；後續必須使用點級 callsign 分段，並將 observed segment 與 IFR inferred connector 分開保存。
`CAL102`／CI102 已提供第二個獨立航空公司的同型證據：同樣在日本南側才開始被觀測、最後抵達 NRT；後續 pair 恢復必須採用多航班／多航空公司交叉支持。
`CAL126`／CI126 另外提供距 KHH 約 212.7 km 的第一觀測段，應作為 KHH-NRT 觀測 route template 的幾何 anchor；KHH 到該點只補 inferred connector，不再直接採用原 IFR graph path。

## 批次自動發現（不可要求使用者逐條提供航班代碼）

航班代碼只能是候選的加分證據，不能是分析入口。正式流程必須直接掃描整批 raw，自己發現 KHH 航線：

1. 對每個 aircraft-day trace 做點級 callsign segmentation；沒有 callsign 的點沿用同一段最近一次的 identity，但不因此丟棄航跡。
2. 建立 KHH 與 NRT 的空間／方向／高度 corridor envelope，不只使用第一點與最後一點的最近機場。
3. 對每個 segment 計算：
   - 是否進入 KHH outbound envelope；
   - 是否進入 NRT arrival envelope；
   - 兩個 envelope 的時間順序；
   - 起飛後爬升、巡航與下降狀態；
   - 航向與 route progress；
   - 與同日及相鄰日期候選的 shape similarity。
4. 先產生所有 `candidate_endpoint`，不要求已知航班號。
5. 將多個航班、不同 callsign、不同航空公司的候選聚類；共同的 KHH-NRT corridor 可互相增強信心。
6. 達到門檻後自動升級為 `recovered_endpoint`，並保存候選 trace、分數、端點缺口與判定原因。
7. 只有高信心群組才覆蓋 IFR；低信心群組保留為候選，不進正式 route pack。

CI126、CI102、AIQ234 的作用是驗證這個自動流程與提供 route template，不是要求使用者日後逐一輸入更多代碼。

批次流程的輸入應只有日期與目標機場，例如 `2026-08-02 + KHH`；輸出應自動列出所有可能的 KHH-NRT、NRT-KHH 及其他 KHH 航線。

## 禁止事項

- 不得把 IFR 圖形路徑當成 ADS-B 實際航跡。
- 不得只因路徑看起來「合理」就升級為 observed。
- 不得將一個方向的航跡自動反轉成另一方向的 observed。
- 不得為了讓地圖看起來符合預期而手動修改經緯度。
- 不得刪除現有原始候選、拒絕紀錄或診斷資料。

## 全球共用走廊網路主計劃（2026-08-08）

本節是後續執行的上位計劃，優先於「直接用 IFR 補 KHH-NRT」的做法。目標不是為每一個機場配一條獨立航線，而是先從多日、多航班的實際航跡建立全球共用走廊網路，再讓機場以端點／進離場連接方式接入。

### 目標資料模型

```text
raw ADS-B traces
  -> directed flight segments
  -> shared corridor graph
  -> airport feeder / endpoint links
  -> route pair view
```

每一條結果都必須同時保存：

- `corridorId`、方向、走廊幾何與涵蓋範圍；
- 支援的日期數、獨立 aircraft 數、callsign 數及航跡數；
- 走廊節點之間的連接距離、方向差、缺口與高度帶；
- 機場接入方式：`observed_endpoint`、`recovered_endpoint`、`corridor_inferred` 或 `reverse_inferred`；
- 原始 trace、來源檔、分析版本與判定理由。

### Phase 0：凍結證據與建立基準

1. 保留現有 28 天衍生 validation path、2026/08/02 raw、IFR graph 與 runtime pack，不覆蓋、不刪除。
2. 將目前 `KHH-NRT` 的結果標記為診斷基準，不把它當成共用走廊真值。
3. 先建立可重現的統計檔：每日 trace 數、leg 數、解析失敗數、端點缺口分布與機場競爭結果。
4. 所有後續計算輸出新版本目錄；完成驗收前不改正式 Web/iOS pack。

#### IFR 污染隔離規則

28 天 `validation path` 已經接受 IFR 路徑作為比較／篩選條件，因此不能再被當成獨立證據去訓練全球走廊。否則會出現循環論證：

```text
IFR 選出的路線
  -> validation path
  -> 建立共用走廊
  -> 反過來證明 IFR 路線正確
```

資料來源分級如下：

- `raw_direct`：原始 ADS-B trace，可作幾何與方向證據；仍需處理端點誤辨識。
- `raw_derived_unbiased`：由 raw 產生但未用 IFR 選路或修形的航跡／走廊，可作網路證據；必須保存產生規則。
- `ifr_validated_derived`：曾用 IFR 比對、篩選、修正或補形的 validation path，只能作候選索引、問題定位與弱先驗，不得計入走廊支援數、橋接證據或最終驗收。

若某一段只有 `ifr_validated_derived` 而沒有 `raw_direct` 或 `raw_derived_unbiased` 支持，該段必須標記 `ifr_contaminated_prior`，不可標記為 observed corridor。

#### 目前暫定 7 天範圍與未來擴展規則

- 目前目標暫定為 7 天；未經使用者重新確認，不下載或處理剩餘 21 天。
- 7 天範圍固定以目前已保留的 2026-08-02 raw 為錨點，採向過去回補，日期與處理順序明確寫入 manifest：`2026-08-02`、`2026-08-01`、`2026-07-31`、`2026-07-30`、`2026-07-29`、`2026-07-28`、`2026-07-27`。不得等待或推算尚未可用的 2026-08-09，也不得改成向未來日期抓取；每次重跑必須讀既有 manifest，不能自行重新推算日期。
- 2026-08-02 已有 raw，先直接進入 benchmark／processing；其餘日期依 manifest 向前逐日下載。若某日 raw 已完整，直接復用，不重新下載；若來源日期清單暫時不可取得，仍以 manifest 既定日期執行，不用網路結果覆蓋日期範圍。
- 7 天工作的目的是驗證 raw provenance、分段、走廊聚合、缺口分類、checkpoint/resume 與 KHH 接入規則；結果只能標為 `7-day provisional`，不得宣稱 28 天穩定結果。
- 未來若要擴展至 28 天，必須重新確認 quota、資料來源與 pipeline version；不得由背景 worker 自動延伸下載。

#### 背景下載與同步處理規則

工作採用 producer／consumer 模式：

```text
download day N+1  ───────────────┐
                                  ├─ process day N
download day N+2  ───────────────┘
```

- 只允許一個 download worker 與一個 process worker；啟動前必須檢查 lock、manifest、status 與現有程序，禁止重複 worker。
- 先在背景建立 7 天下載佇列；某日 raw 完整且通過檔案大小、HTTP headers、checksum 檢查後，才放入 processing queue。
- 處理 day N 時，才允許下載 day N+1；下載與處理可平行，但同一天不得同時被兩個 worker 下載或處理。
- 下載使用暫存檔，完成後 atomic rename；未完成檔不可被 parser 當作 raw input。
- raw 完成、processing 完成、QA 通過、corridor graph 納入，必須是不同狀態；不能以「下載完成」推論「分析完成」。
- 每日輸出必須記錄 input files、bytes、checksum、source URLs、pipeline version、git revision、開始／結束時間與統計數。

#### 硬碟 quota 閘門

所有背景工作啟動前必須先做 quota preflight；quota 不足時狀態只能是 `blocked_quota`，不得開始下載、不得刪除既有 raw，也不得用「先下載再想辦法」的方式繼續。

- 先讀取工作區、raw 目錄與暫存目錄的 filesystem free bytes。
- 先取得每個日期的 HTTP headers／預估 bytes，再計算：既有 raw、尚未下載 raw、下載暫存檔、處理輸出、索引、log 與安全餘量。
- 預設保留至少 20% 計算空間，並保留固定系統安全餘量；下載中的同一 asset 需要同時考慮暫存檔與完成檔，不能只用完成檔大小估算。
- 只有在 `free_bytes >= planned_bytes + processing_headroom + safety_reserve` 時，才可把日期從 `planned` 推進到 `downloading`。
- 7 天工作若要求本機保留全部 raw，必須一次確認 7 天總量；不能只檢查第一天。
- 最新 quota 快照（刪除未使用的 `.lima/docker` 後）：filesystem 約 233 GiB、可用約 31 GiB；2026/08/02 raw 約 3.1 GiB。macOS 顯示約 23 GB 可用，與 filesystem 的 GiB／保留空間差異相符。7 天「全部 raw 留在本機」仍須加計暫存、輸出與安全餘量，必須先通過逐日 preflight 才能解除 `blocked_quota`，不可只看目前 free 值直接啟動。
- quota 不足時只有兩個合法選項：使用者提供足夠容量的外接／另一個 filesystem 保存 raw，或明確批准「逐日處理後將 raw 移至可追溯的外部封存」；不得自動刪除 raw。
- 外部封存也必須保存 checksum、來源 URL、日期、pipeline version 與 manifest；未完成封存驗證前，原始檔不得移除。
- quota 閘門通過後，下載 worker 每完成一天必須重新計算剩餘容量；若下一天無法安全預取，停止在 `blocked_quota`，process worker 可完成已安全下載的日期。

#### 日期級 manifest 與不可重頭做規則

manifest 是唯一工作真相，至少使用以下狀態：

```text
planned -> downloading -> raw_complete -> processing -> processed -> qa_pass -> graph_ready
```

失敗狀態必須保留 `blocked` 與錯誤原因，不得自動退回 `planned`。

1. 啟動任何 worker 前先讀 manifest；`raw_complete` 不重新下載，`processed` 不重新解析，`qa_pass` 不重新計算，除非 input fingerprint、pipeline version 或 schema 明確改變。
2. 程序中斷時，從最後一個完整日期／stage checkpoint resume；不得因為上一日期失敗就刪除或重做已完成日期。
3. 程式修正只重跑受影響的日期與 stage；原始 raw、舊輸出與舊 log 必須保留，新的結果寫入新 version 目錄。
4. 每次重跑前必須記錄 reason：`missing_output`、`checksum_mismatch`、`parser_bug`、`schema_change` 或 `rule_change`；沒有 reason 不得重跑。
5. 不得使用會從頭重建整個 28 天累積包的舊 runner 作為正式 pilot runner，除非它先接入本 manifest、input fingerprint 與日期級 checkpoint。
6. 28 天最終驗收、raw evidence 封存與 checksum index 完成前，不得清理 raw。

#### Pilot 閘門

7 天工作必須先通過以下閘門，才可標記為可擴展；目前不會自動處理剩餘 21 天：

- 7 個日期各自有 `raw_complete` 與 `processed` 記錄，沒有隱藏缺日；
- parse errors、壞 tar、截斷檔與重複 trace 都有統計及處理結果；
- 走廊支援數只來自 `raw_direct`／`raw_derived_unbiased`，沒有把 IFR validation path 混入；
- 中段缺口只產生分類候選，不在單日或 pilot 中提前閉合；
- 同一輸入重新執行會命中 checkpoint，不再重新下載或從頭解析；
- pilot 報告與 manifest 經核對後才把 pipeline version 凍結。

若 pilot 閘門失敗，標記 `blocked` 並修正該 stage；不得繼續消耗剩餘 21 天資料，也不得以部分結果發布路線。

#### 背景處理效能與避免重複計算規則

舊的 IFR 第一版 runner 不得直接作為本計劃 runner。它包含逐日累積包重寫、route fingerprint 過濾、IFR validation 與多階段壓縮；這些工作對本計劃既慢又會引入 IFR 污染。新 runner 必須遵守：

1. 每個日期的 split tar 只做一次完整串流讀取；在同一次 trace／leg 解析中，同時產生 raw-derived geometry、callsign segment、corridor edge、端點候選與統計，不為每個分析另掃一次 raw。
2. 禁止逐日重寫 7 天累積 route pack。先寫日期級 immutable artifacts，7 天全部 `processed` 後才做一次 graph merge／export。
3. 禁止在 raw corridor pipeline 中呼叫 IFR validation、IFR route matching 或 IFR shape repair；這些只能在隔離的 audit stage 使用，不能阻塞 raw processing。
4. 幾何計算必須預先計算固定 polyline／網格常數，先做 bounding-box／空間索引篩選，再做精確距離；不得對每個點重複掃描整條全球 polyline。
5. 下載、解析、聚合與輸出使用 bounded queue；記憶體超過 quota budget 或暫存空間不足時，停止在 `blocked_resource`，不得用 swap 撐過去。
6. 每 10,000 traces 或每 15 分鐘寫一次進度 checkpoint；狀態查詢由使用者需要時讀 status/log，不建立高頻 polling worker。
7. 網路下載失敗只在 asset stage 重試；parser／聚合錯誤必須立即標記日期 `blocked`，不得無限重跑整日。
8. pilot 必須先用 2026/08/02 已保留 raw 做固定 benchmark，記錄 traces/sec、legs/sec、wall time、peak RSS、暫存峰值與 output bytes；新 runner 若比 benchmark 慢超過 30%，先停線優化，不開始下一日。
9. 每一日完成後驗證 input fingerprint 與 output manifest；相同 fingerprint／pipeline version 直接 resume，不重新解壓、重算或重壓縮。
10. 最終全球 corridor graph 只在所有日期處理完成後建立一次；中段缺口閉合不得插入每日處理迴圈。

本次啟動前稽核結論（2026-08-08）：舊 `run_observed_routes_daily_ifr_21d.sh` 已通過 shell 語法檢查，但不得直接重用。它的 60 次下載重試、逐日累積包重寫、IFR validation 串接與 raw cleanup 都不符合本計劃；新 runner 必須先以保留的 2026-08-02 raw 完成 benchmark，未達效能閘門前不得啟動 7 天下載。

目前正式 pilot runner 為 `AviationDB/scripts/run_raw_corridor_7d.sh`，核心元件為 `run_raw_corridor_7d.py`、`download_raw_release_safe.py` 與 `process_raw_corridor_day.py`；背景狀態與 manifest 位於 `/private/tmp/travel-globe-corridor-7d/`。首次啟動曾發現 raw 目錄的 `.tar.aa.headers` sidecar 被泛用 tar filter 誤納入，已改用明確 `.tar.aa` 至 `.tar.af` part 白名單並由 checkpoint 重試；此類 sidecar 不得再視為 raw part。重做版另外把 SHA-256 放入同一個 tar stream、用快速局部距離與端點 cache、以 checkpoint chunks 限制日內記憶體，並用 benchmark gate 阻止未產生 metrics 的日期繼續往下跑。

### Phase 1：從航跡建立全球走廊候選

1. 對每個 aircraft-day trace 做點級 callsign segmentation、時間排序與斷裂切段。
2. 將每一段轉成固定間隔的有向航跡邊；保存位置、航向、速度、高度與時間，不使用 origin/destination 標籤作為必要條件。
3. 以全球等距空間網格聚合鄰近邊，診斷預設為 along-track 80 km、cross-track 25 km；正式網路仍保存原始幾何。
4. 只有同時符合以下條件才形成走廊候選：
   - 相鄰邊的航向差通常不超過 15°；
   - 橫向距離通常不超過 50 km，轉向或匯流節點可放寬至 100 km；
   - 至少 3 條獨立 leg 支援，且至少 2 架不同 aircraft；
   - 有明確方向順序；反向流量另存方向，不直接當成同一條實測航跡。
5. 以圖算法合併相鄰候選邊；允許的缺口最多 150 km，且必須有方向、速度／高度或多日資料支持，不能單靠 IFR 線段跨接。

### Phase 2：建立多日全球共用網路

1. 先盤點現有 28 天衍生資料的 provenance；`ifr_validated_derived` 只用來找候選區域、缺口與需要重查的日期，不得直接建立 corridor edge 或計入 support。
2. 使用可追溯的 `raw_direct`／`raw_derived_unbiased` 建立第一版網路。目前只依 7 天範圍的背景佇列與 manifest 處理；可用保留的 2026/08/02 raw 建立日級 provisional graph，但若未來擴展，仍不能把 28 天 validation path 宣稱為 28 天實測走廊。
3. 對每條 corridor 計算穩定度：
   - `provisional`：單日且至少 3 legs；
   - `supported`：至少 2 日期、3 架 aircraft；
   - `stable`：至少 3 日期、5 架 aircraft，且方向／幾何一致。
4. 將東南亞、台灣周邊、日本、北美、歐洲等區域先各自聚合，再以跨區重疊邊合併，避免全球一次聚合造成錯誤跨洋連線。
5. 每條網路邊保留「直接觀測」與「推定橋接」區分；橋接邊不可提升其兩端原始觀測邊的可信度。
6. 產出全球 corridor graph 與可查詢的 evidence index，而不是只產生一條 `KHH-NRT` shape。

### Phase 2.5：全部資料完成後處理中段缺失

中段缺失與機場端點缺失是兩種不同問題。除非航跡確實進入機場 envelope，否則不得把中段斷點解釋成航班已經抵達或從另一個機場起飛。商業航班的走廊不會在非機場位置憑空終止，因此必須在完整資料集建立後，再做走廊級補接。

#### 補接前置條件

1. 必須先完成全部日期、全部 raw／derived path 的解析、去重、分段與 corridor clustering。
2. 不得在單日掃描中看到缺口就立即插值或寫入 route pack。
3. 補接只能使用已建立的 corridor graph 節點與邊；不可用 KHH-NRT 的 IFR 單一路徑直接填平缺口。
4. 每個候選缺口都要先分類：
   - `trace_observation_gap`：同一架飛機同一 trace 中間漏點；
   - `corridor_sampling_gap`：不同航班共同走廊的觀測涵蓋不足；
   - `corridor_branch_gap`：走廊在匯流／分流節點轉到另一條已存在的 corridor；
   - `unresolved_gap`：沒有足夠證據，保持斷開。

#### 同一 trace 的觀測缺點

- 只有在時間差、速度、航向、高度變化都合理，且前後點落在同一 directed corridor 時，才可產生幾何插值。
- 插值段必須保存前後 raw point、時間差、插值方法與誤差上限，狀態標記為 `trace_interpolated`，不得標記為直接 ADS-B observed。
- 若時間差過大、航向突然改變、速度／高度不合理或跨越不同走廊，保持斷開，不得強行連線。

#### 不同航班之間的共用走廊補接

這是東南亞→日本等長航線的主要補接方法：

1. 將前段 corridor edge 的出口與後段 corridor edge 的入口做有向配對。
2. 候選連接必須符合：
   - 走廊方向差通常不超過 15°；
   - 空間缺口通常不超過 50 km，匯流／轉向節點最多 150 km；
   - 前後兩側各有至少 3 legs、2 架不同 aircraft 支援；
   - 兩側的高度帶、速度範圍或航向變化相容；
   - 至少有兩個日期，或有多條獨立航跡支持同一連接。
3. 通過後產生的是 `corridor_bridge_inferred`，不是某一架飛機的實際航跡。
4. 若橋接跨越的不是既有 corridor edge，或必須依賴 IFR 才能連起來，狀態必須是 `unresolved_gap`。
5. 每個 bridge 必須保存：前後 corridorId、缺口距離、方向差、支援日期／aircraft／legs、使用的證據與信心分數。

#### 全球圖完成後的閉合分析

全部資料處理完後，才執行一次全域閉合分析：

```text
all observed edges
  -> remove duplicate / contradictory edges
  -> detect non-airport dangling ends
  -> find compatible downstream corridor edges
  -> create corridor_bridge_inferred candidates
  -> validate against holdout dates
  -> accept or keep unresolved
```

非機場 dangling end 必須優先尋找同方向、同高度帶、鄰近且跨日重現的下一條走廊；不能因為它靠近 KHH、NRT 或其他機場就直接封口。只有機場 envelope 內的端點才走 Phase 3 的 airport feeder 判定。

#### 中段補接的驗收門檻

- 補接後的走廊必須能在 holdout 日期或獨立航班群中重現；
- 補接不能產生不合理的速度、航向、時間或高度跳變；
- 每一段都能回溯到 raw／derived evidence 或明確標記為 inferred bridge；
- 補接後仍找不到充分證據的區段保持 `unresolved_gap`，不為了讓地圖連續而補直線；
- 任何中段 bridge 都不能把整條 route 的可信度提升到 `observed_adsb_validated`，除非同一條實際 trace 本身通過端點與全段驗證。

#### 全球跨洲走廊統一處理規則

日本 → 北太平洋／阿拉斯加 → 美國只是說明案例，不是特別處理分支。歐洲—北美、亞洲—歐洲、東南亞—澳洲、非洲—歐洲、南美—北美等所有跨洲航線，都必須使用同一套 corridor relay 方法。區域名稱只用於分組、統計與視覺化，不得改變判定門檻。

任何跨洲航線都不能用「起點機場到終點機場」的一條直線補出來。可行的做法是把長航線拆成許多局部、可驗證的走廊接點，再以既有 waypoint 圖尋找一條有方向的 relay path：

```text
起點機場 feeder
  -> 起點洲外圍 corridor
  -> 中間海域／陸域 corridor
  -> 可能的轉向、匯流或中繼 corridor
  -> 終點洲外圍 corridor
  -> 終點機場 feeder
```

執行規則：

1. 先從 raw-derived graph 找出日本側、北太平洋／阿拉斯加側及美國側的 directed corridor terminal；不以 airport-pair endpoint 是否完整作為必要條件。
2. 每個候選接點只允許連到已存在的 waypoint 或 corridor edge；相鄰接點的空間缺口原則上不超過 150 km，並須符合方向、轉向、高度帶及跨日支持。
3. 長距離跨洋路線可以由很多個局部接點串成，但不能把數千公里的日本—美國距離視為一個 bridge。若中間沒有 waypoint relay，結果必須保持 `unresolved_gap`。
4. 對每個 relay path 記錄：waypoint 順序、每段 corridorId、每段距離與方向差、支援日期、獨立 aircraft／callsign 數、原始 trace 來源，以及是否有中段 raw trace 直接支持。
5. 若同一航班 raw trace 保留了日本到美國的連續中段，輸出 `trace_reconstructed`；若只有多航班共用走廊拼接，輸出 `corridor_bridge_inferred`；兩者都不能冒充該機場對的完整 `observed_adsb`。
6. 以日期留出法驗證：例如 7 天資料用 5 天建立 relay path、2 天 holdout；holdout 仍能重現相同 waypoint 序列或走廊帶，才可由 `candidate` 升為 `supported`。
7. 若只能依靠 IFR path、單一日期、單一 aircraft，或某一段沒有任何 raw／corridor waypoint 證據，直接標記 `ifr_contaminated_prior` 或 `unresolved_gap`，不進正式全球走廊。

日本—美國案例與其他所有跨洲案例的判定都不是「圖上有沒有一條跨洲線」，而是：

```text
是否存在一條由多個已觀測局部 corridor 組成、
每個接點都有證據、且可在保留日期重現的 directed waypoint relay path？
```

如果答案是是，就能建立全球共用走廊的跨洋連接；如果答案是否，就只能保留日本側與美國側兩個斷開的觀測網路，不能為了地圖連續而補線。

#### 跨洋橋接的具體輸出與狀態

新增的橋接分析不得覆蓋現有 raw-derived graph，應另寫 immutable artifacts：

- `global-corridor-chains.json.gz`：觀測到的 directed chains；
- `global-corridor-bridges.json.gz`：候選 relay path 與每段證據；
- `global-corridor-evidence-index.json.gz`：waypoint、日期、aircraft、callsign 與來源檔反查索引；
- `global-corridor-bridge-review.json`：接受、拒絕及保持 unresolved 的理由。

只有 `supported` 的 corridor bridge 才能供機場 feeder 查詢；`candidate` 與 `unresolved_gap` 只能供診斷地圖顯示，不能進 route-shape runtime pack。

### Phase 3：將 KHH 接入走廊網路

KHH 必須分去程、回程處理，流程如下：

1. 建立 KHH departure／arrival envelope，考慮跑道方向、爬升／下降、高度與航向，不以第一個 ADS-B 點直接代表機場端點。
2. 尋找 KHH 附近的 corridor edges；先以 50 km 作高信心接入範圍，50–150 km 只能作 `corridor_inferred` 或 `recovered_endpoint`。
3. KHH departure 成立的最低條件：
   - 航跡時間順序符合離場：KHH envelope → corridor edge；
   - 至少兩種獨立證據支持，例如航向／高度爬升、同類航跡重疊、callsign／航班資訊或鄰近機場排除；
   - 沒有 RMQ、TPE、TSA 等鄰近機場更合理的解釋。
4. KHH→日本若中間沒有單條實測航跡，必須先使用 Phase 2.5 的全域中段補接結果；允許由多個共用 corridor edges 串接，但每個接點都要記錄：距離、方向差、支援數、缺口與信心等級。
5. 若只能把 NRT→KHH 反向使用，標記 `reverse_inferred`，不得冒充 KHH→NRT 的獨立 ADS-B 觀測。

### Phase 4：KHH 路線驗收

KHH 路線只有在以下條件下才可進入正式 runtime：

- 至少一個 KHH departure／arrival endpoint 通過 `recovered_endpoint` 或更高等級；
- KHH 至少連到一條 `supported` corridor，且每個橋接缺口不超過 150 km；
- KHH→NRT 與 NRT→KHH 分別有方向證據；
- 至少一個日期之外仍能在 holdout 日期找到相同走廊幾何；
- 所有橋接段與不確定性在 Web、iOS、Replay Engine 顯示警告；
- 舊 IFR path 仍保留為 fallback，不得被誤標為 observed。

若只通過「KHH 鄰近走廊」而未通過完整方向／端點驗證，結果只能進入候選索引，不覆蓋正式 route shape。

### Phase 5：發布與回歸驗證

1. 先發布 diagnostics、corridor graph 與 evidence index，不直接發布路線覆蓋。
2. 通過人工抽查與自動測試後，才產生 shared、Web、iOS 相同版本的 runtime pack。
3. 驗證 route method、corridorId、confidence、warning、方向及首末機場，並做三份 pack hash 比對。
4. Reload Web 與 Replay Engine，確認 KHH 不再被顯示成錯誤的 RMQ/TPE/TSA 端點，也不會把 IFR fallback 顯示成實測航跡。

### 本計劃目前的執行結論

2026/08/02 raw 已證明 KHH 所在區段有高密度共用航跡，但 KHH 與日本段之間仍有連續性缺口。28 天 `ifr_validated_derived` 只能作候選索引，不能拿來填補這個缺口。因此目前可進入 Phase 2–3 的「raw-based 走廊網路與 KHH 接入候選」工作，尚不可直接宣稱完整 `KHH-NRT observed`。下一個實作順序固定為：

```text
provenance audit
  -> raw-based corridor graph
  -> SEA/Taiwan/Japan corridor linkage
  -> KHH departure/arrival feeder
  -> evidence-ranked route candidates
  -> only then consider runtime publish
```
