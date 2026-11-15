# EveDirector R3 — 程式化場景與影片抽樣幾何一致性驗證

**日期：** 2026-11-15  
**基準：** EveDirector R2 Draft PR #14；R3 疊加在 R2 工作分支之上。  
**狀態：** R3 Draft 候選；以精確 GitHub commit 的 Actions 結果為準。  
**授權：** 沿用 OpenMontage／EveDirector AGPL-3.0，保留上游署名。

## 一、為什麼需要 R3

R2 可以確認 MP4 的 H.264、解析度、FPS、影格數與檔案 SHA-256，但這些不能證明畫面確實依 Scene Program 動畫執行。同規格的全黑 MP4，或把某一影格重複成整段影片，可能通過上述格式驗證。

R3 新增離線 **抽樣幾何／色彩檢查器**：根據 Scene IR 與合法調色盤，獨立推算矩形、橢圓及底色的可觀察區域，抽樣對照實際由 FFmpeg 解碼的 RGB 影片像素，並生成逐幀誤差報告。

**R3 不是全影片的畫素等價證明。** 文字 glyph、字體、反鋸齒邊界、音訊、未抽樣影格、素材授權、外部來源真實性，都不在本輪的驗證範圍。

## 二、界線與判準

| 指標 | R3 初版 |
|---|---|
| 最多抽樣影格 | 32 個，含場景時間位置、起訖、關鍵影格候選 |
| 最大解碼 RGB 記憶體 | 80 MiB |
| 每幀最多比對座標 | 3,000 |
| 文字與幾何邊緣 | 明確遮罩排除 |
| 單一 RGB 通道容差 | 20/255 |
| 每幀離群像素比率上限 | 4% |
| 每幀平均通道絕對誤差上限 | 8 |
| 證據不足 | 某幀少於 64 個有效像素，或全程幾何像素少於 25，判為 INCONCLUSIVE |

僅有 PASS_SAMPLED_GEOMETRY、FAIL_SAMPLED_GEOMETRY、INCONCLUSIVE_SAMPLED_GEOMETRY 三種測量結果。這些閾值是工程容差，不代表全影片正確機率或統計置信區間。

## 三、程式與資料

- scripts/evedirector_visual_probe.py：bounded FFmpeg RGB 解碼、關鍵影格選幀、幾何插值、透明度混色、保守遮罩、逐幀比對、報告保存與重播
- tests/test_evedirector_visual_probe_r3.py：採樣界線、來源／影片 SHA 綁定、報告篡改、目錄 symlink、全黑影片負例與 CLI 重播
- tests/test_evedirector_visual_review_api_r3.py：L4 中 NOT_RUN、失敗報告與不合法報告的回應、禁止新增 Apply／POST 路由
- backlot/programmatic_review.py：在每次讀取 R2 候選資料後，選擇性載入 R3 報告，重驗報告雜湊、原始來源／影片 pins、內部數值與狀態一致性
- backlot/ui/agent-review.js、CSS：顯示 R3 抽樣狀態、影格覆蓋、離群像素、逐幀誤差；保留非批准警示
- .github/workflows/evedirector-programmatic-r3.yml：實際 Remotion 正例、同規格全黑與凍結影格負例、R0–R3 回歸、L4 讀取驗收

報告儲存於 projects/<project-id>/programmatic_visual_checks/<candidate-id>/<report-sha256>.json，內容與 R2 候選來源及 MP4 SHA 綁定，只新增、不覆寫。不存在 R3 批准、發行或 canonical 覆寫 API。

## 四、CLI 使用

先以 R2 建立附有 MP4 的候選，然後執行：

    python scripts/evedirector_visual_probe.py check --project-id evedirector-drc-search --candidate-id native_r2_demo
    python scripts/evedirector_visual_probe.py verify --project-id evedirector-drc-search --candidate-id native_r2_demo

check：抽樣並新增不可覆寫報告。verify：重新解碼同一影片，將測量結果與既有報告逐位元組比對。退出碼：0 = 抽樣 PASS；3 = FAIL／INCONCLUSIVE；2 = 執行或完整性錯誤。

L4 的 R3 報告只是**未經簽章的本地觀測記錄**。雜湊可以檢出部分篡改，但無法抵抗可同時替換內容與雜湊的有權攻擊者；較高可信度必須 fresh replay 與獨立 CI。R3 PASS 不能表述為影像整體等價、來源真實、版權許可或人類批准。

## 五、驗收與未完成

必要驗收：R0/R1 Python、R2/L4 舊測試、R3 Python/API、Node 175 組插值、Remotion 真實 MP4、全黑與凍結影片兩種負例、L4 唯讀且無 Apply。以精確 GitHub head CI 為準。

**仍未完成：** Windows 真機、完整 L0–L6 全域回歸、逐像素全部影格、文字內容與音訊核對、外部簽章與 Publication Hub 發行整合。沒有人工核准的候選仍不應作為正式出版作品。

> 驗證的目的不是增加一個 PASS 標籤，而是把本來能偽裝成正確的錯誤影片轉化為可重現反例。
