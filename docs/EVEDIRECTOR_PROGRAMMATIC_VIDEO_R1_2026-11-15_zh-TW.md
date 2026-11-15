# EveDirector — 程式影片 R1：GitHub Remotion 橋接整合候選

**日期：** 2026-11-15
**狀態：** GitHub R1 Draft PR；不可等同於合併、發行、L0–L6 驗收或人工批准。
**基線：** R0 Draft PR #12；本 PR 以 R0 工作分支為 base，避免污染 main。

## 設計立場

AI 不輸出任意可執行程式或未驗證資產，而是輸出 R0 嚴格型別化 Scene Program。R1 讀取已核對的來源文件、計畫 JSON 和本地 style YAML，建立可供 Remotion 消費的**候選 Clip Bundle**。

流程：

    原始來源 + Scene Program + Palette
      -> R0 validate
      -> R1 Python build_props / receipt
      -> R1 Python verify (每次 render 前重播來源)
      -> TypeScript assertSafeBundle + evaluate
      -> Remotion Sequence / Component
      -> 候選 MP4 + FFprobe (CI)
      -> 人工 L4/L5/L6 審核（本輪不自動實作）

## 已建立的程式

- scripts/evedirector_remotion_bridge.py：來源錨定、逐行 SHA-256、clip 起點/長度、全序列重新推導檢查、atomic write、重複 JSON key／NaN／過大文件拒絕。
- scripts/evedirector_r1_vectors.py：由原 R0 插值公式產生測試向量；不由 TypeScript 為自己產生 expected 值。
- remotion/src/SceneProgramCore.ts：白名單、形狀與時間軸約束、有限數值、顏色檢查及分段線性插值。
- remotion/src/SceneProgramVideo.tsx：以 Remotion Sequence 形成片段；只呈現矩形、橢圓、文字；無外部資源存取或 eval。
- tests/test_evedirector_remotion_bridge.py、remotion/tests/test_core.cjs：篡改拒絕、source drift、receipt replay 與 Python/TS 比對。
- .github/workflows/evedirector-programmatic-r1.yml：輸出、重驗、編譯、契約測試、真實 Remotion MP4／ffprobe（視 GitHub Actions 執行情況驗收）。

## 候選資料契約

Schema: evedirector.remotion_clip_bundle.v0.1

Bundle 輸出包含 candidate_only=true、review_required=true、canonical_spec_mutated=false、source_approval_verified=false。每段有明確 id、全域開始影格 from、長度 durationInFrames、來源字串、行號及 UTF-8 邏輯行的 SHA-256。這些記錄只能證明可追溯性，**不能證明來源真實、畫面正確、版權已獲許可或內容可發行**。

Python 端 verify 必須保留原始來源、計畫、風格；TypeScript 端僅能在畫面渲染之前驗證 Bundle 形狀，不可冒充來源驗證或持有 Apply 權限。

## 與既有 EveDirector 的關係

1. 不更動 R0 以外的 canonical Backlot runs 或 L2–L6 權限邊界。
2. 既有 OpenMontage remotion-composer/ 保留；新 remotion/ 是隔離的候選組合測試，尚不是正式統一工作台的寫入後端。
3. 不直接介接 EVOE／ORDR 私有實作，不做 Publication Hub 發行。未取得合約與權限時，只能規劃 read-only adapters。
4. GitHub Actions 的綠燈也不等於 Windows 真機／全專案 L0–L6 的實際回歸，更不等於人工審核通過。
5. R1 ZIP 初版曾在 TSX 內使用未定義的 HEX 常數；GitHub 整合版已改為元件自身安全色碼檢查，另以 npm run typecheck 檢查整體編譯。

## 驗收方法與剩餘邊界

先進行 R0 + R1 Python 回歸；重新產生 props、receipt、175 筆 Python 參考向量；用 Node 編譯的同一套 TS core 核對；再用 Remotion/Chromium 產出候選 H.264 MP4 並由 FFprobe 檢查 fps、長寬、影格數及 codec。所有狀態須以**該次精確 GitHub commit 的 workflow 結果**為準。

R1 未提供配音／音樂／外部圖片授權／任意效果／影片自動發行。L4 人工覆核、L5 derive、L6 的 canonical authority 不可由這個 adapter 越權取得。

**結論：這是 source-grounded AI 原生程式影片的跨後端資料層，尚不是完整影片製作系統，也不是已批准發行的作品。**
