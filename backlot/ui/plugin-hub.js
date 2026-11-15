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
  } catch (e) {
    node.append(el("p", { class: "error" }, `Plugin catalog unavailable: ${e.message || e}`));
  }
}
main();
