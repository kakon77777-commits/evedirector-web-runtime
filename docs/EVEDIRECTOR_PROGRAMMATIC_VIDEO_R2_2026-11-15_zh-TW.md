# EveDirector R2：程式影片候選 × L4 唯讀審核整合

- 日期：2026-11-15
- 分支：feat/ai-native-programmatic-video-r2-l4-review-20261115
- 前置：R0 Draft PR #12、R1 Draft PR #13
- 狀態：R2 Draft CI 候選；是否通過以最新提交對應 GitHub Actions 為準
- 授權：沿用原 EveDirector / OpenMontage 的 AGPL-3.0；保留上游署名

## R2 解決的問題

L4 現行審核針對 **L3 YAML local-agent proposal**：顯示 semantic diff、原始資料行號與提案，並在嚴格權限條件下允許 Validate / Apply / Reject。

R0/R1 程式化影片則是獨立的 **JSON Scene Program** 和 Remotion 候選 MP4。若把 R1 JSON 裝扮成 L3 YAML run，會誤導審核者以為可以直接 Apply 變更。因此 R2 實作**平行、唯讀**的 programmatic-review 通道，顯示於相同 L4 頁面，但完全沒有新的 Apply / Validate / Reject API。

## 已新增元件

| 檔案 | 作用 |
|---|---|
| scripts/evedirector_review_stage.py | 本機 CLI，從 R0 source/plan/style 與 R1 props/receipt 產生可重播的完整候選審核包，可附本地 MP4 |
| backlot/programmatic_review.py | L4 唯讀 list/detail/media API；每次讀取重播 R0/R1 來源驗證、重算 SHA-256、限制檔案大小及路徑 |
| backlot/server.py | 在 FastAPI 主應用直接註冊三個唯讀 GET 端點，執行時才委派 R2 驗證模組；不更改 L3 寫入端點 |
| backlot/ui/agent-review.js | 在現有 L4 工作台下方呈現預覽、clip timeline、逐行來源證據、雜湊與唯讀權限 |
| backlot/ui/agent-review.css | 新增適應不同螢幕的影片審核區 |
| tests/test_evedirector_programmatic_review_r2.py | 來源／計畫／風格／props／receipt／manifest／影片篡改、symlink、跨專案、無 Apply、H.264 及端點驗證 |
| .github/workflows/evedirector-programmatic-r2.yml | GitHub Ubuntu R0/R1/R2 回歸、JS 靜態檢查、真實 Remotion 渲染、封包 staging、L4 TestClient 驗證與工件封裝 |

## 本地使用方式

需要：Python 3.10+、Pillow、PyYAML、FastAPI、watchfiles、uvicorn、FFmpeg／FFprobe，以及 Remotion（R1 工程）。

1. 使用 R1 在 remotion/ 輸出 MP4。務必先執行 R1 source/plan/style verify。
2. 選擇**現存**的 Backlot 專案 ID（以下以 evedirector-drc-search 示意）：

       python scripts/evedirector_review_stage.py stage ^
         --project-id evedirector-drc-search ^
         --candidate-id native_r2_demo ^
         --plan examples/native-video/program.json ^
         --source examples/native-video/source/README.md ^
         --styles-dir styles ^
         --video remotion/out/native-r1.mp4

   Windows PowerShell 使用反引號換行，或把上面命令放成單行；上述 ^ 是 cmd.exe 的續行符。

3. 重新驗證已封存之來源和影片：

       python scripts/evedirector_review_stage.py verify --project-id evedirector-drc-search --candidate-id native_r2_demo

4. 啟動 Backlot：

       python -m backlot serve --port 4750

5. 開啟 http://127.0.0.1:4750/p/evedirector-drc-search/agent-review，往下查看 **Programmatic Video · R2**。

不傳 --video 仍可建立來源與場景證據的唯讀候選；介面會顯示「無已封存影片」，不會偽造影片預覽。

已封存候選存放於 projects/<project-id>/programmatic_candidates/<candidate-id>/，內容為 source.md、plan.json、styles/<style>.yaml、props.json、receipt.json、manifest.json、可選 preview.mp4。候選 ID 為小寫字母起頭的 ASCII slug；目錄不可覆蓋。GitHub CI 輸出的臨時專案與影片**不是本地已部署服務**。

## 唯讀 API

- GET /api/project/<project-id>/programmatic-review
- GET /api/project/<project-id>/programmatic-review/<candidate-id>
- GET /api/project/<project-id>/programmatic-review/<candidate-id>/media

所有 API 都不返回模型原始 prompt／response。來源節錄僅展示被 Scene Program 指定的那一行（最多 500 字元），透過瀏覽器文字節點呈現；無 eval 或富文字注入。media 的 MP4 以 Content-Type video/mp4、no-store 和 nosniff 傳送。

不存在任何 /programmatic-review/.../apply、validate、reject 路由。即使 BACKLOT_ENABLE_AGENT_ACTIONS=1，也只會影響**原 L3** 的指定寫入流程，不會賦予 R2 候選 canonical 寫入權。

## 驗證語義與限制

1. **來源重播**：R0 再次檢查 source_contains、來源行號、場景時間、各個幾何與動畫欄位；R1 重新產生 props 和 receipt，完整逐位元組比對 canonical JSON。
2. **封包一致性**：重算來源、計畫、風格、props、receipt 的雜湊。任何受保護資料被改動且不一致，API 回傳 409、前端標示 integrity_failed，禁止播放。
3. **影片一致性邊界**：staging 當下 FFprobe 檢查 H.264、解析度、fps、幀數，讀取當下再比對 MP4 的 SHA-256。這只證明封存影片與 manifest 一致，**不證明每一畫素確實來自 Scene Program**。測試特別使用合法規格的黑畫面驗證不得冒充視覺等價。
4. **不具外部真實性背書**：來源與其複製品被同時換掉並重新封存，仍可能形成新的自洽候選；沒有外部簽章、原始作者身份或審核者批准證據。UI 明示 source_approval_verified=false、preview_matches_program_verified=false。
5. **本機安全界線**：拒絕路徑穿越、symlink、過大輸入、重複 JSON key、Nan、跨專案候選讀取及不存在的候選；本輪未支援多使用者外網部署，不應公開綁定監聽。

R2 是可用於**本地人工觀看與追溯的隔離橋接版本**，但尚未等同 R0/R1/R2 Merge、跨 OS 正式驗收、L0–L6 整合寫入或 Publication Hub 發行。未執行正式的人為核准流程時，不得把本包視為可發行影片。

## 正式驗收門檻

- R0/R1/R2 精確 GitHub head 的 CI 狀態為 success；
- L4 原有測試通過，不影響 L3 Apply / Reject；
- 真實 Remotion 渲染 MP4 成功 stage，L4 Detail + media 可讀；
- 攻擊性測試與 JS syntax check 通過；
- 人工確認候選影片是預覽，不得與 Approved Release 混淆。
