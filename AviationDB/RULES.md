# AviationDB 資料授權與發布規則

## 資料來源

AviationDB 現在只使用 **FlightGear navdata**（GPL v2 授權）作為全球航路資料來源。

FlightGear 使用的 navdata 最初由 Robin A. Peel 製作，以 X-Plane 格式發布，
並以 GPL v2 授權釋出。資料檔頭明確聲明：

```
This data is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation; either version 2 of the License, or (at your
option) any later version.
```

## 資料檔案

| 檔案 | 內容 | 行數 | 授權 |
|:----|:----|:----:|:----:|
| `fix.dat` | 全球航路點 (waypoints) | 119,724 | GPL v2 |
| `nav.dat` | 全球導航臺 (VOR/NDB/DME) | 26,775 | GPL v2 |
| `awy.dat` | 全球航路 (airways) | 70,295 | GPL v2 |

## 發布規則

FlightGear navdata 是 **GPL v2** 授權，允許：
- ✅ 使用
- ✅ 修改
- ✅ 再散布（需保留版權聲明）
- ✅ 包含在 GitHub 公開儲存庫中
- ✅ 包含在個人 sideload / 本機部署的 iOS app bundle 中（需保留 GPL v2 聲明）
- ✅ 商業使用（需遵守 GPL 條款）

注意：App Store 發布可能與 GPL v2 的再散布條款產生額外相容性問題；本專案目前不以上架 App Store 為目標。

## 資料週期

FlightGear 使用的 navdata 為 **2013.10 AIRAC cycle**。
座標資料在 AIRAC 週期間變化極小，對旅行視覺化應用完全足夠。

## 與其他資料源的關係

AviationDB 以前曾整合多個來源（各國 eAIP、EAD Basic、OpenAIP、AIXM），
但為簡化授權與維護，已統一使用 FlightGear GPL 資料。

其他資料源僅保留 parser 程式碼供參考，不再作為主要資料來源。
