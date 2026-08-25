#!/usr/bin/env bash
set -euo pipefail

url="${PLASMA_CAM_URL:-http://127.0.0.1:8765/}"
base_url="${url%/}/"
if command -v playwright-cli >/dev/null 2>&1; then
  default_pwcli="$(command -v playwright-cli)"
else
  default_pwcli="${HOME}/.codex/skills/playwright/scripts/playwright_cli.sh"
fi
pwcli="${PWCLI:-${default_pwcli}}"
dxf_path="${PLASMA_CAM_REAL_DXF_SMOKE_PATH:-/Users/user/Documents/dxf/models/_extracted/часы_portable/часы_portable.dxf}"
screenshot_path="${PLASMA_CAM_REAL_DXF_SMOKE_SCREENSHOT:-output/playwright/real-dxf-smoke-latest.png}"
payload_json="${TMPDIR:-/tmp}/plasma-cam-real-dxf-payload-$$.json"
project_json="${TMPDIR:-/tmp}/plasma-cam-real-dxf-project-$$.json"
pending_json="${TMPDIR:-/tmp}/plasma-cam-real-dxf-pending-$$.json"

cleanup() {
  rm -f "${payload_json}" "${project_json}" "${pending_json}"
}
trap cleanup EXIT

test -x "${pwcli}"
test -f "${dxf_path}"
mkdir -p "$(dirname "${screenshot_path}")"

python3 - "${dxf_path}" "${payload_json}" <<'PY'
import json
import sys
from pathlib import Path

dxf_path = Path(sys.argv[1])
payload_path = Path(sys.argv[2])
payload = {
    "filename": dxf_path.name,
    "content": dxf_path.read_text(encoding="cp1251", errors="ignore"),
    "import_options": {"auto_close_gaps": True, "unsafe_entity_policy": "warn"},
    "base_project": {
        "format": "kerfgrid-project",
        "format_version": 1,
        "name": "real_dxf_ui_smoke",
        "sheet": {"width_mm": 1000, "height_mm": 1500, "margin_mm": 10},
        "spacing_mm": 8,
        "cut": {
            "material": "mild_steel",
            "thickness_mm": 3,
            "nozzle_mm": 0.9,
            "feed_rate_mode": "auto",
            "manual_feed_rate_mm_min": 1300,
        },
        "post": {
            "kerf_offset_fallback": "centerline",
            "open_path_mode": "centerline",
            "safe_travel": True,
        },
        "nesting": {"auto_nest_max_runtime_s": 4},
        "simulation": {"playback_rate": 1000, "rapid_rate_mm_min": 8000},
        "ui": {},
        "zones": [],
        "tabs": [],
        "lead_overrides": [],
    },
}
payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
PY

curl -sS -X POST \
  -H "Content-Type: application/json" \
  --data-binary "@${payload_json}" \
  "${base_url}api/import-dxf" \
  -o "${project_json}"

python3 - "${project_json}" "${pending_json}" <<'PY'
import json
import sys
from pathlib import Path

project_path = Path(sys.argv[1])
pending_path = Path(sys.argv[2])
project = json.loads(project_path.read_text(encoding="utf-8"))
if "error" in project:
    raise SystemExit(f"DXF import failed: {project.get('type')}: {project.get('error')}")
if len(project.get("parts", [])) != 1 or len(project.get("placements", [])) != 1:
    raise SystemExit("DXF import did not produce one visible placement")
contour_count = len(project["parts"][0].get("contours", []))
if contour_count < 70:
    raise SystemExit(f"DXF import produced too few contours: {contour_count}")
pending_path.write_text(json.dumps({"project": project}, ensure_ascii=False), encoding="utf-8")
PY

curl -sS -X POST \
  -H "Content-Type: application/json" \
  --data-binary "@${pending_json}" \
  "${base_url}api/pending-project" \
  >/dev/null

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

pw --json open "${base_url}?pending_project=1" >/dev/null

wait_real_dxf='async () => {
  const storageKey = "kerfgrid.project.v1";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const projectState = () => JSON.parse(localStorage.getItem(storageKey) || "{}");
  const waitFor = async (predicate, label, timeoutMs = 30000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await wait(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const project = await waitFor(() => {
    const state = projectState();
    if (
      state.name === "часы_portable" &&
      Array.isArray(state.parts) &&
      state.parts.length === 1 &&
      Array.isArray(state.placements) &&
      state.placements.length === 1
    ) {
      return state;
    }
    return null;
  }, "watch DXF project");
  if ((project.parts[0].contours || []).length < 70) {
    throw new Error(`Watch DXF contour count too low: ${(project.parts[0].contours || []).length}`);
  }
  await waitFor(() => {
    const selected = document.getElementById("selectedInfo");
    return selected && selected.textContent.includes("часы_portable_1");
  }, "selected watch placement");
  await waitFor(() => {
    const partsText = document.getElementById("partsTable").textContent || "";
    return partsText.includes("часы_portable.dxf") || partsText.includes("часы_portable");
  }, "watch parts row");
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const canvas = document.getElementById("sheetCanvas");
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 600 || rect.height < 360) {
    throw new Error(`Canvas unexpectedly small: ${rect.width}x${rect.height}`);
  }
  const context = canvas.getContext("2d", { willReadFrequently: true });
  const image = context.getImageData(0, 0, canvas.width, canvas.height).data;
  let nonWhite = 0;
  let strong = 0;
  let red = 0;
  for (let index = 0; index < image.length; index += 16) {
    const r = image[index];
    const g = image[index + 1];
    const b = image[index + 2];
    const a = image[index + 3];
    if (a > 0 && (r < 248 || g < 248 || b < 248)) nonWhite += 1;
    if (a > 0 && (r < 190 || g < 190 || b < 190)) strong += 1;
    if (a > 0 && r > 170 && g < 120 && b < 120) red += 1;
  }
  if (nonWhite < 5000 || strong < 500) {
    throw new Error(`Watch DXF canvas looks blank: nonWhite=${nonWhite}, strong=${strong}`);
  }
  if (red > nonWhite * 0.35) {
    throw new Error(`Watch DXF canvas is dominated by red diagnostics: red=${red}, nonWhite=${nonWhite}`);
  }
  const simulateResponse = await fetch("/api/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project)
  });
  if (!simulateResponse.ok) {
    throw new Error(`Watch DXF API simulation failed: ${await simulateResponse.text()}`);
  }
  const simulation = await simulateResponse.json();
  if (!(simulation.segments || []).some((segment) => segment.type === "cut")) {
    throw new Error("Watch DXF API simulation produced no cut segments");
  }
  document.getElementById("simulateBtn").click();
  await waitFor(
    () => document.getElementById("simulationInfo").textContent.includes("Done"),
    "watch UI simulation completion",
    30000
  );
  if (document.getElementById("status").textContent === "Simulation failed") {
    throw new Error(`Watch UI simulation failed: ${document.getElementById("issues").textContent}`);
  }
  return {
    status: "real-dxf-ui-smoke",
    contours: project.parts[0].contours.length,
    apiSegments: simulation.segments.length,
    nonWhite,
    strong,
    red
  };
}'

pw --json eval "${wait_real_dxf}" >/dev/null
pw --json screenshot --filename "${screenshot_path}" --full-page
