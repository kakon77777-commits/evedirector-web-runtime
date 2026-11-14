# EveDirector R4 — 字形筆畫與圖層遮擋抽樣驗證

**日期：** 2026-11-15  
**前置基線：** R0 PR #12 → R1 PR #13 → R2 PR #14 → R3 PR #15（均維持 Draft，未合併 main）  
**目標：** R4 以獨立 GitHub Draft PR 疊加在 R3 上，補強 R3 刻意排除的文字區域。  
**授權：** 繼承 OpenMontage/EveDirector AGPL-3.0；不更改上游授權及署名。

## 1. 驗證問題與範圍

R3 的幾何與色彩檢查在文字區域刻意返回「不可判定」，因此即使 MP4 的文字完全被抹除，R3 仍可能 PASS。R4 不採用 OCR 猜測，也不宣稱辨識影片中全部文字，而是使用 **R1 指定的 DejaVu Sans 字型家族**及 Python Pillow 的獨立字形模型，在可比較的片段上計算：

- **預期有筆畫的位置**：採樣字形內部（避開反鋸齒邊緣），檢查影片是否真的呈現指定前景色／透明度方向。
- **預期無筆畫的位置**：在文字邊框區域採樣負空間，判定不該出現的文字色彩。
- **後置幾何物件遮擋**：若更高層有不透明矩形／橢圓，文字筆畫應被它取代；反序疊放必須拒絕。
- **時間條件**：最多抽樣 60 幀；對 640×360、60 幀示範片段，實際測量 60/60 幀。較長／高解析度的片段依固定記憶體上限減少樣本，且記錄未測量的部分。

### 重要限制

R4 **只能對可比較的高對比單行 ASCII 文字給出筆畫抽樣驗證**。CJK 字形、字型替換、跨行換行、畫布外部分裁切、過低透明度、不足的有效筆畫／邊界及未支援的複雜重疊都可能得到 `INCONCLUSIVE`。R4 PASS 代表**至少每個文字圖層有有效的抽樣測量**，但不代表它的每一幀都通過；`unmeasured_samples` 和報告的逐層理由需一併閱讀。

這不等於精確 OCR、原始字元核對、字體版權授權、視覺品質核准、所有像素一致性，更不等於發行許可。視覺與文字檢查的 PASS **只屬候選影片的特定工程量測**。

## 2. 報告格式與權限

新增報告 Schema：`evedirector.text_layer_probe.v0.1`；方法 `dejavu-ascii-stroke-and-occlusion-v0.1`。資料內容保留：`sampled_frames`、`total_frames`、`text_samples`、`unmeasured_samples`、`declared_text_layers`、`covered_text_layers`、`ink_pixels`、`blank_pixels`、`occluded_pixels`、`bad_pixels`、`occluded_bad_pixels`、逐影格逐文字圖層紀錄、原 R2 source/program/props/video SHA-256 pins。

允許狀態：

- `PASS_SAMPLED_TEXT`：可量測區域符合工程容差，文字圖層至少各有有效 PASS 測量。
- `FAIL_SAMPLED_TEXT`：偵測到可量測的文字筆畫、負空間或不透明遮擋衝突。
- `INCONCLUSIVE_SAMPLED_TEXT`：必要圖層缺少足夠的可量測筆畫或字型條件不足。
- `NOT_RUN`：L4 API 在沒有 R4 回執時呈現，**不能冒充 PASS**。

資料只增不覆寫：`projects/<project-id>/programmatic_text_checks/<candidate-id>/<sha256>.json`。每次讀取在本地重新解碼 SHA-pinned MP4 並重跑 R4 量測，防止單純「修改結果為 PASS 並重算檔名雜湊」的偽造。注意它仍是**未簽章、可由環境與字型版本影響的本地觀測**，不具第三方真實性背書。

L4 原有 L3 YAML 提案的 Validate/Apply/Reject 流程維持原樣；R4 只透過既有 programmatic-review GET detail 回傳 `text_check`，前端展示完整範圍、未測量數及失敗證據，**沒有新增 POST、Apply 或發行路由**。

## 3. 執行順序

在 R2 建立來源可重播的候選（包含 MP4）後，可執行：

```bash
python scripts/evedirector_visual_probe.py check --project-id r4-ci-demo --candidate-id ci_r4
python scripts/evedirector_text_layers_r4.py check --project-id r4-ci-demo --candidate-id ci_r4
python scripts/evedirector_text_layers_r4.py verify --project-id r4-ci-demo --candidate-id ci_r4
```

R4 CLI 返回：`0` = 抽樣 PASS、`3` = FAIL 或 INCONCLUSIVE、`2` = 執行／完整性錯誤。驗證可以不依賴 R3 報告單獨執行；但前端應**同時顯示 R3 和 R4**，兩者沒有互相覆蓋。

### Windows

本輪 R4 字型輪廓使用 Linux 路徑 `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` 作為固定比較基準，**未宣稱 Windows 真機支援或一致性驗收完成**。Windows 應使用可檢查的相同字型來源與環境契約，在完成測試前，缺少指定字型應判為 INCONCLUSIVE，不得偷換字型後仍標 PASS。

## 4. 敵對測試與驗收

本地先以 R3 GitHub 已驗收的真實 MP4 作基線：原始影片 R4 PASS；對 25–29 幀的 `EVEDIRECTOR` 標題區域覆蓋原背景色，R3 仍 PASS，但 R4 FAIL；在 Scene Program 中增加一個不透明後置圖層、讓原 MP4 的標題本應消失，R4 FAIL。這些是**可重現工程反例**，不是統計準確率聲明。

GitHub R4 CI 必須：

1. 重跑 R0/R1 Python 測試、R2/L4/R3/R4 pytest 與前端語法測試。
2. 保持 R1 TypeScript 175 組插值向量的獨立比對。
3. 以 Remotion 實際渲染候選 MP4，R2 stage、R3 probe 和 R4 check/verify 均為正例。
4. 生成相同規格但標題被抹除的 MP4，驗證 R3 PASS / R4 FAIL 的新增覆蓋能力。
5. 生成「後置遮擋物存在於 Scene Program、但影片實際未遮擋」的候選，驗證 R4 FAIL。
6. L4 API 必須顯示各自的 R3/R4 結果、未批准旗標，且完全沒有程式影片 Apply 端點。
7. 只上傳候選原始碼、測試、證據與影片 ZIP，不進行主分支 Merge 或 Publication Hub 發行。

## 5. 下一個不應跨越的推論

R4 補足了 **純幾何影片與文字真實顯示之間的驗證缺口**，但即使 R3 與 R4 雙 PASS，也不能推論全畫面的文字語義完全一致。要進一步處理 CJK、多行複雜文字，應建立可重現的字型合約、獨立 glyph rasterizer 和足夠的跨平台誤差基準；不能直接把目前的容差視為全域正確。

> 驗證邊界不是為了讓錯誤藏身，而是讓每一個 PASS 都只能聲稱它真正量過的範圍。
