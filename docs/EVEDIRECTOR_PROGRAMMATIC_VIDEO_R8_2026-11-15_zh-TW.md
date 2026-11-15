# EveDirector R8 — 多平台候選矩陣與唯讀並列視覺審核

**日期：** 2026-11-15  
**類型：** R8 隔離開發／候選實作，疊加於 R7 Draft PR；非合併、非正式發布  
**授權：** 沿用 EveDirector / OpenMontage AGPL-3.0，保留上游著作權聲明；本版不含字型檔案。

## 1. 功能定位與不可越權範圍

R7 已能自相同來源編譯橫式、直式、方形三種獨立 Scene Program（六個版本化編輯預設），並將三支 MP4 以 R2 封存、R6 字型／安全區回執重播。然而，原 L4 需要逐支切換候選，難以跨畫幅比較同一影格的字幕位置、審核狀態與來源。

**R8 解決的是「跨版本並列觀察」而非「跨平台內容批准」。** 新增唯讀、可重播的候選比較集合；同一來源指紋、固定影片長度／fps 和三份獨立 MP4 證據皆需核對，缺少任一份則整個矩陣不可標為 REPLAY_PASS。所有影片仍經 R2 專用唯讀媒體端點播放，沒有新的 POST、Apply、Publish 或 canonical 規格寫入路由。

## 2. 工程成分

- `scripts/evedirector_compare_matrix_r8.py`：R7 source/base/request 重播、R2 影片指紋驗證、R6 回執重算、跨版本候選映射及 append-only R8 matrix 封包。
- `examples/native-video/r8-compare-links.json`：三個 R7 版本化 profile 到已封存候選 ID 的明確映射；不可指向任意 HTTP 資源。
- `backlot/programmatic_compare.py`：新增唯讀 matrix list/detail API，呈現六種狀態中的實際比較子集（本例三種）。每個 detail 在回傳之前重播 R7→R6→R2；既有 R3/R4/R5 量測結果如果缺失，呈現 **NOT_RUN** 而不是 PASS。
- `backlot/server.py`：在 Backlot FastAPI 直接註冊 R8 GET 端點及 UI 頁面，確保在 Catch-all route 前生效。
- `backlot/ui/programmatic-compare.{html,js,css}`：影片並排、不同畫幅本身比例、同影格滑桿、來源行號、逐版本 SHA-256、R3–R6 檢查狀態、編輯安全矩形覆蓋層。
- `backlot/ui/agent-review.js` / `backlot/ui/director.js`：L4、L6 入口連結到獨立 R8 唯讀比較頁；仍保留原有人工核准制度。
- `tests/test_evedirector_compare_matrix_r8.py`：來源、layout、MP4、matrix、profile 映射、symlink、跨專案、不可覆寫和不可信檔案拒絕。
- `tests/test_evedirector_compare_review_api_r8.py`：真實 Backlot app route、UI 靜態載入、三支媒體唯讀、缺失驗證不得作 PASS、禁止 Apply、篡改回 409。
- `.github/workflows/evedirector-programmatic-r8.yml`：重播 R0、R1、R6、R7、R8 測試；實際 Remotion Chromium 產生三種 MP4；封存 R2、R6 與 R8；檢查 Backlot HTTP 和禁止 POST；CI 工件統一打包。

## 3. 使用方式（本機）

需先為同一 Backlot 專案（例如 `r8-ci-demo`）封存三個 **R7 編譯結果對應的真實候選**，且為各個候選建立 R6 字型／安全區回執。R7 文檔和 GitHub CI 提供此流程。本輪不會替使用者自動生成／批准／上傳影片，也不下載任何外部媒體。

```
python scripts/evedirector_compare_matrix_r8.py stage \
  --project-id r8-ci-demo --matrix-id r8_three_profiles \
  --base examples/native-video/r6-layout-base.json \
  --source examples/native-video/source/r6-subtitle-layout.md \
  --request examples/native-video/r7-platform-layout-request.json \
  --links examples/native-video/r8-compare-links.json

python scripts/evedirector_compare_matrix_r8.py verify \
  --project-id r8-ci-demo --matrix-id r8_three_profiles

python -m backlot serve --port 4750
```

在本地瀏覽器進入：

- `http://127.0.0.1:4750/p/r8-ci-demo/programmatic-compare`
- 既有 L4 內的「R8 Compare Variants」入口
- L6 統一工作台新增的比較連結

同畫幅的影格滑桿以 `(frame + 0.25) / fps` 設定 HTML5 video 的 `currentTime`，此操作只是 **近似尋找相同位置**，不是幀精準解碼同步。三支影片可能因瀏覽器 keyframe seek、載入、幀率調度而短暫不同步。

## 4. 證據強度

R8 PASS 支援：

1. R7 母來源、底稿、字型 pin、版本化平台 preset 和各 profile 編譯後的 Scene Program 可重新生成。
2. R6 每個候選都具有可重播且與該 profile 完全一致的排版回執；字型版本或來源不同則拒絕。
3. R2 三個候選均為實際封存的 H.264 MP4，尺寸、fps、長度與影片檔 SHA 和 manifest 一致。
4. 所有已映射的 profile 為 R7 既存項目、候選 ID 不重複，來源 SHA 必須相同，影格時間軸可並列比較。

R8 **不保證**：官方平台 UI 遮擋區、不同瀏覽器逐幀精準同步、字形在所有 OS 畫素相同、未執行 R3–R5 檢查的畫面內容、來源獨立真實性、授權和發布批准。尤其「R6 排版 PASS」只是編譯規格一致性，不能代表 R5 實際中文字形 PASS。若 R3/R4/R5 未量測，UI 將顯示 **NOT_RUN**。

## 5. 安全與限制

封包存放於 `projects/<project>/programmatic_compare_matrices/<matrix-id>/`。R8 沒有上傳／刪除／覆蓋 API；CLI 建立時採 append-only，瀏覽器無寫入權。每次 GET 都核驗候選相互一致性；讀取帶 symlink 的敏感檔案會拒絕，遭篡改的矩陣回 `409` 而非展示不可信內容。矩陣不含模型原始 prompt 或 response。

R8 的服務與 R2/L4 一樣只適合可信本機環境，不是完整外網身分權限系統。要公開部署或進行大量多用戶比較，仍須額外身份驗證、資源配額和隔離設計。

## 6. 交付與整合界線

R8 仍應保留 Draft PR，疊加在未合併的 R7 之上，避免直接污染 main。合併 R0–R8、Windows 真機驗證、L0–L6 全域回歸、當時平台實際 UI 校準，以及人工出版審核必須各自完成。

**同一個故事可以有多個平台版本；但是比較之前，必須先證明每個版本是誰、從哪裡來，以及它實際對應哪一份影片。**
