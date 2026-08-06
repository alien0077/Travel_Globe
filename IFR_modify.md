# Travel Globe IFR Routing 修正計畫

## 目標

修正目前 KHH→NRT、CX451 等航線出現錯側繞行、假航點串線及不合理 shortest path 的問題。

本階段不得直接重建全球離線航線。

先以以下三組航線完成演算法驗證：

- RCKH → RJAA
- RCTP → VHHH
- RCTP → RJAA

---

## 一、目前錯誤根因

目前路由器存在兩種錯誤流程。

### 錯誤流程 A

```text
Airport
→ 選最近 waypoint
→ shortest path
→ Destination 最近 waypoint
```

問題：

- 最近 waypoint 不一定是合理離場點。
- 最近 waypoint 可能位於錯誤方向。
- 最近 waypoint 可能只連接低品質或反方向航路。
- 單一 connector 會過早排除其他合理離場方向。

### 錯誤流程 B

```text
Great Circle corridor
→ 挑選附近 waypoint
→ 依位置直接串接
```

問題：

- 未確認 waypoint 之間是否存在 airway segment。
- 會產生資料庫中不存在的 synthetic edge。
- 可能把不同 airway、不同高度或不同方向的 waypoint 強行連接。
- Great Circle 被錯誤當成實際航線產生器。

必須完全移除此 fallback。

Great Circle 只允許用於：

- A* heuristic。
- 搜尋範圍裁切。
- 航線偏離程度的 soft penalty。
- route detour ratio 驗證。

不得用來直接建立 waypoint-to-waypoint edge。

---

## 二、Graph 資料模型修正

每條 airway segment 必須保留原始屬性：

```ts
interface AirwayEdge {
  fromNodeId: number;
  toNodeId: number;

  airwayIdent: string | null;

  direction:
    | "forward"
    | "backward"
    | "both"
    | "unknown";

  minAltitudeFt: number | null;
  maxAltitudeFt: number | null;

  distanceNm: number;

  source: string;
  sourceVersion: string | null;

  validFrom: string | null;
  validTo: string | null;

  confidence: number;
}
```

### 強制要求

1. 不得再將所有 segment 當成無向邊。
2. 雙向 segment 必須明確建立兩條 directed edge。
3. 單向 segment 只建立允許方向。
4. direction unknown 不得直接當成雙向高可信度 edge。
5. airwayIdent、上下限高度及資料來源不得在 pack 過程中遺失。
6. route 輸出中的每一對相鄰 waypoint，都必須能查到實際 edge。

---

## 三、多 Connector 模型

不得只選擇單一起飛 connector 或抵達 connector。

### Departure Connector

對出發機場搜尋：

```text
最小半徑：10 NM
初始最大半徑：80 NM
必要時擴展至：150 NM
```

只選擇：

- 存在於 airway graph 的節點。
- 至少有一條可用 outgoing edge。
- 不屬於孤立節點。
- 不會造成明顯回頭。
- 機場到 fix 的 synthetic connector 可通過基本合理性檢查。

保留：

```text
至少 8 個
最多 30 個
```

候選 connector。

### Arrival Connector

同樣搜尋目的地附近節點，但必須：

- 至少有一條可用 incoming edge。
- 從該節點連接目的地時航向合理。
- 不可只依距離排序。

### Connector 初始成本

```text
connectorCost =
    distanceCost
  + initialHeadingPenalty
  + destinationDirectionPenalty
  + terrainPenalty
  + lowGraphDegreePenalty
  + historicalMismatchPenalty
```

目前尚未完成 DEM 時，terrainPenalty 可先設為 0，但介面必須保留。

---

## 四、使用 Multi-source / Multi-target A*

建立虛擬節點：

```text
Virtual Origin
→ 多個 departure connector
→ Airway Graph
→ 多個 arrival connector
→ Virtual Destination
```

不得逐一固定 connector 後只搜尋一條路線。

A* heuristic：

```text
目前節點至目的地的 Great Circle distance
```

heuristic 必須保持 admissible，不能加入過大的 penalty。

其他 penalty 應放在 edge cost，而不是 heuristic。

---

## 五、候選路徑搜尋

不得只接受第一條 A* 結果。

實作以下任一方法：

- Yen's K-shortest paths。
- Eppstein K-shortest paths。
- 重複 A* 加 edge/path penalty。

第一階段建議使用 Yen's algorithm。

參數：

```text
K = 10
```

對短程測試最多可提高到：

```text
K = 20
```

候選之間需去除近似重複路徑。

若兩條路徑共享超過 90% edge，視為同一路徑族群。

---

## 六、路徑成本

基礎成本：

```text
edge distance
```

加入：

```text
+ turn penalty
+ backtracking penalty
+ airway change penalty
+ Great Circle deviation penalty
+ invalid direction rejection
+ low-confidence edge penalty
+ connector cost
- SID/STAR preference bonus
- historical route bonus
- ADS-B route similarity bonus
```

### 建議初始值

```text
distance：1 cost / NM

airway change：
+8 至 +20

turn 45°以下：
0

turn 45°～90°：
逐步增加至 +20

turn 90°～135°：
+20 至 +100

turn 超過 135°：
原則上拒絕

明顯朝反方向前進：
+50 至 +500

低可信度 edge：
+25 至 +100
```

所有數值應集中於設定檔，不得散落在程式內。

---

## 七、Great Circle 偏離

Great Circle 不能作 hard corridor，否則會排除真實但繞行的 airway。

建議採兩層：

### 搜尋安全範圍

```text
短程：Great Circle 兩側 300 NM
中程：500 NM
長程：800 NM
```

如找不到路線，再逐步擴大。

### Soft deviation cost

對距離 Great Circle 過遠的 node 或 edge 增加成本，但不可直接刪除。

例：

```text
距 Great Circle 0～50 NM：
無 penalty

50～150 NM：
低 penalty

150 NM 以上：
逐步增加 penalty
```

---

## 八、每段連通強制驗證

新增唯一且不可跳過的驗證器：

```ts
validateRouteEdges(route)
```

對每一對相鄰節點：

```text
route[i] → route[i + 1]
```

必須驗證：

1. graph 中存在 directed edge。
2. edge 方向允許。
3. edge airway identification 有保存。
4. edge 未被標記無效。
5. 若有高度資料，預定巡航高度符合限制。

任何一段失敗：

```text
整條 route 判定 invalid
```

禁止以 Great Circle 或 proximity fallback 自動補接。

只有以下兩段可以是明確標示的 synthetic connector：

```text
Airport → first airway node
last airway node → Airport
```

---

## 九、候選路徑重新排序

A* 的 graph cost 只負責產生合理候選。

最終路徑須使用獨立 ranker：

```text
finalScore =
    graphCost
  + detourPenalty
  + excessiveTurnPenalty
  + airwayFragmentationPenalty
  + connectorPenalty
  + wrongSidePenalty
  - procedureBonus
  - historicalRouteBonus
  - adsbSimilarityBonus
```

### Wrong-side 判斷

不能硬寫「KHH 必須走台灣西側」。

應利用：

- SID/STAR。
- connector 航向。
- 地形。
- 歷史航路。
- ADS-B 軌跡。
- 進入主 airway graph 後的整體路線方向。

對 RCKH → RJAA，如果東側候選：

- 穿越高地。
- 初期大幅偏離常見歷史航跡。
- 需要較大轉彎重新朝北。
- 沒有 SID/歷史航路支持。

則應自然得到較高成本。

---

## 十、SID／STAR 與歷史資料定位

SID／STAR、FlightPlanDatabase、ADS-B 都不得直接取代 airway graph。

它們的用途是：

```text
產生 connector 候選
增加候選路徑偏好
驗證路徑是否接近歷史真實航線
```

優先順序：

```text
有效 SID/STAR
→ 官方或已驗證 preferred route
→ 歷史 airport-pair route
→ ADS-B route cluster
→ 純 airway graph 計算
```

任何歷史路徑都必須重新 map 到現有 graph。

不可直接相信歷史 waypoint 字串。

---

## 十一、資料授權

公開發佈版本不得直接包含未確認可再散布的 X-Plane navdata。

優先資料源：

```text
FlightGear 可再散布資料
→ 官方公開航空資料
→ 授權明確允許再散布的來源
```

X-Plane 資料僅可作：

- 開發比較。
- 本機驗證。
- 不隨 app 發佈的測試資料。

所有資料 pack 必須包含：

```json
{
  "source": "...",
  "version": "...",
  "downloadedAt": "...",
  "license": "...",
  "redistributionAllowed": true
}
```

若 `redistributionAllowed` 不是明確 true，不得加入公開 release。

---

## 十二、三條驗證航線

### Test 1：RCKH → RJAA

目標：

- 不再選擇 WAGON → SEDKU → MYC11 這類東側錯誤路線。
- 每一段皆存在於 graph。
- 無假 edge。
- departure connector 保留多個候選。
- 輸出前 10 條候選及評分細節。

### Test 2：RCTP → VHHH

目標：

- 驗證西南向航線。
- 防止演算法過度貼 Great Circle。
- 驗證 airway direction。
- 驗證不同 airway sequence 的 ranking。

### Test 3：RCTP → RJAA

目標：

- 驗證東北向航線。
- 比較與 RCKH → RJAA 的不同 connector。
- 確認不能因目的地相同而共用錯誤 departure path。

---

## 十三、每條測試必須輸出

```json
{
  "origin": "RCKH",
  "destination": "RJAA",
  "candidateCount": 10,
  "selectedCandidate": 0,
  "greatCircleDistanceNm": 0,
  "routeDistanceNm": 0,
  "detourRatio": 0,
  "departureConnector": {},
  "arrivalConnector": {},
  "waypoints": [],
  "airways": [],
  "edgeValidation": {
    "valid": true,
    "invalidSegments": []
  },
  "scoreBreakdown": {
    "distance": 0,
    "turn": 0,
    "backtracking": 0,
    "airwayChanges": 0,
    "greatCircleDeviation": 0,
    "connector": 0,
    "historicalBonus": 0,
    "adsbBonus": 0
  }
}
```

另外輸出 GeoJSON：

```text
candidate-01.geojson
candidate-02.geojson
...
candidate-10.geojson
selected.geojson
great-circle.geojson
```

供地圖疊圖比較。

---

## 十四、禁止事項

1. 禁止依 waypoint 距離直接串線。
2. 禁止將 Great Circle corridor 中的 waypoint 依序連線。
3. 禁止把未知方向 segment 一律當成雙向。
4. 禁止只選一個 departure connector。
5. 禁止只選一個 arrival connector。
6. 禁止未驗證 route edge 就輸出。
7. 禁止 graph 找不到路時靜默建立 waypoint-to-waypoint DCT。
8. 禁止目前階段批次重建全球 route-shapes。
9. 禁止使用 KHH→NRT 單一案例硬寫台灣西側規則。
10. 禁止把 ADS-B 軌跡直接當 airway graph。

---

## 十五、實作順序

### Step 1

修正 FlightGear graph pack，保留：

- directed edge。
- airway ident。
- altitude limit。
- source metadata。
- validity metadata。

### Step 2

移除 Great Circle waypoint chaining fallback。

### Step 3

實作 multi-connector virtual origin/destination。

### Step 4

實作 directed A*。

### Step 5

實作 K-shortest candidate generation。

### Step 6

實作 route edge validator。

### Step 7

實作 score breakdown 與 GeoJSON debug output。

### Step 8

只執行三條測試航線。

### Step 9

人工比對路徑方向與現有 ADS-B／已知航線。

### Step 10

通過驗收後，才評估全球批次 route-shapes 生成。

---

## 十六、驗收標準

三條測試航線均須滿足：

```text
每個 en-route segment 都存在於 directed airway graph
沒有 Great Circle proximity 假 edge
沒有 waypoint loop
沒有超過 135°的不合理掉頭
detour ratio 在合理範圍
至少產生 5 條不同候選
輸出完整 score breakdown
可清楚解釋為何選中最終候選
```

RCKH → RJAA 額外要求：

```text
不得再選中目前已知的 WAGON → SEDKU → MYC11 錯誤路線
除非該路徑能通過 directed edge、地形、歷史航路及總成本驗證
```

最終不得只回報「航線看起來正常」。

必須提供：

- 所選 connector。
- 每個 airway segment。
- 每段方向。
- 每項成本。
- 被淘汰候選及淘汰原因。
- GeoJSON 疊圖結果。



這份修正版比原 IFR.md 多了三個關鍵閘門：
Multi-connector，避免最近航點綁死整條路線。
K 候選再排序，避免第一條 shortest path 被誤認為真實航路。
逐段 edge validation，徹底禁止假航點串線。
在這三條測試通過前，不應批次產生全球 route-shapes。
