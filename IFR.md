# Travel Globe v4.0
# Global IFR Routing Engine（100% 免費版）
# Codex Implementation Plan

==============================================================================
Project Goal
==============================================================================

建立一套完全免費、可離線、可長期維護的全球 IFR Routing Engine。

目標：

Airport
↓
Connector
↓
Airway Graph
↓
Connector
↓
Airport

輸出接近真實航空公司 IFR Route，而不是 Great Circle。

重要限制：

✓ 不使用 Navigraph
✓ 不使用 Jeppesen
✓ 不使用 LIDO
✓ 不依賴付費 API
✓ 可完全離線運作
✓ Travel Globe 可商業化（不得直接內建未授權資料）

==============================================================================

Architecture
==============================================================================

                           +----------------------+
                           |   OurAirports        |
                           +----------+-----------+
                                      |
                                      |
                           Airport / Runway
                                      |
                                      |
                                      V

                           +----------------------+
                           | OpenAIP              |
                           +----------+-----------+
                                      |
                                      |
                           Waypoint / Navaid
                                      |
                                      |
                                      V

                           +----------------------+
                           | X-Plane NavData      |
                           +----------+-----------+
                                      |
                                      |
                              Airway Graph
                                      |
                                      |
                                      V

                           +----------------------+
                           | Routing Engine       |
                           | (LittleNavMap Style) |
                           +----------+-----------+
                                      |
                 +--------------------+----------------------+
                 |                                           |
                 |                                           |
         Terrain Connector                         Historical Bias
                 |                                           |
                 |                                           |
          Copernicus DEM                     FlightPlanDatabase
                                             FAA Preferred Route
                                      |
                                      |
                                      V
                           Final IFR Route

==============================================================================

PHASE 1
Airport Database
==============================================================================

資料來源：

OurAirports

下載：

https://github.com/davidmegginson/ourairports-data

下載：

airports.csv
runways.csv
navaids.csv

建立：

SQLite

Tables

airports
runways
navaids

完成：

✓ ICAO lookup

✓ Runway lookup

✓ Airport elevation

==============================================================================

PHASE 2
Waypoint + Airway Graph
==============================================================================

資料來源：

X-Plane NavData

Repository：

https://github.com/mcantsin/x-plane-navdata

下載：

earth_fix.dat

earth_nav.dat

earth_awy.dat

Parser：

建立 parser：

parser_fix.py

parser_nav.py

parser_airway.py

SQLite：

fixes

airway_edges

Graph：

Node：

Waypoint

Edge：

Airway

Edge 必須包含：

distance

bearing

direction

min altitude

max altitude

source

==============================================================================

PHASE 3
OpenAIP Integration
==============================================================================

來源：

https://www.openaip.net/

用途：

補：

Waypoint

Navaid

Coordinates

不要：

使用 OpenAIP 建立 Airway Graph。

優先序：

XPlane

↓

OpenAIP

↓

OurAirports

==============================================================================

PHASE 4
Routing Engine
==============================================================================

不要：

Dijkstra

改：

A*

Heuristic：

Great Circle Distance

Cost：

distance

+

turn penalty

+

airway change penalty

+

backtracking penalty

+

terrain penalty

-

preferred route bonus

Routing：

Airport

↓

Connector

↓

Airway Graph

↓

Connector

↓

Airport

==============================================================================

PHASE 5
Airport Connector
==============================================================================

不要：

建立 Exit Gate Database。

改：

Dynamic Connector

流程：

Airport

↓

搜尋：

15~80 NM

所有：

Connected Airway Fix

↓

Terrain Check

↓

Heading Check

↓

Cost

↓

選最佳 Connector

Arrival：

同理。

==============================================================================

PHASE 6
Terrain Engine
==============================================================================

資料來源：

Copernicus DEM GLO-30

下載：

https://dataspace.copernicus.eu/

建立：

Tile Cache

GeoTIFF

功能：

Airport

↓

Connector

↓

Sampling

↓

Terrain Cost

不要：

檢查正式 Airway。

只檢查：

Connector

Synthetic Edge

==============================================================================

PHASE 7
Historical Route Library
==============================================================================

主來源：

FlightPlanDatabase

https://flightplandatabase.com/

用途：

Airport Pair

↓

Route

↓

Waypoints

↓

Airways

↓

Preference

不是：

直接相信。

而是：

Validation：

Waypoint Exist

↓

Airway Exist

↓

Similarity

↓

Confidence

建立：

preferred_routes

==============================================================================

PHASE 8
FAA Preferred Routes
==============================================================================

資料來源：

https://www.fly.faa.gov/rmt/nfdc_preferred_routes_database

只適用：

USA

用途：

直接建立：

Official Route Library

Priority：

最高

==============================================================================

PHASE 9
Route Validation
==============================================================================

每條 Route：

必須驗證：

Loop

Backtracking

Detour Ratio

Turn Angle

Disconnected Edge

Invalid Waypoint

若：

Detour Ratio > 1.5

重新 Routing。

==============================================================================

PHASE 10
Route Quality
==============================================================================

Quality：

A

官方 Route

B

Historical Route

C

Generated Airway Route

D

Estimated Route

Route JSON：

{
    "quality":"B",
    "confidence":0.91,
    "official":false,
    "historical":true,
    "generated":false
}

==============================================================================

Little NavMap Research
==============================================================================

Repository：

https://github.com/albar965/littlenavmap

不要：

直接搬程式。

研究：

Route Calculation

Airway Graph

Airway Preference

One Way Airway

Altitude Restriction

Turn Penalty

Search Corridor

Graph Optimization

全部：

重新實作。

==============================================================================

FlightGear Research
==============================================================================

Repository：

https://github.com/FlightGear/flightgear

研究：

Route Manager

Flight Plan Format

Airway Data

NavData

不要：

直接採用其 Routing。

==============================================================================

Project Folder
==============================================================================

routing/

    parser/

        parser_fix.py

        parser_nav.py

        parser_airway.py

    graph/

        graph_builder.py

        graph_index.py

        astar.py

        connector.py

        terrain.py

        validator.py

    datasource/

        ourairports.py

        openaip.py

        xplane.py

        flightplandatabase.py

        faa_preferred.py

    database/

        routing.db

==============================================================================

Priority
==============================================================================

Priority 1

OurAirports

Priority 2

XPlane Airway

Priority 3

LittleNavMap Routing Algorithm

Priority 4

Terrain Connector

Priority 5

FlightPlanDatabase

Priority 6

FAA Preferred Route

Priority 7

Route Validation

==============================================================================

Important Rules
==============================================================================

禁止：

使用 Great Circle 作為最終 Route。

Great Circle：

只能：

Heuristic

Search Corridor

不得：

直接連 Waypoint。

==============================================================================

Expected Result
==============================================================================

輸入：

RCKH

RJAA

輸出：

Airport

↓

Connector

↓

Airway

↓

Airway

↓

Airway

↓

Connector

↓

Airport

Route：

Quality

Confidence

Distance

Estimated Time

Airway List

Waypoint List

全部輸出 JSON。

==============================================================================

Future Expansion
==============================================================================

完成 v4.0 後：

新增：

SID

STAR

RNAV Procedure

ETOPS

Oceanic Tracks

Wind Optimization

Dynamic Cost

Airspace Avoidance

NOTAM

最後目標：

Travel Globe 能在完全免費資料下，產生接近真實航空公司 IFR 航線，並保持可離線、可維護、可商業化的架構。




建議補充（建議加入 Codex 工作規範）
另外建議在計畫書最前面增加以下要求，讓 Codex 不會一次做完整個專案，而是循序漸進：
Implementation Rules

1. 每個 Phase 完成後先 commit，不要跨 Phase 修改。
2. 每個 Phase 都必須有單元測試（pytest）。
3. 每個 Phase 都要提供 README 說明。
4. 每個 Phase 完成後輸出測試結果與完成報告，再等待下一步。
5. 所有下載資料都放在 data/raw，處理後資料放在 data/processed。
6. 不得直接修改原始下載資料。
7. 所有外部資料來源需保留 version、下載日期與授權資訊。
8. 若發現授權限制或資料不可商業使用，立即停止該資料源的整合並提出替代方案。
我也建議再拆成 10 份獨立的 Codex 任務（每份約 300～600 行工作內容），比一次丟整份計畫成功率高得多，也更容易驗收與除錯。


若需openaip api key , 可由環境參數，請使用：  $OPENAIP_API_KEY
