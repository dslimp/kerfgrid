#!/usr/bin/env bash
set -euo pipefail

url="${PLASMA_CAM_URL:-http://127.0.0.1:8765/}"
if command -v playwright-cli >/dev/null 2>&1; then
  default_pwcli="$(command -v playwright-cli)"
else
  default_pwcli="${HOME}/.codex/skills/playwright/scripts/playwright_cli.sh"
fi
pwcli="${PWCLI:-${default_pwcli}}"

test -x "${pwcli}"

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
    if [[ "${args[0]:-}" == "click" && "${args[1]:-}" == \#* ]]; then
      local selector="${args[1]}"
      args=(eval "async () => { const started = Date.now(); let node = null; while (Date.now() - started < 10000) { node = document.querySelector('${selector}'); if (node) break; await new Promise((resolve) => setTimeout(resolve, 100)); } if (!node) throw new Error('Selector not found: ${selector}'); node.click(); return true; }")
    fi
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

wait_demo='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () =>
      Array.isArray(projectState().placements) &&
      projectState().placements.length === 1 &&
      document.getElementById("selectedInfo").textContent.includes("X 250.0 mm"),
    "demo load"
  );
  return { status: "demo", placements: projectState().placements.length };
}'

wait_duplicate='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () =>
      Array.isArray(projectState().placements) &&
      projectState().placements.length === 2 &&
      document.getElementById("issues").textContent.includes("part_collision") &&
      document.getElementById("selectedInfo").textContent.includes("Preview: collision/spacing"),
    "duplicate validation"
  );
  return {
    status: "duplicate",
    placements: projectState().placements.length,
    selectedInfo: document.getElementById("selectedInfo").textContent
  };
}'

wait_drag_part_from_list='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () => Array.isArray(projectState().placements) && projectState().placements.length === 1,
    "drag-drop base"
  );
  const row = document.querySelector("#partsTable tbody tr");
  const canvas = document.getElementById("sheetCanvas");
  if (!row || !canvas) throw new Error("Missing parts row or canvas");
  const transfer = new DataTransfer();
  row.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: transfer }));
  const rect = canvas.getBoundingClientRect();
  const clientX = rect.left + rect.width * 0.75;
  const clientY = rect.top + rect.height * 0.50;
  canvas.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, clientX, clientY, dataTransfer: transfer }));
  canvas.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, clientX, clientY, dataTransfer: transfer }));
  const state = await waitFor(() => {
    const current = projectState();
    const selected = document.getElementById("selectedInfo").textContent;
    if (
      Array.isArray(current.placements) &&
      current.placements.length === 2 &&
      selected.includes("disk_2") &&
      selected.includes("Preview:") === false
    ) {
      return current;
    }
    return null;
  }, "drag-drop placement");
  const placed = state.placements.find((item) => item.part_name === "disk" && item.instance === 2);
  if (!placed) throw new Error("Dropped disk_2 placement missing");
  return {
    status: "drag-drop",
    placements: state.placements.length,
    selectedInfo: document.getElementById("selectedInfo").textContent,
    placement: { dx: placed.dx, dy: placed.dy }
  };
}'

wait_save_project='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(() => document.getElementById("status").textContent === "Project saved", "project save");
  const saved = projectState();
  if (saved.format !== "kerfgrid-project") throw new Error(`Unexpected project format ${saved.format}`);
  if (saved.format_version !== 2) throw new Error(`Unexpected project version ${saved.format_version}`);
  if (document.getElementById("sheetMargin")) throw new Error("Sheet margin control is still present");
  if ("margin_mm" in saved.sheet) throw new Error("Saved project still contains a sheet margin");
  if (!Array.isArray(saved.parts) || !saved.parts.length) throw new Error("Saved project has no parts");
  if (!Array.isArray(saved.placements) || !saved.placements.length) throw new Error("Saved project has no placements");
  return { status: "saved", format: saved.format, version: saved.format_version };
}'

wait_project_file_roundtrip='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 12000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const setInput = (id, value) => {
    const node = document.getElementById(id);
    if (!node) throw new Error(`Missing control ${id}`);
    node.value = String(value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const setChecked = (id, checked) => {
    const node = document.getElementById(id);
    if (!node) throw new Error(`Missing control ${id}`);
    node.checked = checked;
    node.dispatchEvent(new Event("change", { bubbles: true }));
  };

  await waitFor(() => Array.isArray(projectState().placements) && projectState().placements.length === 1, "round-trip base");
  setInput("sheetWidth", 1234);
  setInput("sheetHeight", 678);
  setInput("spacing", 6);
  setInput("thickness", 5);
  setInput("nozzle", 0.9);
  setInput("feedMode", "manual");
  setInput("manualFeed", 777);
  setInput("leadMode", "none");
  setInput("leadLength", 0);
  setInput("leadOutLength", 0);
  setInput("pierceCrater", 0);
  setInput("leadClearance", 0);
  setInput("nestAttempts", 18);
  setInput("nestAngleStep", 15);
  setInput("nestMaxRuntime", 9);
  setInput("cutOrderStrategy", "lower_left");
  setChecked("safeTravel", false);
  setChecked("centerlineFallback", true);
  setChecked("openPathCenterline", true);
  setChecked("importUnsafeEntityWarn", true);
  await waitFor(() => {
    const state = projectState();
    const post = state.post || {};
    return state.sheet &&
      state.sheet.width_mm === 1234 &&
      state.sheet.height_mm === 678 &&
      state.cut &&
      state.cut.feed_rate_mode === "manual" &&
      state.cut.manual_feed_rate_mm_min === 777 &&
      post.kerf_offset_fallback === "centerline" &&
      post.open_path_mode === "centerline" &&
      post.cut_order_strategy === "lower_left" &&
      state.import_options &&
      state.import_options.auto_close_gaps === false &&
      state.import_options.repair_geometry === false &&
      state.import_options.unsafe_entity_policy === "warn";
  }, "round-trip source settings");

  const originalCreateObjectURL = URL.createObjectURL.bind(URL);
  const originalClick = HTMLAnchorElement.prototype.click;
  window.__plasmaCamLastProjectDownload = null;
  URL.createObjectURL = (blob) => {
    if (blob && String(blob.type || "").includes("json")) {
      blob.text().then((text) => { window.__plasmaCamLastProjectDownload = { text, type: blob.type }; });
    }
    return originalCreateObjectURL(blob);
  };
  HTMLAnchorElement.prototype.click = function () {
    if (this.download && this.download.endsWith(".kerfgrid.json")) return;
    return originalClick.call(this);
  };
  document.getElementById("saveProjectBtn").click();
  const captured = await waitFor(
    () => window.__plasmaCamLastProjectDownload && window.__plasmaCamLastProjectDownload.text,
    "captured project download"
  );
  URL.createObjectURL = originalCreateObjectURL;
  HTMLAnchorElement.prototype.click = originalClick;
  const saved = JSON.parse(captured);
  if (saved.format !== "kerfgrid-project" || saved.format_version !== 2 || !saved.saved_at) {
    throw new Error(`Saved project metadata mismatch: ${JSON.stringify({ format: saved.format, version: saved.format_version, saved_at: saved.saved_at })}`);
  }
  const legacy = { ...saved, format_version: 1, sheet: { ...saved.sheet, margin_mm: 99 } };

  document.getElementById("loadExampleBtn").click();
  await waitFor(() => (projectState().sheet || {}).width_mm === 1000, "demo reset before project import");
  document.getElementById("openProjectBtn").click();
  const input = document.getElementById("importFile");
  if (!input.accept.includes(".kerfgrid.json")) {
    throw new Error(`Open Project did not switch file accept: ${input.accept}`);
  }
  const transfer = new DataTransfer();
  transfer.items.add(new File([JSON.stringify(legacy)], "roundtrip.kerfgrid.json", { type: "application/json" }));
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
  await waitFor(() => {
    const state = projectState();
    const post = state.post || {};
    return state.sheet &&
      state.format_version === 2 &&
      !("margin_mm" in state.sheet) &&
      state.sheet.width_mm === 1234 &&
      state.sheet.height_mm === 678 &&
      state.cut &&
      state.cut.thickness_mm === 5 &&
      state.cut.nozzle_mm === 0.9 &&
      state.cut.manual_feed_rate_mm_min === 777 &&
      state.nesting &&
      state.nesting.auto_nest_attempts === 18 &&
      state.nesting.auto_nest_angle_step_deg === 15 &&
      state.nesting.auto_nest_max_runtime_s === 9 &&
      post.kerf_offset_fallback === "centerline" &&
      post.open_path_mode === "centerline" &&
      post.safe_travel === false &&
      state.import_options &&
      state.import_options.unsafe_entity_policy === "warn";
  }, "project JSON import round-trip");
  if (!document.getElementById("status").textContent.includes("Opened roundtrip.kerfgrid.json")) {
    throw new Error(`Open Project status missing: ${document.getElementById("status").textContent}`);
  }
  const restored = projectState();
  const validationResponse = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(restored)
  });
  const validation = await validationResponse.json();
  const blocking = (validation.issues || []).filter((issue) => issue.blocking !== false);
  if (blocking.length) {
    throw new Error(`Round-trip validation blocking issues: ${blocking.map((issue) => issue.code).join(", ")}`);
  }
  const exportResponse = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(restored)
  });
  if (!exportResponse.ok) throw new Error(`Round-trip export failed: ${await exportResponse.text()}`);
  const simulateResponse = await fetch("/api/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(restored)
  });
  if (!simulateResponse.ok) throw new Error(`Round-trip simulation failed: ${await simulateResponse.text()}`);
  const simulation = await simulateResponse.json();
  if (!(simulation.segments || []).some((segment) => segment.type === "cut")) {
    throw new Error("Round-trip simulation produced no cut segments");
  }
  return { status: "project-file-roundtrip", parts: restored.parts.length, placements: restored.placements.length };
}'

wait_manual_ergonomics='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(() => Array.isArray(projectState().placements) && projectState().placements.length === 1, "manual base");
  const snapEnabled = document.getElementById("snapEnabled");
  const snapMm = document.getElementById("snapMm");
  snapEnabled.checked = true;
  snapEnabled.dispatchEvent(new Event("change", { bubbles: true }));
  snapMm.value = "5";
  snapMm.dispatchEvent(new Event("change", { bubbles: true }));
  const allowHoleFiller = document.getElementById("selectedAllowHoleFiller");
  const allowHoleParent = document.getElementById("selectedAllowHoleParent");
  if (allowHoleFiller.disabled || allowHoleParent.disabled) {
    throw new Error("Selected part hole nesting policy controls are disabled");
  }
  allowHoleFiller.checked = false;
  allowHoleFiller.dispatchEvent(new Event("change", { bubbles: true }));
  allowHoleParent.checked = false;
  allowHoleParent.dispatchEvent(new Event("change", { bubbles: true }));
  await waitFor(
    () => {
      const state = projectState();
      return state.manual_controls && state.manual_controls.snap_enabled && state.manual_controls.snap_mm === 5;
    },
    "snap persistence"
  );
  await waitFor(
    () => {
      const state = projectState();
      const part = (state.parts || [])[0] || {};
      return part.allow_hole_filler === false && part.allow_hole_parent === false;
    },
    "part hole nesting policy persistence"
  );
  return { status: "manual-controls" };
}'

wait_import_options_controls='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const unsafeWarn = document.getElementById("importUnsafeEntityWarn");
  if (!unsafeWarn) throw new Error("Import option controls missing");
  unsafeWarn.checked = true;
  unsafeWarn.dispatchEvent(new Event("change", { bubbles: true }));
  await waitFor(
    () => {
      const options = projectState().import_options || {};
      return options.auto_close_gaps === false &&
        options.repair_geometry === false &&
        options.unsafe_entity_policy === "warn";
    },
    "import option persistence"
  );
  return { status: "import-options" };
}'

wait_reimport_update='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 15000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const dxf = [
    "0", "SECTION", "2", "ENTITIES",
    "0", "CIRCLE", "8", "CUT", "10", "0", "20", "0", "30", "0", "40", "40",
    "0", "CIRCLE", "8", "CUT", "10", "0", "20", "0", "30", "0", "40", "10",
    "0", "ENDSEC", "0", "EOF"
  ].join("\n");
  const importFile = async () => {
    const input = document.getElementById("importFile");
    if (!input) throw new Error("Import file input missing");
    const transfer = new DataTransfer();
    transfer.items.add(new File([dxf], "reimport_circle.dxf", { type: "application/dxf" }));
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };
  await importFile();
  await waitFor(
    () => {
      const state = projectState();
      return Array.isArray(state.parts) &&
        state.parts.length === 1 &&
        state.parts[0].source_file === "reimport_circle.dxf" &&
        Array.isArray(state.placements) &&
        state.placements.length === 1;
    },
    "first DXF import"
  );
  document.getElementById("rotateBtn").click();
  document.getElementById("lockBtn").click();
  await waitFor(
    () => {
      const placement = (projectState().placements || [])[0] || {};
      return Math.abs((placement.rotation_deg || 0) - 90) < 0.001 && placement.locked === true;
    },
    "edited imported placement"
  );
  await importFile();
  await waitFor(
    () => {
      const state = projectState();
      const placement = (state.placements || [])[0] || {};
      return state.parts &&
        state.parts.length === 1 &&
        state.parts[0].source_file === "reimport_circle.dxf" &&
        state.parts[0].source_part_name &&
        state.placements.length === 1 &&
        Math.abs((placement.rotation_deg || 0) - 90) < 0.001 &&
        placement.locked === true &&
        document.getElementById("status").textContent.includes("Updated 1");
    },
    "reimport update"
  );
  return { status: "reimport-update", parts: projectState().parts.length, placements: projectState().placements.length };
}'

wait_template_parts='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const setValue = (id, value) => {
    const input = document.getElementById(id);
    if (!input) throw new Error(`Template control missing: ${id}`);
    input.value = String(value);
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };
  setValue("templateOuterDia", 160);
  setValue("templateCenterDia", 40);
  setValue("templateWidth", 220);
  setValue("templateHeight", 120);
  setValue("templateBoltCount", 6);
  setValue("templateBoltCircleDia", 100);
  setValue("templateBoltDia", 10);
  await waitFor(
    () => {
      const defaults = projectState().template_defaults || {};
      return defaults.outer_dia_mm === 160 &&
        defaults.center_hole_dia_mm === 40 &&
        defaults.plate_width_mm === 220 &&
        defaults.plate_height_mm === 120 &&
        defaults.bolt_count === 6 &&
        defaults.bolt_circle_dia_mm === 100 &&
        defaults.bolt_hole_dia_mm === 10;
    },
    "template defaults persistence"
  );
  for (const id of ["templateDiskBtn", "templatePlateBtn", "templateFlangeBtn"]) {
    const button = document.getElementById(id);
    if (!button) throw new Error(`Template button missing: ${id}`);
    button.click();
  }
  await waitFor(
    () => {
      const state = projectState();
      return Array.isArray(state.parts) &&
        state.parts.length === 4 &&
        Array.isArray(state.placements) &&
        state.placements.length === 4 &&
        state.parts.filter((part) => part.import_source === "template").length === 3;
    },
    "template part creation"
  );
  const project = projectState();
  const names = project.parts.map((part) => part.name);
  for (const expected of ["template_disk", "template_plate", "template_flange"]) {
    if (!names.includes(expected)) throw new Error(`Template part missing: ${expected}`);
  }
  const disk = project.parts.find((part) => part.name === "template_disk");
  const plate = project.parts.find((part) => part.name === "template_plate");
  const flange = project.parts.find((part) => part.name === "template_flange");
  if (disk.outer.radius_mm !== 80 || disk.holes[0].radius_mm !== 20) {
    throw new Error(`Disk template dimensions wrong: ${JSON.stringify(disk)}`);
  }
  const plateXs = plate.contours[0].segments.flatMap((segment) => [segment.start.x, segment.end.x]);
  const plateYs = plate.contours[0].segments.flatMap((segment) => [segment.start.y, segment.end.y]);
  if (Math.max(...plateXs) - Math.min(...plateXs) !== 220 || Math.max(...plateYs) - Math.min(...plateYs) !== 120) {
    throw new Error(`Plate template dimensions wrong: ${JSON.stringify(plate.contours[0])}`);
  }
  if (flange.outer.radius_mm !== 80 || flange.holes.length !== 7) {
    throw new Error(`Flange template dimensions wrong: ${JSON.stringify(flange)}`);
  }
  const validationResponse = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project)
  });
  const validation = await validationResponse.json();
  if (validation.error) throw new Error(`Template validation failed: ${validation.error}`);
  const blocking = (validation.issues || []).filter((issue) => issue.blocking !== false);
  if (blocking.length) {
    throw new Error(`Template validation blocking issues: ${blocking.map((issue) => issue.code).join(", ")}`);
  }
  const exportProject = {
    ...project,
    post: {
      ...(project.post || {}),
      lead_in_mode: "none",
      lead_in_mm: 0,
      lead_out_mm: 0,
      pierce_crater_diameter_mm: 0,
      lead_clearance_mm: 0,
      kerf_offset_fallback: "block"
    }
  };
  const exportResponse = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(exportProject)
  });
  if (!exportResponse.ok) throw new Error(`Template export failed: ${await exportResponse.text()}`);
  const exported = await exportResponse.json();
  if (!String(exported.gcode || "").includes("template_plate_outer")) {
    throw new Error("Template G-code missing plate contour");
  }
  return { status: "templates", parts: project.parts.length, placements: project.placements.length };
}'

wait_cut_order_controls='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(() => Array.isArray(projectState().placements) && projectState().placements.length === 1, "cut order base");
  const strategy = document.getElementById("cutOrderStrategy");
  const heatWeight = document.getElementById("heatSpreadWeight");
  const heatLookback = document.getElementById("heatLookback");
  const groups = document.getElementById("cutOrderGroups");
  const avoid = document.getElementById("safeTravel");
  const openPathCenterline = document.getElementById("openPathCenterline");
  if (!strategy || !heatWeight || !heatLookback || !groups || !avoid || !openPathCenterline) {
    throw new Error("Cut order controls missing");
  }
  strategy.value = "heat_spread";
  strategy.dispatchEvent(new Event("change", { bubbles: true }));
  heatWeight.value = "0.75";
  heatWeight.dispatchEvent(new Event("change", { bubbles: true }));
  heatLookback.value = "4";
  heatLookback.dispatchEvent(new Event("change", { bubbles: true }));
  groups.value = "disk_1";
  groups.dispatchEvent(new Event("change", { bubbles: true }));
  avoid.checked = true;
  avoid.dispatchEvent(new Event("change", { bubbles: true }));
  const autoTabs = document.getElementById("autoTabs");
  const autoTabCount = document.getElementById("autoTabCount");
  const autoTabLength = document.getElementById("autoTabLength");
  const autoTabMinDiameter = document.getElementById("autoTabMinDiameter");
  const smallFeatureSource = document.getElementById("smallFeatureSource");
  if (!smallFeatureSource) throw new Error("Small feature source control missing");
  smallFeatureSource.value = "cut_chart";
  smallFeatureSource.dispatchEvent(new Event("change", { bubbles: true }));
  autoTabs.checked = true;
  autoTabs.dispatchEvent(new Event("change", { bubbles: true }));
  autoTabCount.value = "3";
  autoTabCount.dispatchEvent(new Event("change", { bubbles: true }));
  autoTabLength.value = "9";
  autoTabLength.dispatchEvent(new Event("change", { bubbles: true }));
  autoTabMinDiameter.value = "40";
  autoTabMinDiameter.dispatchEvent(new Event("change", { bubbles: true }));
  openPathCenterline.checked = true;
  openPathCenterline.dispatchEvent(new Event("change", { bubbles: true }));
  await waitFor(
    () => {
      const post = projectState().post || {};
      return post.cut_order_strategy === "heat_spread" &&
        post.heat_spread_weight === 0.75 &&
        post.heat_lookback === 4 &&
        Array.isArray(post.cut_order_groups) &&
        post.cut_order_groups[0] === "disk_1" &&
        post.avoid_completed_contours === true &&
        post.auto_tabs === true &&
        post.auto_tab_count === 3 &&
        post.auto_tab_length_mm === 9 &&
        post.auto_tab_min_outer_diameter_mm === 40 &&
        post.small_feature_source === "cut_chart" &&
        post.open_path_mode === "centerline";
    },
    "cut order, auto tabs, and open-path persistence"
  );
  const response = await fetch("/api/review-report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(projectState())
  });
  const result = await response.json();
  const order = result.report && result.report.cut_order;
  const preflight = result.report && result.report.export_preflight;
  if (!order || order.strategy !== "heat_spread" || order.heat_spread_weight !== 0.75 || order.heat_lookback !== 4) {
    throw new Error(`Cut order report mismatch: ${JSON.stringify(order)}`);
  }
  if (!Array.isArray(order.manual_groups) || order.manual_groups[0] !== "disk_1") {
    throw new Error(`Manual cut order groups missing: ${JSON.stringify(order)}`);
  }
  if (!preflight || preflight.can_export !== true || preflight.gcode_validation_issue_count !== 0) {
    throw new Error(`Export preflight mismatch: ${JSON.stringify(preflight)}`);
  }
  if (!document.getElementById("cutOrderInfo").textContent.includes("heat spread")) {
    throw new Error("Cut order info did not update");
  }
  const preview = document.getElementById("previewCutOrderBtn");
  const clearPreview = document.getElementById("clearCutOrderPreviewBtn");
  if (!preview || !clearPreview) throw new Error("Cut order preview controls missing");
  preview.click();
  await waitFor(
    () => document.getElementById("cutOrderInfo").textContent.includes("Preview"),
    "cut order preview"
  );
  clearPreview.click();
  await waitFor(
    () => !document.getElementById("cutOrderInfo").textContent.includes("Preview"),
    "cut order preview clear"
  );
  return { status: "cut-order-controls", strategy: order.strategy, manualGroups: order.manual_groups.length };
}'

wait_export_preflight='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  document.getElementById("exportBtn").click();
  await waitFor(
    () =>
      document.getElementById("status").textContent.startsWith("Exported ") &&
      document.getElementById("gcode").value.includes("M3 $0 S1") &&
      !document.getElementById("issues").textContent.includes("Click Export NGC again"),
    "clean export preflight"
  );
  return { status: "export-preflight" };
}'

wait_arrow_nudge='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () => Math.abs(((projectState().placements || [])[0] || {}).dx - 255) < 0.001,
    "arrow nudge"
  );
  return { status: "arrow-nudge", dx: projectState().placements[0].dx };
}'

wait_mirror_selected='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () => {
      const state = projectState();
      return (state.parts || []).some((part) => part.mirrored_from === "disk") &&
        ((state.placements || [])[0] || {}).part_name.includes("mirrored") &&
        document.getElementById("selectedInfo").textContent.includes("mirrored");
    },
    "mirror selected"
  );
  const state = projectState();
  return { status: "mirror", part: state.placements[0].part_name };
}'

wait_cut_chart_edit='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () => Array.from(document.querySelectorAll("#cutChartTable tbody tr")).some(
      (row) => row.dataset.thickness === "3" && row.dataset.nozzle === "0.9"
    ),
    "cut chart rows"
  );
  const row = Array.from(document.querySelectorAll("#cutChartTable tbody tr")).find(
    (row) => row.dataset.thickness === "3" && row.dataset.nozzle === "0.9"
  );
  document.getElementById("smallFeatureSource").value = "cut_chart";
  document.getElementById("smallFeatureSource").dispatchEvent(new Event("change", { bubbles: true }));
  const inputs = row.querySelectorAll("input");
  inputs[3].value = "1234";
  inputs[3].dispatchEvent(new Event("change", { bubbles: true }));
  inputs[9].value = "88";
  inputs[9].dispatchEvent(new Event("change", { bubbles: true }));
  inputs[11].value = "55";
  inputs[11].dispatchEvent(new Event("change", { bubbles: true }));
  await waitFor(
    () => {
      const chartRow = ((projectState().cut_chart || {}).rows || []).find(
        (item) => item.thickness_mm === 3 && item.nozzle_mm === 0.9
      );
      return chartRow &&
        chartRow.feed_rate_mm_min === 1234 &&
        chartRow.small_hole_threshold_mm === 88 &&
        chartRow.small_hole_speed_percent === 55;
    },
    "project cut chart save"
  );
  const settingsResponse = await fetch("/api/cut-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(projectState())
  });
  const settings = await settingsResponse.json();
  if (settings.feed_rate_mm_min !== 1234) {
    throw new Error(`Project cut chart not used by backend: ${settings.feed_rate_mm_min}`);
  }
  if (settings.small_hole_threshold_mm !== 88 || settings.small_hole_speed_percent !== 55) {
    throw new Error(`Project small-feature chart not used by backend: ${JSON.stringify(settings)}`);
  }
  document.getElementById("resetCutChartBtn").click();
  await waitFor(() => !projectState().cut_chart, "starter chart reset");
  return { status: "cut-chart-edit" };
}'

wait_coupon_import='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const input = document.getElementById("couponResultsInput");
  const button = document.getElementById("importCouponResultsBtn");
  if (!input || !button) throw new Error("Coupon import controls missing");
  input.value = JSON.stringify({
    revision: "browser-smoke-r1",
    source: "Browser smoke measured coupon",
    results: [{
      material: "mild_steel",
      thickness_mm: 3,
      nozzle_mm: 0.9,
      current_a: 35,
      feed_rate_mm_min: 1111,
      kerf_width_mm: 1.31,
      pierce_delay_s: 0.46,
      cut_height_mm: 1.45,
      arc_voltage_v: 104.5,
      thc_enabled: false,
      coupon_id: "browser-smoke-01",
      operator: "playwright",
      measured_at: "2026-08-23T10:00:00Z"
    }]
  });
  input.dispatchEvent(new Event("input", { bubbles: true }));
  button.click();
  await waitFor(
    () => {
      const chart = projectState().cut_chart || {};
      return (chart.rows || []).some(
        (row) => row.coupon_id === "browser-smoke-01" && row.feed_rate_mm_min === 1111 && row.calibration_state === "measured"
      );
    },
    "measured coupon row"
  );
  const settingsResponse = await fetch("/api/cut-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(projectState())
  });
  const settings = await settingsResponse.json();
  if (settings.feed_rate_mm_min !== 1111 || settings.coupon_id !== "browser-smoke-01") {
    throw new Error(`Coupon row not active: ${JSON.stringify(settings)}`);
  }
  if (!document.getElementById("couponResultsInfo").textContent.includes("Imported 1")) {
    throw new Error("Coupon import status did not update");
  }
  return { status: "coupon-import", feed: settings.feed_rate_mm_min, coupon: settings.coupon_id };
}'

wait_cut_chart_profile_export='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const button = document.getElementById("exportCutChartBtn");
  if (!button) throw new Error("Export cut chart button missing");

  const originalCreateObjectURL = URL.createObjectURL.bind(URL);
  const originalClick = HTMLAnchorElement.prototype.click;
  window.__plasmaCamLastCutChartDownload = null;
  URL.createObjectURL = (blob) => {
    if (blob && String(blob.type || "").includes("json")) {
      blob.text().then((text) => {
        window.__plasmaCamLastCutChartDownload = JSON.parse(text);
      });
    }
    return originalCreateObjectURL(blob);
  };
  HTMLAnchorElement.prototype.click = function () {
    window.__plasmaCamLastCutChartFilename = this.download || "";
  };
  try {
    button.click();
    const exported = await waitFor(() => window.__plasmaCamLastCutChartDownload, "cut chart profile download");
    if (!String(window.__plasmaCamLastCutChartFilename || "").endsWith(".cut-chart.json")) {
      throw new Error(`Unexpected cut chart filename ${window.__plasmaCamLastCutChartFilename}`);
    }
    if (!exported.profile_id || exported.source !== "Browser smoke measured coupon") {
      throw new Error(`Unexpected cut chart metadata ${JSON.stringify({ profile_id: exported.profile_id, source: exported.source })}`);
    }
    if (!exported.exported_at) {
      throw new Error("Cut chart export missing exported_at");
    }
    const measured = (exported.rows || []).find(
      (row) => row.coupon_id === "browser-smoke-01" && row.feed_rate_mm_min === 1111 && row.calibration_state === "measured"
    );
    if (!measured) {
      throw new Error(`Measured row missing from cut chart export: ${JSON.stringify(exported.rows || [])}`);
    }
    if (!document.getElementById("status").textContent.includes("Cut chart exported")) {
      throw new Error("Cut chart export status did not update");
    }
    return { status: "cut-chart-export", rows: exported.rows.length, coupon: measured.coupon_id };
  } finally {
    URL.createObjectURL = originalCreateObjectURL;
    HTMLAnchorElement.prototype.click = originalClick;
  }
}'

wait_cut_chart_profile_import='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const exported = window.__plasmaCamLastCutChartDownload;
  if (!exported || !Array.isArray(exported.rows)) {
    throw new Error("No exported cut chart profile available for import round-trip");
  }
  document.getElementById("resetCutChartBtn").click();
  await waitFor(() => !projectState().cut_chart, "cut chart reset before profile import");
  const starterSettingsResponse = await fetch("/api/cut-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(projectState())
  });
  const starterSettings = await starterSettingsResponse.json();
  if (starterSettings.coupon_id === "browser-smoke-01") {
    throw new Error("Starter chart reset did not clear measured coupon row");
  }

  const input = document.getElementById("cutChartProfileFile");
  if (!input) throw new Error("Cut chart profile file input missing");
  const transfer = new DataTransfer();
  transfer.items.add(new File(
    [JSON.stringify(exported, null, 2)],
    "browser-smoke.cut-chart.json",
    { type: "application/json" }
  ));
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
  const state = await waitFor(() => {
    const current = projectState();
    const chart = current.cut_chart || {};
    if (
      chart.imported_from === "browser-smoke.cut-chart.json" &&
      (chart.rows || []).some(
        (row) => row.coupon_id === "browser-smoke-01" && row.feed_rate_mm_min === 1111 && row.calibration_state === "measured"
      )
    ) {
      return current;
    }
    return null;
  }, "cut chart profile import");

  const settingsResponse = await fetch("/api/cut-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state)
  });
  const settings = await settingsResponse.json();
  if (settings.feed_rate_mm_min !== 1111 || settings.coupon_id !== "browser-smoke-01") {
    throw new Error(`Imported cut chart profile is not active: ${JSON.stringify(settings)}`);
  }
  if (!document.getElementById("status").textContent.includes("Cut chart imported")) {
    throw new Error("Cut chart import status did not update");
  }
  return { status: "cut-chart-import", feed: settings.feed_rate_mm_min, coupon: settings.coupon_id };
}'

wait_cut_chart_profile_import_rejects_invalid='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const before = projectState().cut_chart || {};
  if (before.imported_from !== "browser-smoke.cut-chart.json") {
    throw new Error(`Expected valid imported profile before invalid import: ${JSON.stringify(before)}`);
  }
  const invalidProfile = {
    profile_id: "wrong-nozzle-browser-smoke",
    version: "invalid",
    machine: "Fubag Plasma 40",
    source: "Browser smoke invalid profile",
    rows: [{
      material: "mild_steel",
      thickness_mm: 3,
      nozzle_mm: 0.8,
      current_a: 35,
      feed_rate_mm_min: 999,
      kerf_width_mm: 1.2,
      pierce_delay_s: 0.5
    }]
  };
  const input = document.getElementById("cutChartProfileFile");
  if (!input) throw new Error("Cut chart profile file input missing");
  const transfer = new DataTransfer();
  transfer.items.add(new File(
    [JSON.stringify(invalidProfile, null, 2)],
    "wrong-nozzle.cut-chart.json",
    { type: "application/json" }
  ));
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
  const state = await waitFor(() => {
    const current = projectState();
    if (
      document.getElementById("status").textContent.includes("Cut chart import failed") &&
      document.getElementById("issues").textContent.includes("Cut chart profile rejected") &&
      (current.cut_chart || {}).imported_from === "browser-smoke.cut-chart.json"
    ) {
      return current;
    }
    return null;
  }, "invalid cut chart import rejection");
  const settingsResponse = await fetch("/api/cut-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state)
  });
  const settings = await settingsResponse.json();
  if (settings.feed_rate_mm_min !== 1111 || settings.coupon_id !== "browser-smoke-01") {
    throw new Error(`Invalid cut chart import did not preserve previous active profile: ${JSON.stringify(settings)}`);
  }
  return { status: "cut-chart-invalid-import-rejected", feed: settings.feed_rate_mm_min };
}'

wait_autonest='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const text = (node) => (node.textContent || "").trim();
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () =>
      text(document.getElementById("status")) === "Valid" &&
      Array.isArray(projectState().placements) &&
      projectState().placements.length === 2,
    "valid auto nest",
    30000
  );
  const nested = projectState();
  if (!nested.nesting || !nested.nesting.last_result) throw new Error("Auto nest summary missing");
  if (!Array.isArray(nested.nesting.run_history) || !nested.nesting.run_history.length) {
    throw new Error("Auto nest run history missing");
  }
  if ((nested.placements || []).length !== 2) throw new Error("Auto nest lost duplicated placement");
  if (document.getElementById("issues").textContent !== "No issues") throw new Error("Auto nest left issues");
  return {
    status: "autonest",
    placements: nested.placements.length,
    bestAttempt: nested.nesting.last_result.best_attempt,
    history: nested.nesting.run_history.length
  };
}'

wait_sim='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(() => document.getElementById("simulationInfo").textContent.includes("Done"), "simulation completion", 15000);
  return { status: "simulation", info: document.getElementById("simulationInfo").textContent };
}'

wait_outline='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(() => document.getElementById("gcode").value.includes("Torch is never started"), "outline export");
  const gcode = document.getElementById("gcode").value;
  if (gcode.includes("M3")) throw new Error("Outline export contains torch start");
  if (!gcode.includes("outer dry outline")) throw new Error("Outline export does not trace outer contours");
  if (!gcode.includes("#<kerfgrid_outline_feed> = ") || !gcode.includes("F#<kerfgrid_outline_feed>")) {
    throw new Error("Outline export must use an independent named feed parameter");
  }
  if (/^F[0-9]/m.test(gcode)) throw new Error("Outline export contains a literal material-checked feed");
  return { status: "outline", lines: gcode.split("\n").length };
}'

wait_review_report='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(() => document.getElementById("gcode").value.includes("\"simulation_metrics\""), "review report");
  const report = JSON.parse(document.getElementById("gcode").value);
  if (!report.cut_settings || !report.cut_settings.row_id) throw new Error("Review report missing cut settings row");
  if (!report.simulation_metrics || report.simulation_metrics.pierce_count < 1) {
    throw new Error("Review report missing simulation pierces");
  }
  if (!report.operator_checklist || !["ready", "warnings"].includes(report.operator_checklist.status)) {
    throw new Error(`Review report checklist not ready: ${JSON.stringify(report.operator_checklist)}`);
  }
  if (!document.getElementById("issues").textContent.includes("Pierces")) {
    throw new Error("Review report summary missing pierces");
  }
  if (!document.getElementById("issues").textContent.includes("Checklist")) {
    throw new Error("Review report summary missing checklist");
  }
  return { status: "review-report", pierces: report.simulation_metrics.pierce_count, checklist: report.operator_checklist.status };
}'

wait_common_line='async () => {
  const nested = JSON.parse(localStorage.getItem("kerfgrid.project.v1") || "{}");
  const rect = {
    name: "plate",
    quantity: 2,
    allowed_rotations: [0, 90, 180, 270],
    contours: [{
      type: "path",
      kind: "outer",
      name: "plate_outer",
      segments: [
        { type: "line", start: { x: -25, y: -25 }, end: { x: 25, y: -25 } },
        { type: "line", start: { x: 25, y: -25 }, end: { x: 25, y: 25 } },
        { type: "line", start: { x: 25, y: 25 }, end: { x: -25, y: 25 } },
        { type: "line", start: { x: -25, y: 25 }, end: { x: -25, y: -25 } }
      ]
    }]
  };
  const commonLineProject = {
    ...nested,
    sheet: { width_mm: 200, height_mm: 100, margin_mm: 10 },
    spacing_mm: 8,
    parts: [rect],
    placements: [
      { part_name: "plate", instance: 1, dx: 35, dy: 35, rotation_deg: 0 },
      { part_name: "plate", instance: 2, dx: 85, dy: 35, rotation_deg: 0 }
    ],
    lead_overrides: [],
    tabs: [],
    nesting: { ...(nested.nesting || {}), common_line_cutting: true },
    post: {
      ...(nested.post || {}),
      lead_in_mode: "none",
      lead_in_mm: 0,
      lead_out_mm: 0,
      pierce_crater_diameter_mm: 0,
      lead_clearance_mm: 0,
      kerf_offset_fallback: "block"
    }
  };
  const response = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(commonLineProject)
  });
  const validation = await response.json();
  const codes = (validation.issues || []).map((issue) => issue.code);
  if (!codes.includes("common_line_kerf_offset")) {
    throw new Error(`Common-line kerf safety issue missing: ${codes.join(", ")}`);
  }
  const centerlineProject = {
    ...commonLineProject,
    post: { ...(commonLineProject.post || {}), kerf_offset_fallback: "centerline" }
  };
  const centerlineValidationResponse = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(centerlineProject)
  });
  const centerlineValidation = await centerlineValidationResponse.json();
  const centerlineCodes = (centerlineValidation.issues || []).map((issue) => issue.code);
  if (!centerlineCodes.includes("common_line_centerline")) {
    throw new Error(`Common-line centerline warning missing: ${centerlineCodes.join(", ")}`);
  }
  const blocking = (centerlineValidation.issues || []).filter((issue) => issue.blocking !== false);
  if (blocking.length) {
    throw new Error(`Common-line centerline should not block simulation: ${blocking.map((issue) => issue.code).join(", ")}`);
  }
  const simulateResponse = await fetch("/api/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(centerlineProject)
  });
  if (!simulateResponse.ok) {
    throw new Error(`Common-line centerline simulation failed: ${await simulateResponse.text()}`);
  }
  const simulation = await simulateResponse.json();
  if (!(simulation.segments || []).some((segment) => segment.type === "cut")) {
    throw new Error("Common-line centerline simulation did not produce cut segments");
  }

  return {
    status: "ok",
    placements: nested.placements.length,
    bestAttempt: nested.nesting.last_result.best_attempt,
    commonLineCodes: codes,
    centerlineCodes,
    simulationSegments: simulation.segments.length
  };
}'

load_common_line_ui_project='async () => {
  const storageKey = "kerfgrid.project.v1";
  const rect = {
    name: "plate",
    quantity: 2,
    allowed_rotations: [0, 90, 180, 270],
    contours: [{
      type: "path",
      kind: "outer",
      name: "plate_outer",
      segments: [
        { type: "line", start: { x: -25, y: -25 }, end: { x: 25, y: -25 } },
        { type: "line", start: { x: 25, y: -25 }, end: { x: 25, y: 25 } },
        { type: "line", start: { x: 25, y: 25 }, end: { x: -25, y: 25 } },
        { type: "line", start: { x: -25, y: 25 }, end: { x: -25, y: -25 } }
      ]
    }]
  };
  const project = {
    format: "kerfgrid-project",
    format_version: 1,
    name: "common-line-ui-smoke",
    sheet: { width_mm: 200, height_mm: 100, margin_mm: 10 },
    spacing_mm: 8,
    cut: { material: "mild_steel", thickness_mm: 3, nozzle_mm: 0.9, feed_rate_mode: "auto", manual_feed_rate_mm_min: 1300 },
    post: {
      lead_in_mode: "none",
      lead_in_mm: 0,
      lead_out_mm: 0,
      pierce_crater_diameter_mm: 0,
      lead_clearance_mm: 0,
      safe_travel: false,
      kerf_offset_fallback: "centerline"
    },
    nesting: { common_line_cutting: true },
    parts: [rect],
    placements: [
      { part_name: "plate", instance: 1, dx: 35, dy: 35, rotation_deg: 0 },
      { part_name: "plate", instance: 2, dx: 85, dy: 35, rotation_deg: 0 }
    ],
    zones: [],
    tabs: [],
    lead_overrides: [],
    simulation: { playback_rate: 200, rapid_rate_mm_min: 8000 }
  };
  const current = await (await fetch("/api/workspace")).json();
  const saved = await fetch("/api/workspace", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: current.revision, project })
  });
  if (!saved.ok) throw new Error(await saved.text());
  return { status: "common-line-ui-loaded", placements: project.placements.length };
}'

wait_common_line_ui_sim='async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, label, timeoutMs = 15000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () => (document.getElementById("issues").textContent || "").includes("common_line_centerline"),
    "common-line UI validation"
  );
  document.getElementById("simulateBtn").click();
  await waitFor(
    () => document.getElementById("simulationInfo").textContent.includes("Done"),
    "common-line UI simulation"
  );
  const issues = document.getElementById("issues").textContent || "";
  if (document.getElementById("status").textContent === "Simulation failed") {
    throw new Error(`Common-line UI simulation failed: ${issues}`);
  }
  if (!issues.includes("common_line_centerline")) {
    throw new Error(`Common-line UI warning missing: ${issues}`);
  }
  const selected = document.getElementById("selectedInfo").textContent || "";
  if (selected.includes("outside sheet")) {
    throw new Error(`Common-line UI preview reported false sheet bounds issue: ${selected}`);
  }
  return { status: "common-line-ui-sim", info: document.getElementById("simulationInfo").textContent };
}'

wait_auto_leads='async () => {
  const storageKey = "kerfgrid.project.v1";
  const project = {
    format: "kerfgrid-project",
    format_version: 1,
    name: "auto-lead-smoke",
    sheet: { width_mm: 260, height_mm: 207, margin_mm: 10 },
    spacing_mm: 0,
    cut: { material: "mild_steel", thickness_mm: 3, nozzle_mm: 0.9, feed_rate_mode: "auto", manual_feed_rate_mm_min: 1300 },
    post: {
      lead_in_mode: "line",
      lead_in_mm: 5,
      lead_out_mm: 0,
      lead_in_min_hole_diameter_mm: 20,
      pierce_crater_diameter_mm: 4,
      lead_clearance_mm: 1,
      small_hole_threshold_mm: 37,
      small_shape_threshold_mm: 37,
      small_hole_speed_percent: 65,
      small_hole_overburn_mm: 0,
      small_hole_torch_off_before_end_mm: 0,
      safe_travel: true,
      travel_clearance_mm: 8
    },
    nesting: { auto_nest_attempts: 1, auto_nest_angle_step_deg: 30, allow_arbitrary_rotation: true },
    parts: [{ name: "round", quantity: 3, outer: { type: "circle", radius_mm: 50 }, holes: [] }],
    placements: [],
    zones: [],
    tabs: [],
    lead_overrides: []
  };
  const response = await fetch("/api/auto-nest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project)
  });
  if (!response.ok) throw new Error(await response.text());
  const nested = await response.json();
  const autoCount = (nested.lead_overrides || []).filter((item) => item.auto_generated).length;
  if (autoCount <= 0) throw new Error("Auto leads were not generated");
  const current = await (await fetch("/api/workspace")).json();
  const saved = await fetch("/api/workspace", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: current.revision, project: nested })
  });
  if (!saved.ok) throw new Error(await saved.text());
  return { status: "auto-leads-loaded", autoCount };
}'

wait_clear_auto_leads='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () => (projectState().lead_overrides || []).some((item) => item.auto_generated),
    "auto leads after reload"
  );
  document.getElementById("clearAutoLeadsBtn").click();
  await waitFor(
    () => !(projectState().lead_overrides || []).some((item) => item.auto_generated),
    "clear auto leads"
  );
  if (!document.getElementById("leadEditInfo").textContent.includes("auto")) {
    throw new Error("Lead info does not show auto lead count");
  }
  return { status: "auto-leads-cleared" };
}'

wait_accept_auto_leads='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () =>
      Boolean(document.getElementById("acceptAutoLeadsBtn")) &&
      (projectState().lead_overrides || []).some((item) => item.auto_generated),
    "auto leads before accept"
  );
  const before = (projectState().lead_overrides || []).filter((item) => item.auto_generated).length;
  if (before <= 0) throw new Error("No auto leads to accept");
  document.getElementById("acceptAutoLeadsBtn").click();
  await waitFor(
    () => {
      const leads = projectState().lead_overrides || [];
      return leads.length >= before && !leads.some((item) => item.auto_generated);
    },
    "accept auto leads"
  );
  if (!document.getElementById("leadEditInfo").textContent.includes("0 auto")) {
    throw new Error("Lead info did not show accepted auto leads as manual");
  }
  return { status: "auto-leads-accepted", accepted: before };
}'

wait_hole_filler='async () => {
  const rect = (name, width, height, kind = "outer") => {
    const points = [
      { x: -width / 2, y: -height / 2 },
      { x: width / 2, y: -height / 2 },
      { x: width / 2, y: height / 2 },
      { x: -width / 2, y: height / 2 }
    ];
    return {
      type: "path",
      kind,
      name,
      segments: points.map((start, index) => ({
        type: "line",
        start,
        end: points[(index + 1) % points.length]
      }))
    };
  };
  const project = {
    format: "kerfgrid-project",
    format_version: 1,
    name: "hole-filler-smoke",
    sheet: { width_mm: 220, height_mm: 140, margin_mm: 10 },
    spacing_mm: 0,
    cut: { material: "mild_steel", thickness_mm: 3, nozzle_mm: 0.9, feed_rate_mode: "auto", manual_feed_rate_mm_min: 1300 },
    post: { lead_in_mode: "none", pierce_crater_diameter_mm: 0, lead_clearance_mm: 0, safe_travel: true, travel_clearance_mm: 8 },
    nesting: { auto_nest_attempts: 1, auto_nest_angle_step_deg: 90, allow_arbitrary_rotation: false, allow_hole_filler: true },
    parts: [
      { name: "frame", quantity: 1, contours: [rect("frame_outer", 100, 100), rect("frame_window", 60, 60, "hole")] },
      { name: "token", quantity: 1, contours: [rect("token_outer", 40, 40)] }
    ],
    placements: [],
    zones: [],
    tabs: [],
    lead_overrides: []
  };
  const response = await fetch("/api/auto-nest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project)
  });
  if (!response.ok) throw new Error(await response.text());
  const nested = await response.json();
  if ((nested.nesting.last_result || {}).hole_filler_relocation_count !== 1) {
    throw new Error(`Hole filler did not relocate: ${JSON.stringify(nested.nesting.last_result)}`);
  }
  return { status: "hole-filler", count: nested.nesting.last_result.hole_filler_relocation_count };
}'

reload_current_page='() => {
  window.location.reload();
  return true;
}'

wait_delete_selected='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (predicate()) return;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  await waitFor(
    () =>
      Array.isArray(projectState().placements) &&
      projectState().placements.length === 1 &&
      document.getElementById("selectedInfo").textContent.trim() === "None",
    "keyboard delete"
  );
  return { status: "keyboard-delete", placements: projectState().placements.length };
}'

pw click "#loadExampleBtn" >/dev/null
pw --json eval "${wait_demo}" >/dev/null
pw --json eval "${wait_reimport_update}" >/dev/null
pw click "#loadExampleBtn" >/dev/null
pw --json eval "${wait_demo}" >/dev/null
pw --json eval "${wait_template_parts}" >/dev/null
pw click "#loadExampleBtn" >/dev/null
pw --json eval "${wait_demo}" >/dev/null
pw --json eval "${wait_manual_ergonomics}" >/dev/null
pw --json eval "${wait_import_options_controls}" >/dev/null
pw --json eval "${wait_cut_order_controls}" >/dev/null
pw --json eval "${wait_export_preflight}" >/dev/null
pw press ArrowRight >/dev/null
pw --json eval "${wait_arrow_nudge}" >/dev/null
pw click "#mirrorBtn" >/dev/null
pw --json eval "${wait_mirror_selected}" >/dev/null
pw click "#loadExampleBtn" >/dev/null
pw --json eval "${wait_demo}" >/dev/null
pw click "#saveProjectBtn" >/dev/null
pw --json eval "${wait_save_project}" >/dev/null
pw --json eval "${wait_project_file_roundtrip}" >/dev/null
pw click "#loadExampleBtn" >/dev/null
pw --json eval "${wait_demo}" >/dev/null
pw --json eval "${wait_cut_chart_edit}" >/dev/null
pw --json eval "${wait_coupon_import}" >/dev/null
pw --json eval "${wait_cut_chart_profile_export}" >/dev/null
pw --json eval "${wait_cut_chart_profile_import}" >/dev/null
pw --json eval "${wait_cut_chart_profile_import_rejects_invalid}" >/dev/null
pw click "#loadExampleBtn" >/dev/null
pw --json eval "${wait_demo}" >/dev/null
pw --json eval "${wait_drag_part_from_list}" >/dev/null
pw click "#loadExampleBtn" >/dev/null
pw --json eval "${wait_demo}" >/dev/null
pw click "#duplicateBtn" >/dev/null
pw --json eval "${wait_duplicate}" >/dev/null
pw click "#autoNestBtn" >/dev/null
pw --json eval "${wait_autonest}" >/dev/null
pw click "#outlineBtn" >/dev/null
pw --json eval "${wait_outline}" >/dev/null
pw click "#reviewReportBtn" >/dev/null
pw --json eval "${wait_review_report}" >/dev/null
pw click "#simulateBtn" >/dev/null
pw --json eval "${wait_sim}" >/dev/null
pw --json eval "${wait_common_line}" >/dev/null
pw --json eval "${load_common_line_ui_project}" >/dev/null
pw --json eval "${reload_current_page}" >/dev/null
pw --json eval "${wait_common_line_ui_sim}" >/dev/null
pw --json eval "${wait_hole_filler}" >/dev/null
pw --json eval "${wait_auto_leads}" >/dev/null
pw --json eval "${reload_current_page}" >/dev/null
pw --json eval "${wait_accept_auto_leads}" >/dev/null
pw --json eval "${wait_auto_leads}" >/dev/null
pw --json eval "${reload_current_page}" >/dev/null
pw --json eval "${wait_clear_auto_leads}" >/dev/null
pw click "#loadExampleBtn" >/dev/null
pw --json eval "${wait_demo}" >/dev/null
pw click "#duplicateBtn" >/dev/null
pw --json eval "${wait_duplicate}" >/dev/null
pw click "#autoNestBtn" >/dev/null
pw --json eval "${wait_autonest}" >/dev/null
pw press Delete >/dev/null
pw --json eval "${wait_delete_selected}"
pw --json eval 'async () => {
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const state = () => JSON.parse(localStorage.getItem("kerfgrid.project.v1") || "{}");
  for (const mode of ["compact", "strip"]) {
    const select = document.getElementById("nestLayoutMode");
    if (!select || select.options.length !== 2) throw new Error("Missing nesting mode selector");
    const panel = select.closest("section");
    const wasActive = panel.classList.contains("active");
    panel.classList.add("active");
    const width = select.getBoundingClientRect().width;
    if (!wasActive) panel.classList.remove("active");
    if (width < 250) throw new Error("Nesting mode text is clipped by a narrow selector");
    select.value = mode;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    const started = Date.now();
    while (state().nesting?.layout_mode !== mode && Date.now() - started < 5000) await wait(50);
    if (state().nesting?.layout_mode !== mode) throw new Error(`Mode ${mode} was not saved`);
    document.getElementById("autoNestBtn").click();
    while (state().nesting?.last_result?.layout_mode !== mode && Date.now() - started < 20000) await wait(100);
    if (state().nesting?.last_result?.layout_mode !== mode) throw new Error(`Mode ${mode} was not used by auto nest`);
  }
  return { status: "nesting modes", selected: state().nesting.layout_mode };
}'
pw --json eval 'async () => {
  const { completedCutPaths, pointsUntilTime } = await import("/js/simulation.js");
  const points = [{x:0,y:0,t:0}, {x:10,y:0,t:1,type:"rapid"}, {x:20,y:0,t:2,type:"cut"}, {x:40,y:0,t:3,type:"rapid"}, {x:50,y:0,t:4,type:"cut"}];
  const duringRapid = completedCutPaths(pointsUntilTime(points, 2.5));
  const duringCut = completedCutPaths(pointsUntilTime(points, 3.5));
  if (duringRapid.length !== 1 || duringRapid[0].at(-1).x !== 20) throw new Error("Rapid was highlighted as cut");
  if (duringCut.length !== 2 || duringCut[1][0].x !== 40 || duringCut[1].at(-1).x !== 45) throw new Error("Separate cuts were joined across rapid");
  return { status: "simulation cut/rapid separation" };
}'
pw --json eval 'async () => {
  const current = await (await fetch("/api/workspace")).json();
  const project = structuredClone(current.project);
  project.name = "interlocking-bounds-smoke";
  project.sheet = { width_mm: 200, height_mm: 150 };
  project.spacing_mm = 6;
  project.post = { ...project.post, lead_in_mode: "none", lead_in_mm: 0, lead_out_mm: 0, pierce_crater_diameter_mm: 0, safe_travel: false };
  const points = [{x:-40,y:-20},{x:40,y:-20},{x:-40,y:20}];
  project.parts = [{ name: "triangle", quantity: 2, allowed_rotations: [0,180], contours: [{type:"path",name:"triangle_outer",kind:"outer",segments:points.map((start,index) => ({type:"line",start,end:points[(index+1)%points.length]}))}] }];
  project.placements = [{part_name:"triangle",instance:1,dx:50,dy:30,rotation_deg:0},{part_name:"triangle",instance:2,dx:50,dy:37,rotation_deg:180}];
  project.zones = []; project.tabs = []; project.lead_overrides = [];
  project.nesting = { layout_mode: "compact" };
  const response = await fetch("/api/workspace", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_revision:current.revision,project})});
  if (!response.ok) throw new Error(await response.text());
  return { status: "interlocking bounds loaded" };
}' >/dev/null
pw --json eval "${reload_current_page}" >/dev/null
pw --json eval 'async () => {
  const started=Date.now();
  while (Date.now()-started<10000) {
    const p=JSON.parse(localStorage.getItem("kerfgrid.project.v1") || "{}");
    const selected=document.getElementById("selectedInfo").textContent;
    if (p.name==="interlocking-bounds-smoke" && document.getElementById("issues").textContent==="No issues" && selected.includes("triangle_") && !selected.includes("collision/spacing")) return {status:"interlocking bounds validated"};
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error(`False bounding-box collision after exact validation: ${document.getElementById("selectedInfo").textContent}`);
}'
pw --json eval 'async () => {
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const state = () => JSON.parse(localStorage.getItem("kerfgrid.project.v1") || "{}");
  const control = document.getElementById("safeTravel");
  if (!control || document.getElementById("avoidCompletedContours")) throw new Error("Travel controls are not consolidated");
  for (const enabled of [false, true]) {
    control.checked = enabled;
    control.dispatchEvent(new Event("change", { bubbles: true }));
    const started = Date.now();
    let stored = null;
    while (Date.now() - started < 10000) {
      stored = await (await fetch("/api/workspace")).json();
      if (state().post.safe_travel === enabled && stored.project.post.safe_travel === enabled) break;
      await wait(100);
    }
    if (stored.project.post.safe_travel !== enabled) throw new Error("Travel mode did not save on server");
    if (document.getElementById("travelClearance").disabled === enabled) throw new Error("Clearance control does not follow travel mode");
    if (enabled && !document.getElementById("travelModeInfo").textContent.includes("M0")) throw new Error("Missing blocked-route pause explanation");
  }
  return { status: "travel mode saved", safe: state().post.safe_travel };
}'
pw --json eval "${reload_current_page}" >/dev/null
pw --json eval 'async () => {
  const started = Date.now();
  while (Date.now() - started < 10000) {
    if (document.getElementById("workspaceStatus").textContent === "Saved on server") {
      const project = JSON.parse(localStorage.getItem("kerfgrid.project.v1") || "{}");
      if (!project.post.safe_travel || !document.getElementById("safeTravel").checked) throw new Error("Travel mode lost after reload");
      return {status:"travel mode survives reload"};
    }
    await new Promise(resolve => setTimeout(resolve,100));
  }
  throw new Error("Workspace did not load after travel mode reload");
}'
