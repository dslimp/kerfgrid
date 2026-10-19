#!/usr/bin/env bash
set -euo pipefail

url="${PLASMA_CAM_URL:-http://127.0.0.1:8765/}"
if command -v playwright-cli >/dev/null 2>&1; then
  default_pwcli="$(command -v playwright-cli)"
else
  default_pwcli="${HOME}/.codex/skills/playwright/scripts/playwright_cli.sh"
fi
pwcli="${PWCLI:-${default_pwcli}}"
screenshot_path="${PLASMA_CAM_VISUAL_SMOKE_SCREENSHOT:-output/playwright/visual-smoke-latest.png}"

test -x "${pwcli}"
mkdir -p "$(dirname "${screenshot_path}")"

pw() {
  local output
  local status
  if [[ "${pwcli}" == *playwright_cli.sh ]]; then
    output="$("${pwcli}" "$@" 2>&1)" || status=$?
  else
    local args=()
    local arg
    for arg in "$@"; do
      if [[ "${arg}" != "--json" ]]; then
        args+=("${arg}")
      fi
    done
    output="$("${pwcli}" "${args[@]}" 2>&1)" || status=$?
  fi
  status="${status:-0}"
  if [[ "${output}" == "### Error"* || "${output}" == *$'\n### Error'* ]]; then
    printf "%s\n" "${output}" >&2
    return 1
  fi
  if [[ "${status}" != "0" ]]; then
    printf "%s\n" "${output}" >&2
    return "${status}"
  fi
  printf "%s" "${output}"
  return "${status}"
}

pw --json open "${url}" >/dev/null

seed_closed_path='async () => {
  const storageKey = "kerfgrid.project.v1";
  const project = {
    format: "kerfgrid-project",
    format_version: 1,
    name: "closed_path_visual_regression",
    sheet: { width_mm: 200, height_mm: 120, margin_mm: 10 },
    spacing_mm: 8,
    parts: [{
      name: "closed_square",
      quantity: 1,
      contours: [{
        type: "path",
        kind: "outer",
        name: "closed_square_outer",
        open: false,
        segments: [
          { type: "line", start: { x: -40, y: -30 }, end: { x: 40, y: -30 } },
          { type: "line", start: { x: 40, y: -30 }, end: { x: 40, y: 30 } },
          { type: "line", start: { x: 40, y: 30 }, end: { x: -40, y: 30 } },
          { type: "line", start: { x: -40, y: 30 }, end: { x: -40, y: -30 } }
        ]
      }]
    }],
    placements: [{ part_name: "closed_square", instance: 1, dx: 100, dy: 60, rotation_deg: 0 }],
    cut: { material: "mild_steel", thickness_mm: 3, nozzle_mm: 0.9, feed_rate_mode: "auto", manual_feed_rate_mm_min: 1300 },
    post: { kerf_offset_fallback: "centerline", open_path_mode: "centerline" },
    nesting: {},
    simulation: {},
    ui: {},
    import_options: {},
    zones: [],
    tabs: [],
    lead_overrides: []
  };
  const snapshot = await (await fetch("/api/workspace")).json();
  const saved = await fetch("/api/workspace", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: snapshot.revision, project })
  });
  if (!saved.ok) throw new Error(await saved.text());
  window.location.reload();
  return true;
}'

check_closed_path_fill='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = await predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(() => {
    const raw = localStorage.getItem("kerfgrid.project.v1");
    if (!raw) return false;
    const project = JSON.parse(raw);
    return project.name === "closed_path_visual_regression" &&
      Array.isArray(project.placements) &&
      project.placements.length === 1;
  }, "closed path project");
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const canvas = document.getElementById("sheetCanvas");
  const rect = canvas.getBoundingClientRect();
  const ratio = canvas.width / rect.width;
  const pad = 42;
  const scale = Math.max(0.01, Math.min((rect.width - pad * 2) / 200, (rect.height - pad * 2) / 120));
  const originX = (rect.width - 200 * scale) / 2;
  const originY = (rect.height - 120 * scale) / 2 + 120 * scale;
  const x = Math.round((originX + 85 * scale) * ratio);
  const y = Math.round((originY - 65 * scale) * ratio);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  const image = context.getImageData(x - 10, y - 10, 21, 21).data;
  let filledPixels = 0;
  for (let index = 0; index < image.length; index += 4) {
    const r = image[index];
    const g = image[index + 1];
    const b = image[index + 2];
    if (r < 247 || g < 247 || b < 247) filledPixels += 1;
  }
  if (filledPixels < 260) {
    throw new Error(`Closed path did not render filled; filledPixels=${filledPixels}`);
  }
  return { status: "closed-path-fill", filledPixels };
}'

reset_after_closed_path='async () => {
  const snapshot = await (await fetch("/api/workspace")).json();
  const project = await (await fetch("/api/example")).json();
  const saved = await fetch("/api/workspace", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: snapshot.revision, project })
  });
  if (!saved.ok) throw new Error(await saved.text());
  window.location.reload();
  return true;
}'

pw --json eval "${seed_closed_path}" >/dev/null
pw --json eval "${check_closed_path_fill}" >/dev/null
pw --json eval "${reset_after_closed_path}" >/dev/null

seed_review_only_project='async () => {
  const storageKey = "kerfgrid.project.v1";
  const project = {
    format: "kerfgrid-project",
    format_version: 1,
    name: "review_only_visual_regression",
    sheet: { width_mm: 200, height_mm: 120, margin_mm: 10 },
    spacing_mm: 8,
    parts: [
      {
        name: "review_open",
        quantity: 1,
        review_only: true,
        contours: [{
          type: "path",
          kind: "outer",
          name: "review_open_outer",
          source: "dxf_review_open",
          open: true,
          segments: [
            { type: "line", start: { x: -45, y: 0 }, end: { x: 45, y: 0 } }
          ]
        }]
      },
      {
        name: "closed_square",
        quantity: 1,
        contours: [{
          type: "path",
          kind: "outer",
          name: "closed_square_outer",
          open: false,
          segments: [
            { type: "line", start: { x: -25, y: -25 }, end: { x: 25, y: -25 } },
            { type: "line", start: { x: 25, y: -25 }, end: { x: 25, y: 25 } },
            { type: "line", start: { x: 25, y: 25 }, end: { x: -25, y: 25 } },
            { type: "line", start: { x: -25, y: 25 }, end: { x: -25, y: -25 } }
          ]
        }]
      }
    ],
    placements: [],
    cut: { material: "mild_steel", thickness_mm: 3, nozzle_mm: 0.9, feed_rate_mode: "auto", manual_feed_rate_mm_min: 1300 },
    post: { kerf_offset_fallback: "centerline", open_path_mode: "block" },
    nesting: {},
    simulation: {},
    ui: {},
    import_options: {},
    zones: [],
    tabs: [],
    lead_overrides: []
  };
  const snapshot = await (await fetch("/api/workspace")).json();
  const saved = await fetch("/api/workspace", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: snapshot.revision, project })
  });
  if (!saved.ok) throw new Error(await saved.text());
  window.location.reload();
  return true;
}'

check_review_only_visible_nonproduction='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = await predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(() => {
    const raw = localStorage.getItem("kerfgrid.project.v1");
    if (!raw) return false;
    const project = JSON.parse(raw);
    return project.name === "review_only_visual_regression" &&
      Array.isArray(project.placements) &&
      project.placements.some((placement) => placement.part_name === "review_open") &&
      project.placements.some((placement) => placement.part_name === "closed_square");
  }, "review-only project");
  await waitFor(() => {
    const selectedInfo = document.getElementById("selectedInfo");
    return selectedInfo && selectedInfo.textContent.includes("review_open_1");
  }, "review-only selection");
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const canvas = document.getElementById("sheetCanvas");
  const rect = canvas.getBoundingClientRect();
  const ratio = canvas.width / rect.width;
  const pad = 42;
  const scale = Math.max(0.01, Math.min((rect.width - pad * 2) / 200, (rect.height - pad * 2) / 120));
  const originX = (rect.width - 200 * scale) / 2;
  const originY = (rect.height - 120 * scale) / 2 + 120 * scale;
  const current = JSON.parse(localStorage.getItem("kerfgrid.project.v1"));
  const placement = current.placements.find(item => item.part_name === "review_open");
  const sampleX = Math.round((originX + (placement.dx - 20) * scale) * ratio);
  const sampleY = Math.round((originY - placement.dy * scale) * ratio);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  const image = context.getImageData(sampleX - 60, sampleY - 4, 121, 9).data;
  let contourPixels = 0;
  let redDiagnosticPixels = 0;
  for (let index = 0; index < image.length; index += 4) {
    const r = image[index];
    const g = image[index + 1];
    const b = image[index + 2];
    const a = image[index + 3];
    if (a > 0 && g > 90 && r < 130 && b < 210) contourPixels += 1;
    if (a > 0 && r > 170 && g < 130 && b < 130) redDiagnosticPixels += 1;
  }
  if (contourPixels < 20) {
    throw new Error(`Review-only contour did not render as normal contour; contourPixels=${contourPixels}`);
  }
  if (redDiagnosticPixels > 4) {
    throw new Error(`Review-only contour still renders as red diagnostic geometry; redDiagnosticPixels=${redDiagnosticPixels}`);
  }
  return { status: "review-only-visible-nonproduction", contourPixels, redDiagnosticPixels };
}'

pw --json eval "${seed_review_only_project}" >/dev/null
pw --json eval "${check_review_only_visible_nonproduction}" >/dev/null
pw --json eval "${reset_after_closed_path}" >/dev/null

wait_visual='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = await predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };

  await waitFor(
    () => document.querySelector("#sheetCanvas") && document.querySelector("#partsTable"),
    "app shell"
  );
  document.getElementById("loadExampleBtn").click();

  const state = await waitFor(
    () => {
      const raw = localStorage.getItem("kerfgrid.project.v1");
      if (!raw) return null;
      const project = JSON.parse(raw);
      return Array.isArray(project.placements) && project.placements.length ? project : null;
    },
    "demo project"
  );

  await waitFor(() => {
    const selectedInfo = document.getElementById("selectedInfo");
    return selectedInfo && selectedInfo.textContent.includes("X 250.0 mm");
  }, "selected demo placement");

  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

  const canvas = document.getElementById("sheetCanvas");
  const canvasRect = canvas.getBoundingClientRect();
  if (canvasRect.width < 600 || canvasRect.height < 360) {
    throw new Error(`Canvas unexpectedly small: ${canvasRect.width}x${canvasRect.height}`);
  }

  const context = canvas.getContext("2d", { willReadFrequently: true });
  const sampleWidth = Math.min(canvas.width, 600);
  const sampleHeight = Math.min(canvas.height, 360);
  const image = context.getImageData(0, 0, sampleWidth, sampleHeight).data;
  let nonWhite = 0;
  let strong = 0;
  for (let index = 0; index < image.length; index += 4) {
    const r = image[index];
    const g = image[index + 1];
    const b = image[index + 2];
    const a = image[index + 3];
    if (a > 0 && (r < 248 || g < 248 || b < 248)) nonWhite += 1;
    if (a > 0 && (r < 180 || g < 180 || b < 180)) strong += 1;
  }
  if (nonWhite < 5000 || strong < 200) {
    throw new Error(`Canvas looks blank: nonWhite=${nonWhite}, strong=${strong}`);
  }

  const toolbar = document.querySelector(".view-toolbar");
  const toolbarRect = toolbar.getBoundingClientRect();
  if (toolbarRect.width <= 0 || toolbarRect.height <= 0) {
    throw new Error("View toolbar is not visible");
  }

  const undo = document.getElementById("undoBtn");
  const redo = document.getElementById("redoBtn");
  if (!undo || !redo) throw new Error("Undo/redo buttons missing");
  if (!undo.disabled || !redo.disabled) throw new Error("Undo/redo should be disabled on freshly loaded demo");
  const primaryToolbarIds = [
    "toolbarImportBtn",
    "toolbarOpenProjectBtn",
    "toolbarSaveProjectBtn",
    "toolbarAutoNestBtn",
    "toolbarValidateBtn",
    "toolbarExportBtn",
    "toolbarOutlineBtn",
    "toolbarSimBtn",
    "toolbarReportBtn",
  ];
  for (const id of primaryToolbarIds) {
    const button = document.getElementById(id);
    if (!button) throw new Error(`Primary toolbar button missing: ${id}`);
    if (!button.querySelector("svg")) throw new Error(`Primary toolbar button has no icon: ${id}`);
    const rect = button.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) throw new Error(`Primary toolbar button is too small: ${id}`);
  }

  const partsRows = document.querySelectorAll("#partsTable tbody tr");
  if (!partsRows.length || !partsRows[0].textContent.includes("disk")) {
    throw new Error("Parts table did not render demo part");
  }

  const sidebar = document.querySelector(".sidebar");
  const workspace = document.querySelector(".workspace");
  const sidebarRect = sidebar.getBoundingClientRect();
  const workspaceRect = workspace.getBoundingClientRect();
  if (sidebarRect.right > workspaceRect.left + 1) {
    throw new Error(`Sidebar overlaps workspace: ${sidebarRect.right} > ${workspaceRect.left}`);
  }

  return {
    status: "visual-smoke",
    canvas: { width: Math.round(canvasRect.width), height: Math.round(canvasRect.height) },
    placements: state.placements.length,
    nonWhite,
    strong
  };
}'

pw --json eval "${wait_visual}" >/dev/null
pw --json screenshot --filename "${screenshot_path}" --full-page
