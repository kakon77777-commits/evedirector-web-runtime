# EveDirector — AI 原生程式生成影片 R0

**日期：** 2026-11-15  
**狀態：** `R0 / EXECUTABLE ISOLATED CANDIDATE / NOT MERGED INTO L0–L6`  
**原稿編碼：** UTF-8 Markdown  
**範圍：** 本地封閉式 JSON 場景語言、來源錨定、視覺風格調色、影格與 MP4、回執  
**授權：** 供合併至原 EveDirector AGPL-3.0 專案；沿用上游授權義務。獨立外部專案依個別授權審查。

## 1. 定位

EveDirector 已是 OpenMontage（AGPL-3.0）分支，既有 L0–L6 來源錨定、Remotion 視訊輸出及人工審核工作台。本 R0 不取代任何部分，而是先驗證一種**模型只產生受限制的宣告式場景程式**、由決定性的本地運算產生影格與影片的方式。模型不被允許將 Python／JS／shell 或網路 URL 當成可執行素材注入渲染流程。

從研究角度，這與「用生成影片模型直接吐出影片」不同：生成對象是一份有限、有型別、可驗證、可逐影格求值的 scene program。影片只是其投影成果。

## 2. 本輪已可執行的路徑

```
Human-approved UTF-8 Markdown (source)
    + model-proposed JSON scene program (candidate)
    + checked-in style YAML (palette subset)
        ↓
strict contract validation + exact line anchor
        ↓
per-frame primitive evaluation + keyframe interpolation
        ↓
Pillow frame rendering (RGB PNG)
        ↓
FFmpeg H.264 MP4
        ↓
FFprobe codec/dimension checks
        ↓
SHA-256 evidence receipt + preview MP4
        ↓
manual review before any canonical / publication handoff
```

R0 算子類型限定 `rect`、`ellipse`、`text`；運動軌道為 `x`、`y`、`opacity`，幾何物件另可有 `width`、`height`。時間為場景局部整數影格，線性插值，未指定區間固定保持；不是任意 Python 程式。可變動的風格顏色由倉庫內既有 YAML playbook 中 `visual_language.color_palette` 提取，使用的 YAML 原始位元組有 SHA-256 錨定。**R0 並未實作 playbook 的整套排版、音樂、轉場或品質判斷。**

## 3. Windows 使用指令

在 EveDirector 倉庫根目錄執行：

```powershell
python -m pip install pyyaml pillow
python scripts/evedirector_programmatic.py validate `
  --plan examples/native-video/program.json `
  --source examples/native-video/source/README.md

python scripts/evedirector_programmatic.py render `
  --plan examples/native-video/program.json `
  --source examples/native-video/source/README.md `
  --output output/evedirector-native-r0.mp4 `
  --manifest output/render_receipt.json

python -m unittest discover -s tests -p 'test_evedirector_programmatic.py' -v
```

需在 `PATH` 上安裝 FFmpeg / FFprobe；若不同平台字型影響筆畫，使用 `--font` 指定**本機已合法安裝**的字型檔（不將字型嵌入公開倉庫）。如需重跑覆蓋同名輸出，加上 `--force`。

本 ZIP 完整包含示範所需獨立風格 `styles/evemiss-native-demo.yaml`。合併到 EveDirector 後，同樣可將 `program.json` 的 `style` 改成現有 `flat-motion-graphics`、`clean-professional`、`premium-minimalist` 或 `minimalist-diagram`，並重新編譯。各 playbook 的可使用性不等於其附帶素材的著作權授權。

## 4. 契約與拒絕策略

- 來源檔只能由呼叫者以 `--source` 明確指定；JSON 場景不得指定外部 URL、素材路徑、執行碼或程序呼叫。
- 場景必須逐段完整覆蓋時間軸，場景 ID 不得重複；每個 `source_contains` 必須在 UTF-8 來源的某一行出現。
- JSON 僅接受完整明列欄位、有限數值、有限畫面尺寸、影格總數及純色值，不接受未知物件、NaN、無限數或污染型別。
- 風格名稱只能是安全 slug 並存在本地 `styles/`；使用 `yaml.safe_load`，不支援 URL 路徑、動態腳本或未授權素材。
- 場景動畫以資料方式傳遞，嚴格不等同於允許 AI 執行任意程式碼；若未來需要完整 Python/JS 場景腳本，必須另建沙箱、權限、資源預算和來源鏈。
- R0 不執行 L3 Apply、L4 Validate、L5 derive 或 Publication Hub Upload；不能繞過人工審核。原有正典與審核權威不變。
- 視覺忠實度不代表事實真實性；source anchor 僅證明引文存在，仍須獨立確認敘事是否曲解來源。

## 5. 與 EVOE、ORDR 的橋接（尚未實作）

| 專案 | 現況 | 下一個版本化橋接 |
|---|---|---|
| EVOE | 獨立私有研究倉，已有場景／幾何／多解析度與時間算子 | `evoe.source_frame.v0.1`：由本地 CLI 導出帧＋來源收據；路徑與雜湊進入只讀 asset manifest；需來源授權核對 |
| ORDR-Core | 私有 Phase 7，Adapter Contract `1.0.0` | `ordr.renderer_readonly.v0.1`：僅消費有限 `AdapterSnapshot` / `AdapterDelta`，保留版本、世界指紋、座標、來源分類及遺失資訊標記 |
| ORDR-Adapters | 私有，Rust read-only consumer 已有示例 | 狀態→視覺層轉譯；絕不在 EveDirector 建造第二套 canonical world model |
| Publication Hub | 私有發行權威 | 自成一份 handoff，載入 MP4 SHA-256、來源／風格／渲染收據，人工檢查後才入庫；不共用 SQLite 與 OAuth |

ORDR 原生座標採右手系、影像右向 +X、下向 +Y、向前 +Z。影片影格尺寸與攝影機投影不同；轉譯須有明確 coordinate transform、可視範圍、lossy flag 與來源標記。ORDR adapter 的任何 `can_write_canonical` 均需保持 `false`。

EVOE 尚無已驗收的 EveDirector 影音 API；R0 不聲稱已接通，也不把私有 EVOE 原始碼或素材複製進公開 EveDirector。

## 6. 渲染後端的中期策略

以 `Scene Program / Scene IR` 作為內部編排語言，再讓各後端作為可替換的 renderer：

- **Remotion（已在 EveDirector）：** 正式影片編排、字幕、合成與時間軸；R1 加入 `scene program → Remotion props` adapter，不重建原有 composer。
- **Pillow + FFmpeg（本 R0）：** 零雲端 API 的封閉式影格產生和 H.264 驗證，適合可重現的基本構圖及動作。
- **Manim：** 科學、數學與幾何動畫；輸入及輸出需透過安全化中介，而非執行不受信的模型原始碼。
- **Blender／Three.js：** 未來立體場景、攝影機、可見度與較高階動作，須先制定邊界測試。
- **EVOE、ORDR：** 專有的算子與空間來源，而非強迫替換目前可靠的播放器／編碼器。

## 7. 外部授權界線（部署前必查）

- **OpenMontage／EveDirector：** 專案屬 AGPL-3.0 系列，架設修改版供他人網路使用時要履行相應原始碼提供義務；不能因這次 R0 是自有程式碼便忽略上游條款。
- **Remotion：** 並非所有組織都享無條件的 OSI 開源授權。官方目前以個人與符合人數條件的小企業免費授權、較大型公司另需商業授權；長期產品化前應逐項核對實際使用方式及當時條款。
- **Manim／Three.js／Motion Canvas：** 可參考其明列的開源授權，但軟體程式碼授權**不等於**風格圖集、角色、配音、攝影素材都可自由再製。
- **Blender：** 其 GPL 軟體授權原則上不要求以 GPL 釋出生成的影片；外部貼圖、外掛與模型各有權利條款。
- **FFmpeg／libx264：** 目前 R0 使用可本機安裝的 `ffmpeg` 與 `libx264`，不隨 ZIP 夾帶編碼器二進位。若要重新散布工具鏈，需確認 FFmpeg LGPL/GPL 與 libx264 GPL 相關義務。

授權參考：Remotion 官方 `https://www.remotion.dev/docs/license/pricing`、Manim Community `https://docs.manim.community/en/stable/`、Blender `https://www.blender.org/about/license/`、FFmpeg `https://ffmpeg.org/legal.html`。

## 8. 本輪驗收與非宣稱

在隔離 Linux 工作容器：13/13 單元與安全反例測試通過；Pillow 影格差異測試通過；FFmpeg `libx264` 成功產生 640×360、12 fps、60 帧、5 秒影片；FFprobe 確認 H.264 及尺寸。示範素材沒有外部 API、雲端帳號、音效、生成圖片或來源影片。

**未驗收：** Windows／PowerShell 真機、完整 EveDirector L0–L6 回歸、Remotion renderer 介接、不同主機位元完全相同、EVOE 與 ORDR 真實連線、TTS、音樂、鏡頭合成、動畫物理一致性、Publication Hub 真正接收和對外發布。輸出 `VERIFIED_LOCAL` 只代表這個本地容器的 MP4 檢查，不代表整套產品可發布。

## 9. 後續門檻

R1 最小交付：定義 `scene_program → Remotion clip` adapter，將每段 source anchor 與影片片段綁定，通過 L2 / L3 / L4 / L5 / L6 非破壞式測試及 Windows 真機重播。接著才有條件建立 EVOE 受控輸入和 ORDR 唯讀視角管線。未完成 R1 以前，R0 與現有 canonical video spec 保持隔離。
