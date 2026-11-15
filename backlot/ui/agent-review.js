import { el, fmtDuration, getJSON, subscribe } from "/ui/lib.js";

const suffix = "/agent-review";
const encodedProject = location.pathname.startsWith("/p/") && location.pathname.endsWith(suffix)
  ? location.pathname.slice(3, -suffix.length)
  : "";
const projectId = decodeURIComponent(encodedProject);
const encodedProjectId = encodeURIComponent(projectId);
const app = document.getElementById("app");
const REVIEWER_KEY = "evedirector.reviewer";

let indexState = null;
let detailState = null;
let selectedRun = null;
let loading = true;
let errorText = "";

// R2 is a separate read-only evidence/preview channel, NOT an L3 agent run.
let programIndexState = null;
let programDetailState = null;
let selectedProgram = null;
let programErrorText = "";

function textValue(value) {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function statusClass(status) {
  return `status ${String(status || "unknown").replaceAll(" ", "_")}`;
}

function metric(label, value) {
  return el("div", { class: "metric" }, el("span", {}, label), el("b", {}, value ?? "—"));
}

async function loadIndex({ keepSelection = true } = {}) {
  indexState = await getJSON(`/api/project/${encodedProjectId}/agent-review`);
  const ids = new Set((indexState.runs || []).map((run) => run.run_id));
  if (!keepSelection || !selectedRun || !ids.has(selectedRun)) {
    selectedRun = (indexState.runs || [])[0]?.run_id || null;
  }
  if (selectedRun) {
    detailState = await getJSON(`/api/project/${encodedProjectId}/agent-review/${encodeURIComponent(selectedRun)}`);
  } else {
    detailState = null;
  }

  // Optional R2 channel must never suppress a working L3/L4 review.
  programErrorText = "";
  try {
    programIndexState = await getJSON(`/api/project/${encodedProjectId}/programmatic-review`);
    const candidates = programIndexState.candidates || [];
    const ids = new Set(candidates.filter((c) => c.status !== "integrity_failed").map((c) => c.candidate_id));
    if (!keepSelection || !selectedProgram || !ids.has(selectedProgram)) {
      selectedProgram = candidates.find((c) => ids.has(c.candidate_id))?.candidate_id || null;
    }
    programDetailState = selectedProgram
      ? await getJSON(`/api/project/${encodedProjectId}/programmatic-review/${encodeURIComponent(selectedProgram)}`)
      : null;
  } catch (error) {
    programErrorText = error.message || String(error);
    programDetailState = null;
  }
}

async function refresh(options) {
  loading = true;
  errorText = "";
  render();
  try {
    await loadIndex(options);
  } catch (error) {
    errorText = error.message || String(error);
  } finally {
    loading = false;
    render();
  }
}

async function chooseRun(runId) {
  selectedRun = runId;
  loading = true;
  errorText = "";
  render();
  try {
    detailState = await getJSON(`/api/project/${encodedProjectId}/agent-review/${encodeURIComponent(runId)}`);
  } catch (error) {
    errorText = error.message || String(error);
  } finally {
    loading = false;
    render();
  }
}

function renderTopbar() {
  const enabled = Boolean(indexState?.actions_enabled);
  return el("header", { class: "topbar" },
    el("div", { class: "brand" },
      el("div", { class: "brand-mark", "aria-hidden": "true" }, "E"),
      el("div", {},
        el("h1", {}, "EveDirector Review"),
        el("p", {}, projectId || "Unknown project"),
      ),
    ),
    el("div", { class: "spacer" }),
    el("span", { class: `pill ${enabled ? "enabled" : "locked"}` },
      enabled ? "ACTIONS ENABLED" : "READ-ONLY"),
    el("a", { class: "back-link", href: `/p/${encodedProjectId}` }, "← Backlot Board"),
  );
}

function renderRuns() {
  const runs = indexState?.runs || [];
  return el("aside", { class: "panel" },
    el("div", { class: "panel-head" },
      el("h2", {}, "Proposal Runs"),
      el("span", { class: "pill" }, String(runs.length))),
    el("div", { class: "panel-body run-list" },
      runs.length ? runs.map((run) => el("button", {
        type: "button",
        class: `run-card${run.run_id === selectedRun ? " active" : ""}`,
        onclick: () => chooseRun(run.run_id),
      },
        el("span", { class: statusClass(run.status) }, run.status),
        el("b", { title: run.run_id }, run.run_id),
        el("small", {}, `${run.semantic_change_count ?? 0} changes · ${run.source_anchor_count ?? 0} anchors`),
        el("small", {}, run.model ? `${run.provider || "model"} · ${run.model}` : (run.provider || "unknown provider")),
      )) : el("div", { class: "empty" }, "No local-agent proposal runs were found."),
    ),
  );
}

function renderGraph(detail) {
  const graph = detail.graph || { nodes: [] };
  const nodes = new Map((graph.nodes || []).map((node) => [node.id, node]));
  const order = ["source", "canonical", "candidate", "validation", "gate"];
  const main = order.map((id) => nodes.get(id)).filter(Boolean);
  const scenes = (detail.candidate?.scenes || []);
  return el("div", {},
    el("div", { class: "graph" },
      el("div", { class: "graph-row" }, main.map((node) => el("div", { class: "graph-node" },
        el("span", { class: "kind" }, node.type),
        el("strong", {}, node.label),
        el("em", {}, node.status || "unknown"),
      ))),
    ),
    el("div", { class: "scene-grid" }, scenes.map((scene) => el("div", {
      class: `scene-node${scene.changed ? " changed" : ""}`,
      title: scene.source_contains || "",
    },
      el("b", {}, scene.title || scene.id),
      el("small", {}, `${fmtDuration(scene.in_seconds)} – ${fmtDuration(scene.out_seconds)} · ${scene.type || "scene"}`),
      el("small", {}, scene.changed ? "SEMANTIC CHANGE" : "SOURCE GROUNDED"),
    ))),
  );
}

function renderChanges(changes) {
  if (!changes.length) return el("div", { class: "empty" }, "No semantic changes.");
  return changes.map((change) => el("article", { class: "change" },
    el("code", {}, change.path),
    el("div", { class: "change-grid" },
      el("pre", {}, `BEFORE\n${textValue(change.before)}`),
      el("pre", {}, `AFTER\n${textValue(change.after)}`),
    ),
  ));
}

function renderAnchors(anchors) {
  if (!anchors.length) return el("div", { class: "empty" }, "No source anchors were reported.");
  return anchors.map((anchor) => el("article", { class: "anchor" },
    el("b", {}, `${anchor.scene_id} · lines ${anchor.line_start}–${anchor.line_end}`),
    el("p", {}, anchor.excerpt || anchor.query || ""),
  ));
}

function renderCenter(detail) {
  const run = detail.run || {};
  return el("main", { class: "panel" },
    el("section", { class: "hero" },
      el("span", { class: statusClass(run.status) }, run.status),
      el("h2", {}, detail.candidate?.title || "Candidate specification"),
      el("p", {}, run.instruction || "Local-agent proposal awaiting review."),
      el("div", { class: "metrics" },
        metric("Semantic changes", run.semantic_change_count ?? detail.semanticChanges?.length ?? 0),
        metric("Source anchors", run.source_anchor_count ?? detail.source?.anchors?.length ?? 0),
        metric("Scenes", detail.candidate?.scene_count),
        metric("Timeline", fmtDuration(detail.candidate?.timeline_seconds)),
      ),
    ),
    renderGraph(detail),
    el("section", { class: "section" },
      el("h3", {}, "Semantic Diff"),
      ...renderChanges(detail.semanticChanges || []),
    ),
  );
}

async function postAction(action, runId, reviewer, reason = "") {
  const verb = action.toUpperCase();
  const confirmation = `${verb} ${runId}`;
  const label = action === "apply"
    ? "Apply this candidate to the canonical video specification?"
    : action === "reject"
      ? "Reject this candidate without modifying the canonical specification?"
      : "Revalidate this candidate against the current source and policy?";
  if (!window.confirm(`${label}\n\nConfirmation: ${confirmation}`)) return;

  errorText = "";
  loading = true;
  render();
  try {
    const response = await fetch(
      `/api/project/${encodedProjectId}/agent-review/${encodeURIComponent(runId)}/${action}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-EveDirector-Action": "review",
        },
        body: JSON.stringify({ reviewer, reason, confirmation }),
      },
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `${response.status} ${action}`);
    detailState = payload;
    await loadIndex({ keepSelection: true });
  } catch (error) {
    errorText = error.message || String(error);
  } finally {
    loading = false;
    render();
  }
}

function renderActions(detail) {
  const enabled = Boolean(detail.actions_enabled);
  const status = detail.run?.status;
  const reviewable = ["awaiting_human", "validated"].includes(status);
  const reviewer = localStorage.getItem(REVIEWER_KEY) || "";
  const reviewerInput = el("input", { value: reviewer, placeholder: "Reviewer name" });
  reviewerInput.addEventListener("input", () => localStorage.setItem(REVIEWER_KEY, reviewerInput.value));
  const reasonInput = el("textarea", { placeholder: "Required when rejecting a candidate" });
  const actionButtons = el("div", { class: "action-row" },
    el("button", {
      type: "button", class: "validate", disabled: !enabled || !reviewable,
      onclick: () => postAction("validate", detail.run.run_id, reviewerInput.value.trim()),
    }, "VALIDATE"),
    el("button", {
      type: "button", class: "apply", disabled: !enabled || !reviewable,
      onclick: () => postAction("apply", detail.run.run_id, reviewerInput.value.trim()),
    }, "APPLY"),
    el("button", {
      type: "button", class: "reject", disabled: !enabled || ["applied", "rejected"].includes(status),
      onclick: () => postAction("reject", detail.run.run_id, reviewerInput.value.trim(), reasonInput.value.trim()),
    }, "REJECT"),
  );
  return el("div", { class: "actions" },
    enabled ? null : el("div", { class: "notice" },
      "Backlot is read-only. Restart it with BACKLOT_ENABLE_AGENT_ACTIONS=1 to enable guarded review actions."),
    el("label", {}, "Reviewer", reviewerInput),
    el("label", {}, "Rejection reason", reasonInput),
    actionButtons,
    el("div", { class: "notice" },
      "Apply and reject still execute the L3 contract. A stale baseline, invalid source anchor, or unsupported field is rejected server-side."),
  );
}

function renderRight(detail) {
  return el("aside", { class: "panel right-panel" },
    el("div", { class: "panel-head" }, el("h2", {}, "Evidence & Authority")),
    el("section", { class: "section" },
      el("h3", {}, "Source Anchors"),
      ...renderAnchors(detail.source?.anchors || []),
    ),
    el("section", { class: "section" },
      el("h3", {}, "Human Gate"),
      renderActions(detail),
    ),
  );
}


async function chooseProgram(candidateId) {
  selectedProgram = candidateId;
  programErrorText = "";
  programDetailState = null;
  render();
  try {
    programDetailState = await getJSON(
      `/api/project/${encodedProjectId}/programmatic-review/${encodeURIComponent(candidateId)}`
    );
  } catch (error) {
    programErrorText = error.message || String(error);
  }
  render();
}

function renderVisualCheck(visual) {
  const check = visual || { status: "NOT_RUN" };
  const measured = Array.isArray(check.frame_checks) ? check.frame_checks : [];
  const failures = measured.filter((row) => row.status !== "PASS");
  const head = el("div", { class: "visual-check-head" },
    el("div", {},
      el("h4", {}, "R3 sampled visual geometry check"),
      el("code", {}, check.status || "NOT_RUN"),
    ),
    el("span", { class: "pill locked" }, "UNSIGNED · NOT APPROVED"),
  );
  if (!measured.length) {
    return el("section", { class: "visual-check" }, head,
      el("p", { class: "programmatic-disclaimer" },
        "No R3 frame measurements staged. Use the offline R3 CLI to verify the candidate."),
    );
  }
  const errors = el("details", { class: "visual-check-detail" },
    el("summary", {}, `Inspect ${measured.length} measured frames · ${failures.length} non-PASS`),
    el("div", { class: "visual-check-rows" }, measured.map((row) =>
      el("div", { class: `visual-check-row ${row.status === "PASS" ? "" : "failed"}` },
        el("b", {}, `#${row.frame} · ${row.clip_id}`),
        el("span", {}, `${row.status} · ${row.geometry_pixels} geometric pixels · ${row.outlier_pixels} outliers · MAE ${row.mean_channel_absolute_error}`),
      ),
    )),
  );
  return el("section", { class: "visual-check" }, head,
    el("div", { class: "programmatic-metrics" },
      metric("Sampled frames", `${check.sampled_frames}/${check.total_frames}`),
      metric("Eligible pixels", check.eligible_pixels),
      metric("Geometry pixels", check.geometry_pixels),
      metric("Bad pixel ratio", `${(check.bad_pixel_fraction * 100).toFixed(2)}%`),
    ),
    el("p", { class: "programmatic-disclaimer" },
      "PASS means only sampled flat-color geometry interiors matched within declared tolerances. " +
      "Text glyphs, edge antialiasing, unsampled frames and audio are NOT verified. " +
      "This is an unsigned local measurement, never an approval or proof of full visual equivalence."),
    errors,
  );
}

function renderTextCheck(check) {
  const value = check || { status: "NOT_RUN" };
  const rows = Array.isArray(value.layer_checks) ? value.layer_checks : [];
  const failed = rows.filter((row) => row.status === "FAIL");
  const unmeasured = rows.filter((row) => row.status === "INCONCLUSIVE");
  const heading = el("div", { class: "visual-check-head" },
    el("div", {}, el("h4", {}, "R4 ASCII text strokes & occlusion"),
      el("code", {}, value.status || "NOT_RUN")),
    el("span", { class: "pill locked" }, "UNSIGNED · NO APPLY"),
  );
  if (!rows.length) {
    return el("section", { class: "visual-check" }, heading,
      el("p", { class: "programmatic-disclaimer" },
        "R4 text check not staged. Missing check is never treated as a PASS."));
  }
  return el("section", { class: "visual-check" }, heading,
    el("div", { class: "programmatic-metrics" },
      metric("Measured frames", `${value.sampled_frames}/${value.total_frames}`),
      metric("Text layers", `${value.covered_text_layers}/${value.declared_text_layers}`),
      metric("Ink probes", value.ink_pixels),
      metric("Outlier ink/blank", value.bad_pixels),
    ),
    el("p", { class: "programmatic-disclaimer" },
      `${value.unmeasured_samples} samples excluded or inconclusive. ` +
      `Opaque occlusion mismatches: ${value.occluded_bad_pixels}/${value.occluded_pixels}. ` +
      "DejaVu Sans ASCII only; text wrapping, CJK, font substitutions, exact glyph identity and audio are not certified. " +
      "Neither R3 nor R4 grants publication authority."),
    el("details", { class: "visual-check-detail" },
      el("summary", {}, `Review ${rows.length} text samples · ${failed.length} FAIL · ${unmeasured.length} unmeasured`),
      el("div", { class: "visual-check-rows" }, rows.map((row) =>
        el("div", { class: `visual-check-row ${row.status === "PASS" ? "" : "failed"}` },
          el("b", {}, `#${row.frame} · ${row.clip_id}/${row.layer_id}`),
          el("span", {}, `${row.status} · ${row.bad_pixels} outliers / ${row.ink_pixels} ink pixels · ` +
            `${row.occluded_bad_pixels} bad occlusions${row.reason ? ` · ${row.reason}` : ""}`),
        ),
      )),
    ),
  );
}

function renderMultilingualCheck(check) {
  const value = check || { status: "NOT_RUN" };
  const rows = Array.isArray(value.checks) ? value.checks : [];
  const font = value.font || {};
  return el("section", { class: "visual-check" },
    el("div", { class: "visual-check-head" },
      el("div", {}, el("h4", {}, "R5 繁體中文／多語字形與字型契約"),
        el("code", {}, value.status || "NOT_RUN")),
      el("span", { class: "pill locked" }, "UNSIGNED · NO APPLY"),
    ),
    el("div", { class: "programmatic-metrics" },
      metric("Sampled frames", value.sampled_frames != null ? `${value.sampled_frames}/${value.total_frames}` : "—"),
      metric("Verified lines", value.covered_text_lines != null ? `${value.covered_text_lines}/${value.declared_text_lines}` : "—"),
      metric("Failures", value.failed_samples ?? "—"),
      metric("Inconclusive", value.unmeasured_samples ?? "—"),
    ),
    el("p", { class: "programmatic-disclaimer" },
      `Font: ${font.family || "not measured"} · SHA-256: ${font.sha256 || "unavailable"}. ` +
      "Only high-contrast, locally sampled glyph evidence is checked. This is NOT OCR, " +
      "a semantic/complete typography proof, or permission to publish."),
    rows.length ? el("details", { class: "visual-check-detail" },
      el("summary", {}, `Inspect ${rows.length} line measurements`),
      el("div", { class: "visual-check-rows" },
        rows.filter((r) => r.status !== "PASS").slice(0, 80).map((r) =>
          el("div", { class: `visual-check-row ${r.status === "PASS" ? "" : "failed"}` },
            el("b", {}, `#${r.frame} · ${r.clip_id}/${r.layer_id} · line ${r.line+1}`),
            el("span", {}, `${r.status}: ${r.reason || ""} · ink ${r.ink_ratio ?? "—"} · blank ${r.blank_ratio ?? "—"}`),
          ),
        ),
      ),
    ) : el("p", { class: "programmatic-disclaimer" },
      "No R5 report is staged; NOT_RUN is never a PASS."),
  );
}

function renderLayoutCheck(check) {
  const v = check || { status: "NOT_RUN" };
  const rows = Array.isArray(v.lines) ? v.lines : [];
  const area = v.safe_area || {};
  const font = v.font || {};
  return el("section", { class: "visual-check" },
    el("div", { class: "visual-check-head" },
      el("div", {}, el("h4", {}, "R6 安全字幕區／確定性換行／字型指紋"),
        el("code", {}, v.status || "NOT_RUN")),
      el("span", { class: "pill locked" }, "LAYOUT ONLY · NO APPLY"),
    ),
    el("div", { class: "programmatic-metrics" },
      metric("Lines", v.line_count ?? "—"),
      metric("Left / Right", area.left == null ? "—" : `${area.left} / ${area.right} px`),
      metric("Top / Bottom", area.top == null ? "—" : `${area.top} / ${area.bottom} px`),
      metric("Font", font.profile || "NOT PINNED"),
    ),
    el("p", { class: "programmatic-disclaimer" },
      `Font fingerprint: ${font.sha256 || "unavailable"}. ` +
      "A layout PASS certifies only pinned local metrics, explicit line placement and source-grounded text. " +
      "R5 separately checks sampled video glyphs. Neither grants pixel-equivalence or publish approval."),
    rows.length ? el("details", { class: "visual-check-detail" },
      el("summary", {}, `Inspect ${rows.length} compiled source-grounded subtitle lines`),
      el("div", { class: "visual-check-rows" }, rows.map((line) =>
        el("div", { class: "visual-check-row" },
          el("b", {}, `${line.scene_id} / ${line.layer_id} (${line.x}, ${line.y})`),
          el("span", {}, `${line.text} · ${line.width_px} px · ${line.placement}`),
        ),
      )),
    ) : el("p", { class: "programmatic-disclaimer" },
      "No R6 layout report staged. NOT_RUN must never be treated as a PASS."),
  );
}

function renderProgramDetail(detail) {
  const timing = detail.timing || {};
  const preview = detail.preview || {};
  const digest = detail.digests || {};
  const authority = detail.authority || {};
  const player = preview.available && preview.media_url
    ? el("video", {
      class: "programmatic-player",
      controls: "",
      playsinline: "",
      preload: "metadata",
      src: preview.media_url,
    })
    : el("div", { class: "notice" },
      "No verified local MP4 was staged. Source evidence is still available.");
  return el("div", { class: "programmatic-detail" },
    el("div", { class: "programmatic-title" },
      el("div", {},
        el("h3", {}, detail.title || "Programmatic candidate"),
        el("small", {}, detail.candidate_id || ""),
      ),
      el("span", { class: "pill locked" }, "PREVIEW ONLY · NO APPLY"),
    ),
    el("p", { class: "programmatic-disclaimer" },
      "R0/R1 data replay checked. Source authenticity, visual equivalence, copyright and publishing approval are NOT attested. Existing L3 review actions do not apply to these clips."),
    player,
    renderVisualCheck(detail.visual_check),
    renderTextCheck(detail.text_check),
    renderMultilingualCheck(detail.multilingual_check),
    renderLayoutCheck(detail.layout_check),
    el("div", { class: "programmatic-metrics" },
      metric("Clips", (detail.scenes || []).length),
      metric("FPS", timing.fps),
      metric("Frames", timing.frames),
      metric("Seconds", timing.seconds?.toFixed(2) ?? "—"),
    ),
    el("div", { class: "programmatic-evidence" },
      el("h4", {}, "Source-grounded timeline and evidence"),
      ...(detail.scenes || []).map((scene) => el("article", { class: "programmatic-scene" },
        el("b", {}, `${scene.id} · frame ${scene.from}–${scene.from + scene.durationInFrames - 1}`),
        el("small", {}, `${scene.layers} layers · ${scene.duration_seconds.toFixed(2)}s · source line ${scene.source?.line_start ?? "?"}`),
        el("p", {}, scene.source?.excerpt || scene.source?.source_contains || "—"),
        el("code", {}, `line sha256: ${scene.source?.logical_line_sha256 || "—"}`),
      )),
      el("h4", {}, "Verifiable bundle hashes"),
      ...Object.entries(digest).map(([key, value]) =>
        el("div", { class: "programmatic-hash" },
          el("b", {}, key), el("code", {}, value))),
      el("p", { class: "programmatic-disclaimer" },
        `Authority: ${authority.mode || "read_only"} · canonical write: ${authority.canonical_spec_mutated === false ? "NO" : "UNVERIFIED"} · preview/program equivalence: NOT ATTESTED`),
    ),
  );
}

function renderProgrammatic() {
  const candidates = programIndexState?.candidates || [];
  return el("section", { class: "panel programmatic-panel" },
    el("div", { class: "panel-head" },
      el("h2", {}, "Programmatic Video · R2/R3"),
      el("span", { class: "pill locked" }, "READ-ONLY PREVIEW")),
    programErrorText ? el("div", { class: "error" }, programErrorText) : null,
    el("div", { class: "programmatic-workspace" },
      el("aside", { class: "programmatic-list" },
        candidates.length
          ? candidates.map((item) => el("button", {
              type: "button",
              class: `run-card${item.candidate_id === selectedProgram ? " active" : ""}`,
              disabled: item.status === "integrity_failed",
              onclick: () => chooseProgram(item.candidate_id),
            },
            el("span", { class: statusClass(item.status) }, item.status),
            el("b", {}, item.candidate_id),
            el("small", {}, item.status === "integrity_failed"
              ? "Failed integrity check; not reviewable"
              : `${item.scene_count} scenes · ${item.frames} frames · ${item.preview_available ? "MP4" : "evidence only"}`),
          ))
          : el("div", { class: "empty" }, "No staged programmatic candidates in this project."),
      ),
      programDetailState
        ? renderProgramDetail(programDetailState)
        : el("div", { class: "empty" }, "Select a source-verified programmatic preview. No candidate can Apply a canonical L3 specification."),
    ),
  );
}

function render() {
  app.innerHTML = "";
  app.append(renderTopbar());
  if (errorText) app.append(el("div", { class: "error" }, errorText));
  if (loading && !indexState) {
    app.append(el("div", { class: "panel empty", style: "margin-top:16px" }, "Loading proposal graph…"));
    return;
  }
  const center = detailState
    ? renderCenter(detailState)
    : el("main", { class: "panel empty" }, "Select or create a local-agent proposal run.");
  const right = detailState
    ? renderRight(detailState)
    : el("aside", { class: "panel right-panel empty" }, "No review detail available.");
  app.append(el("div", { class: "workspace" }, renderRuns(), center, right));
  app.append(renderProgrammatic());
}

refresh({ keepSelection: false });
subscribe(`/api/project/${encodedProjectId}/events`, () => refresh({ keepSelection: true }));
