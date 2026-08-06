# Travel Globe AviationDB v2.0 — 全球航路資料庫實作計畫

## 1. 專案目標

建立一套獨立、可維護、可逐國擴充的航空導航資料管線，從各國官方航空資料來源取得並解析：

* Airport
* Waypoint / Significant Point / IFR FIX
* Navaid
* Airway
* Airway Segment
* SID
* STAR

最終產出供 Travel Globe 離線使用的：

```text
world_airway.sqlite
world_airway.compact.json
coverage_report.json
validation_report.json
```
主要用途：

1. 根據起點與終點產生接近正式航路的路徑。
2. 支援 Flight Replay。
3. 支援 Flight Plan 模式。
4. 支援 waypoint 與 airway 顯示。
5. 不依賴 FlightAware、ADS-B Exchange 或付費導航資料。
6. 原始資料優先使用官方來源。
7. 所有來源都必須保留授權與來源 metadata。
8. 在授權未確認前，不公開重新散布完整解析資料。

---

# 2. 重要原則

## 2.1 不建立單一巨型爬蟲

每個國家或資料供應者使用獨立 adapter：

```text
src/aviationdb/adapters/
├── faa.py
├── taiwan.py
├── japan.py
├── hong_kong.py
├── singapore.py
├── thailand.py
├── vietnam.py
└── base.py
```

Adapter 只負責：

```text
發現目前有效版本
下載原始資料
記錄來源資訊
保存原始檔
```

Adapter 不負責解析航空資料內容。

---

## 2.2 Parser 依格式區分，不依國家區分

```text
src/aviationdb/parsers/
├── arinc424.py
├── eaip_xhtml.py
├── eaip_html.py
├── eaip_pdf_text.py
├── coordinate.py
└── base.py
```

例如：

```text
FAA CIFP
→ ARINC 424 Parser

Taiwan eAIP
→ eAIP XHTML Parser

其他純 HTML eAIP
→ HTML Parser
```

禁止把國家特定邏輯大量混入通用 parser。

若某國格式特殊，應使用：

```text
Generic Parser
+
Country Mapping/Profile
```

---

## 2.3 原始資料、解析資料、App 資料分離

目錄結構：

```text
data/
├── raw/
│   ├── faa/
│   ├── taiwan/
│   ├── japan/
│   └── ...
├── staging/
├── processed/
├── releases/
└── reports/
```

定義：

```text
raw/
官方原始檔，不修改。

staging/
解析中的中間資料。

processed/
標準化後的完整資料。

releases/
供 Travel Globe 使用的精簡資料。

reports/
coverage、validation、diff 與錯誤報告。
```

---

# 3. 第一階段範圍

先完成：

```text
Phase 1A
1. Taiwan eAIP
2. FAA CIFP

Phase 1B
3. Hong Kong eAIP
4. Singapore eAIP
5. Thailand eAIP
6. Vietnam eAIP

Phase 1C
7. Japan
8. South Korea
9. Malaysia
10. Philippines
```

不要一開始嘗試全球所有國家。

第一個驗證目標：

```text
Taiwan eAIP
→ ENR 3
→ ENR 4.4
→ SQLite
```

第二個驗證目標：

```text
FAA CIFP
→ ARINC 424
→ Waypoint + Airway + Segment
→ SQLite
```

---

# 4. 技術選型

使用：

```text
Python 3.12+
SQLite
SQLAlchemy 2.x 或 sqlite3
Pydantic 2.x
httpx
BeautifulSoup4
lxml
pytest
ruff
mypy
Typer
```

必要時才使用：

```text
pypdf
pdfplumber
```

不要使用 OCR，除非官方 PDF 沒有文字層且沒有其他資料來源。

---

# 5. 專案目錄

建立：

```text
AviationDB/
├── pyproject.toml
├── README.md
├── LICENSE
├── .env.example
├── .gitignore
├── config/
│   ├── sources.yaml
│   ├── countries.yaml
│   └── validation.yaml
├── src/
│   └── aviationdb/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── logging.py
│       ├── adapters/
│       ├── parsers/
│       ├── models/
│       ├── storage/
│       ├── normalization/
│       ├── validation/
│       ├── routing/
│       ├── exporters/
│       └── reporting/
├── tests/
│   ├── fixtures/
│   ├── unit/
│   └── integration/
├── scripts/
├── data/
└── .github/
    └── workflows/
```

---

# 6. 統一資料模型

## 6.1 SourceRecord

所有資料都必須記錄來源：

```python
class SourceMetadata:
    source_id: str
    provider: str
    country: str | None
    source_url: str
    source_type: str
    airac_cycle: str | None
    effective_date: date | None
    retrieved_at: datetime
    raw_file_sha256: str
    license_url: str | None
    redistribution_status: str
```

`redistribution_status` 限定：

```text
unknown
private_use_only
redistribution_allowed
redistribution_restricted
manual_review_required
```

預設必須是：

```text
unknown
```

禁止自動假設可重新發布。

---

## 6.2 Waypoint

```python
class Waypoint:
    uid: str
    ident: str
    name: str | None
    latitude: float
    longitude: float
    point_type: str
    usage_type: str | None
    country: str | None
    fir: str | None
    region_code: str | None
    source_id: str
    airac_cycle: str | None
    effective_date: date | None
    is_active: bool
```

`uid` 不得只使用 `ident`。

建議：

```text
SHA256(
    normalized_ident
    + rounded_latitude
    + rounded_longitude
    + fir
)
```

因為相同 ident 可能存在於不同區域。

--[118;1:3u-

## 6.3 Navaid

```python
class Navaid:
    uid: str
    ident: str
    name: str | None
    navaid_type: str
    latitude: float
    longitude: float
    frequency: float | None
    channel: str | None
    country: str | None
    fir: str | None
    source_id: str
    airac_cycle: str | None
    is_active: bool
```

---

## 6.4 Airway

```python
class Airway:
    uid: str
    designator: str
    route_type: str | None
    direction: str | None
    lower_limit_ft: int | None
    upper_limit_ft: int | None
    country: str | None
    fir: str | None
    source_id: str
    airac_cycle: str | None
    is_active: bool
```

---

## 6.5 AirwaySegment

```python
class AirwaySegment:
    uid: str
    airway_uid: str
    sequence: int
    from_waypoint_uid: str
    to_waypoint_uid: str
    distance_nm: float | None
    initial_course_deg: float | None
    reverse_course_deg: float | None
    direction: str | None
    minimum_altitude_ft: int | None
    maximum_altitude_ft: int | None
    source_id: str
    airac_cycle: str | None
```

---

## 6.6 Airport

```python
class Airport:
    uid: str
    icao: str | None
    iata: str | None
    name: str
    latitude: float
    longitude: float
    elevation_ft: int | None
    country: str | None
    fir: str | None
    source_id: str
```

Airport 可暫時使用既有 OurAirports 資料，但必須保留來源欄位。

---

# 7. SQLite Schema

建立 migrations 或 schema builder。

最低限度包含：

```sql
CREATE TABLE source_metadata (
    source_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    country TEXT,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    airac_cycle TEXT,
    effective_date TEXT,
    retrieved_at TEXT NOT NULL,
    raw_file_sha256 TEXT NOT NULL,
    license_url TEXT,
    redistribution_status TEXT NOT NULL
);

CREATE TABLE waypoint (
    uid TEXT PRIMARY KEY,
    ident TEXT NOT NULL,
    name TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    point_type TEXT NOT NULL,
    usage_type TEXT,
    country TEXT,
    fir TEXT,
    region_code TEXT,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    effective_date TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE navaid (
    uid TEXT PRIMARY KEY,
    ident TEXT NOT NULL,
    name TEXT,
    navaid_type TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    frequency REAL,
    channel TEXT,
    country TEXT,
    fir TEXT,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE airway (
    uid TEXT PRIMARY KEY,
    designator TEXT NOT NULL,
    route_type TEXT,
    direction TEXT,
    lower_limit_ft INTEGER,
    upper_limit_ft INTEGER,
    country TEXT,
    fir TEXT,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE airway_segment (
    uid TEXT PRIMARY KEY,
    airway_uid TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    from_waypoint_uid TEXT NOT NULL,
    to_waypoint_uid TEXT NOT NULL,
    distance_nm REAL,
    initial_course_deg REAL,
    reverse_course_deg REAL,
    direction TEXT,
    minimum_altitude_ft INTEGER,
    maximum_altitude_ft INTEGER,
    source_id TEXT NOT NULL,
    airac_cycle TEXT,
    FOREIGN KEY (airway_uid) REFERENCES airway(uid),
    FOREIGN KEY (from_waypoint_uid) REFERENCES waypoint(uid),
    FOREIGN KEY (to_waypoint_uid) REFERENCES waypoint(uid)
);
```

Indexes：

```sql
CREATE INDEX idx_waypoint_ident ON waypoint(ident);
CREATE INDEX idx_waypoint_country ON waypoint(country);
CREATE INDEX idx_waypoint_fir ON waypoint(fir);
CREATE INDEX idx_waypoint_location ON waypoint(latitude, longitude);

CREATE INDEX idx_airway_designator ON airway(designator);
CREATE INDEX idx_segment_airway_sequence
ON airway_segment(airway_uid, sequence);

CREATE INDEX idx_segment_from
ON airway_segment(from_waypoint_uid);

CREATE INDEX idx_segment_to
ON airway_segment(to_waypoint_uid);
```

---

# 8. CLI 設計

建立以下指令：

```bash
aviationdb source list
aviationdb source inspect taiwan
aviationdb download taiwan
aviationdb parse taiwan
aviationdb import taiwan
aviationdb validate taiwan
aviationdb report taiwan
aviationdb build taiwan
```

完整建置：

```bash
aviationdb build-all
```

輸出 release：

```bash
aviationdb export sqlite
aviationdb export compact-json
aviationdb export geojson
```

查詢測試：

```bash
aviationdb query waypoint ELATO
aviationdb query waypoint MAKOT
aviationdb query airway A1
aviationdb query route RCTP RJAA
```

---

# 9. Taiwan eAIP 第一階段實作

## 9.1 下載目標

Adapter 應：

1. 取得台灣官方 eAIP 入口。
2. 找到目前有效版本。
3. 記錄 effective date。
4. 找到：

   * ENR 3.1
   * ENR 3.2
   * ENR 3.3，如存在
   * ENR 4.1
   * ENR 4.2
   * ENR 4.4
5. 下載 XHTML／HTML。
6. 保存原始檔。
7. 計算 SHA-256。
8. 產生 `manifest.json`。

Manifest 格式：

```json
{
  "provider": "Taiwan CAA AIS",
  "country": "TW",
  "effective_date": "YYYY-MM-DD",
  "airac_cycle": null,
  "downloaded_at": "ISO-8601",
  "files": [
    {
      "section": "ENR-3.1",
      "url": "...",
      "path": "...",
      "sha256": "..."
    }
  ]
}
```

---

## 9.2 ENR 4.4 Parser

解析 Significant Points：

必要欄位：

```text
ident
name
latitude
longitude
usage/type
remarks
```

座標解析必須支援：

```text
250012N 1213025E
25°00'12"N 121°30'25"E
250012.34N 1213025.67E
```

轉成 decimal degrees。

所有座標 parser 都必須有單元測試。

---

## 9.3 ENR 3 Parser

解析 ATS routes / RNAV routes：

必要欄位：

```text
airway designator
waypoint sequence
waypoint ident
coordinates
track/course
distance
vertical limits
direction restrictions
remarks
```

對每一條 route：

```text
Waypoint A
Waypoint B
Waypoint C
```

建立：

```text
A → B
B → C
```

禁止只存 waypoint list 而不建立 segment。

---

## 9.4 Taiwan 驗收條件

必須產出：

```text
data/processed/taiwan.sqlite
data/reports/taiwan_coverage.json
data/reports/taiwan_validation.json
```

測試至少包含：

```text
能解析至少一條 airway
每條 airway 至少有一個 segment
segment 的 from/to waypoint 都存在
所有座標在合法範圍
沒有相鄰重複 waypoint
沒有空 ident
```

另外搜尋：

```text
ELATO
MAKOT
KAPLI
TONGA
```

不得硬編碼結果。

若找不到，要在報告中列出：

```json
{
  "ident": "ELATO",
  "found": false
}
```

---

# 10. FAA CIFP 第二階段實作

## 10.1 Adapter

FAA adapter 應：

1. 發現目前有效 CIFP cycle。
2. 下載官方 CIFP。
3. 保存原始壓縮檔。
4. 解壓到 cycle 目錄。
5. 記錄 AIRAC cycle。
6. 計算 SHA-256。
7. 保存來源與授權 metadata。

---

## 10.2 ARINC 424 Parser

先實作最小必要 record types：

```text
Enroute Waypoint
Navaid
Airway Route
Airport
SID
STAR
```

第一版可先完成：

```text
Waypoint
Navaid
Airway
Airway Segment
```

SID／STAR 延後。

Parser 必須：

```text
保留原始 record
記錄 record type
記錄 parse warning
遇到未知 record 不得 crash
```

未知 record 寫入：

```text
data/reports/faa_unknown_records.json
```

---

## 10.3 FAA 驗收條件

```text
成功建立 waypoint
成功建立 airway
成功建立 airway segment
所有 segment 引用有效 waypoint 或 navaid
airway sequence 可重建
```

抽樣至少 20 條 airway 驗證。

---

# 11. Normalization

不同國家資料統一處理：

## 11.1 Ident normalization

```text
trim
uppercase
移除不可見字元
保留合法連字號
```

禁止任意刪除數字。

---

## 11.2 Coordinate normalization

要求：

```text
latitude: -90 到 90
longitude: -180 到 180
```

保留至少六位小數。

---

## 11.3 Distance validation

若來源有距離：

```text
source_distance_nm
calculated_distance_nm
difference_percent
```

使用 haversine 或 geodesic 計算。

若差異過大，記 warning，不直接覆寫來源值。

---

## 11.4 Duplicate resolution

不要只依 ident 去重。

候選重複條件：

```text
相同 ident
距離小於指定門檻
相同 FIR 或相鄰 FIR
相同 point type
```

合併前保留：

```text
source aliases
source records
confidence
```

若無法確定，不合併。

---

# 12. Validation Engine

建立：

```text
src/aviationdb/validation/
├── waypoint_validator.py
├── airway_validator.py
├── segment_validator.py
├── topology_validator.py
└── coverage_validator.py
```

檢查：

## Waypoint

```text
ident 非空
座標合法
來源存在
UID 唯一
```

## Airway

```text
designator 非空
至少一個 segment
sequence 不重複
segment 連續
```

## Segment

```text
from != to
from waypoint 存在
to waypoint 存在
距離不是 0
距離不異常
```

## Topology

```text
孤立 waypoint
斷裂 airway
重複 segment
反向重複 segment
非預期 cycle
異常迴圈
```

驗證結果分級：

```text
error
warning
info
```

只要存在 error，正式 release build 必須失敗。

---

# 13. Coverage Report

產生：

```json
{
  "generated_at": "...",
  "countries": {
    "TW": {
      "waypoints": 0,
      "navaids": 0,
      "airways": 0,
      "segments": 0
    }
  },
  "known_points": {
    "ELATO": {
      "found": true,
      "matches": []
    }
  },
  "validation": {
    "errors": 0,
    "warnings": 0
  }
}
```

另產生 Markdown：

```text
data/reports/coverage.md
```

---

# 14. AIRAC Delta Engine

第三階段才做。

比較：

```text
previous cycle
current cycle
```

輸出：

```text
added_waypoints
removed_waypoints
modified_waypoints
added_airways
removed_airways
modified_segments
```

判定修改時，比較：

```text
ident
coordinates
route membership
altitude limits
direction
status
```

產出：

```text
data/reports/diff_<old>_<new>.json
```

---

# 15. Route Engine

資料庫建立完成後，實作最小 route engine。

## 15.1 Graph

Node：

```text
Waypoint
Navaid
Airport connector
```

Edge：

```text
AirwaySegment
```

Edge cost：

```text
distance_nm
+ route penalty
+ direction penalty
+ altitude penalty
```

第一版使用 Dijkstra。

第二版使用 A*。

---

## 15.2 Airport Connector

Airport 不一定直接位於 airway graph。

第一版：

```text
從 airport 搜尋半徑內最近 N 個 waypoint
建立 temporary connector edge
```

限制：

```text
最大半徑
最大 connector 數量
避免跨越過大距離
```

這只是 route approximation。

未加入 SID／STAR 前，不得宣稱是正式 filed route。

---

## 15.3 Route 查詢

```bash
aviationdb route RCTP RJAA
```

輸出：

```json
{
  "origin": "RCTP",
  "destination": "RJAA",
  "method": "airway_graph_approximation",
  "distance_nm": 0,
  "waypoints": [],
  "polyline": [],
  "warnings": []
}
```

若資料不足：

```text
不得偽造 waypoint
不得生成不存在的 airway
可以 fallback 到 great-circle
但必須標記 fallback
```

---

# 16. Travel Globe Export

App 不需要完整來源欄位。

輸出精簡格式：

```json
{
  "version": 1,
  "cycle": "YYYYMM",
  "points": [
    ["ELATO", 25.123456, 122.123456, 1]
  ],
  "segments": [
    [0, 1, "A1"]
  ]
}
```

要求：

```text
gzip 或 zstd 壓縮
支援分區下載
支援版本號
支援 checksum
```

建議分區：

```text
asia-east
asia-southeast
north-america
europe
oceania
middle-east
africa
south-america
```

不要一開始把整個全球 DB 包進 App。

---

# 17. 授權與發布規則

建立：

```text
config/sources.yaml
```

每個來源包含：

```yaml
taiwan:
  provider: Taiwan CAA AIS
  country: TW
  source_type: eaip_xhtml
  source_url: ""
  license_url: ""
  redistribution_status: manual_review_required
  allow_raw_publication: false
  allow_processed_publication: false
  allow_app_bundle: false
```

在授權狀態不是：

```text
redistribution_allowed
```

之前：

```text
不得把完整 processed DB 上傳 GitHub Release
不得將原始官方檔案 commit 到公開 repo
不得將完整資料包進公開 App
```

允許公開的內容：

```text
程式碼
parser
schema
測試用小型人工 fixture
coverage count
validation summary
```

fixture 必須足夠小，且不可等同重新發布完整資料。

---

# 18. GitHub Actions

建立兩個 workflow。

## 18.1 CI

每次 push：

```text
ruff
mypy
pytest
build sample fixtures
validation
```

---

## 18.2 AIRAC Update

手動或排程執行：

```text
download
parse
normalize
validate
diff
build private artifacts
```

由於部分來源可能禁止自動抓取：

```text
每個 adapter 必須有 automation_allowed 設定
```

若為 false：

```text
workflow 只能使用手動上傳的 raw input
```

---

# 19. 測試要求

## Unit Tests

```text
座標解析
DMS 轉 decimal
ident normalization
UID generation
distance calculation
HTML table parsing
ARINC record parsing
duplicate matching
```

## Integration Tests

```text
Taiwan fixture → SQLite
FAA fixture → SQLite
SQLite → route graph
route graph → JSON
```

## Regression Tests

每個 parser 修正 bug 後：

```text
新增對應 fixture
新增 regression test
```

---

# 20. 執行順序

Codex 必須嚴格按順序執行。

## Milestone 0：專案骨架

完成：

```text
pyproject.toml
目錄
logging
config
CLI skeleton
基本測試
```

驗收：

```bash
pytest
ruff check .
mypy src
aviationdb --help
```

完成後提交一份進度報告，不開始下一階段直到本階段測試通過。

---

## Milestone 1：資料模型與 SQLite

完成：

```text
Pydantic models
SQLite schema
repository layer
insert/query
migration/version
```

驗收：

```text
可插入 waypoint
可插入 airway
可插入 segment
可依 ident 查 waypoint
可依 airway 查完整 segment sequence
```

---

## Milestone 2：座標與 XHTML 基礎 Parser

完成：

```text
DMS parser
HTML/XHTML loader
table extraction
source manifest
```

驗收：

```text
fixture 可解析
異常資料有 warning
parser 不因單列錯誤而整批失敗
```

---

## Milestone 3：Taiwan Adapter

完成：

```text
發現有效 eAIP
下載 ENR 3 / ENR 4.4
保存 raw files
保存 manifest
```

驗收：

```text
可重複執行
相同檔案不重複下載
有 checksum
失敗可 retry
```

---

## Milestone 4：Taiwan Parser

完成：

```text
ENR 4.4 waypoint
ENR 3 airway
airway segment
SQLite import
coverage report
validation report
```

驗收：

```text
無 validation error
可查 waypoint
可查 airway
可重建 airway segment sequence
```

---

## Milestone 5：FAA Adapter + ARINC Parser

完成：

```text
下載 CIFP
解析 waypoint
解析 navaid
解析 airway
解析 segment
```

驗收：

```text
至少 20 條 airway 通過 topology validation
未知 record 不 crash
```

---

## Milestone 6：合併與去重

完成：

```text
multi-source import
duplicate candidates
source provenance
conflict report
```

驗收：

```text
不依 ident 粗暴合併
所有合併可追蹤來源
```

---

## Milestone 7：Route Engine

完成：

```text
graph builder
Dijkstra
airport connector
fallback
route JSON
```

驗收：

```text
能在有資料區域建立 airway route
資料不足時標記 fallback
不偽造 waypoint
```

---

## Milestone 8：Travel Globe Export

完成：

```text
compact JSON
regional packages
checksum
version manifest
```

驗收：

```text
可由離線 HTML 載入
可顯示 polyline
可顯示 waypoint label
```

---

## Milestone 9：擴展亞洲資料來源

依序：

```text
Hong Kong
Singapore
Thailand
Vietnam
Japan
South Korea
Malaysia
Philippines
```

每新增一國都必須完成：

```text
adapter
parser profile
fixture
tests
coverage report
license metadata
```

---

# 21. Codex 工作規則

1. 每次只處理一個 milestone。
2. 開始修改前先檢查現有 repo。
3. 不得重寫已正常工作的模組。
4. 優先新增最小修改。
5. 所有外部 URL 放入 config，不散落在程式碼。
6. 所有網路操作支援 timeout、retry、backoff。
7. 所有下載保存 checksum。
8. 所有 parser 保留 provenance。
9. 不得硬編碼 ELATO、MAKOT 等 waypoint。
10. 不得用 great-circle 偽裝正式 airway route。
11. 不得把推測資料標成官方資料。
12. 不得因單筆解析錯誤丟棄整份資料。
13. 每階段完成後執行完整測試。
14. 每階段輸出：

    * 修改檔案
    * 設計說明
    * 測試結果
    * 已知限制
    * 下一 milestone
15. 若來源結構與預期不同，先輸出調查結果，再調整 adapter。
16. 若授權不清楚，標記 `manual_review_required`，不要自行判斷可重新發布。

---

# 22. 第一個 Codex 任務

現在只執行 Milestone 0，不要提前實作下載器或 parser。

任務：

```text
建立 AviationDB Python 專案骨架。

要求：
1. 使用 Python 3.12。
2. 使用 src layout。
3. 建立 Typer CLI。
4. 建立 config loader。
5. 建立結構化 logging。
6. 建立 pytest、ruff、mypy 設定。
7. 建立基本 README。
8. 建立 .env.example。
9. 建立 data 目錄，但 raw data 不得加入 Git。
10. 建立 aviationdb --help。
11. 建立最小測試，確認 package import 與 CLI 正常。
12. 執行並修正：
    - pytest
    - ruff check .
    - mypy src
13. 不要實作任何國家 adapter。
14. 不要下載任何航空資料。
15. 完成後回報：
    - 新增檔案
    - 執行指令
    - 測試結果
    - 下一步建議
```
