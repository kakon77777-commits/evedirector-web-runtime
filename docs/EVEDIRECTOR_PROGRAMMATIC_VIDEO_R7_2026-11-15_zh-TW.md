# EveDirector R7 — 跨平台畫幅與字幕安全區矩陣

日期：2026-11-15
版本：R7 isolated candidate；疊加於 R6 Draft PR
授權：EveDirector/OpenMontage AGPL-3.0

## 目的

R6 已經能將有來源錨點的字幕轉換為固定的文字行、座標和字型回執。R7 將同一份文字意圖編譯為不同畫幅的獨立候選，避免誤把橫式文字座標直接套用至直式影片。

## 六種版本化編輯預設

| ID | 平台用途 | 畫幅 | 解析度 | L/R/T/B 安全留白 px |
|---|---|---|---|---|
| youtube_landscape_v1 | YouTube 橫式 | 16:9 | 640×360 | 36/36/36/36 |
| bilibili_landscape_v1 | Bilibili 橫式 | 16:9 | 640×360 | 42/42/38/48 |
| youtube_shorts_v1 | Shorts | 9:16 | 360×640 | 36/36/64/120 |
| tiktok_vertical_v1 | TikTok 直式 | 9:16 | 360×640 | 36/46/72/140 |
| bilibili_vertical_v1 | Bilibili 直式 | 9:16 | 360×640 | 40/40/60/126 |
| square_social_v1 | 通用方形 | 1:1 | 540×540 | 50/50/50/94 |

以上數值是 **EveDirector 自定的保守編輯預設**，不代表官方安全區、正式上傳規格或全部裝置 UI 遮擋範圍。平台 UI 會變動，不能因 R7 PASS 就直接發布。

## 源碼與資料

- scripts/evedirector_platform_layout_r7.py：有限的版本化 preset 和重新排版編譯器；以 R0、R6 檢查來源、字型指紋、場景。
- examples/native-video/r7-platform-layout-request.json：三種代表畫幅，沿用相同的來源與字幕意圖。
- tests/test_evedirector_platform_layout_r7.py：不受控 profile、重複／未排序 profile、字型漂移、來源不符、文字遺失、動態圖層禁止自動縮放、重播與篡改拒絕。
- .github/workflows/evedirector-programmatic-r7.yml：Linux GitHub CI，六個 preset 編譯、三個真實 Remotion MP4、R2 封存、R6 replay、L4 唯讀查驗。

每個 profile 的底稿、R6 request、Scene Program 與 receipt 都獨立導出；matrix.json 帶有 source/base/request/catalog 與 plan/receipt SHA-256。所有輸出採 append-only，拒絕覆寫；字型檔只從本機環境取得，**不放入 ZIP 或倉庫**。

在 repo 根目錄執行：

    python scripts/evedirector_platform_layout_r7.py compile --base examples/native-video/r6-layout-base.json --source examples/native-video/source/r6-subtitle-layout.md --request examples/native-video/r7-platform-layout-request.json --out generated/r7-variants

    python scripts/evedirector_platform_layout_r7.py verify --base examples/native-video/r6-layout-base.json --source examples/native-video/source/r6-subtitle-layout.md --request examples/native-video/r7-platform-layout-request.json --out generated/r7-variants

## 限制與權限

R7 依照水平與垂直縮放率處理**無動畫的矩形與橢圓**，並重新編譯字幕。帶 keyframes 的底稿在 R7 v0.1 明確拒絕；它不是「自動智能重構鏡頭」系統。

矩陣狀態 PASS_EDITING_SAFE_LAYOUT_MATRIX 僅表示**來源、字型度量、換行、安全矩形與版本追蹤**符合目前契約。它不保證字體在瀏覽器每像素一致，不保證平台 UI 不遮擋字幕，更不代表人類已核准影片、同意版權或外部發布。L4 的原有人工審核權限不變；R7 沒有新增 Apply、Publish 或遠端上傳端點。

正式使用前仍須獨立完成 Windows、完整 L0–L6、實際平台當時規格以及人工審查。
