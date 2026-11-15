# EveDirector R5：繁體中文／中英混排字型契約與抽樣字形驗證

**日期：** 2026-11-15  
**版本：** R5 isolated candidate / Draft PR, 疊加於 R4  
**授權：** EveDirector/OpenMontage AGPL-3.0；Noto CJK 字型由各執行環境獨立安裝，本提案**不再散布字型檔**。

## 1. 問題與決策

R4 的 DejaVu Sans 字形檢查只能對單行 ASCII 做抽樣推定。若不顯式限制字型，中文字或多語字幕可能在開發機與渲染機使用不同的 fallback，產生「影片存在、雜湊正確，但文字不符合提案」的假陽性。

R5 不改造既有 R0/R1 Scene Program v0.1；只在**文字圖層**增加白名單欄位 `font_profile`：

- 未指定：維持 R0–R4 的 ASCII 舊資料相容性，仍使用 DejaVu Sans CSS。
- `dejavu-ascii-v1`：顯式 ASCII 舊版字型。
- `noto-cjk-tc-v1`：使用 `"Noto Sans CJK TC", sans-serif` CSS 家族、固定 `white-space: pre` 禁止自動換行。允許 **至多兩行明確的 `\n`**，每行至多 28 字元。

非 ASCII 字元必須指定 `noto-cjk-tc-v1`。所有外部字型 URL、未知 profile、幾何圖層攜帶 profile、雙向方向控制字元、隱形連接字元、Tab、CR 與不支援換行等均拒絕。這不是對所有 Unicode 腳本的通用排版支援：Emoji、Bidi、複雜 ligature、竪排、跨平台自由替換仍不支援。

## 2. 獨立驗證

R5 新增 `scripts/evedirector_multilang_probe_r5.py`：

1. R2 驗證來源、原始 Scene Program、style、R1 props/receipt，以及影片檔案 SHA-256。
2. 從 OS fontconfig 解析 `Noto Sans CJK TC` 真實本地字型來源與 TTC face index，使用 FontTools cmap 確認必要字元覆蓋，記錄整個字型檔案 SHA-256（不嵌入字型本體）。缺字型為 **INCONCLUSIVE**，不得自動 fallback。
3. 用 Pillow 依字體形狀建立每行的預期「字形內部筆畫／負空間」樣本，在影片中選取上限 30 個影格，以 FFmpeg `rgb24` 解碼，對比字色相對於背景色的投影強度。
4. 對小範圍的 PIL／Chromium 基線與抗鋸齒偏移允許局部位移搜索，且只採樣足夠高對比、充分入鏡、字級至少 36 px 的文字。小字級、低透明度、被其他圖層覆蓋、不支持 Unicode 字形及顯示邊界不足時為 **INCONCLUSIVE**。
5. PASS 必須每一個宣告的 CJK 文字行至少被成功量測一次，且所有可比較的 sampled rows 沒有 FAIL。FAIL、PASS 及 INCONCLUSIVE 都是有限影格的量測，不是對整支影片的完全背書。

結果：

- `PASS_SAMPLED_MULTILINGUAL_TEXT`
- `FAIL_SAMPLED_MULTILINGUAL_TEXT`
- `INCONCLUSIVE_MULTILINGUAL_TEXT`
- `NOT_RUN`（L4 尚未收到 R5 報告）

報告 Schema：`evedirector.multilingual_glyph_probe.v0.1`。報告 pin 住 source/program/props/video SHA-256，記錄採樣影格、分行、字形與負空間比率、字型 SHA-256、TTC index、未測量樣本與拒絕原因；未存放字型檔及敏感路徑。報告不可覆寫；L4 每次讀取時**重新執行影片／字型量測**，因此更改報告內容、甚至修改後重新命名 SHA 檔案，都不能直接偽造 PASS。

## 3. L4 檢視與權限

現有的 `GET /api/project/<project>/programmatic-review/<candidate>` 追加 `multilingual_check` 欄位。前端同一頁呈現 R3 幾何、R4 ASCII、R5 多語檢查的**獨立**結果；缺報告必須顯示 NOT_RUN。**沒有新增 POST、Validate、Apply、Reject、Publish 端點**；即使開啟 `BACKLOT_ENABLE_AGENT_ACTIONS=1`，R5 也無法取得 L3 的 canonical spec 寫入權限。

## 4. 可重現測試

在 repo 根目錄：

```bash
python -m pip install 'Pillow>=10' 'PyYAML>=6' 'fonttools>=4.55'
# Linux 安裝 ffmpeg fonts-dejavu-core fonts-noto-cjk；不把字型放入 repository
python scripts/evedirector_remotion_bridge.py export --plan examples/native-video/r5-multilingual.json --source examples/native-video/source/r5-multilingual.md --props generated/remotion-props.json --receipt generated/remotion-bridge-receipt.json
python scripts/evedirector_remotion_bridge.py verify --plan examples/native-video/r5-multilingual.json --source examples/native-video/source/r5-multilingual.md --props generated/remotion-props.json --receipt generated/remotion-bridge-receipt.json
cd remotion && npm install && npm run typecheck && npm run render && cd ..
mkdir -p projects/r5-demo
python scripts/evedirector_review_stage.py stage --project-id r5-demo --candidate-id multilingual --plan examples/native-video/r5-multilingual.json --source examples/native-video/source/r5-multilingual.md --styles-dir styles --video remotion/out/native-r1.mp4
python scripts/evedirector_multilang_probe_r5.py check --project-id r5-demo --candidate-id multilingual
python scripts/evedirector_multilang_probe_r5.py verify --project-id r5-demo --candidate-id multilingual
```

API 本地觀看：`http://127.0.0.1:4750/p/r5-demo/agent-review`。不指定 candidate 的正典影片 Apply，僅是人工檢視。

CI 除了原有 R0–R4 契約及 175 組 R0 ↔ TS 插值向量，也需要真實 Remotion 生成、正例 PASS、同規格影片的中文字被抹除、Scene Program 宣告錯誤文字、全黑反例 FAIL，以及 L4 無 Apply／報告篡改拒絕。

## 5. 資訊與版權邊界

- **字型 SHA-256 不證明瀏覽器實際載入了它**；R5 的獨立像素比對可增加可信度，但仍是局部推定。
- 字型可用性、字體 face 與字級高度依賴作業環境；未經 Windows/其他版本基準校正時，不能跨平台聲稱 PASS。未滿可靠字級的文字列為 INCONCLUSIVE。
- 即使文字在某些抽樣影格通過，也不保證字詞含義、字形變體、全部影格、字距、排版美感、音訊、版權或發行批准。
- R0–R5 仍為疊加 Draft PR，不修改 main，不可將 CI 預覽影片視為 Publication Hub 已發布素材。

**核心結論：字型不是可忽略的渲染環境變數；當字型無法被指認與重新驗證，字形的 PASS 就沒有充分的工程含義。**
