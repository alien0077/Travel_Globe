# 2026-08-02 KHH-NRT ADS-B 分析報告與最終做法

## 結論摘要

2026-08-02 的 raw 確實包含 `AIQ234`，但沒有包含完整的 KHH 起飛段。這不是航班不存在，也不是 raw 損壞，而是該 aircraft-day trace 在飛行中段才開始被資料源觀測到。

因此：

- 可以確認 `AIQ234` 的航班身份與 NRT 抵達段。
- 不能只靠這份 raw 證明 KHH 到觀測起點之間是走台灣東側或西側。
- 目前的「最近機場」演算法把第一個觀測點錯分成日本附近機場，導致 KHH 端點消失。
- IFR 可以補足「推測連接段」，但不能把推測段標成 ADS-B 實際航跡。

## 原始資料證據

來源：

- `AviationDB/data/raw/adsblol/2026-08-02/v2026.08.02-planes-readsb-prod-0.tar.aa`
- `AviationDB/data/raw/adsblol/2026-08-02/v2026.08.02-planes-readsb-prod-0.tar.ab`
- trace：`./traces/47/trace_full_880c47.json`
- ICAO24：`880c47`
- 註冊號：`HS-CBG`
- 機型：`A20N`

同一個 aircraft-day trace 的點級航班切換如下：

| 航班資訊 | 起始點索引 | elapsed | 起始座標／狀態 |
|---|---:|---:|---|
| `AIQ234` | 3 | 9040.67 秒 | 32.902359, 134.394379，約 FL370 |
| `AIQ235` | 483 | 17801.74 秒 | 35.764938, 140.374889，NRT 附近 |
| `AIQ140` | 1335 | 50398.94 秒 | 13.901615, 100.602578 |
| `AIQ141` | 1623 | 75510.85 秒 | 14.228073, 98.669207 |

`AIQ234` 觀測段的結果：

- 觀測點數：482
- 觀測段距離：約 779.6 km
- 最接近 NRT：約 1.3 km
- 第一個觀測點距 KHH：約 1,792.2 km
- 方向：觀測段由日本南側前往 NRT

所以 raw 中的 `AIQ234` 只有後段，不是完整的 KHH-NRT 軌跡。現有 21 條寬鬆 KHH-NRT corridor 候選也沒有形成嚴格 KHH-NRT 配對，多數其實是 HKG、TPE、HND 或其他機場航段。

### CI102 交叉證據

同一日期的 `CI102` 也存在於 raw：

- trace：`./traces/0a/trace_full_89910a.json`
- ICAO24：`89910a`
- 註冊號：`B-18203`
- 點級 callsign：`CAL102`
- 觀測點數：319
- 第一個觀測點：`33.1633, 135.9493`
- 最後觀測點：`35.7834, 140.3938`
- 最接近 KHH：約 1,929.1 km
- 最接近 NRT：約 1.2 km
- 觀測段方向：前往 NRT

CI102 與 AIQ234 都呈現相同模式：航跡在日本南側才開始，最後抵達 NRT；兩份 raw 都沒有收到 KHH 起飛後的大段航跡。這證明問題是資料覆蓋／trace 起點，不是 FD234 單一航班或單一航空公司的異常。

### CI126 交叉證據（目前最有價值）

`CI126` 在同一天有一條更接近 KHH 的 `CAL126` trace：

- trace：`./traces/19/trace_full_899119.json`
- ICAO24：`899119`
- 註冊號：`B-18807`
- 第一段：73 點，從 `24.41414, 121.05327` 到 `26.19640, 123.38305`
- 第一段最接近 KHH：約 212.7 km
- 第一段航向約 38–50 度，持續往東北離開台灣附近
- 第二段：423 點，從 `31.11003, 130.92940` 到 NRT
- 第二段最接近 NRT：約 1.2 km
- 中間是 raw trace gap，不是航班身份切換

CI126 提供目前最接近 KHH 的實際觀測幾何。它不能證明 KHH 跑道到第一觀測點之間的 212 km，但已顯示航跡在 `24.4N, 121.05E` 後往東北、經度持續增加至 `123.38E`；因此 KHH-NRT 的共同 route template 應優先以這條觀測走廊建立，而不是直接採用原本的 IFR graph path。

## 為什麼先前會看不到 AIQ234

raw 的航班號不是每個點都有，而是寫在部分點的 metadata 中。更重要的是，同一個 aircraft-day trace 會包含多個航班，航班號會在點級資料中切換。

因此以下兩種做法都不可靠：

1. 只看 trace 頂層是否有 `flight`。
2. 只要整個 trace 內出現 `AIQ234`，就把整個 trace 或所有 legs 都標成 AIQ234。

正確做法是依照點級 `flight` metadata、航段旗標、時間 gap 與位置連續性切成 flight segment。

## 最終做法

### A. 航班身份層

建立點級 callsign segment：

- 讀取每個 trace point 的 `flight`／`callsign`。
- 依航班號切換、`flags & 2`、長時間 gap 與不合理跳點切段。
- `AIQ234`、`AIQ235`、`AIQ140`、`AIQ141` 必須是四個獨立航段。
- 航班號缺失的點，沿用同一 segment 最近一次已確認的 callsign，但遇到新 callsign 時立即切換。

### B. 端點恢復層

對 `AIQ234` 這種只有部分航跡的案例，使用航班身份資料確認 airport pair：

- callsign 與日期一致。
- 航班時刻或可信航班資料支持 `KHH-NRT`。
- 觀測段終點確實接近 NRT。
- 不把第一個觀測點附近的日本機場當成真正起點。

這個結果標記為 `recovered_endpoint`，並保存：

- `originEvidence: schedule_or_flight_identity`
- `observedStartPoint`
- `observedEndPoint`
- `missingOriginDistanceKm`
- `geometryCoverage: partial`
- 原始 trace source 與 callsign transition evidence

端點恢復不應只依賴最近機場。對 KHH-NRT 應建立航線群組證據：

- `AIQ234`／FD234 的航班身份與 NRT 抵達段。
- `CAL102`／CI102 的航班身份與 NRT 抵達段。
- 同日期或相鄰日期的相同 airport pair 航班紀錄。
- 至少兩個獨立航班／航空公司的交叉支持後，才把 pair 恢復成 KHH-NRT。
- `CAL126` 應作為幾何 anchor，因為它的第一觀測點已接近 KHH，且保留離開台灣後的東北向航跡。

### C. 航跡幾何層

幾何必須拆成兩種：

1. **Observed segment**：只使用 raw 真正觀測到的 `AIQ234` 點。
2. **Inferred connector**：KHH 到第一個觀測點的連接段，使用 IFR 或其他推測方法，但必須標示為 estimated／inferred。

不得把兩者合成一條沒有警告的 ADS-B 實線。

如果目前 UI 尚未支援兩種線型，寧可顯示「部分觀測 + 缺失段估算」警告，也不能把 IFR 估算冒充完整 ADS-B。

### D. 真正要確認台灣東西側時

2026-08-02 這份 raw 缺失 KHH 到 32.9N、134.4E 之間約 1,792 km，因此無法單靠它判定台灣東側或西側。

若必須確認完整實際路徑，還需要：

- 另一個涵蓋 KHH 起飛時段的完整 ADS-B source；或
- 同一航班的其他完整歷史 trace；或
- 可信的完整 flight playback／歷史航跡來源。

在沒有第二個完整幾何來源前，不能用 IFR 路徑替代這段證據。

但若目標只是恢復 route pair 的身份，AIQ234 與 CI102 已足以支持「這不是 KCZ、SHM 或其他日本機場航線，而是 KHH-NRT 航線的部分觀測」；正式資料應恢復 airport pair，並保留 `geometryCoverage=partial`。

若目標是建立可用的 KHH-NRT 顯示路線，應改採 `CAL126` 的觀測走廊作為 route template，將 KHH 到 `24.41414,121.05327` 的短缺口標示為 inferred connector；不可再用原本經由 `PARPA-HCN-BONEY-MEVIN` 的 IFR 選路直接代表實際路徑。

## 不採用的做法

- 不單純把 KHH 機場距離門檻從 150 km 放寬到 1,800 km。
- 不把最近的日本機場改名成 KHH。
- 不把整個 aircraft-day trace 套用成 AIQ234。
- 不把 IFR 路徑直接升級成 observed ADS-B。
- 不因使用者預期路徑在台灣西側，就手動改經緯度。

## 最終資料分類

```text
完整起訖 ADS-B
  -> observed_adsb_mapped

航班身份與一端觀測可確認，但幾何部分缺失
  -> recovered_endpoint + geometryCoverage=partial

只知道機場 pair，沒有足夠觀測幾何
  -> directed_airway_graph / airport_pair_fallback
```

目前 `AIQ234` 應屬第二類，而不是第一類。
