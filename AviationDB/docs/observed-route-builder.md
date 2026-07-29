# ADS-B 觀測航線 Builder

這個 builder 的目的不是把完整 ADS-B 歷史資料塞進 App，而是用免費、可下載的 ADSB.lol `globe_history` 原始 trace，離線抽出每組機場 OD 的代表航線。原始資料很大，代表路線包會小很多。

## 免費資料源

- ADSB.lol historical dumps: `https://www.adsb.lol/docs/open-data/historical/`
- GitHub releases manifest: `https://github.com/adsblol/globe_history_2025`
- 授權: ODbL 1.0

不要爬 FlightRadar24、FlightAware、RadarBox 等商業網站來重建全球資料庫；通常會違反條款。FlightGear 仍然有用，它是離線 airway/waypoint 骨架、fallback 和品質檢查基準，但它不是實際飛行軌跡。

## 建置方式

先用一天資料試跑。每日 raw release 通常是數 GB，全年可能超過 TB，因此請逐日或逐月處理。

```bash
cd /Users/alien/Desktop/Travel_Globe
python3 AviationDB/scripts/build_observed_routes.py \
  --year 2025 \
  --date 2025-07-21 \
  --download \
  --pretty-summary
```

如果已經手動下載或解開資料：

```bash
python3 AviationDB/scripts/build_observed_routes.py \
  --input /path/to/extracted/traces \
  --pretty-summary
```

如果有 ADSB.lol split tar release：

```bash
python3 AviationDB/scripts/build_observed_routes.py \
  --release-dir /Users/alien/Desktop/Travel_Globe/AviationDB/data/raw/adsblol/2025-07-21 \
  --pretty-summary
```

輸出預設在：

```text
/Users/alien/Desktop/Travel_Globe/AviationDB/data/releases/private/observed-routes/adsblol/observed-routes.global.json.gz
```

`AviationDB/data/raw/**` 和 `AviationDB/data/releases/**` 已被 `AviationDB/.gitignore` 排除，不會提交大型 raw 檔或 ODbL 衍生資料。

## Builder 做了什麼

1. 用 OurAirports 離線機場索引推斷起終點機場。
2. 讀取 readsb trace JSON，遇到新航段 flag、長時間 gap 或不合理跳點就切段。
3. 排除太短、找不到 OD 機場、同場起降、繞路比例過大的低信心航段。
4. 用 Douglas-Peucker 簡化軌跡到最多 96 點。
5. 以量化後的 shape signature 聚類，為每個 OD 保留多個 variant，最高 sample count 的 variant 作為代表航線。

## 建議流程

先從亞洲高問題區域開始，例如台灣、日本、韓國附近的日期；確認 FD234 KHH-NRT 這類航線能產生合理代表路線後，再擴大到全球逐月跑。App 端套用時，優先序應該是：

```text
GPS replay/import > local observed route pack > local live ADS-B cache > FlightGear airway graph > Great Circle
```

這樣飛航模式下也能先用 local observed route pack；有網路時查到 live ADS-B 或 post-flight OpenSky/ADSB.lol 資料，再回填本機快取。
