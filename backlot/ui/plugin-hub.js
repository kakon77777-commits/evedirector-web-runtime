import { el, getJSON } from "/ui/lib.js";
const node = document.getElementById("app");
const relative = location.pathname.startsWith("/p/") && location.pathname.endsWith("/plugins")
  ? location.pathname.slice(3, -8) : "";
const project = decodeURIComponent(relative);
const projectUrl = encodeURIComponent(project);
const root = "python scripts/evedirector_plugin_hub.py";
const commands = {
  "native-r0": [
    `${root} catalog`,
    `${root} run --request examples/native-video/plugins/native-r0.request.json --input-root examples/native-video --output-root output/plugin-runs`
  ],
  evoe: [
    `${root} doctor --plugin evoe --evoe-root <your-local-EVOE-directory>`,
    `${root} run --request examples/native-video/plugins/evoe-animation.request.json --input-root examples/native-video --output-root output/plugin-runs --evoe-root <your-local-EVOE-directory> --allow-external`
  ],
  ordr: [
    `${root} doctor --plugin ordr`,
    `${root} run --request examples/native-video/plugins/ordr-snapshot.request.json --input-root examples/native-video --output-root output/plugin-runs`
  ]
};
// R10 is a local candidate-only composition recipe, not a browser execution API.
const sceneIR = "python scripts/evedirector_scene_ir_r10.py";
const recipe = [
  "# 1. Native R0 and ORDR: create separate candidate runs with R9 commands above",
  `${root} run --request examples/native-video/plugins/r10-evoe-60.request.json --input-root examples/native-video --output-root output/plugin-runs --evoe-root <your-local-EVOE-directory> --allow-external`,
  `${sceneIR} lock --draft examples/native-video/plugins/r10-composition.draft.json --input-root examples/native-video --runs-root output/plugin-runs --out output/r10.locked.json`,
  `${sceneIR} compose --ir output/r10.locked.json --input-root examples/native-video --runs-root output/plugin-runs --output-root output/compositions`,
  `${sceneIR} verify --candidate-dir output/compositions/r10_native_evoe_ordr_composite --input-root examples/native-video --runs-root output/plugin-runs`
];
function renderSceneIR() {
  const steps = recipe.map((line) => {
    const code = el("code", {}, line);
    const btn = el("button", { type: "button", onclick: async () => {
      try { await navigator.clipboard.writeText(line); btn.textContent = "Copied"; }
      catch { btn.textContent = "Copy unavailable"; }
    }}, "Copy");
    return el("div", { class: "command" }, code, btn);
  });
  return el("section", { class: "plugin" },
    el("h2", {}, "R10 · Typed Scene IR / Plugin Composer"),
    el("p", {}, "AI 可指定 Native 基底、EVOE 幾何動畫圖層與 ORDR 唯讀空間證據，再以固定合成器產出候選 MP4。"),
    el("p", { class: "hint" }, "先在受信任的本地端完成 R9 各外掛執行。EVOE 需要獨立安裝及明確授權；ORDR 僅提供證據，不自動繪製 3D。"),
    el("div", { class: "code-list" }, ...steps),
    el("p", { class: "hint" }, "Scene IR 必須鎖定來源與每筆外掛回執。命令僅供複製，不會從瀏覽器觸發執行、Apply 或 Publish。")
  );
}
function panel(plugin) {
  const actions = commands[plugin.plugin_id] || [];
  return el("article", { class: "plugin" },
    el("header", {},
      el("h2", {}, plugin.title),
      el("span", { class: "status" }, plugin.status)),
    el("p", {}, plugin.source),
    el("p", { class: "capability" }, `Capabilities: ${plugin.operations.join(", ")}`),
    el("div", { class: "code-list" }, ...actions.map((line) => {
      const pre = el("code", {}, line);
      const btn = el("button", { type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(line); btn.textContent="Copied"; }
        catch { btn.textContent="Copy unavailable"; }
      }}, "Copy");
      return el("div", { class: "command" }, pre, btn);
    })),
    el("p", { class: "hint" }, "候選輸出而非已核准作品；禁止遠端執行、直接 Apply 與自動發行。"));
}
async function main() {
  node.replaceChildren(el("header", { class: "hero" },
    el("div", {}, el("h1", {}, "EveDirector · AI Drawing Plugin Hub"),
      el("p", {}, "AI → typed operation → plugin adapter → geometry/frames → candidate video → receipts")),
    el("a", { href: `/p/${projectUrl}/agent-review` }, "← Return to L4 Review")));
  node.append(el("p", { class: "notice" },
    "這裡是唯讀能力目錄。執行外部繪圖引擎必須在已授權的本地端透過 CLI 明確啟動。外部私有專案原始碼不會被複製進 EveDirector。"));
  try {
    const data = await getJSON("/api/evedirector/plugins");
    if (data.runtime_execution_allowed_by_api !== false || !Array.isArray(data.plugins)) {
      throw new Error("Unrecognized capability registry");
    }
    node.append(el("div", { class: "plugins" }, ...data.plugins.map(panel)));
    node.append(renderSceneIR());
  } catch (e) {
    node.append(el("p", { class: "error" }, `Plugin catalog unavailable: ${e.message || e}`));
  }
}
main();
