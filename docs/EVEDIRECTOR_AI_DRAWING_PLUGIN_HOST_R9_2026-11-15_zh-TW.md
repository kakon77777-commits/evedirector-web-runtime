# EveDirector R9 — AI 原生繪圖與動畫外掛主機

版本：`evedirector.plugin_request.v1` / `evedirector.plugin_run_receipt.v1`  
狀態：隔離式候選實作；不代表上游私有引擎已安裝或完成整合。  
目標：**AI 透過有型別的操作，直接讓程式畫出幾何與動畫，輸出影格／影片及可檢查的來源回執。**

## 1. 方向修正

R0–R8 的媒體審核、字幕、畫幅和視覺回歸不是終點；EveDirector 要成為 AI 可以原生使用的程式製片工作台。R9 開始採用外掛架構，不把每一種演算法寫進 EveDirector 核心，也不讓 AI 在宿主直接執行任意 Python／Shell 程式。

```text
AI / Scene Planner
       |
       v
Plugin Catalog → Capability Selection → Strict Typed Request
       |
       v
[ Native R0 | EVOE Adapter | ORDR Snapshot Consumer | future plugins ]
       |
       v
Geometry / Frames / Spatial Hints → Composer → Candidate MP4
       |
       v
Source Hash + Per-operation Receipts → L4/L6 review
       |
       v
Human review / existing L3 authority gate (independent)
```

這是**真實可呼叫的本機 CLI 主機**；新的 Browser Hub 只能讀取外掛能力及範例指令，不能發送 Run、Apply、Publish 或 Canonical Write。

## 2. R9 實際具備的三個 Handler

| 外掛 ID | 操作 | 目前能實際完成 | 尚未完成 |
|---|---|---|---|
| `native-r0` | `render_video` | 呼叫 EveDirector R0 幾何／時間線渲染器，產生 MP4 + 回執，重新核對來源、時間與影片 | 高階角色、3D、EVOE 圖形構造 |
| `evoe` | `animate_frames` | **使用者明確指定已安裝的 EVOE 本地根目錄**後，以固定 `python -m evoe.cli animate` 操作渲染連續幾何的 PNG；由 FFmpeg 組成候選 MP4 | CI 無法存取私有 EVOE 原始碼；真實 EVOE 端到端尚待授權環境驗收 |
| `ordr` | `inspect_snapshot` | 讀取 ORDR Core-to-Adapter `1.0.0` 的**有界唯讀 Snapshot**，輸出區域、材料化狀態及座標摘要；拒絕未允許欄位 | 未呼叫 ORDR Core 執行空間重建、Delta、相機路徑或 3D 渲染；不宣稱繪出 ORDR 世界 |

### 為什麼 ORDR 不應直接變成 EveDirector 的 Canonical World

ORDR Core 負責世界與空間資料，ORDR-Adapters 只負責能力與資料傳遞。EveDirector 是 Consumer：讀取有界 `AdapterSnapshot`／未來 `AdapterDelta`，把視點、深度、遮擋、區域邊界與來源資訊轉成鏡頭與影像操作，不覆寫 ORDR 原始世界。ORDR v1 仍必須 `can_write_canonical=false`，且此階段 renderer profile 不允許 semantic／demand／conflict 資料偷渡。

ORDR 來源：既有私有 `ORDR-Core` Phase 7 v1 與 `ORDR-Adapters` read-only renderer consumer。R9 的 `ordr-synthetic-snapshot.json` 是**自行製作的契約測試樣本，不是 ORDR Core 實際生成的世界快照**。

### EVOE 呼叫界線

EVOE reference CLI 已有 `evoe.scene.v0.1`、`animate`、`render`、`verify` 等操作。R9 只適配 `animate` 的有限 2D 幾何／時間範圍，不將私有 EVOE 原始碼或字型封裝進公開的 EveDirector。外部 EVOE 必須由使用者自行於本地安裝與授權。R9 會用隔離輸出目錄、固定命令參數、少量環境變數、執行逾時及檔案/影格預算保護。

## 3. AI / 使用者如何直接調用

所有命令在 EveDirector 專案**根目錄**執行。

### 3.1 查詢可用外掛

```sh
python scripts/evedirector_plugin_hub.py catalog
python scripts/evedirector_plugin_hub.py describe --plugin evoe
python scripts/evedirector_plugin_hub.py doctor --plugin evoe --evoe-root /local/EveMissLab-Visual-Operator-Engine
python scripts/evedirector_plugin_hub.py doctor --plugin ordr
```

AI 可讀取 `evedirector.plugin_catalog.v1` JSON，選擇預先註冊的 `plugin_id` 與 `operation`，然後輸出`evedirector.plugin_request.v1` JSON，而不是任意腳本。`validate` 可在呼叫前拒絕未知操作、惡意欄位和超限幀數。

### 3.2 使用 EveDirector 原生繪圖製片

```sh
python scripts/evedirector_plugin_hub.py validate --request examples/native-video/plugins/native-r0.request.json
python scripts/evedirector_plugin_hub.py run --request examples/native-video/plugins/native-r0.request.json --input-root examples/native-video --output-root output/plugin-runs
python scripts/evedirector_plugin_hub.py verify --run-dir output/plugin-runs/native_demo_r9
```

此操作**實際生成** `candidate.mp4`，檢查 R0 source-grounding 與時間軸後存為待審核的候選文件，不會更動 L3 正典。

### 3.3 呼叫安裝於本機的 EVOE 畫出連續動畫

```sh
python scripts/evedirector_plugin_hub.py validate --request examples/native-video/plugins/evoe-animation.request.json
python scripts/evedirector_plugin_hub.py run --request examples/native-video/plugins/evoe-animation.request.json --input-root examples/native-video --output-root output/plugin-runs --evoe-root /local/EveMissLab-Visual-Operator-Engine --allow-external
python scripts/evedirector_plugin_hub.py verify --run-dir output/plugin-runs/evoe_geometry_demo_r9
```

輸出會包括 `scene.json`、`frames/frame_*.png`、`frames/frames.json`、`candidate.mp4` 與 `run-receipt.json`。`--allow-external` 是顯式授權執行已安裝的外部原始碼；倘若沒有該私有來源，會**明確拒絕**，不可暗中使用模擬器假裝 EVOE 已連通。R9 測試中的 fake CLI **僅驗證程序呼叫的安全邊界**，不是 EVOE 真實繪圖性能驗收。

Windows PowerShell 應改用實際本地路徑，例如 `C:\\EveMissLab\\EVOE`。不要把密碼、Token 或 API Key 放入 Request JSON。

### 3.4 讀取 ORDR 有界空間快照

```sh
python scripts/evedirector_plugin_hub.py run --request examples/native-video/plugins/ordr-snapshot.request.json --input-root examples/native-video --output-root output/plugin-runs
python scripts/evedirector_plugin_hub.py verify --run-dir output/plugin-runs/ordr_snapshot_demo_r9
```

輸出 `ordr_projection.json` 為源自有限 `AdapterSnapshot` 的 **diagnostic_only** 資料，供未來鏡頭視點／遮擋／圖層排程使用。`origin_verified_by_ordr_core=false`，因為 R9 無法只憑 JSON 確認產生者身份、完整世界真實性或模型精度。未來應以 ORDR v1 negotiated session + snapshot/delta cursor 實作真正的狀態流，不能只用固定影格當成最新空間狀態。

## 4. Plugin Request 的最小契約

```json
{
  "schema": "evedirector.plugin_request.v1",
  "candidate_id": "evoe_geometry_demo_r9",
  "plugin_id": "evoe",
  "operation": "animate_frames",
  "inputs": {
    "scene": "plugins/evoe-demo.scene.json",
    "size": 64,
    "frame_count": 12,
    "fps": 12,
    "samples": 2
  }
}
```

所有輸入僅限明確指定的本地 `--input-root` 目錄相對路徑；禁止絕對路徑、`..`、符號連結、執行字串、任意 Python 模組名稱、網路 URL、超大文件及未列入白名單的欄位。

`run-receipt.json` 逐檔記錄 SHA-256、schema、operation、來源摘要、`candidate_only=true`、`review_required=true`、`canonical_write=false`、`published=false`。輸出目錄 append-only，不可同名覆蓋；`verify` 只擔保已實作的來源／輸出一致性，**不代表影片內容經人類核准或跨引擎像素等價**。

## 5. 現有 L4 的外掛區

Backlot 啟動後開啟：

```text
http://127.0.0.1:4750/p/<project-id>/plugins
```

提供三個外掛能力卡、安裝邊界、固定 CLI 用法，以及返回 L4 的連結。API：

```text
GET /api/evedirector/plugins
```

**沒有** `/plugins/run`、`/plugins/apply` 或 `/plugins/publish` POST 端點。AI 或自動化的執行應在本地可信程序環境中走型別化 CLI，跨端權限由後續批准的執行器處理。

## 6. R9 驗收與後續工程

本輪新增 Python 單元測試（catalog、schema、參數預算、路徑穿越、EVOE opt-in、惡意欄位、ORDR Renderer 限權、Native MP4、篡改、模擬 CLI 隔離）與 Backlot GET/UI 測試。GitHub Actions 不需私有 EVOE 或 ORDR Core 的 clone 憑證，會實際跑 Native MP4＋ORDR 樣本及 fake EVOE invocation；真正外部引擎的整合結果另行記錄。

下一階段應依序做：EVOE 真實已授權環境之動畫跑通、ORDR typed snapshot/delta stream + camera scheduling、EVOE 影格與 ORDR 2.5D 視點層進入 Scene IR、再串 Remotion／EveDirector 的 L4 審核。外掛可擴充到 NOVA／ADDR／ISQL，但必須逐一實作、驗證資料契約、使用許可與權限，不會因為目錄存在就聲稱已可運行。

**R9 是 AI 原生動畫外掛底座的可執行起點，不是完整 EVOE／ORDR 雙引擎融合產品。**
