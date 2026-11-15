# EveDirector R10 — 跨外掛 Scene IR 與 AI 原生程式動畫合成

版本：`evedirector.scene_ir_draft.v1`、`evedirector.scene_ir.v1`、`evedirector.scene_ir_render_receipt.v1`  
日期：2026-11-15  
權限：**候選作品，需人工審核；禁止 Canonical Write／Publish；不等同於完整 ORDR 或私有 EVOE 引擎連接驗收。**

## 1. 正確的系統分工

```text
AI 意圖 / 來源 Markdown
   ↓ 受限制的 Structured JSON
R9 插件發現 / Capability 檢查
   ├─ Native R0：產生 2D 程式畫面、影片與來源回執
   ├─ EVOE：以明確授權執行的本機幾何動畫 CLI → PNG → MP4
   └─ ORDR：受限 AdapterSnapshot v1 → 唯讀空間證據（不生成 3D 畫素）
   ↓
R10 Scene IR：固定圖層、畫幅、影格時鐘、來源行、外掛回執 SHA-256
   ↓
R10 有界 FFmpeg compositor（預先審查的運算子、沒有任意 ffmpeg filter 或 shell）
   ↓
候選 MP4 + Scene IR + dependencies + 組合回執
   ↓
L4/L6 仍依既有權限進行人工審閱；**R10 不提供 Apply API**
```

ORDR/Core v1 提供 `AdapterSnapshot`／`AdapterDelta` 的資料契約、座標方向、邊界與 provenance。R10 **沒有**對 ORDR Core/Adapters 執行真實重建，也沒有把 ORDR 資料當作影格；僅驗證 R9 已準備好的唯讀空間摘要。未來實際畫出 ORDR 視點必須獨立實作 camera/geometry consumer 與 renderer mapping。

EVOE 目前提供 `evoe.cli animate`、幾何規格與離散時間取樣。R10 使用 R9 既有 EVOE adapter 的候選 MP4。**本輪 GitHub CI 的 EVOE 僅為固定命令傳輸模擬器，不能代表真實 EVOE 私有引擎已驗收。** 真實 EVOE 需要本地已有合法存取的獨立安裝，R9 `--allow-external` 開關才可執行。

## 2. AI/使用者如何調用

在 EveDirector repository 根目錄執行，Python 3.11+、Pillow／PyYAML、FFmpeg／FFprobe 必須可用。先準備 R9 三個獨立 plugin runs：

```powershell
python scripts/evedirector_plugin_hub.py catalog
python scripts/evedirector_plugin_hub.py run --request examples/native-video/plugins/native-r0.request.json --input-root examples/native-video --output-root output/plugin-runs
python scripts/evedirector_plugin_hub.py run --request examples/native-video/plugins/ordr-snapshot.request.json --input-root examples/native-video --output-root output/plugin-runs
python scripts/evedirector_plugin_hub.py doctor --plugin evoe --evoe-root "C:\EveMissLab\EVOE"
python scripts/evedirector_plugin_hub.py run --request examples/native-video/plugins/r10-evoe-60.request.json --input-root examples/native-video --output-root output/plugin-runs --evoe-root "C:\EveMissLab\EVOE" --allow-external
```

這個範例的三個 R9 輸出為：`native_demo_r9`、`evoe_geometry_demo_r10`、`ordr_snapshot_demo_r9`。其後使用同一份 R10 IR：

```powershell
python scripts/evedirector_scene_ir_r10.py lock --draft examples/native-video/plugins/r10-composition.draft.json --input-root examples/native-video --runs-root output/plugin-runs --out output/r10.locked.json
python scripts/evedirector_scene_ir_r10.py compose --ir output/r10.locked.json --input-root examples/native-video --runs-root output/plugin-runs --output-root output/compositions
python scripts/evedirector_scene_ir_r10.py verify --candidate-dir output/compositions/r10_native_evoe_ordr_composite --input-root examples/native-video --runs-root output/plugin-runs
```

`lock` 不會執行任何外掛；只會重播 R9 輸出、核對來源 Markdown 指定行，填入 Scene IR 與 plugin receipt 的 SHA-256。

`compose` 再次驗證所有依賴，採固定順序進行 Native 基底與 EVOE 圖層的有界合成，讓 ORDR 作為獨立不可視空間證據。`verify` 重新計算來源、外掛回執、輸出影片 SHA-256，並使用 FFprobe 核對 H.264、畫幅、fps 和影格數。

## 3. 有限版 Scene IR 具備哪些能力

R10 v1 限制如下：

- 必須恰好一個 Native R0 影片基底、至少一個 EVOE 影片圖層；至多三個 EVOE 圖層，以及至多一筆 ORDR 診斷資料；ORDR 僅能放置於最後一個 evidence track。
- 影片輸入必須同 FPS、同影格數；基底尺寸等於輸出畫幅；EVOE overlay 採明確的偶數像素邊界與整張畫布之內的座標。
- 來源必須是 UTF-8 Markdown，逐 track 設定 `source_line` 與 `source_contains`；改動後必須重新鎖定，不可假裝舊版本依然有效。
- 所有輸出都是 append-only、候選-only；不允許模型提供 shell、Python、URL、任意 FFmpeg filtergraph、字型檔或其他未白名單化參數。
- `ORDR-Core`／`EVOE` 仍是各自維護權威資料的獨立專案；R10 不帶入私有實作、不把它們的權威改寫為 EveDirector 的權威。

### 範例 JSON

```json
{
  "schema": "evedirector.scene_ir_draft.v1",
  "candidate_id": "r10_native_evoe_ordr_composite",
  "source": {"path":"source/r10-plugin-composition.md"},
  "canvas":{"width":640,"height":360,"fps":12,"frames":60},
  "tracks": [
    {"track_id":"native_stage","plugin_id":"native-r0","role":"background_video","run_id":"native_demo_r9","source_line":3,"source_contains":"Native R0 draws the grounded base scene"},
    {"track_id":"evoe_operator","plugin_id":"evoe","role":"overlay_video","run_id":"evoe_geometry_demo_r10","source_line":4,"source_contains":"EVOE provides geometry-derived motion frames","placement":{"x":350,"y":44,"width":220,"height":220}},
    {"track_id":"ordr_spatial","plugin_id":"ordr","role":"spatial_evidence","run_id":"ordr_snapshot_demo_r9","source_line":5,"source_contains":"ORDR provides read-only spatial provenance"}
  ]
}
```

## 4. 實作、測試及權限邊界

- `scripts/evedirector_scene_ir_r10.py`：IR 結構驗證、來源重播、run receipt 鎖定、固定圖層合成、MP4 回執及重新核對。
- `tests/test_evedirector_scene_ir_r10.py`：實際 Native R0 → MP4、ORDR 唯讀摘要、EVOE 固定 CLI stub、跨外掛合成、未知指令拒絕、非法圖層、來源與雜湊篡改、時鐘不一致、symlink、覆寫拒絕。
- `tests/support/r10_mock_evoe.py`：**只供測試**的模擬 CLI，不含真實 EVOE 幾何運算子。
- `tests/integration_r10_ci.py`：使用上述 stub 與真正的 R0 畫面生成合成候選，輸出可核對的 H.264 影片及機器可讀 CI 紀錄。
- Backlot 外掛頁面 `/p/<project-id>/plugins` 新增 R10 呼叫流程的唯讀複製命令，不提供瀏覽器遠端執行或 Apply/Publish。

這次的視覺整合證明的是**固定插件影片的圖層合成流程可實際執行**，不是 ORDR 3D 重建、EVOE 真實引擎性能、視覺語義等價、電影製作完成度或正式影片發行。

## 5. 下一個技術門檻

R11 應把已安裝的實際 EVOE 幾何／時間運算子接入目前 R10 Scene IR，並讓 ORDR snapshot／delta 的過時游標、座標投影與 region 進出被明確處理；只有逐步通過實際測試後，才能繼續推進相機控制與 2.5D／3D 場景動畫。
