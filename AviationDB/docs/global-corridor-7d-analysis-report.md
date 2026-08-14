# 全球共用空中走廊 7 日分析報告

日期範圍：2026-07-27 至 2026-08-02。這是 `7-day provisional` raw-based 結果，不是 28 天穩定結果，也不是 IFR 路線驗證結果。

## 執行範圍

- 7 個日期的 ADS-B raw 均已完成解析，原始 raw 與 checkpoint 保留。
- long-leg extractor 共讀取 18,787 條長航段；其中 18,698 條有雙機場辨識、89 條只有部分端點。
- 解析錯誤為 0；IFR 未參與 raw geometry、corridor edge 或 bridge 判定。
- 原始每日 corridor merge 未被覆蓋，另建立 supplemental graph。

## Supplemental graph

long-leg sampled geometry 只在局部取樣點間距不超過 180 km 時建立 edge；已有 base edge 不重複加權，單日 edge 不納入 supported graph。

| 項目 | 結果 |
|---|---:|
| long-leg 長航段 | 18,787 |
| candidate local edges | 185,082 |
| 新增 supplemental edges | 3,936 |
| 與既有 graph 重疊、未重複加權 | 174,257 |
| 單日支持而保留為未納入 | 6,889 |
| 超過 180 km 的 sampled gap，未補直線 | 14,622 |
| long-leg airport pair evidence | 4,526 |
| KHH 直接 airport pair evidence | 0 |

## 全球 graph 前後比較

| 指標 | Base graph | Supplemental graph |
|---|---:|---:|
| supported directed edges | 420,325 | 424,261 |
| vertices | 89,524 | 89,636 |
| weak components | 436 | 435 |
| display chains | 19,248 | 19,456 |
| gap candidates | 10,483 | 10,977 |
| supported local bridges | 7 | 8 |
| holdout-ready bridges | 1 | 2 |

新增 edge 確實讓一個弱連通元件合併，並新增一條 43.22 km、跨 3 日且通過留出日驗證的 local bridge；這是局部走廊改善，不代表已經把全球跨洲航線全部接通。

## 跨洲結果

在一致的 150 km、15°、至少 2 日期、兩架 aircraft、至少 3 terminal legs 門檻下：

- 目前只有 Europe → Africa 的跨區 local bridge 通過 supported 判定。
- 日本 → 北太平洋／阿拉斯加 → 北美沒有足夠的連續 waypoint relay 證據，因此保持斷開。
- 沒有用機場端點直線、IFR path 或數千公里單一 bridge 填補中段。
- `candidate_gap` 與 `unresolved_gap` 不進 runtime route pack。

## KHH 驗證結論

本批 7 日 long-leg evidence 沒有任何 `KHH` 直接 airport pair；supplemental chain 的 endpoint evidence 也沒有 KHH。這表示：

1. KHH 仍不能被標記成 `observed_endpoint`。
2. `KHH-NRT` 與 `NRT-KHH` 不能因為全球 graph 變大就自動升格為完整 observed route。
3. 既有 KHH 附近 corridor 只能作 `corridor_inferred` 候選；鄰近 RMQ/TPE/TSA 的辨識問題仍需獨立 endpoint envelope 證據處理。
4. IFR path 仍只能是 fallback／audit prior，不可用來填 KHH 與日本段的中段缺口。

## 產出檔案

- `/private/tmp/travel-globe-corridor-7d/corridor-merge-long-legs.sqlite`
- `/private/tmp/travel-globe-corridor-7d/long-leg-supplement.json`
- `/private/tmp/travel-globe-corridor-7d/global-long-legs/global-corridor-chains.json.gz`
- `/private/tmp/travel-globe-corridor-7d/global-long-legs/global-corridor-bridges.json.gz`
- `/private/tmp/travel-globe-corridor-7d/global-long-legs/global-corridor-evidence-index.json.gz`
- `/private/tmp/travel-globe-corridor-7d/global-long-legs/global-corridor-bridge-review.json`

evidence index 包含 19,456 chains、350,613 chain edge references 與 26 bridge candidates；edge provenance 可區分 `raw_derived_unbiased` 與 `raw_long_leg_geometry`。

## QA 結論

新增 supplemental graph、evidence index 後，相關 Python compile、ruff、diff check 與 11 項測試均通過。結果可作為 7 日全球共用走廊 provisional graph；尚不可宣稱全球所有跨洲 airport pair 已完整恢復，也不可將 KHH-NRT 視為已通過獨立雙向 endpoint 驗證。
