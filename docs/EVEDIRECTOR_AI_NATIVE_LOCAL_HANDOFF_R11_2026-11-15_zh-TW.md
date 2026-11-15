# EveDirector R11｜EVOE／ORDR 本地整合與暫停交接

**日期：2026-11-15**  
**狀態：候選功能；GitHub Draft PR，未合併，非正式發行。**  
**基線：R10 Draft PR #22（R0–R10 均為堆疊式 Draft）。**  
**授權：EveDirector / OpenMontage AGPL-3.0；未將 EVOE／ORDR 私有程式或字型併入公開倉庫。**

## 1. 用途

R9 已有 Native R0、EVOE 與 ORDR 的固定外掛呼叫；R10 以來源錨點鎖定 Scene IR 並合成 H.264。但先前 GitHub CI 的 EVOE 是**模擬 CLI**，ORDR 是**合成測試快照**，不能當成真實私有引擎整合完成。

R11 提供：明確授權的本地引擎呼叫、引擎版本指紋、不可覆寫候選輸出、Windows 驗收入口、完整來源及影片回執的離線重播。完成後暫停新功能，交由本地整合。

## 2. 角色與權限

| 模組 | R11 功能 | 不能聲稱 |
|---|---|---|
| Native R0 | 來源錨定 Scene Program → 基底 MP4 | 已核准發布 |
| EVOE | 固定 Python CLI animate，明確 opt-in | CI mock 等於私有引擎驗收 |
| ORDR-Core / ORDR-Adapters | 檢查私有契約檔指紋與 Git HEAD；R9 讀取 v1 bounded snapshot | ORDR Core 已執行／已建構真 3D |
| R10 Scene IR | 鎖定來源、三組 run receipt 與合成影片 | 可取得 canonical write / Apply |
| R11 handoff | 檢查 SHA、封存結果、離線 verify | 可驗證引擎作者身分或獨立重新渲染 |

EVOE 本地 CLI 實際支援 animate --scene --times --size --samples --output；ORDR-Core/Adapters 使用 Core-to-Adapter 版本 1.0.0 的唯讀資料契約。引擎版本指紋不是密碼學簽章。沒有任何私有來源檔案被複製入公開 EveDirector。

## 3. Windows PowerShell 操作

在 EveDirector 專案根目錄，改用自己電腦的路徑：

~~~powershell
$EvoeRoot = 'D:\research\EveMissLab-Visual-Operator-Engine'
$OrdrCore = 'D:\research\ORDR-Core'
$OrdrAdapters = 'D:\research\ORDR-Adapters'

python --version
ffmpeg -version
ffprobe -version

.\scripts\evedirector-r11-local.ps1 -Action doctor -EvoeRoot $EvoeRoot -OrdrCoreRoot $OrdrCore -OrdrAdaptersRoot $OrdrAdapters

# 只有 stage 加上 -AllowLocalEngines 才能執行 EVOE。
.\scripts\evedirector-r11-local.ps1 -Action stage -EvoeRoot $EvoeRoot -OrdrCoreRoot $OrdrCore -OrdrAdaptersRoot $OrdrAdapters -OutputRoot 'output\local-handoffs' -CandidateId local_r11_01 -AllowLocalEngines

.\scripts\evedirector-r11-local.ps1 -Action verify -CandidateDir 'output\local-handoffs\local_r11_01'
~~~

直接使用 Python 也可以：

~~~shell
python scripts/evedirector_local_handoff_r11.py doctor --evoe-root "YOUR_LOCAL_EVOE" --ordr-core-root "YOUR_ORDR_CORE" --ordr-adapters-root "YOUR_ORDR_ADAPTERS"
python scripts/evedirector_local_handoff_r11.py stage --evoe-root "YOUR_LOCAL_EVOE" --ordr-core-root "YOUR_ORDR_CORE" --ordr-adapters-root "YOUR_ORDR_ADAPTERS" --allow-local-engines --output-root output/local-handoffs --candidate-id local_r11_01
python scripts/evedirector_local_handoff_r11.py verify --candidate-dir output/local-handoffs/local_r11_01
~~~

可在私有 ORDR repo 另行執行 Cargo tests（需要 Rust 工具鏈、私有相依授權）：

~~~powershell
cargo test --manifest-path "$OrdrCore\Cargo.toml"
cargo test --manifest-path "$OrdrAdapters\Cargo.toml"
~~~

這些 Cargo 指令**不是 R11 自動執行的部分**，也不代表已產生 ORDR 真實空間畫面。

## 4. 輸入與封存

預設 input-root 是 examples/native-video。其 plugins/ordr-synthetic-snapshot.json **是測試用合成快照**。真正對接 ORDR 時，應在本機另外建立 input-root，使用 ORDR Core 產出的有界 v1 read-only Snapshot 替換相同相對路徑，再使用 -InputRoot 指定本地資料夾，不將敏感原始資料提交 GitHub。

每次 stage 在 output/local-handoffs/<candidate-id>/ 建立新目錄，包括：

- inputs/：本輪 source、Scene Program、EVOE scene JSON 與 ORDR Snapshot
- runs/：Native、EVOE、ORDR 的 R9 固定操作收據
- composition/：R10 的 locked Scene IR、合成 MP4 和合成回執
- scene-ir.locked.json、handoff-receipt.json：來源與引擎指紋、run SHA、候選影片 SHA 和權限聲明

輸出不得覆蓋既有候選，不得位於私有引擎 checkout 或輸入目錄內。網頁 Plugin Hub 只顯示／複製命令，**不能透過網頁執行外部引擎**。

verify 可以在未再安裝 EVOE 時重驗已封存來源、三組 R9 收據、ORDR snapshot 格式、Scene IR、MP4 規格及 SHA；但**不會重新執行 EVOE**，也不會獨立證明影片的每個像素或內容已獲授權發行。

## 5. 邊界與暫停點

GitHub CI 使用模擬 EVOE CLI 和合成 ORDR 快照；即使全部 PASS，也**不等於 Windows 真實私有引擎通過**。真正本機驗收需單獨記錄版本、實際影格、快照來源與權限；私人素材不得未審核上傳公共 GitHub。

本輪不擴張 L3–L6 Apply、ORDR canonical write 或自動發行。R11 Draft PR 與 ZIP 交付後，**停止新增 R12 功能**；先讓本地端完成接線與驗收，再依真實錯誤決定是否修復。

**AI 可以指揮繪圖引擎，但指令、執行結果與被授權的事實必須各自驗證。**
