# EveDirector R6：字型指紋鎖定、來源錨定自動換行與安全字幕區

日期：2026-11-15  
專案：EveDirector — Programmatic Native Video  
狀態：隔離候選 / 疊加 Draft PR；不得視為人類批准、影片公開發行、或既有 L0–L6 正式驗收。  
授權：沿用 OpenMontage/EveDirector 的 AGPL-3.0；Noto Sans CJK TC 字型必須由執行環境另行合法安裝，所有交付不含字型二進位檔。

## R6 定位

R5 已能檢查明確逐行的繁體中文字幕，但依賴作者手工換行，並不保證在不同比例的螢幕或字級下安全放置。R6 將**自動換行決策前移到編譯階段**，而非依賴瀏覽器的隱式 CSS `wrap`。R6 **沒有修改既有 R0/R1 Scene Program Schema**，而是以獨立且更嚴格的 `evedirector.subtitle_layout_request.v0.1` 宣告編譯為 R5 相容的文字圖層。

新增工具：`scripts/evedirector_subtitle_layout_r6.py`。其產物為標準 R5 Scene Program、R6 Layout Receipt，以及供 R2 本地候選封存的可重播 R6 證據。圖層使用 `_r6_1`、`_r6_2` 的安全識別碼，每行獨立計算座標，以免一個 CSS 文字框的第二行無法真正居中。

## 白名單與工程邊界

- **來源錨定**：每個 Cue 的完整字幕文字必須直接出現在該場景原始 Markdown 錨點行內；不得藉由改寫／補詞冒充原始內容。
- **字型固定**：需提供 `noto-cjk-tc-v1`、Noto Sans CJK TC 字型檔 SHA-256 及 face index。使用 fontconfig + FontTools 檢查本地版本及字元 coverage。字型錯誤、缺少或不一致即拒絕編譯，不得 fallback 或默默重新 PIN。**請勿上傳／分發字型檔**。
- **確定性排版**：使用 Noto 指定 face 與 Pillow 單行 glyph metrics 決定切行；英文單字不拆、CJK 可以逐字切，優先空格／常見標點；最多兩行，每行 28 字元，字級限定 36–64px，文字僅允許已知安全 Unicode 子集合。無法容納長單字或三行需求就 Fail Closed，不縮字、溢出或隱式換行。
- **安全區**：指定畫面四邊整數留白（16–220px），先檢查剩餘寬高，再逐行比對 glyph bounding box 是否位於安全區。支援 `middle` 與 `lower_third` 二種定位。這是座標與字型度量保證，不保證跨播放器平台的遮蔽安全，也不保證 Chrome 字形完全等同 Pillow。
- **逐行輸出**：R6 編譯產物仍由 R0 驗證、R1 輸出 props/receipt，R2 封存 MP4，R5 可另行執行 sampled glyph 檢查。互相獨立的 PASS 不會提升影片的發行權限。

明確不支援：未核對字型替代、實際視窗像素安全區（如 TikTok 右側互動按鈕）、字幕逐字語義、任意 HTML、來源未核准文本、自動翻譯、Emoji、Bidi、複雜 shaping、Emoji ZWJ、多人審核／外網部署及任意商用影片發行。

## 可重現指令

下列範例需 Windows PowerShell 合併為單行或使用反引號換行。Linux/CI 可直接使用以下形式：

```bash
python scripts/evedirector_subtitle_layout_r6.py compile \
  --base examples/native-video/r6-layout-base.json \
  --layout examples/native-video/r6-layout-request.json \
  --source examples/native-video/source/r6-subtitle-layout.md \
  --output generated/r6-plan.json --receipt generated/r6-layout-receipt.json
python scripts/evedirector_subtitle_layout_r6.py verify \
  --base examples/native-video/r6-layout-base.json \
  --layout examples/native-video/r6-layout-request.json \
  --source examples/native-video/source/r6-subtitle-layout.md \
  --output generated/r6-plan.json --receipt generated/r6-layout-receipt.json
python scripts/evedirector_remotion_bridge.py export \
  --plan generated/r6-plan.json \
  --source examples/native-video/source/r6-subtitle-layout.md \
  --props generated/remotion-props.json --receipt generated/remotion-bridge-receipt.json
cd remotion && npm install && npm run typecheck && npm run render && cd ..
mkdir -p projects/r6-demo
python scripts/evedirector_review_stage.py stage \
  --project-id r6-demo --candidate-id r6_first \
  --plan generated/r6-plan.json \
  --source examples/native-video/source/r6-subtitle-layout.md \
  --styles-dir styles --video remotion/out/native-r1.mp4
python scripts/evedirector_subtitle_layout_r6.py stage \
  --project-id r6-demo --candidate-id r6_first \
  --base examples/native-video/r6-layout-base.json \
  --layout examples/native-video/r6-layout-request.json
python scripts/evedirector_subtitle_layout_r6.py replay --project-id r6-demo --candidate-id r6_first
python scripts/evedirector_multilang_probe_r5.py check --project-id r6-demo --candidate-id r6_first
```

如果當地使用另一個 Noto 發行版本，範例 PIN 不得直接視為有效；應經由獨立授權／部署流程建立明確的版本變更與新的 layout request，再重跑全部驗收。不能自動替換 Request 的 SHA 成本地值而宣稱跨平台可重現。

## L4 的 R6 記錄

`GET /api/project/<project>/programmatic-review/<candidate>` 額外提供 `layout_check`，可能狀態為 `NOT_RUN`（未執行）或 `PASS_SAFE_LAYOUT_CONTRACT`（本機環境重新編譯的安全區／字型度量與提交版本一致）。若受保護檔案、來源、幾何、字型 SHA 或報告遭到改動，就回傳 409，不會把失敗顯示成 PASS。新增證據檔位於 `projects/<project>/programmatic_layout_checks/<candidate>/`，包含 base plan、layout request、receipt，且只允許新增、不可覆寫。R6 的 Load 操作重新編譯並與 R2 封存候選的 plan 比對，以避免偽造通過。

前端只顯示文字與數值，不回傳本地 font path 或原始模型 prompt。原有 R5 `multilingual_check` 另外記錄實際影片的有限抽樣結果；兩者不可取代。任何 R6 PASS 均明示 `approved_for_publish=false`、`visual_equivalence_attested=false`。沒有新增 POST Apply／Reject／Validate／Publish 端點，所有 canonical authority 保持不變。

## 驗收證據與已知限制

Python 單元測試涵蓋字型 SHA/face mismatch、無字型不可 fallback、source quote 不匹配、控制字元、不可拆英文長詞、安全區溢出、篡改 receipt／plan、symlink、候選不可覆蓋。GitHub CI 另外測試既有 R0–R5 回歸、Python/TypeScript 175 插值向量、真實 Remotion 字幕影片、R5 sample glyph、黑影片 FAIL、反事實移動文字拒絕、L4 唯讀 API 與實際視頻讀取。請使用該次精確提交的 GitHub Actions 成功結果，而非僅從本文件推定完成。

**本輪結論：先把換行位置變成可重播的程式輸出，才能嚴格討論後端渲染是否符合它；PASS 不應超出真正檢查過的因果範圍。**
