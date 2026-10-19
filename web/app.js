import { downloadText, fileSafeName, postJson } from "./js/http.js";
import { SharedWorkspace } from "./js/workspace.js";
import { completedCutPaths, pointAtTime, pointsUntilTime } from "./js/simulation.js";
import {
  boundedHoleRadius,
  boxInside,
  boxesOverlap,
  circleContour,
  contourPoints,
  mirrorContour,
  normalizeAllowedRotations,
  normalizeAngle,
  partBounds,
  partContours,
  placementWorldBounds,
  rectangleContour,
  rotateLocal,
  rotatedPartBounds,
  transformLocal,
  transformWorldToLocal,
  zoneBounds,
} from "./js/geometry.js";

(function () {
  const canvas = document.getElementById("sheetCanvas");
  const ctx = canvas.getContext("2d");
  const issuesEl = document.getElementById("issues");
  const gcodeEl = document.getElementById("gcode");
  const statusEl = document.getElementById("status");
  const selectedInfoEl = document.getElementById("selectedInfo");
  const importFileEl = document.getElementById("importFile");
  const cutSettingsInfoEl = document.getElementById("cutSettingsInfo");
  const simulationInfoEl = document.getElementById("simulationInfo");
  const cutChartTableEl = document.getElementById("cutChartTable");
  const cutChartInfoEl = document.getElementById("cutChartInfo");
  const partsTableEl = document.getElementById("partsTable");
  const zoomPercentEl = document.getElementById("zoomPercent");
  const panViewBtn = document.getElementById("panViewBtn");
  const viewToolbar = document.querySelector(".view-toolbar");
  const zonesListEl = document.getElementById("zonesList");
  const leadEditInfoEl = document.getElementById("leadEditInfo");
  const nestingInfoEl = document.getElementById("nestingInfo");
  const nestHistoryEl = document.getElementById("nestHistory");
  const importLayerInfoEl = document.getElementById("importLayerInfo");
  const couponResultsFileEl = document.getElementById("couponResultsFile");
  const couponResultsInputEl = document.getElementById("couponResultsInput");
  const couponResultsInfoEl = document.getElementById("couponResultsInfo");
  const cutChartProfileFileEl = document.getElementById("cutChartProfileFile");
  const cutOrderInfoEl = document.getElementById("cutOrderInfo");
  const selectedRotationsEl = document.getElementById("selectedRotations");
  const selectedGrainLockEl = document.getElementById("selectedGrainLock");
  const selectedAllowHoleFillerEl = document.getElementById("selectedAllowHoleFiller");
  const selectedAllowHoleParentEl = document.getElementById("selectedAllowHoleParent");
  const undoBtn = document.getElementById("undoBtn");
  const redoBtn = document.getElementById("redoBtn");
  const clearSheetBtn = document.getElementById("clearSheetBtn");
  const storageKey = "kerfgrid.project.v1";
  const viewStorageKey = "kerfgrid.view.v1";
  const migrationBackupKey = "kerfgrid.project.before-shared.v1";
  const projectFormat = "kerfgrid-project";
  const projectFormatVersion = 2;
  const autoNestUiTimeoutGraceS = 3;
  const cutOrderStrategies = new Set(["nearest", "lower_left", "heat_spread"]);
  const layerMappingModes = new Set(["heuristic", "cut_all", "mapped_only"]);
  const layerProcesses = new Set(["cut", "ignore", "construction", "mark"]);
  const layerProcessAliases = {
    cutting: "cut",
    profile: "cut",
    skip: "ignore",
    ignored: "ignore",
    hidden: "ignore",
    construction_line: "construction",
    construct: "construction",
    reference: "construction",
    center: "construction",
    centerline: "construction",
    dimension: "construction",
    dim: "construction",
    text: "construction",
    etch: "mark",
    marking: "mark",
    scratch: "mark",
    bend: "mark",
  };

  const controls = {
    sheetWidth: document.getElementById("sheetWidth"),
    sheetHeight: document.getElementById("sheetHeight"),
    snapEnabled: document.getElementById("snapEnabled"),
    snapMm: document.getElementById("snapMm"),
    templateOuterDia: document.getElementById("templateOuterDia"),
    templateCenterDia: document.getElementById("templateCenterDia"),
    templateWidth: document.getElementById("templateWidth"),
    templateHeight: document.getElementById("templateHeight"),
    templateBoltCount: document.getElementById("templateBoltCount"),
    templateBoltCircleDia: document.getElementById("templateBoltCircleDia"),
    templateBoltDia: document.getElementById("templateBoltDia"),
    spacing: document.getElementById("spacing"),
    nestLayoutMode: document.getElementById("nestLayoutMode"),
    nestAttempts: document.getElementById("nestAttempts"),
    nestAngleStep: document.getElementById("nestAngleStep"),
    nestMaxRuntime: document.getElementById("nestMaxRuntime"),
    nestWorkers: document.getElementById("nestWorkers"),
    allowArbitraryRotation: document.getElementById("allowArbitraryRotation"),
    allowHoleFiller: document.getElementById("allowHoleFiller"),
    commonLineCutting: document.getElementById("commonLineCutting"),
    safeTravel: document.getElementById("safeTravel"),
    travelClearance: document.getElementById("travelClearance"),
    thickness: document.getElementById("thickness"),
    nozzle: document.getElementById("nozzle"),
    feedMode: document.getElementById("feedMode"),
    manualFeed: document.getElementById("manualFeed"),
    materialMode: document.getElementById("materialMode"),
    materialNumber: document.getElementById("materialNumber"),
    materialWait: document.getElementById("materialWait"),
    cutOrderStrategy: document.getElementById("cutOrderStrategy"),
    optimizeCutOrder: document.getElementById("optimizeCutOrder"),
    keepPartContoursTogether: document.getElementById("keepPartContoursTogether"),
    heatSpreadWeight: document.getElementById("heatSpreadWeight"),
    heatLookback: document.getElementById("heatLookback"),
    cutOrderGroups: document.getElementById("cutOrderGroups"),
    leadMode: document.getElementById("leadMode"),
    leadLength: document.getElementById("leadLength"),
    leadOutLength: document.getElementById("leadOutLength"),
    leadHoleMin: document.getElementById("leadHoleMin"),
    pierceCrater: document.getElementById("pierceCrater"),
    leadClearance: document.getElementById("leadClearance"),
    smallFeatureSource: document.getElementById("smallFeatureSource"),
    smallHoleThreshold: document.getElementById("smallHoleThreshold"),
    smallShapeThreshold: document.getElementById("smallShapeThreshold"),
    smallHoleSpeed: document.getElementById("smallHoleSpeed"),
    smallFeatureOverburn: document.getElementById("smallFeatureOverburn"),
    smallFeatureEarlyOff: document.getElementById("smallFeatureEarlyOff"),
    tabLength: document.getElementById("tabLength"),
    autoTabs: document.getElementById("autoTabs"),
    autoTabCount: document.getElementById("autoTabCount"),
    autoTabLength: document.getElementById("autoTabLength"),
    autoTabMinDiameter: document.getElementById("autoTabMinDiameter"),
    centerlineFallback: document.getElementById("centerlineFallback"),
    openPathCenterline: document.getElementById("openPathCenterline"),
    importUnsafeEntityWarn: document.getElementById("importUnsafeEntityWarn"),
    importLayerMode: document.getElementById("importLayerMode"),
    importLayerMapping: document.getElementById("importLayerMapping"),
    simPlayback: document.getElementById("simPlayback"),
  };

  let project = null;
  let selectedKey = null;
  let selectedZoneId = null;
  let editorMode = "select";
  let dragging = null;
  let autoNesting = false;
  let autoNestTimer = null;
  let couponImporting = false;
  let cutChart = [];
  let cutChartProfile = null;
  let simulation = emptySimulation();
  let cutOrderPreview = [];
  let importing = false;
  let validatedLayout = null;
  let pendingImportMode = "any";
  let importLayerMappingErrors = [];
  let pendingExportApprovalSignature = null;
  let statusVersion = 0;
  let view = { scale: 1, pad: 40, originX: 40, originY: 40 };
  let viewState = loadViewState();
  let panning = null;
  let panMode = false;
  let spacePan = false;
  let viewRedrawFrame = null;
  let undoStack = [];
  let redoStack = [];
  let pendingControlHistory = null;
  let historyRestoring = false;
  const rotateHandleRadiusPx = 8;
  const rotateHandleGapPx = 28;
  const historyLimit = 50;
  const importAcceptAny = ".json,.kerfgrid.json,.dxf";
  const importAcceptProject = ".json,.kerfgrid.json,application/json";
  const sharedWorkspace = new SharedWorkspace({
    onProject(value) {
      undoStack = [];
      redoStack = [];
      pendingControlHistory = null;
      activateLoadedProject(value, "");
      updateHistoryControls();
    },
    onState({ status, files = [], conflict = false }) {
      document.getElementById("workspaceStatus").textContent = status;
      document.getElementById("workspaceConflict").hidden = !conflict;
      const list = document.getElementById("workspaceFiles");
      list.replaceChildren();
      for (const file of files) {
        const link = document.createElement("a");
        link.href = `/api/workspace/files/${encodeURIComponent(file.id)}`;
        link.textContent = file.filename;
        link.download = file.filename;
        list.append(link);
      }
      if (!files.length) list.textContent = "No uploaded files";
    },
    isBusy: () => Boolean(dragging || panning || autoNesting || importing || couponImporting || pendingControlHistory),
  });

  function keyForPlacement(placement) {
    return `${placement.part_name}_${placement.instance}`;
  }

  function setStatus(text) {
    statusVersion += 1;
    statusEl.textContent = text;
  }

  function emptySimulation() {
    return {
      data: null,
      points: [],
      running: false,
      startedAt: 0,
      elapsedBeforePause: 0,
      frameId: null,
      currentTime: 0,
      currentPoint: null,
    };
  }

  function invalidateSimulation() {
    if (simulation.frameId) {
      cancelAnimationFrame(simulation.frameId);
    }
    simulation = emptySimulation();
    cutOrderPreview = [];
    if (project) {
      updateCutOrderInfo();
    }
    simulationInfoEl.textContent = "Simulation idle";
  }

  function numericSetting(value, fallback, min = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? Math.max(min, numeric) : fallback;
  }

  function normalizeTemplateDefaults(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    const outerDia = numericSetting(source.outer_dia_mm, 120, 1);
    const centerDia = Math.min(numericSetting(source.center_hole_dia_mm, 36, 0), Math.max(0, outerDia - 2));
    const width = numericSetting(source.plate_width_mm, 180, 1);
    const height = numericSetting(source.plate_height_mm, 100, 1);
    const boltCount = Math.max(0, Math.min(24, Math.round(numericSetting(source.bolt_count, 4, 0))));
    const boltDia = numericSetting(source.bolt_hole_dia_mm, 12, 0);
    const boltCircleDia = Math.min(
      numericSetting(source.bolt_circle_dia_mm, 90, 0),
      Math.max(0, outerDia - boltDia - 2)
    );
    return {
      outer_dia_mm: outerDia,
      center_hole_dia_mm: centerDia,
      plate_width_mm: width,
      plate_height_mm: height,
      bolt_count: boltCount,
      bolt_circle_dia_mm: boltCircleDia,
      bolt_hole_dia_mm: boltDia,
    };
  }

  function normalizeProject(value) {
    if (!value || typeof value !== "object") return null;
    value.format = value.format || projectFormat;
    value.format_version = projectFormatVersion;
    value.sheet = {
      width_mm: 1000,
      height_mm: 500,
      ...(value.sheet || {}),
    };
    delete value.sheet.margin_mm;
    value.spacing_mm = Number(value.spacing_mm ?? 8);
    value.cut = {
      material: "mild_steel",
      thickness_mm: 3,
      nozzle_mm: 0.9,
      feed_rate_mode: "auto",
      manual_feed_rate_mm_min: 1300,
      ...(value.cut || {}),
    };
    value.cut_chart = normalizeProjectCutChart(value.cut_chart);
    const postInput = value.post || {};
    const hasLegacySmallFeatureOverrides = [
      "small_hole_threshold_mm",
      "small_shape_threshold_mm",
      "small_hole_speed_percent",
      "small_hole_overburn_mm",
      "small_hole_torch_off_before_end_mm",
    ].some((field) => Object.prototype.hasOwnProperty.call(postInput, field));
    value.post = {
      lead_in_mode: "auto",
      lead_in_mm: 5,
      lead_out_mm: 0,
      lead_in_min_hole_diameter_mm: 20,
      pierce_crater_diameter_mm: 4,
      lead_clearance_mm: 1,
      qtplasmac_material_mode: "temporary",
      qtplasmac_material_number: 0,
      qtplasmac_material_wait_s: 1,
      safe_travel: true,
      travel_clearance_mm: 8,
      avoid_completed_contours: true,
      optimize_cut_order: true,
      keep_part_contours_together: true,
      cut_order_strategy: "nearest",
      cut_order_groups: [],
      heat_spread_weight: 0.35,
      heat_lookback: 3,
      small_feature_source: hasLegacySmallFeatureOverrides ? "manual" : "cut_chart",
      small_hole_threshold_mm: 37,
      small_shape_threshold_mm: 37,
      small_hole_speed_percent: 65,
      small_hole_overburn_mm: 0,
      small_hole_torch_off_before_end_mm: 0,
      auto_tabs: false,
      auto_tab_count: 2,
      auto_tab_length_mm: 8,
      auto_tab_min_outer_diameter_mm: 60,
      kerf_offset_fallback: "centerline",
      open_path_mode: "centerline",
      path_tolerance_mm: 0.1,
      precision: 3,
      ...postInput,
    };
    value.post.safe_travel = value.post.safe_travel !== false && value.post.avoid_completed_contours !== false;
    value.post.avoid_completed_contours = true;
    value.post.optimize_cut_order = value.post.optimize_cut_order !== false;
    value.post.keep_part_contours_together = value.post.keep_part_contours_together !== false;
    value.post.cut_order_strategy = normalizeCutOrderStrategy(value.post.cut_order_strategy);
    value.post.cut_order_groups = normalizeCutOrderGroups(
      value.post.cut_order_groups ?? value.post.cut_order_override
    );
    value.post.heat_spread_weight = Math.max(0, Number(value.post.heat_spread_weight ?? 0.35));
    value.post.heat_lookback = Math.max(1, Math.min(20, Math.round(Number(value.post.heat_lookback ?? 3))));
    value.post.small_feature_source = value.post.small_feature_source === "manual" ? "manual" : "cut_chart";
    value.post.auto_tabs = Boolean(value.post.auto_tabs);
    value.post.auto_tab_count = Math.max(1, Math.min(12, Math.round(Number(value.post.auto_tab_count ?? 2))));
    value.post.auto_tab_length_mm = Math.max(0, Number(value.post.auto_tab_length_mm ?? 8));
    value.post.auto_tab_min_outer_diameter_mm = Math.max(0, Number(value.post.auto_tab_min_outer_diameter_mm ?? 60));
    value.post.kerf_offset_fallback = value.post.kerf_offset_fallback === "block" ? "block" : "centerline";
    value.post.open_path_mode = value.post.open_path_mode === "block" ? "block" : "centerline";
    value.simulation = {
      playback_rate: 20,
      rapid_rate_mm_min: 8000,
      ...(value.simulation || {}),
    };
    value.ui = {
      tab_length_mm: 8,
      ...(value.ui || {}),
    };
    value.import_options = {
      auto_close_gaps: false,
      repair_geometry: false,
      unsafe_entity_policy: "warn",
      layer_mapping_mode: "heuristic",
      layer_mapping: {},
      ...(value.import_options || {}),
    };
    value.import_options.auto_close_gaps = Boolean(value.import_options.auto_close_gaps);
    value.import_options.repair_geometry = Boolean(value.import_options.repair_geometry);
    value.import_options.unsafe_entity_policy =
      value.import_options.unsafe_entity_policy === "block" ? "block" : "warn";
    value.import_options.layer_mapping_mode = normalizeLayerMappingMode(value.import_options.layer_mapping_mode);
    value.import_options.layer_mapping = normalizeLayerMappingObject(value.import_options.layer_mapping);
    value.manual_controls = {
      snap_enabled: false,
      snap_mm: 5,
      ...(value.manual_controls || {}),
    };
    value.manual_controls.snap_enabled = Boolean(value.manual_controls.snap_enabled);
    value.manual_controls.snap_mm = Math.max(0.1, Number(value.manual_controls.snap_mm || 5));
    value.template_defaults = normalizeTemplateDefaults(value.template_defaults);
    value.nesting = {
      auto_nest_attempts: 12,
      auto_nest_angle_step_deg: 30,
      auto_nest_max_runtime_s: 12,
      auto_nest_parallel_workers: 0,
      allow_arbitrary_rotation: true,
      allow_hole_filler: false,
      common_line_cutting: false,
      ...(value.nesting || {}),
    };
    value.nesting.run_history = Array.isArray(value.nesting.run_history)
      ? value.nesting.run_history.map(normalizeNestRun).filter(Boolean).slice(-20)
      : [];
    value.nesting.auto_nest_attempts = Math.max(1, Math.min(240, Math.round(Number(value.nesting.auto_nest_attempts || 12))));
    value.nesting.layout_mode = value.nesting.layout_mode === "compact" ? "compact" : "strip";
    value.nesting.auto_nest_angle_step_deg = Math.max(1, Math.min(90, Number(value.nesting.auto_nest_angle_step_deg || 30)));
    value.nesting.auto_nest_max_runtime_s = Math.max(1, Math.min(120, Number(value.nesting.auto_nest_max_runtime_s || 12)));
    value.nesting.auto_nest_parallel_workers = Math.max(0, Math.min(16, Math.round(Number(value.nesting.auto_nest_parallel_workers ?? 0))));
    value.nesting.allow_arbitrary_rotation = value.nesting.allow_arbitrary_rotation !== false;
    value.nesting.allow_hole_filler = Boolean(value.nesting.allow_hole_filler);
    value.nesting.common_line_cutting = Boolean(value.nesting.common_line_cutting);
    value.zones = Array.isArray(value.zones) ? value.zones.map(normalizeZone) : [];
    value.tabs = Array.isArray(value.tabs) ? value.tabs.map(normalizeTab).filter(Boolean) : [];
    value.lead_overrides = Array.isArray(value.lead_overrides)
      ? value.lead_overrides.map(normalizeLeadOverride).filter(Boolean)
      : [];
    value.parts = Array.isArray(value.parts) ? value.parts : [];
    const globalImportIssues = Array.isArray(value.import && value.import.issues)
      ? value.import.issues
      : [];
    value.parts = value.parts.map((part) => {
      const normalized = { ...part };
      normalized.name = String(normalized.name || "part");
      normalized.quantity = Math.max(1, Math.round(Number(normalized.quantity || 1)));
      normalized.source_file = normalized.source_file || normalized.file_name || normalized.name;
      normalized.source_part_name = normalized.source_part_name || normalized.name;
      normalized.grain_lock = Boolean(normalized.grain_lock);
      normalized.allow_hole_filler = normalized.allow_hole_filler !== false;
      normalized.allow_hole_parent = normalized.allow_hole_parent !== false;
      normalized.allowed_rotations = normalizeAllowedRotations(
        normalized.allowed_rotations,
        normalized.grain_lock ? [0] : [0, 90, 180, 270]
      );
      if (normalized.grain_lock) {
        normalized.allowed_rotations = [0];
      }
      if (!Array.isArray(normalized.import_issues)) {
        normalized.import_issues = value.parts.length === 1 ? globalImportIssues : [];
      }
      normalized.import_partial = Boolean(normalized.import_partial || normalized.import_issues.length);
      return normalized;
    });
    value.placements = Array.isArray(value.placements) ? value.placements : [];
    value.placements = value.placements.map((placement) => ({
      ...placement,
      part_name: String(placement.part_name || ""),
      instance: Math.max(1, Math.round(Number(placement.instance || 1))),
      dx: Number(placement.dx || 0),
      dy: Number(placement.dy || 0),
      rotation_deg: normalizeAngle(Number(placement.rotation_deg || 0)),
      locked: Boolean(placement.locked),
      manual: Boolean(placement.manual),
    }));
    return value;
  }

  function normalizeZone(zone) {
    const type = String(zone.type || "keepout");
    return {
      id: zone.id || uniqueId("zone"),
      type,
      name: zone.name || type,
      x_mm: Number(zone.x_mm ?? zone.x ?? 0),
      y_mm: Number(zone.y_mm ?? zone.y ?? 0),
      width_mm: Math.max(1, Number(zone.width_mm ?? zone.width ?? 100)),
      height_mm: Math.max(1, Number(zone.height_mm ?? zone.height ?? 60)),
      enabled: zone.enabled !== false,
    };
  }

  function normalizeTab(tab) {
    if (!tab || !tab.contour_name) return null;
    return {
      id: tab.id || uniqueId("tab"),
      contour_name: String(tab.contour_name),
      x_mm: Number(tab.x_mm ?? tab.x ?? 0),
      y_mm: Number(tab.y_mm ?? tab.y ?? 0),
      length_mm: Math.max(0, Number(tab.length_mm ?? tab.length ?? 8)),
    };
  }

  function normalizeLeadOverride(override) {
    if (!override || !override.contour_name) return null;
    return {
      id: override.id || uniqueId("lead"),
      contour_name: String(override.contour_name),
      start_x_mm: nullableNumber(override.start_x_mm ?? override.start_x),
      start_y_mm: nullableNumber(override.start_y_mm ?? override.start_y),
      pierce_x_mm: nullableNumber(override.pierce_x_mm ?? override.pierce_x),
      pierce_y_mm: nullableNumber(override.pierce_y_mm ?? override.pierce_y),
      lead_in_mode: override.lead_in_mode || null,
      lead_in_mm: nullableNumber(override.lead_in_mm ?? override.lead_in),
      lead_out_mm: nullableNumber(override.lead_out_mm ?? override.lead_out),
      auto_generated: Boolean(override.auto_generated),
    };
  }

  function normalizeProjectCutChart(chart) {
    if (!chart || typeof chart !== "object" || !Array.isArray(chart.rows)) return null;
    const rows = chart.rows.map(normalizeCutChartRow).filter(Boolean);
    if (!rows.length) return null;
    const normalized = {
      profile_id: String(chart.profile_id || chart.id || "project-cut-chart"),
      base_profile_id: chart.base_profile_id ? String(chart.base_profile_id) : null,
      version: String(chart.version || "project"),
      revision: String(chart.revision || chart.profile_revision || chart.version || "project"),
      updated_at: chart.updated_at ? String(chart.updated_at) : "",
      machine: String(chart.machine || "Fubag Plasma 40"),
      source: String(chart.source || "Project cut chart"),
      notes: Array.isArray(chart.notes) ? chart.notes.map((item) => String(item)) : [],
      rows,
    };
    if (chart.exported_at) normalized.exported_at = String(chart.exported_at);
    if (chart.imported_at) normalized.imported_at = String(chart.imported_at);
    if (chart.imported_from) normalized.imported_from = String(chart.imported_from);
    return normalized;
  }

  function normalizeCutChartRow(row) {
    if (!row || typeof row !== "object") return null;
    return {
      material: String(row.material || "mild_steel"),
      thickness_mm: Number(row.thickness_mm || 0),
      nozzle_mm: Number(row.nozzle_mm || 0),
      current_a: Math.max(0, Math.round(Number(row.current_a || 0))),
      feed_rate_mm_min: Math.max(1, Math.round(Number(row.feed_rate_mm_min || 1))),
      kerf_width_mm: Math.max(0, Number(row.kerf_width_mm || 0)),
      pierce_delay_s: Math.max(0, Number(row.pierce_delay_s || 0)),
      pierce_height_mm: Math.max(0, Number(row.pierce_height_mm ?? 3)),
      cut_height_mm: Math.max(0, Number(row.cut_height_mm ?? 1.5)),
      arc_voltage_v: nullableNumber(row.arc_voltage_v ?? row.cut_volts),
      thc_enabled: row.thc_enabled !== false,
      air_pressure_bar: Math.max(0, Number(row.air_pressure_bar ?? 5.0)),
      small_hole_threshold_mm: Math.max(0, Number(row.small_hole_threshold_mm ?? 37)),
      small_shape_threshold_mm: Math.max(0, Number(row.small_shape_threshold_mm ?? row.small_hole_threshold_mm ?? 37)),
      small_hole_speed_percent: Math.max(1, Math.min(100, Number(row.small_hole_speed_percent ?? 65))),
      small_hole_overburn_mm: Math.max(0, Number(row.small_hole_overburn_mm ?? 0)),
      small_hole_torch_off_before_end_mm: Math.max(0, Number(row.small_hole_torch_off_before_end_mm ?? 0)),
      notes: Array.isArray(row.notes) ? row.notes.map((item) => String(item)) : [],
      row_id: row.row_id ? String(row.row_id) : "",
      revision: row.revision || row.row_revision ? String(row.revision || row.row_revision) : "",
      calibration_state: String(row.calibration_state || "starter"),
      measured_at: row.measured_at ? String(row.measured_at) : "",
      operator: row.operator ? String(row.operator) : "",
      coupon_id: row.coupon_id ? String(row.coupon_id) : "",
      quality_notes: Array.isArray(row.quality_notes) ? row.quality_notes.map((item) => String(item)) : [],
    };
  }

  function nullableNumber(value) {
    return value === null || value === undefined || value === "" ? null : Number(value);
  }

  function uniqueId(prefix) {
    return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  }

  function saveProject({ publish = true } = {}) {
    if (!project) return;
    try {
      project.format = projectFormat;
      project.format_version = projectFormatVersion;
      localStorage.setItem(storageKey, JSON.stringify(project));
    } catch (error) {
      document.getElementById("workspaceStatus").textContent = "Local cache unavailable";
    }
    if (publish) sharedWorkspace.queue(project);
  }

  function cloneProjectState(value) {
    return value ? JSON.parse(JSON.stringify(value)) : null;
  }

  function captureHistoryState() {
    const state = {
      project: cloneProjectState(project),
      selectedKey: selectedKey || null,
      selectedZoneId: selectedZoneId || null,
      editorMode,
    };
    state.signature = historyStateSignature(state);
    return state;
  }

  function historyStateSignature(state) {
    return JSON.stringify({
      project: state.project,
      selectedKey: state.selectedKey || null,
      selectedZoneId: state.selectedZoneId || null,
      editorMode: state.editorMode || "select",
    });
  }

  function captureMutationHistory() {
    commitPendingControlHistory("Settings");
    return captureHistoryState();
  }

  function pushHistoryState(previousState, label) {
    if (historyRestoring || !previousState || !previousState.project || !project) return;
    const currentState = captureHistoryState();
    if (previousState.signature === currentState.signature) return;
    undoStack.push({ state: previousState, label });
    if (undoStack.length > historyLimit) {
      undoStack = undoStack.slice(-historyLimit);
    }
    redoStack = [];
    updateHistoryControls();
  }

  function beginControlHistory(control) {
    if (historyRestoring || !project) return;
    if (pendingControlHistory && pendingControlHistory.control !== control) {
      commitPendingControlHistory("Settings");
    }
    if (!pendingControlHistory) {
      pendingControlHistory = { control, state: captureHistoryState() };
    }
  }

  function commitPendingControlHistory(label) {
    if (!pendingControlHistory) return;
    const previous = pendingControlHistory.state;
    pendingControlHistory = null;
    pushHistoryState(previous, label);
  }

  function restoreHistoryState(state) {
    if (!state || !state.project) return;
    historyRestoring = true;
    project = normalizeProject(cloneProjectState(state.project));
    selectedKey = normalizedSelectedKey(state.selectedKey);
    selectedZoneId = state.selectedZoneId && zoneById(state.selectedZoneId) ? state.selectedZoneId : null;
    editorMode = state.editorMode || "select";
    dragging = null;
    invalidateSimulation();
    syncControlsFromProject();
    saveProject();
    draw();
    validateProject();
    historyRestoring = false;
  }

  function undoHistory() {
    if (autoNesting || importing || couponImporting) {
      setStatus("Busy");
      return;
    }
    commitPendingControlHistory("Settings");
    const entry = undoStack.pop();
    if (!entry) return;
    redoStack.push({ state: captureHistoryState(), label: entry.label });
    restoreHistoryState(entry.state);
    updateHistoryControls();
    setStatus(`Undo ${entry.label}`);
  }

  function redoHistory() {
    if (autoNesting || importing || couponImporting) {
      setStatus("Busy");
      return;
    }
    const entry = redoStack.pop();
    if (!entry) return;
    undoStack.push({ state: captureHistoryState(), label: entry.label });
    restoreHistoryState(entry.state);
    updateHistoryControls();
    setStatus(`Redo ${entry.label}`);
  }

  function updateHistoryControls() {
    const busy = Boolean(autoNesting || importing || couponImporting);
    clearSheetBtn.disabled = busy || !project || !["parts", "placements", "zones", "tabs", "lead_overrides"].some(key => project[key]?.length);
    if (undoBtn) {
      undoBtn.disabled = busy || !undoStack.length;
      undoBtn.title = undoStack.length ? `Undo ${undoStack[undoStack.length - 1].label} (Cmd/Ctrl+Z)` : "Undo (Cmd/Ctrl+Z)";
    }
    if (redoBtn) {
      redoBtn.disabled = busy || !redoStack.length;
      redoBtn.title = redoStack.length ? `Redo ${redoStack[redoStack.length - 1].label} (Cmd/Ctrl+Shift+Z / Ctrl+Y)` : "Redo (Cmd/Ctrl+Shift+Z / Ctrl+Y)";
    }
  }

  function parseProjectFile(content) {
    const parsed = JSON.parse(content);
    if (!parsed || typeof parsed !== "object") {
      throw new Error("Project file must contain an object");
    }
    if (parsed.format && parsed.format !== projectFormat) {
      throw new Error(`Unsupported project format ${parsed.format}`);
    }
    const version = Number(parsed.format_version || projectFormatVersion);
    if (version > projectFormatVersion) {
      throw new Error(`Unsupported project version ${parsed.format_version}`);
    }
    return normalizeProject(parsed);
  }

  function normalizeNestRun(run) {
    if (!run || typeof run !== "object") return null;
    return {
      ...run,
      run_id: Math.max(1, Math.round(Number(run.run_id || 1))),
      created_at: String(run.created_at || ""),
      attempt_count: Math.max(0, Math.round(Number(run.attempt_count || 0))),
      successful_attempt_count: Math.max(0, Math.round(Number(run.successful_attempt_count || 0))),
      runtime_ms: Number(run.runtime_ms || 0),
      part_instance_count: Math.max(0, Math.round(Number(run.part_instance_count || 0))),
      packing_utilization_percent: Number(run.packing_utilization_percent || 0),
      sheet_utilization_percent: Number(run.sheet_utilization_percent || 0),
      used_width_mm: Number(run.used_width_mm || 0),
      used_height_mm: Number(run.used_height_mm || 0),
      top_free_height_mm: Number(run.top_free_height_mm || 0),
      time_limited: Boolean(run.time_limited),
      lead_spacing_fallback: Boolean(run.lead_spacing_fallback),
      lead_spacing_fallback_skipped: run.lead_spacing_fallback_skipped ? String(run.lead_spacing_fallback_skipped) : "",
      hole_filler_relocation_count: Math.max(0, Math.round(Number(run.hole_filler_relocation_count || 0))),
      common_line_cutting: Boolean(run.common_line_cutting),
    };
  }

  function loadStoredProject() {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      const stored = parseProjectFile(raw);
      return stored && stored.parts.length ? stored : null;
    } catch (error) {
      return null;
    }
  }

  function pendingProjectRequested() {
    return new URLSearchParams(window.location.search).has("pending_project");
  }

  function clearPendingProjectRequest() {
    if (!pendingProjectRequested() || !window.history || !window.history.replaceState) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("pending_project");
    window.history.replaceState({}, "", url);
  }

  function activateLoadedProject(loadedProject, statusText) {
    project = normalizeProject(loadedProject);
    syncAllPartQuantities();
    rebuildProjectImportState();
    selectedKey = firstSelectablePlacementKey();
    invalidateSimulation();
    syncControlsFromProject();
    gcodeEl.value = "";
    issuesEl.textContent = "";
    saveProject();
    draw();
    validateProject({ persist: false });
    if (statusText) setStatus(statusText);
  }

  function syncControlsFromProject() {
    normalizeProject(project);
    controls.sheetWidth.value = project.sheet.width_mm;
    controls.sheetHeight.value = project.sheet.height_mm;
    controls.snapEnabled.checked = Boolean(project.manual_controls.snap_enabled);
    controls.snapMm.value = project.manual_controls.snap_mm;
    controls.templateOuterDia.value = project.template_defaults.outer_dia_mm;
    controls.templateCenterDia.value = project.template_defaults.center_hole_dia_mm;
    controls.templateWidth.value = project.template_defaults.plate_width_mm;
    controls.templateHeight.value = project.template_defaults.plate_height_mm;
    controls.templateBoltCount.value = project.template_defaults.bolt_count;
    controls.templateBoltCircleDia.value = project.template_defaults.bolt_circle_dia_mm;
    controls.templateBoltDia.value = project.template_defaults.bolt_hole_dia_mm;
    controls.spacing.value = project.spacing_mm;
    controls.nestLayoutMode.value = project.nesting.layout_mode;
    controls.nestAttempts.value = project.nesting.auto_nest_attempts;
    controls.nestAngleStep.value = project.nesting.auto_nest_angle_step_deg;
    controls.nestMaxRuntime.value = project.nesting.auto_nest_max_runtime_s;
    controls.nestWorkers.value = project.nesting.auto_nest_parallel_workers;
    controls.allowArbitraryRotation.checked = Boolean(project.nesting.allow_arbitrary_rotation);
    controls.allowHoleFiller.checked = Boolean(project.nesting.allow_hole_filler);
    controls.commonLineCutting.checked = Boolean(project.nesting.common_line_cutting);
    controls.safeTravel.checked = Boolean(project.post.safe_travel);
    controls.travelClearance.value = project.post.travel_clearance_mm;
    controls.travelClearance.disabled = !project.post.safe_travel;
    document.getElementById("travelModeInfo").textContent = project.post.safe_travel
      ? "Обход деталей и зон. Если пути нет — пауза M0 перед проблемным переходом."
      : "Прямые переходы: вырезанные детали и зоны не обходятся.";
    controls.thickness.value = project.cut.thickness_mm;
    controls.nozzle.value = project.cut.nozzle_mm;
    controls.feedMode.value = project.cut.feed_rate_mode;
    controls.manualFeed.value = project.cut.manual_feed_rate_mm_min;
    controls.materialMode.value = project.post.qtplasmac_material_mode;
    controls.materialNumber.value = project.post.qtplasmac_material_number;
    controls.materialWait.value = project.post.qtplasmac_material_wait_s;
    controls.cutOrderStrategy.value = normalizeCutOrderStrategy(project.post.cut_order_strategy);
    controls.optimizeCutOrder.checked = Boolean(project.post.optimize_cut_order);
    controls.keepPartContoursTogether.checked = Boolean(project.post.keep_part_contours_together);
    controls.heatSpreadWeight.value = project.post.heat_spread_weight;
    controls.heatLookback.value = project.post.heat_lookback;
    controls.cutOrderGroups.value = formatCutOrderGroups(project.post.cut_order_groups);
    controls.leadMode.value = project.post.lead_in_mode;
    controls.leadLength.value = project.post.lead_in_mm;
    controls.leadOutLength.value = project.post.lead_out_mm;
    controls.leadHoleMin.value = project.post.lead_in_min_hole_diameter_mm;
    controls.pierceCrater.value = project.post.pierce_crater_diameter_mm;
    controls.leadClearance.value = project.post.lead_clearance_mm;
    controls.smallFeatureSource.value = project.post.small_feature_source;
    controls.smallHoleThreshold.value = project.post.small_hole_threshold_mm;
    controls.smallShapeThreshold.value = project.post.small_shape_threshold_mm;
    controls.smallHoleSpeed.value = project.post.small_hole_speed_percent;
    controls.smallFeatureOverburn.value = project.post.small_hole_overburn_mm;
    controls.smallFeatureEarlyOff.value = project.post.small_hole_torch_off_before_end_mm;
    controls.tabLength.value = project.ui.tab_length_mm;
    controls.autoTabs.checked = Boolean(project.post.auto_tabs);
    controls.autoTabCount.value = project.post.auto_tab_count;
    controls.autoTabLength.value = project.post.auto_tab_length_mm;
    controls.autoTabMinDiameter.value = project.post.auto_tab_min_outer_diameter_mm;
    controls.centerlineFallback.checked = project.post.kerf_offset_fallback === "centerline";
    controls.openPathCenterline.checked = project.post.open_path_mode === "centerline";
    controls.importUnsafeEntityWarn.checked = project.import_options.unsafe_entity_policy === "warn";
    controls.importLayerMode.value = normalizeLayerMappingMode(project.import_options.layer_mapping_mode);
    controls.importLayerMapping.value = formatLayerMapping(project.import_options.layer_mapping);
    updateImportLayerInfo();
    controls.simPlayback.value = project.simulation.playback_rate;
    updateCutOrderInfo();
    updateFeedControls();
  }

  function syncProjectFromControls() {
    normalizeProject(project);
    project.sheet.width_mm = Number(controls.sheetWidth.value);
    project.sheet.height_mm = Number(controls.sheetHeight.value);
    project.manual_controls.snap_enabled = Boolean(controls.snapEnabled.checked);
    project.manual_controls.snap_mm = Math.max(0.1, Number(controls.snapMm.value || 5));
    project.template_defaults = normalizeTemplateDefaults({
      outer_dia_mm: controls.templateOuterDia.value,
      center_hole_dia_mm: controls.templateCenterDia.value,
      plate_width_mm: controls.templateWidth.value,
      plate_height_mm: controls.templateHeight.value,
      bolt_count: controls.templateBoltCount.value,
      bolt_circle_dia_mm: controls.templateBoltCircleDia.value,
      bolt_hole_dia_mm: controls.templateBoltDia.value,
    });
    project.spacing_mm = Number(controls.spacing.value);
    project.nesting.layout_mode = controls.nestLayoutMode.value;
    project.nesting.auto_nest_attempts = Math.max(1, Math.min(240, Math.round(Number(controls.nestAttempts.value || 12))));
    project.nesting.auto_nest_angle_step_deg = Math.max(1, Math.min(90, Number(controls.nestAngleStep.value || 30)));
    project.nesting.auto_nest_max_runtime_s = Math.max(1, Math.min(120, Number(controls.nestMaxRuntime.value || 12)));
    project.nesting.auto_nest_parallel_workers = Math.max(0, Math.min(16, Math.round(Number(controls.nestWorkers.value ?? 0))));
    project.nesting.allow_arbitrary_rotation = Boolean(controls.allowArbitraryRotation.checked);
    project.nesting.allow_hole_filler = Boolean(controls.allowHoleFiller.checked);
    project.nesting.common_line_cutting = Boolean(controls.commonLineCutting.checked);
    project.post.safe_travel = Boolean(controls.safeTravel.checked);
    controls.travelClearance.disabled = !project.post.safe_travel;
    document.getElementById("travelModeInfo").textContent = project.post.safe_travel
      ? "Обход деталей и зон. Если пути нет — пауза M0 перед проблемным переходом."
      : "Прямые переходы: вырезанные детали и зоны не обходятся.";
    project.post.travel_clearance_mm = Number(controls.travelClearance.value);
    project.cut.thickness_mm = Number(controls.thickness.value);
    project.cut.nozzle_mm = Number(controls.nozzle.value);
    project.cut.feed_rate_mode = controls.feedMode.value;
    project.cut.manual_feed_rate_mm_min = Number(controls.manualFeed.value);
    project.post.qtplasmac_material_mode = controls.materialMode.value;
    project.post.qtplasmac_material_number = Math.max(0, Math.round(Number(controls.materialNumber.value || 0)));
    project.post.qtplasmac_material_wait_s = Number(controls.materialWait.value);
    project.post.cut_order_strategy = normalizeCutOrderStrategy(controls.cutOrderStrategy.value);
    project.post.optimize_cut_order = Boolean(controls.optimizeCutOrder.checked);
    project.post.keep_part_contours_together = Boolean(controls.keepPartContoursTogether.checked);
    project.post.avoid_completed_contours = true;
    project.post.heat_spread_weight = Math.max(0, Number(controls.heatSpreadWeight.value || 0));
    project.post.heat_lookback = Math.max(1, Math.min(20, Math.round(Number(controls.heatLookback.value || 3))));
    project.post.cut_order_groups = normalizeCutOrderGroups(controls.cutOrderGroups.value);
    project.post.lead_in_mode = controls.leadMode.value;
    project.post.lead_in_mm = Number(controls.leadLength.value);
    project.post.lead_out_mm = Number(controls.leadOutLength.value);
    project.post.lead_in_min_hole_diameter_mm = Number(controls.leadHoleMin.value);
    project.post.pierce_crater_diameter_mm = Number(controls.pierceCrater.value);
    project.post.lead_clearance_mm = Number(controls.leadClearance.value);
    project.post.small_feature_source = controls.smallFeatureSource.value === "manual" ? "manual" : "cut_chart";
    project.post.small_hole_threshold_mm = Number(controls.smallHoleThreshold.value);
    project.post.small_shape_threshold_mm = Number(controls.smallShapeThreshold.value);
    project.post.small_hole_speed_percent = Number(controls.smallHoleSpeed.value);
    project.post.small_hole_overburn_mm = Number(controls.smallFeatureOverburn.value);
    project.post.small_hole_torch_off_before_end_mm = Number(controls.smallFeatureEarlyOff.value);
    project.post.auto_tabs = Boolean(controls.autoTabs.checked);
    project.post.auto_tab_count = Math.max(1, Math.min(12, Math.round(Number(controls.autoTabCount.value || 2))));
    project.post.auto_tab_length_mm = Math.max(0, Number(controls.autoTabLength.value || 0));
    project.post.auto_tab_min_outer_diameter_mm = Math.max(0, Number(controls.autoTabMinDiameter.value || 0));
    project.post.kerf_offset_fallback = controls.centerlineFallback.checked ? "centerline" : "block";
    project.post.open_path_mode = controls.openPathCenterline.checked ? "centerline" : "block";
    project.ui.tab_length_mm = Number(controls.tabLength.value);
    project.import_options.unsafe_entity_policy = controls.importUnsafeEntityWarn.checked ? "warn" : "block";
    project.import_options.layer_mapping_mode = normalizeLayerMappingMode(controls.importLayerMode.value);
    const parsedLayerMapping = parseLayerMappingText(controls.importLayerMapping.value);
    importLayerMappingErrors = parsedLayerMapping.errors;
    project.import_options.layer_mapping = parsedLayerMapping.mapping;
    updateImportLayerInfo();
    project.simulation.playback_rate = Number(controls.simPlayback.value);
    updateCutOrderInfo();
    updateFeedControls();
  }

  function normalizeCutOrderStrategy(value) {
    const strategy = String(value || "nearest");
    return cutOrderStrategies.has(strategy) ? strategy : "nearest";
  }

  function normalizeCutOrderGroups(value) {
    const rawItems = Array.isArray(value)
      ? value
      : String(value || "").split(/[\n,]+/);
    const groups = [];
    const seen = new Set();
    for (const item of rawItems) {
      const group = String(item || "").trim();
      if (!group || seen.has(group)) continue;
      seen.add(group);
      groups.push(group);
    }
    return groups;
  }

  function formatCutOrderGroups(value) {
    return normalizeCutOrderGroups(value).join("\n");
  }

  function updateCutOrderInfo() {
    if (!cutOrderInfoEl || !project) return;
    const groups = normalizeCutOrderGroups(project.post.cut_order_groups);
    const strategy = normalizeCutOrderStrategy(project.post.cut_order_strategy).replace(/_/g, " ");
    const mode = project.post.optimize_cut_order ? strategy : "file order";
    const parts = [
      `Order: ${mode}`,
      project.post.keep_part_contours_together ? "grouped by part" : "contours independent",
      project.post.avoid_completed_contours ? "safe travel avoids cutouts" : "completed cutouts ignored",
      groups.length ? `${groups.length} manual group(s)` : null,
      cutOrderPreview.length ? `Preview ${cutOrderPreview.length} cuts` : null,
    ].filter(Boolean);
    cutOrderInfoEl.textContent = parts.join(", ");
  }

  function normalizeLayerMappingMode(value) {
    const mode = String(value || "heuristic");
    return layerMappingModes.has(mode) ? mode : "heuristic";
  }

  function normalizeLayerName(value) {
    return String(value || "").trim().toUpperCase();
  }

  function normalizeLayerProcess(value) {
    const key = String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    if (layerProcesses.has(key)) return key;
    return layerProcessAliases[key] || null;
  }

  function normalizeLayerMappingObject(rawMapping) {
    if (!rawMapping || typeof rawMapping !== "object") return {};
    const output = {};
    for (const [rawLayerOrProcess, rawProcessOrLayers] of Object.entries(rawMapping)) {
      const processKey = normalizeLayerProcess(rawLayerOrProcess);
      if (processKey && Array.isArray(rawProcessOrLayers)) {
        for (const rawLayer of rawProcessOrLayers) {
          const layer = normalizeLayerName(rawLayer);
          if (layer) output[layer] = processKey;
        }
        continue;
      }
      const process = normalizeLayerProcess(rawProcessOrLayers);
      const layer = normalizeLayerName(rawLayerOrProcess);
      if (layer && process) output[layer] = process;
    }
    return output;
  }

  function splitLayerList(value) {
    return String(value || "")
      .split(",")
      .map((item) => normalizeLayerName(item))
      .filter(Boolean);
  }

  function parseLayerMappingText(text) {
    const mapping = {};
    const errors = [];
    String(text || "")
      .split(/\r?\n/)
      .forEach((rawLine, index) => {
        const line = rawLine.replace(/[;#].*$/, "").trim();
        if (!line) return;
        const separator = line.includes("=") ? "=" : line.includes(":") ? ":" : null;
        let left = "";
        let right = "";
        if (separator) {
          const parts = line.split(separator);
          left = parts.shift().trim();
          right = parts.join(separator).trim();
        } else {
          const parts = line.split(/\s+/);
          left = parts.shift() || "";
          right = parts.join(" ");
        }
        const leftProcess = normalizeLayerProcess(left);
        const rightProcess = normalizeLayerProcess(right);
        if (leftProcess && !rightProcess) {
          const layers = splitLayerList(right);
          if (!layers.length) {
            errors.push(`Line ${index + 1}: no layer names`);
            return;
          }
          for (const layer of layers) mapping[layer] = leftProcess;
          return;
        }
        if (rightProcess) {
          const layers = splitLayerList(left);
          if (!layers.length) {
            errors.push(`Line ${index + 1}: no layer names`);
            return;
          }
          for (const layer of layers) mapping[layer] = rightProcess;
          return;
        }
        errors.push(`Line ${index + 1}: unknown process`);
      });
    return { mapping, errors };
  }

  function formatLayerMapping(mapping) {
    return Object.entries(normalizeLayerMappingObject(mapping))
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([layer, process]) => `${layer}=${process}`)
      .join("\n");
  }

  function extractDxfLayerNames(content) {
    const layers = new Set();
    const lines = String(content || "").split(/\r\n|\n|\r/);
    for (let index = 0; index < lines.length - 1; index += 1) {
      if (lines[index].trim() === "8") {
        const layer = normalizeLayerName(lines[index + 1]);
        if (layer && layer !== "0") layers.add(layer);
      }
    }
    return [...layers].sort((left, right) => left.localeCompare(right));
  }

  function resolveDxfLayerMappingForImport(content, importOptions) {
    const mode = normalizeLayerMappingMode(importOptions.layer_mapping_mode);
    const explicit = normalizeLayerMappingObject(importOptions.layer_mapping);
    const layerNames = extractDxfLayerNames(content);
    const mapping = {};
    if (mode === "cut_all" || mode === "mapped_only") {
      const defaultProcess = mode === "cut_all" ? "cut" : "ignore";
      for (const layerName of layerNames) {
        mapping[layerName] = defaultProcess;
      }
    }
    return {
      layerNames,
      mapping: {
        ...mapping,
        ...explicit,
      },
    };
  }

  function buildDxfImportPlan(content) {
    const parsedLayerMapping = parseLayerMappingText(controls.importLayerMapping.value);
    importLayerMappingErrors = parsedLayerMapping.errors;
    project.import_options.layer_mapping_mode = normalizeLayerMappingMode(controls.importLayerMode.value);
    project.import_options.layer_mapping = parsedLayerMapping.mapping;
    if (importLayerMappingErrors.length) {
      updateImportLayerInfo();
      return null;
    }
    const { layerNames, mapping } = resolveDxfLayerMappingForImport(content, project.import_options);
    updateImportLayerInfo(layerNames.length, Object.keys(mapping).length);
    return {
      content,
      importOptions: {
        ...project.import_options,
        layer_mapping: mapping,
      },
      uiImportOptions: cloneProjectState(project.import_options),
    };
  }

  function updateImportLayerInfo(layerCount = null, effectiveCount = null) {
    if (!importLayerInfoEl || !project) return;
    const explicitCount = Object.keys(normalizeLayerMappingObject(project.import_options.layer_mapping)).length;
    const mode = normalizeLayerMappingMode(project.import_options.layer_mapping_mode).replace(/_/g, " ");
    if (importLayerMappingErrors.length) {
      importLayerInfoEl.textContent = `Layer map error: ${importLayerMappingErrors[0]}`;
      return;
    }
    const suffix = layerCount === null
      ? ""
      : `, ${layerCount} DXF layer(s), ${effectiveCount ?? explicitCount} import rule(s)`;
    importLayerInfoEl.textContent = `${mode}, ${explicitCount} explicit rule(s)${suffix}`;
  }

  function updateFeedControls() {
    controls.manualFeed.disabled = controls.feedMode.value !== "manual";
    const fixedMaterial = controls.materialMode.value === "fixed";
    controls.materialNumber.disabled = !fixedMaterial;
    controls.materialWait.disabled = !fixedMaterial;
  }

  function partDef(name) {
    return project.parts.find((part) => part.name === name);
  }

  function isDisplayablePart(part) {
    return Boolean(part && partContours(part).length);
  }

  function isSelectablePlacement(placement) {
    return Boolean(placement && isDisplayablePart(partDef(placement.part_name)));
  }

  function firstSelectablePlacementKey() {
    const placement = project && project.placements.find(isSelectablePlacement);
    return placement ? keyForPlacement(placement) : null;
  }

  function normalizedSelectedKey(key) {
    const placement = key ? placementByKey(key) : null;
    return placement && isSelectablePlacement(placement) ? key : firstSelectablePlacementKey();
  }

  function placementByKey(key) {
    return project.placements.find((placement) => keyForPlacement(placement) === key);
  }

  function ensureSelectedPlacement() {
    selectedKey = normalizedSelectedKey(selectedKey);
    if (selectedKey) selectedZoneId = null;
    return selectedKey;
  }

  function placementCount(partName) {
    return project.placements.filter((placement) => placement.part_name === partName).length;
  }

  function syncPartQuantity(partName) {
    const part = partDef(partName);
    if (part) {
      part.quantity = Math.max(1, placementCount(partName));
    }
  }

  function syncAllPartQuantities() {
    for (const part of project.parts) {
      if (!isDisplayablePart(part)) continue;
      const desired = Math.max(1, Math.round(Number(part.quantity || 1)), placementCount(part.name));
      while (placementCount(part.name) < desired) {
        project.placements.push(defaultPlacementForPart(part, nextInstance(part.name)));
      }
      syncPartQuantity(part.name);
    }
  }

  function partSourceLabel(part) {
    return part.source_file || part.file_name || part.name;
  }

  function partPolicyLabel(part) {
    const items = [part.name];
    if (part.grain_lock) items.push("grain");
    if (part.allow_hole_filler === false) items.push("no filler");
    if (part.allow_hole_parent === false) items.push("no host");
    const rotations = normalizeAllowedRotations(part.allowed_rotations);
    if (!part.grain_lock && rotations.join(",") !== "0,90,180,270") {
      items.push(`rot ${rotations.join("/")}`);
    }
    return items.join(" | ");
  }

  function partImportIssues(part) {
    return Array.isArray(part.import_issues) ? part.import_issues : [];
  }

  function isReviewRequiredImportIssue(issue) {
    return !issue || issue.review_required === true || issue.blocking !== false;
  }

  function rebuildProjectImportState() {
    if (!project) return;
    const issues = [];
    for (const part of project.parts) {
      for (const issue of partImportIssues(part)) {
        const message = issue.message || issue.code || "DXF import issue";
        issues.push({
          ...issue,
          message: `${partSourceLabel(part)}: ${message}`,
        });
      }
    }
    const previous = project.import || {};
    project.import = {
      ...previous,
      source: issues.length || project.parts.some((part) => part.import_source === "dxf") ? "mixed" : previous.source,
      safe_for_export: true,
      partial: issues.length > 0,
      blocking_issue_count: 0,
      review_required_issue_count: issues.filter(isReviewRequiredImportIssue).length,
      warning_count: issues.length,
      issues,
    };
  }

  function uniquePartName(name, usedNames) {
    const base = String(name || "part").replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "part";
    if (!usedNames.has(base)) {
      usedNames.add(base);
      return base;
    }
    let index = 2;
    while (usedNames.has(`${base}_${index}`)) {
      index += 1;
    }
    const value = `${base}_${index}`;
    usedNames.add(value);
    return value;
  }

  function setupTabs() {
    const buttons = [...document.querySelectorAll(".tab-btn")];
    const panels = [...document.querySelectorAll(".sidebar-panel")];
    function selectTab(tab) {
      buttons.forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
      panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.tabPanel === tab));
    }
    buttons.forEach((button) => {
      button.addEventListener("click", () => selectTab(button.dataset.tab));
    });
  }

  function manualSnapStep() {
    return Math.max(0.1, Number(project.manual_controls && project.manual_controls.snap_mm) || 5);
  }

  function snapCoordinate(value) {
    if (!project || !project.manual_controls || !project.manual_controls.snap_enabled) {
      return value;
    }
    const step = manualSnapStep();
    return Math.round(value / step) * step;
  }

  function snapPlacementPoint(point) {
    return {
      x: snapCoordinate(point.x),
      y: snapCoordinate(point.y),
    };
  }

  function templateMetadata(name, type) {
    return {
      name,
      quantity: 1,
      source_file: `template:${type}`,
      source_part_name: type,
      import_source: "template",
      allowed_rotations: [0, 90, 180, 270],
      grain_lock: false,
      allow_hole_filler: true,
      allow_hole_parent: true,
      import_issues: [],
      import_partial: false,
    };
  }

  function templatePartFromType(type, name) {
    const defaults = normalizeTemplateDefaults(project ? project.template_defaults : {});
    const outerRadius = defaults.outer_dia_mm / 2;
    const centerRadius = boundedHoleRadius(defaults.center_hole_dia_mm, outerRadius);
    const boltRadius = boundedHoleRadius(defaults.bolt_hole_dia_mm, outerRadius);
    if (type === "plate") {
      const width = defaults.plate_width_mm;
      const height = defaults.plate_height_mm;
      const plateBoltRadius = Math.max(0, defaults.bolt_hole_dia_mm / 2);
      const holeRadius = Math.min(plateBoltRadius, Math.max(0, Math.min(width, height) / 2 - 2));
      const inset = Math.max(15, holeRadius * 3);
      const hx = Math.max(0, width / 2 - inset);
      const hy = Math.max(0, height / 2 - inset);
      const holes = holeRadius > 0 && hx > 0 && hy > 0
        ? [
            circleContour(`${name}_hole_1`, -hx, -hy, holeRadius, "hole"),
            circleContour(`${name}_hole_2`, hx, -hy, holeRadius, "hole"),
            circleContour(`${name}_hole_3`, hx, hy, holeRadius, "hole"),
            circleContour(`${name}_hole_4`, -hx, hy, holeRadius, "hole"),
          ]
        : [];
      return {
        ...templateMetadata(name, type),
        contours: [
          rectangleContour(`${name}_outer`, width, height, "outer"),
          ...holes,
        ],
      };
    }
    if (type === "flange") {
      const holes = [];
      if (centerRadius > 0) {
        holes.push({ type: "circle", x: 0, y: 0, radius_mm: centerRadius });
      }
      if (boltRadius > 0 && defaults.bolt_count > 0 && defaults.bolt_circle_dia_mm > 0) {
        const boltCircleRadius = Math.min(defaults.bolt_circle_dia_mm / 2, Math.max(0, outerRadius - boltRadius - 1));
        if (boltCircleRadius > 0) {
          for (let index = 0; index < defaults.bolt_count; index += 1) {
            const angle = (Math.PI * 2 * index) / defaults.bolt_count;
            holes.push({
              type: "circle",
              x: Math.cos(angle) * boltCircleRadius,
              y: Math.sin(angle) * boltCircleRadius,
              radius_mm: boltRadius,
            });
          }
        }
      }
      return {
        ...templateMetadata(name, type),
        outer: { type: "circle", x: 0, y: 0, radius_mm: outerRadius },
        holes,
      };
    }
    const holes = centerRadius > 0 ? [{ type: "circle", x: 0, y: 0, radius_mm: centerRadius }] : [];
    return {
      ...templateMetadata(name, "disk"),
      outer: { type: "circle", x: 0, y: 0, radius_mm: outerRadius },
      holes,
    };
  }

  function mirroredPartFrom(part, mirroredName) {
    const bounds = partBounds(part);
    const mirrorX = (bounds.minX + bounds.maxX) / 2;
    const contours = partContours(part).map((contour) => mirrorContour(contour, mirrorX, part.name, mirroredName));
    const mirrored = {
      ...part,
      name: mirroredName,
      quantity: 1,
      contours,
      source_file: `${partSourceLabel(part)} mirrored`,
      mirrored_from: part.name,
    };
    delete mirrored.outer;
    delete mirrored.holes;
    return mirrored;
  }

  function enabledZonesOfTypes(types) {
    const typeSet = new Set(types);
    return (project.zones || []).filter((zone) => zone.enabled !== false && typeSet.has(String(zone.type || "keepout")));
  }

  function effectivePreviewSpacing() {
    if (project.nesting && project.nesting.common_line_cutting) return 0;
    return Math.max(0, Number(project.spacing_mm || 0));
  }

  function placementPreviewIssue(placement) {
    const part = placement ? partDef(placement.part_name) : null;
    if (!placement || !part) return null;
    const key = keyForPlacement(placement);
    const box = placementWorldBounds(part, placement);
    const usable = usableSheetBounds();
    if (!boxInside(box, usable)) {
      return { code: "sheet_bounds", message: "outside sheet" };
    }

    const spacing = effectivePreviewSpacing();
    const checkPartBounds = !validatedLayout || validatedLayout.signature !== layoutGeometrySignature() || validatedLayout.possibleCollision;
    for (const other of checkPartBounds ? project.placements || [] : []) {
      const otherKey = keyForPlacement(other);
      if (otherKey === key) continue;
      const otherPart = partDef(other.part_name);
      if (!otherPart) continue;
      if (boxesOverlap(box, placementWorldBounds(otherPart, other), spacing)) {
        return { code: "part_collision", message: `collision/spacing with ${otherKey}` };
      }
    }

    for (const zone of enabledZonesOfTypes(["keepout", "clamp", "damaged", "slat"])) {
      if (boxesOverlap(box, zoneBounds(zone), 0)) {
        return { code: "zone_collision", message: `inside ${zone.type} zone` };
      }
    }

    const remnants = enabledZonesOfTypes(["remnant"]);
    if (remnants.length && !remnants.some((zone) => boxInside(box, zoneBounds(zone)))) {
      return { code: "outside_remnant", message: "outside remnant" };
    }
    return null;
  }

  function layoutGeometrySignature() {
    return JSON.stringify([project.sheet, project.spacing_mm, project.nesting?.common_line_cutting, project.parts, project.placements, project.zones]);
  }

  function usableSheetBounds() {
    return {
      minX: 0,
      minY: 0,
      maxX: Number(project.sheet.width_mm || 0),
      maxY: Number(project.sheet.height_mm || 0),
    };
  }

  function nextInstance(partName) {
    const instances = project.placements
      .filter((placement) => placement.part_name === partName)
      .map((placement) => placement.instance);
    return instances.length ? Math.max(...instances) + 1 : 1;
  }

  function worldToScreen(point) {
    return {
      x: view.originX + point.x * view.scale,
      y: view.originY - point.y * view.scale,
    };
  }

  function screenToWorld(point) {
    return {
      x: (point.x - view.originX) / view.scale,
      y: (view.originY - point.y) / view.scale,
    };
  }

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function configureView() {
    if (dragging && dragging.view) {
      view = { ...dragging.view };
      return;
    }
    const area = viewArea();
    const bounds = viewBounds();
    const pad = 42;
    const width = Math.max(1, bounds.maxX - bounds.minX);
    const height = Math.max(1, bounds.maxY - bounds.minY);
    const fitScale = Math.max(1e-9, Math.min(area.width / width, area.height / height));
    const scale = fitScale * viewState.zoom;
    const targetWidth = width * scale;
    const targetHeight = height * scale;
    const left = area.left + (area.width - targetWidth) / 2 + viewState.panX;
    const top = area.top + (area.height - targetHeight) / 2 + viewState.panY;
    view = {
      scale,
      pad,
      originX: left - bounds.minX * scale,
      originY: top + bounds.maxY * scale,
    };
  }

  function viewArea() {
    const rect = canvas.getBoundingClientRect();
    const top = Math.max(42, viewToolbar.getBoundingClientRect().bottom - rect.top + 12);
    return { left: 42, top, width: Math.max(1, rect.width - 84), height: Math.max(1, rect.height - top - 42) };
  }

  function loadViewState() {
    const defaults = { mode: "sheet", zoom: 1, bounds: null, panX: 0, panY: 0 };
    try {
      const stored = JSON.parse(localStorage.getItem(viewStorageKey));
      if (!stored || typeof stored !== "object") return defaults;
      const bounds = stored.bounds;
      const validBounds = bounds && [bounds.minX, bounds.minY, bounds.maxX, bounds.maxY].every(Number.isFinite)
        && bounds.maxX > bounds.minX && bounds.maxY > bounds.minY;
      return { mode: stored.mode === "parts" && validBounds ? "parts" : "sheet",
        zoom: Number.isFinite(stored.zoom) ? clamp(stored.zoom, 0.05, 50) : 1,
        bounds: validBounds ? bounds : null,
        panX: Number.isFinite(stored.panX) ? stored.panX : 0,
        panY: Number.isFinite(stored.panY) ? stored.panY : 0 };
    } catch (error) {
      return defaults;
    }
  }

  function saveViewState() {
    try {
      localStorage.setItem(viewStorageKey, JSON.stringify(viewState));
    } catch (error) {
      return;
    }
  }

  function viewBounds() {
    if (viewState.mode === "parts" && viewState.bounds) {
      return viewState.bounds;
    }
    return sheetViewBounds();
  }

  function sheetViewBounds() {
    return {
      minX: 0,
      minY: 0,
      maxX: Number(project.sheet.width_mm || 1),
      maxY: Number(project.sheet.height_mm || 1),
    };
  }

  function partsViewBounds() {
    const bounds = placedPartsBounds();
    if (!bounds) return null;
    const padMm = Math.max(10, Number(project.spacing_mm || 0) * 2);
    return {
      minX: bounds.minX - padMm,
      minY: bounds.minY - padMm,
      maxX: bounds.maxX + padMm,
      maxY: bounds.maxY + padMm,
    };
  }

  function placedPartsBounds() {
    const boxes = [];
    for (const placement of project.placements) {
      const part = partDef(placement.part_name);
      if (!part) continue;
      boxes.push(placementWorldBounds(part, placement));
    }
    if (!boxes.length) return null;
    return {
      minX: Math.min(...boxes.map((box) => box.minX)),
      minY: Math.min(...boxes.map((box) => box.minY)),
      maxX: Math.max(...boxes.map((box) => box.maxX)),
      maxY: Math.max(...boxes.map((box) => box.maxY)),
    };
  }

  function setViewZoom(zoom, anchor = null) {
    if (!project || dragging || panning || !Number.isFinite(zoom)) return;
    configureView();
    const area = viewArea();
    const point = anchor || { x: area.left + area.width / 2, y: area.top + area.height / 2 };
    const world = screenToWorld(point);
    viewState.zoom = clamp(zoom, 0.05, 50);
    configureView();
    const moved = worldToScreen(world);
    viewState.panX += point.x - moved.x;
    viewState.panY += point.y - moved.y;
    saveViewState();
    drawViewChange();
  }

  function zoomView(factor, anchor = null) {
    setViewZoom(viewState.zoom * factor, anchor);
  }

  function fitSheetView() {
    viewState = { mode: "sheet", zoom: 1, bounds: null, panX: 0, panY: 0 };
    saveViewState();
    drawViewChange();
  }

  function fitPartsView() {
    viewState = { mode: "parts", zoom: 1, bounds: partsViewBounds() || sheetViewBounds(), panX: 0, panY: 0 };
    saveViewState();
    drawViewChange();
  }

  function drawViewChange() {
    if (viewRedrawFrame) {
      cancelAnimationFrame(viewRedrawFrame);
      viewRedrawFrame = null;
    }
    draw();
    viewRedrawFrame = requestAnimationFrame(() => {
      viewRedrawFrame = null;
      draw();
    });
  }

  function updateZoomLabel() {
    if (document.activeElement !== zoomPercentEl) zoomPercentEl.value = String(Math.round(viewState.zoom * 1000) / 10);
  }

  function updatePanCursor() {
    canvas.classList.toggle("pan-ready", panMode || spacePan);
    canvas.classList.toggle("pan-active", Boolean(panning));
    panViewBtn.setAttribute("aria-pressed", String(panMode));
  }

  function finishPanning() {
    if (panning) saveViewState();
    panning = null;
    updatePanCursor();
  }

  function togglePanMode() {
    if (dragging) return;
    finishPanning();
    panMode = !panMode;
    updatePanCursor();
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function formatValue(value, fallback = "") {
    return value === null || value === undefined || Number.isNaN(Number(value)) ? fallback : String(value);
  }

  function draw() {
    if (!project) return;
    resizeCanvas();
    configureView();
    const rect = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);
    drawSheet();
    drawZones();
    drawPlacements();
    if (editorMode === "lead") {
      drawLeadSafetyPreview();
    }
    drawTabsAndLeads();
    drawCutOrderPreview();
    drawSimulation();
    updateZoomLabel();
    updateSelectedInfo();
    renderPartsTable();
    renderZonesList();
    updateLeadEditInfo();
    updateNestingInfo();
    updateNestHistoryInfo();
    updateHistoryControls();
  }

  function drawSheet() {
    const sheetW = project.sheet.width_mm;
    const sheetH = project.sheet.height_mm;
    const origin = worldToScreen({ x: 0, y: 0 });
    const far = worldToScreen({ x: sheetW, y: sheetH });
    const x = far.x;
    const y = far.y;
    const w = origin.x - far.x;
    const h = origin.y - far.y;

    ctx.save();
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#8d98a6";
    ctx.lineWidth = 1;
    ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x, y, w, h);

    ctx.strokeStyle = "#eef1f4";
    ctx.lineWidth = 1;
    const grid = 50;
    for (let gx = grid; gx < sheetW; gx += grid) {
      const p0 = worldToScreen({ x: gx, y: 0 });
      const p1 = worldToScreen({ x: gx, y: sheetH });
      ctx.beginPath();
      ctx.moveTo(p0.x, p0.y);
      ctx.lineTo(p1.x, p1.y);
      ctx.stroke();
    }
    for (let gy = grid; gy < sheetH; gy += grid) {
      const p0 = worldToScreen({ x: 0, y: gy });
      const p1 = worldToScreen({ x: sheetW, y: gy });
      ctx.beginPath();
      ctx.moveTo(p0.x, p0.y);
      ctx.lineTo(p1.x, p1.y);
      ctx.stroke();
    }
    ctx.restore();
    drawRulers();
  }

  function drawRulers() {
    const sheetW = project.sheet.width_mm;
    const sheetH = project.sheet.height_mm;
    const xStep = niceRulerStep(sheetW);
    const yStep = niceRulerStep(sheetH);
    const origin = worldToScreen({ x: 0, y: 0 });
    const top = worldToScreen({ x: 0, y: sheetH });
    const right = worldToScreen({ x: sheetW, y: 0 });

    ctx.save();
    ctx.strokeStyle = "#4b5563";
    ctx.fillStyle = "#4b5563";
    ctx.lineWidth = 1;
    ctx.font = "11px system-ui";
    ctx.textBaseline = "middle";

    ctx.beginPath();
    ctx.moveTo(origin.x, origin.y);
    ctx.lineTo(right.x, right.y);
    ctx.moveTo(origin.x, origin.y);
    ctx.lineTo(top.x, top.y);
    ctx.stroke();

    ctx.textAlign = "center";
    for (let x = 0; x <= sheetW + 0.001; x += xStep) {
      const point = worldToScreen({ x, y: 0 });
      ctx.beginPath();
      ctx.moveTo(point.x, point.y);
      ctx.lineTo(point.x, point.y + 7);
      ctx.stroke();
      ctx.fillText(String(Math.round(x)), point.x, point.y + 18);
    }

    ctx.textAlign = "right";
    for (let y = 0; y <= sheetH + 0.001; y += yStep) {
      const point = worldToScreen({ x: 0, y });
      ctx.beginPath();
      ctx.moveTo(point.x - 7, point.y);
      ctx.lineTo(point.x, point.y);
      ctx.stroke();
      ctx.fillText(String(Math.round(y)), point.x - 10, point.y);
    }

    ctx.textAlign = "right";
    ctx.fillText("X mm", right.x, origin.y + 33);
    ctx.save();
    ctx.translate(origin.x - 32, top.y);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "right";
    ctx.fillText("Y mm", 0, 0);
    ctx.restore();
    ctx.restore();
  }

  function drawZones() {
    if (!project.zones.length) return;
    ctx.save();
    for (const zone of project.zones) {
      const a = worldToScreen({ x: zone.x_mm, y: zone.y_mm });
      const b = worldToScreen({ x: zone.x_mm + zone.width_mm, y: zone.y_mm + zone.height_mm });
      const x = Math.min(a.x, b.x);
      const y = Math.min(a.y, b.y);
      const w = Math.abs(b.x - a.x);
      const h = Math.abs(b.y - a.y);
      const colors = zoneColors(zone.type);
      ctx.fillStyle = colors.fill;
      ctx.strokeStyle = zone.id === selectedZoneId ? "#111827" : colors.stroke;
      ctx.lineWidth = zone.id === selectedZoneId ? 2.5 : 1.5;
      ctx.setLineDash(zone.type === "remnant" ? [7, 5] : []);
      ctx.fillRect(x, y, w, h);
      ctx.strokeRect(x, y, w, h);
      if (zone.type === "slat") {
        ctx.beginPath();
        ctx.setLineDash([]);
        for (let sx = x - h; sx < x + w + h; sx += 12) {
          ctx.moveTo(sx, y + h);
          ctx.lineTo(sx + h, y);
        }
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.fillStyle = colors.text;
      ctx.font = "12px system-ui";
      ctx.fillText(zone.name || zone.type, x + 6, y + 15);
    }
    ctx.restore();
  }

  function zoneColors(type) {
    if (type === "remnant") return { fill: "rgba(37, 99, 235, 0.08)", stroke: "#2563eb", text: "#1d4ed8" };
    if (type === "clamp") return { fill: "rgba(17, 24, 39, 0.16)", stroke: "#111827", text: "#111827" };
    if (type === "damaged") return { fill: "rgba(217, 119, 6, 0.14)", stroke: "#b45309", text: "#92400e" };
    if (type === "slat") return { fill: "rgba(75, 85, 99, 0.08)", stroke: "#6b7280", text: "#4b5563" };
    if (type === "pierce_keepout") return { fill: "rgba(124, 58, 237, 0.10)", stroke: "#7c3aed", text: "#5b21b6" };
    return { fill: "rgba(220, 38, 38, 0.12)", stroke: "#dc2626", text: "#991b1b" };
  }

  function niceRulerStep(lengthMm) {
    const targetTicks = 10;
    const raw = Math.max(1, lengthMm / targetTicks);
    const power = 10 ** Math.floor(Math.log10(raw));
    for (const multiplier of [1, 2, 5, 10]) {
      const candidate = multiplier * power;
      if (candidate >= raw) {
        return candidate;
      }
    }
    return 10 * power;
  }

  function drawPlacements() {
    for (const placement of project.placements) {
      const part = partDef(placement.part_name);
      if (!part) continue;
      const key = keyForPlacement(placement);
      const selected = key === selectedKey;

      ctx.save();
      drawPartFill(part, placement, selected);
      for (const contour of partContours(part)) {
        drawContour(contour, placement, selected);
      }
      drawPartImportIssueSegments(part, placement);

      const center = worldToScreen({ x: placement.dx, y: placement.dy });
      const radius = handleRadius(part);
      const angle = (placement.rotation_deg * Math.PI) / 180;
      ctx.strokeStyle = "#1f2933";
      ctx.beginPath();
      ctx.moveTo(center.x, center.y);
      ctx.lineTo(
        center.x + Math.cos(angle) * radius,
        center.y - Math.sin(angle) * radius
      );
      ctx.stroke();

      ctx.fillStyle = "#1f2933";
      ctx.font = "12px system-ui";
      ctx.fillText(key, center.x + 8, center.y - 8);
      if (placement.locked) {
        ctx.fillText("locked", center.x + 8, center.y + 8);
      }
      if (selected) {
        drawRotateHandle(placement, part);
      }
      ctx.restore();
    }
  }

  function drawPartFill(part, placement, selected) {
    const path = new Path2D();
    let hasFillPath = false;
    for (const contour of partContours(part)) {
      if (appendContourPath(path, contour, placement)) {
        hasFillPath = true;
      }
    }
    if (!hasFillPath) return;
    ctx.fillStyle = selected ? "rgba(42, 128, 185, 0.16)" : "rgba(65, 132, 92, 0.16)";
    ctx.fill(path, "evenodd");
  }

  function drawTabsAndLeads() {
    ctx.save();
    for (const tab of project.tabs) {
      const screen = worldToScreen({ x: tab.x_mm, y: tab.y_mm });
      ctx.fillStyle = "#f59e0b";
      ctx.strokeStyle = "#78350f";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.rect(screen.x - 5, screen.y - 5, 10, 10);
      ctx.fill();
      ctx.stroke();
    }
    if (editorMode !== "lead") {
      ctx.restore();
      return;
    }
    for (const override of project.lead_overrides) {
      if (override.start_x_mm === null || override.start_y_mm === null) continue;
      const screen = worldToScreen({ x: override.start_x_mm, y: override.start_y_mm });
      const automatic = Boolean(override.auto_generated);
      ctx.strokeStyle = automatic ? "#d97706" : "#2563eb";
      ctx.fillStyle = "#ffffff";
      ctx.lineWidth = 2;
      if (automatic) {
        ctx.setLineDash([4, 3]);
      }
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(screen.x - 8, screen.y);
      ctx.lineTo(screen.x + 8, screen.y);
      ctx.moveTo(screen.x, screen.y - 8);
      ctx.lineTo(screen.x, screen.y + 8);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawLeadSafetyPreview() {
    if (!project.placements.length) return;
    const craterRadius = Math.max(0, Number(project.post.pierce_crater_diameter_mm || 0) / 2);
    ctx.save();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "rgba(217, 119, 6, 0.70)";
    ctx.fillStyle = "rgba(217, 119, 6, 0.12)";
    for (const placement of project.placements) {
      const part = partDef(placement.part_name);
      if (!part) continue;
      const key = keyForPlacement(placement);
      for (const contour of partContours(part)) {
        const visual = leadVisualForContour(key, contour, placement);
        if (!visual) continue;
        const start = worldToScreen(visual.start);
        const pierce = worldToScreen(visual.pierce);
        if (visual.hasLead) {
          ctx.setLineDash([5, 4]);
          ctx.beginPath();
          ctx.moveTo(pierce.x, pierce.y);
          ctx.lineTo(start.x, start.y);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        if (craterRadius > 0) {
          ctx.beginPath();
          ctx.arc(pierce.x, pierce.y, Math.max(2, craterRadius * view.scale), 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        }
        ctx.beginPath();
        ctx.arc(pierce.x, pierce.y, 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.setLineDash([]);
    ctx.restore();
  }

  function leadVisualForContour(key, contour, placement) {
    const points = contourPoints(contour).map((point) => transformLocal(point, placement));
    if (points.length < 2) return null;
    const contourName = `${key}_${contour.name}`;
    const override = leadOverrideForContour(contourName, contour.name);
    const start = leadStartPoint(points, override);
    const mode = String((override && override.lead_in_mode) || project.post.lead_in_mode || "auto");
    const leadLength = Math.max(0, Number((override && override.lead_in_mm) ?? project.post.lead_in_mm ?? 0));
    if (
      override &&
      isFiniteNumberValue(override.pierce_x_mm) &&
      isFiniteNumberValue(override.pierce_y_mm)
    ) {
      return {
        start,
        pierce: { x: Number(override.pierce_x_mm), y: Number(override.pierce_y_mm) },
        hasLead: true,
      };
    }
    if (mode === "none" || leadLength <= 0) {
      return { start, pierce: start, hasLead: false };
    }
    const tangent = leadTangentAtStart(points, start);
    return {
      start,
      pierce: {
        x: start.x - tangent.x * leadLength,
        y: start.y - tangent.y * leadLength,
      },
      hasLead: true,
    };
  }

  function leadOverrideForContour(contourName, localContourName) {
    return project.lead_overrides.find((item) => item.contour_name === contourName || item.contour_name === localContourName);
  }

  function leadStartPoint(points, override) {
    if (
      override &&
      isFiniteNumberValue(override.start_x_mm) &&
      isFiniteNumberValue(override.start_y_mm)
    ) {
      return { x: Number(override.start_x_mm), y: Number(override.start_y_mm) };
    }
    return points[0];
  }

  function leadTangentAtStart(points, start) {
    let bestIndex = 0;
    let bestDistance = Infinity;
    for (const [index, point] of points.entries()) {
      const distance = Math.hypot(point.x - start.x, point.y - start.y);
      if (distance < bestDistance) {
        bestIndex = index;
        bestDistance = distance;
      }
    }
    const next = points[(bestIndex + 1) % points.length] || points[bestIndex];
    const length = Math.hypot(next.x - start.x, next.y - start.y);
    if (length <= 1e-9) return { x: 1, y: 0 };
    return {
      x: (next.x - start.x) / length,
      y: (next.y - start.y) / length,
    };
  }

  function drawCutOrderPreview() {
    if (!cutOrderPreview.length) return;
    const points = cutOrderPreview
      .filter((item) => isFiniteNumberValue(item.x) && isFiniteNumberValue(item.y))
      .map((item) => ({
        item,
        screen: worldToScreen({ x: Number(item.x), y: Number(item.y) }),
      }));
    if (!points.length) return;

    ctx.save();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "rgba(37, 99, 235, 0.65)";
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    points.forEach(({ screen }, index) => {
      if (index === 0) {
        ctx.moveTo(screen.x, screen.y);
      } else {
        ctx.lineTo(screen.x, screen.y);
      }
    });
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.font = "12px system-ui";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const { item, screen } of points) {
      const label = String(item.sequence || "");
      const radius = Math.max(9, 7 + label.length * 3);
      ctx.fillStyle = item.kind === "hole" ? "#6d28d9" : "#2563eb";
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#ffffff";
      ctx.fillText(label, screen.x, screen.y);
    }
    ctx.restore();
  }

  function isFiniteNumberValue(value) {
    return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  }

  function drawContour(contour, placement, selected) {
    const open = isOpenContour(contour);
    ctx.lineWidth = selected ? 3 : 1.5;
    ctx.strokeStyle = contour.kind === "outer" ? (selected ? "#2a80b9" : "#41845c") : "#734b9a";

    if (contour.type === "circle") {
      const center = contour.center || { x: contour.x || 0, y: contour.y || 0 };
      const worldCenter = worldToScreen(transformLocal(center, placement));
      ctx.beginPath();
      ctx.arc(worldCenter.x, worldCenter.y, Number(contour.radius_mm || contour.radius || 0) * view.scale, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      return;
    }

    const points = contourPoints(contour).map((point) => worldToScreen(transformLocal(point, placement)));
    if (points.length < 2) {
      ctx.setLineDash([]);
      return;
    }
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) {
        ctx.moveTo(point.x, point.y);
      } else {
        ctx.lineTo(point.x, point.y);
      }
    });
    if (!open) {
      ctx.closePath();
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawPartImportIssueSegments(part, placement) {
    const segments = partImportIssues(part)
      .map((issue) => importIssueSegmentForPart(issue, part))
      .filter(Boolean);
    if (!segments.length) return;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const { issue, start, end } of segments) {
      const screenStart = worldToScreen(transformLocal(start, placement));
      const screenEnd = worldToScreen(transformLocal(end, placement));
      ctx.strokeStyle = importIssueSegmentColor(issue);
      ctx.lineWidth = issue.blocking === false ? 3 : 4;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(screenStart.x, screenStart.y);
      ctx.lineTo(screenEnd.x, screenEnd.y);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.restore();
  }

  function importIssueSegmentForPart(issue, part) {
    if (!issue || !isFiniteNumberValue(issue.x) || !isFiniteNumberValue(issue.y)) return null;
    if (!sourceIssueBelongsToPart(issue, part)) return null;
    if (isFiniteNumberValue(issue.target_x) && isFiniteNumberValue(issue.target_y)) {
      const start = sourceIssuePointToPartLocal(issue.x, issue.y, part);
      const end = sourceIssuePointToPartLocal(issue.target_x, issue.target_y, part);
      if (!start || !end) return null;
      if (Math.hypot(start.x - end.x, start.y - end.y) <= 1e-6) return null;
      return { issue, start, end };
    }
    const point = sourceIssuePointToPartLocal(issue.x, issue.y, part);
    return point ? nearestIssueContourSegment(issue, part, point) : null;
  }

  function sourceIssuePointToPartLocal(xValue, yValue, part) {
    const x = Number(xValue);
    const y = Number(yValue);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    const center = part && part.source_center ? part.source_center : null;
    if (!center || !isFiniteNumberValue(center.x) || !isFiniteNumberValue(center.y)) {
      return { x, y };
    }
    return { x: x - Number(center.x), y: y - Number(center.y) };
  }

  function sourceIssueBelongsToPart(issue, part) {
    const bbox = Array.isArray(part && part.source_bbox) ? part.source_bbox.map(Number) : null;
    if (!bbox || bbox.length !== 4 || !bbox.every(Number.isFinite)) {
      return project && project.parts.length <= 1;
    }
    const tolerance = Math.max(5, Number(issue.gap_mm || 0) + 2);
    return (
      pointNearSourceBbox(Number(issue.x), Number(issue.y), bbox, tolerance) ||
      pointNearSourceBbox(Number(issue.target_x), Number(issue.target_y), bbox, tolerance)
    );
  }

  function pointNearSourceBbox(x, y, bbox, tolerance) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
    return (
      x >= bbox[0] - tolerance &&
      x <= bbox[2] + tolerance &&
      y >= bbox[1] - tolerance &&
      y <= bbox[3] + tolerance
    );
  }

  function importIssueSegmentColor(issue) {
    const code = String(issue.code || "");
    if (code.includes("repaired") || issue.blocking === false) {
      return "rgba(217, 119, 6, 0.92)";
    }
    return "rgba(220, 38, 38, 0.92)";
  }

  function nearestIssueContourSegment(issue, part, point) {
    let best = null;
    for (const contour of partContours(part)) {
      const points = contourPoints(contour);
      if (points.length < 2) continue;
      const endIndex = isOpenContour(contour) ? points.length - 1 : points.length;
      for (let index = 0; index < endIndex; index += 1) {
        const start = points[index];
        const end = points[(index + 1) % points.length];
        const candidate = projectedSegmentDistance(point, start, end);
        if (!candidate) continue;
        if (!best || candidate.distance < best.distance) {
          best = candidate;
        }
      }
    }
    if (!best) return null;
    const tolerance = issuePointHighlightTolerance(issue, part);
    if (best.distance > tolerance) return null;
    const segment = trimmedHighlightSegment(best.start, best.end, best.t, issuePointHighlightLength(part));
    return segment ? { issue, start: segment.start, end: segment.end } : null;
  }

  function projectedSegmentDistance(point, start, end) {
    const ax = Number(start.x);
    const ay = Number(start.y);
    const bx = Number(end.x);
    const by = Number(end.y);
    const px = Number(point.x);
    const py = Number(point.y);
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSq = dx * dx + dy * dy;
    if (!Number.isFinite(lengthSq) || lengthSq <= 1e-12) return null;
    const rawT = ((px - ax) * dx + (py - ay) * dy) / lengthSq;
    const t = clamp(rawT, 0, 1);
    const x = ax + dx * t;
    const y = ay + dy * t;
    return {
      start: { x: ax, y: ay },
      end: { x: bx, y: by },
      t,
      distance: Math.hypot(px - x, py - y),
    };
  }

  function trimmedHighlightSegment(start, end, t, lengthMm) {
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.hypot(dx, dy);
    if (!Number.isFinite(length) || length <= 1e-6) return null;
    const halfT = Math.min(0.5, Math.max(0.001, lengthMm / Math.max(length, 1e-6) / 2));
    const t0 = clamp(t - halfT, 0, 1);
    const t1 = clamp(t + halfT, 0, 1);
    if (Math.abs(t1 - t0) <= 1e-6) return null;
    return {
      start: { x: start.x + dx * t0, y: start.y + dy * t0 },
      end: { x: start.x + dx * t1, y: start.y + dy * t1 },
    };
  }

  function issuePointHighlightTolerance(issue, part) {
    const bounds = partBounds(part);
    const diagonal = Math.hypot(bounds.width, bounds.height);
    return Math.max(2, Math.min(12, diagonal * 0.02), Number(issue.gap_mm || 0) + 1);
  }

  function issuePointHighlightLength(part) {
    const bounds = partBounds(part);
    const diagonal = Math.hypot(bounds.width, bounds.height);
    return Math.max(8, Math.min(30, diagonal * 0.04));
  }

  function appendContourPath(path, contour, placement) {
    if (isOpenContour(contour)) return false;
    if (contour.type === "circle") {
      const center = contour.center || { x: contour.x || 0, y: contour.y || 0 };
      const worldCenter = worldToScreen(transformLocal(center, placement));
      const radius = Number(contour.radius_mm || contour.radius || 0) * view.scale;
      if (radius <= 0) return false;
      path.moveTo(worldCenter.x + radius, worldCenter.y);
      path.arc(worldCenter.x, worldCenter.y, radius, 0, Math.PI * 2);
      path.closePath();
      return true;
    }

    const points = contourPoints(contour).map((point) => worldToScreen(transformLocal(point, placement)));
    if (points.length < 3) return false;
    points.forEach((point, index) => {
      if (index === 0) {
        path.moveTo(point.x, point.y);
      } else {
        path.lineTo(point.x, point.y);
      }
    });
    path.closePath();
    return true;
  }

  function isOpenContour(contour) {
    if (!contour || contour.type === "circle") return false;
    if (contour.open === false || contour.closed === true) return false;
    if (contour.open === true || contour.closed === false) return true;
    const segments = contour.segments || [];
    if (segments.length) {
      const first = segments[0].start;
      const last = segments[segments.length - 1].end;
      if (!first || !last) return true;
      return Math.hypot(Number(first.x) - Number(last.x), Number(first.y) - Number(last.y)) > 0.05;
    }
    return contourPoints(contour).length < 3;
  }

  function drawSimulation() {
    if (!simulation.data || !simulation.data.segments.length) return;
    ctx.save();
    for (const segment of simulation.data.segments) {
      drawSegment(segment, segmentColor(segment), segment.type === "cut" ? 2 : 1.5);
    }

    const completed = pointsUntilTime(simulation.points, simulation.currentTime);
    const cutPaths = completedCutPaths(completed);
    if (cutPaths.length) {
      ctx.strokeStyle = "#c9482d";
      ctx.lineWidth = 3;
      ctx.setLineDash([]);
      ctx.beginPath();
      for (const path of cutPaths) {
        for (let index = 0; index < path.length; index += 1) {
          const screen = worldToScreen(path[index]);
          if (index === 0) ctx.moveTo(screen.x, screen.y);
          else ctx.lineTo(screen.x, screen.y);
        }
      }
      ctx.stroke();
    }

    const torch = simulation.currentPoint || (simulation.points.length ? simulation.points[0] : null);
    if (torch) {
      const screen = worldToScreen(torch);
      ctx.fillStyle = "#111827";
      ctx.strokeStyle = "#ffb000";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(screen.x, screen.y, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(screen.x - 11, screen.y);
      ctx.lineTo(screen.x + 11, screen.y);
      ctx.moveTo(screen.x, screen.y - 11);
      ctx.lineTo(screen.x, screen.y + 11);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawSegment(segment, color, width) {
    if (!segment.points || !segment.points.length) return;
    if (segment.type === "pierce") {
      drawPierceMarker(segment);
      return;
    }
    if (segment.points.length < 2) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(segment.safe_travel_warning ? [9, 3, 2, 3] : segment.tab_bridge ? [2, 4] : segment.type === "rapid" ? [5, 6] : segment.thc_disabled ? [4, 4] : []);
    ctx.beginPath();
    segment.points.forEach((point, index) => {
      const screen = worldToScreen(point);
      if (index === 0) {
        ctx.moveTo(screen.x, screen.y);
      } else {
        ctx.lineTo(screen.x, screen.y);
      }
    });
    ctx.stroke();
    ctx.setLineDash([]);
    if (segment.safe_travel_warning) {
      drawUnsafeTravelMarker(segment);
    }
  }

  function segmentColor(segment) {
    if (segment.safe_travel_warning) return "rgba(220, 38, 38, 0.78)";
    if (segment.tab_bridge) return "rgba(245, 158, 11, 0.62)";
    if (segment.safe_travel) return "rgba(37, 99, 235, 0.38)";
    if (segment.type === "rapid") return "rgba(81, 93, 108, 0.24)";
    if (segment.type === "pierce") return "#111827";
    if (segment.reduced_feed && segment.thc_disabled) return "rgba(124, 58, 237, 0.62)";
    if (segment.reduced_feed) return "rgba(217, 119, 6, 0.58)";
    if (segment.thc_disabled) return "rgba(37, 99, 235, 0.58)";
    return "rgba(203, 86, 40, 0.38)";
  }

  function drawUnsafeTravelMarker(segment) {
    const points = segment.points || [];
    if (points.length < 2) return;
    const midpoint = points[Math.floor(points.length / 2)];
    const screen = worldToScreen(midpoint);
    ctx.save();
    ctx.fillStyle = "#dc2626";
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(screen.x, screen.y, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.font = "12px system-ui";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("!", screen.x, screen.y);
    ctx.restore();
  }

  function drawPierceMarker(segment) {
    const point = segment.points[0];
    const screen = worldToScreen(point);
    ctx.save();
    ctx.fillStyle = segment.thc_disabled ? "#7c3aed" : "#111827";
    ctx.strokeStyle = segment.reduced_feed ? "#d97706" : "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(screen.x, screen.y, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function rotateHandlePoint(placement, part) {
    const center = worldToScreen({ x: placement.dx, y: placement.dy });
    const angle = ((placement.rotation_deg || 0) * Math.PI) / 180;
    const distance = handleRadius(part) + rotateHandleGapPx;
    return {
      x: center.x + Math.cos(angle) * distance,
      y: center.y - Math.sin(angle) * distance,
    };
  }

  function handleRadius(part) {
    const bounds = partBounds(part);
    return (Math.max(bounds.width, bounds.height) * view.scale) / 2;
  }

  function drawRotateHandle(placement, part) {
    const center = worldToScreen({ x: placement.dx, y: placement.dy });
    const handle = rotateHandlePoint(placement, part);
    ctx.save();
    ctx.strokeStyle = "#243447";
    ctx.fillStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(center.x, center.y);
    ctx.lineTo(handle.x, handle.y);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(handle.x, handle.y, rotateHandleRadiusPx, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(handle.x, handle.y, rotateHandleRadiusPx * 0.52, -0.8, Math.PI * 1.35);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(handle.x + 3, handle.y - 5);
    ctx.lineTo(handle.x + 7, handle.y - 5);
    ctx.lineTo(handle.x + 6, handle.y - 1);
    ctx.stroke();
    ctx.restore();
  }

  function hitTestRotateHandle(screenPoint) {
    if (!selectedKey) return null;
    const placement = placementByKey(selectedKey);
    const part = placement ? partDef(placement.part_name) : null;
    if (!placement || !isDisplayablePart(part)) return null;
    const handle = rotateHandlePoint(placement, part);
    const dx = screenPoint.x - handle.x;
    const dy = screenPoint.y - handle.y;
    const distance = Math.sqrt(dx * dx + dy * dy);
    return distance <= rotateHandleRadiusPx + 5 ? selectedKey : null;
  }

  function hitTest(world) {
    for (let i = project.placements.length - 1; i >= 0; i -= 1) {
      const placement = project.placements[i];
      const part = partDef(placement.part_name);
      if (!isDisplayablePart(part)) continue;
      const local = transformWorldToLocal(world, placement);
      const bounds = partBounds(part);
      if (
        local.x >= bounds.minX &&
        local.x <= bounds.maxX &&
        local.y >= bounds.minY &&
        local.y <= bounds.maxY
      ) {
        return keyForPlacement(placement);
      }
    }
    return null;
  }

  function updateSelectedInfo() {
    const placement = selectedKey ? placementByKey(selectedKey) : null;
    if (!placement) {
      selectedInfoEl.textContent = "None";
      selectedRotationsEl.disabled = true;
      selectedRotationsEl.value = "";
      selectedGrainLockEl.disabled = true;
      selectedGrainLockEl.checked = false;
      selectedAllowHoleFillerEl.disabled = true;
      selectedAllowHoleFillerEl.checked = false;
      selectedAllowHoleParentEl.disabled = true;
      selectedAllowHoleParentEl.checked = false;
      return;
    }
    const part = partDef(placement.part_name);
    const previewIssue = placementPreviewIssue(placement);
    selectedInfoEl.textContent = [
      selectedKey,
      `X ${placement.dx.toFixed(1)} mm`,
      `Y ${placement.dy.toFixed(1)} mm`,
      `R ${placement.rotation_deg.toFixed(0)} deg`,
      placement.locked ? "locked" : "editable",
      previewIssue ? `Preview: ${previewIssue.message}` : null,
    ].filter(Boolean).join("\n");
    selectedRotationsEl.disabled = !part;
    if (document.activeElement !== selectedRotationsEl) {
      selectedRotationsEl.value = part ? normalizeAllowedRotations(part.allowed_rotations).join(",") : "";
    }
    selectedGrainLockEl.disabled = !part;
    selectedGrainLockEl.checked = Boolean(part && part.grain_lock);
    selectedAllowHoleFillerEl.disabled = !part;
    selectedAllowHoleFillerEl.checked = Boolean(part && part.allow_hole_filler !== false);
    selectedAllowHoleParentEl.disabled = !part;
    selectedAllowHoleParentEl.checked = Boolean(part && part.allow_hole_parent !== false);
  }

  function renderPartsTable() {
    if (!partsTableEl || !project) return;
    const body = partsTableEl.querySelector("tbody");
    body.textContent = "";
    if (!project.parts.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.textContent = "No parts imported";
      cell.className = "muted-cell";
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }

    for (const part of project.parts) {
      const row = document.createElement("tr");
      const selectedPlacement = selectedKey ? placementByKey(selectedKey) : null;
      row.classList.toggle("active", Boolean(selectedPlacement && selectedPlacement.part_name === part.name));

      const fileCell = document.createElement("td");
      fileCell.className = "part-file-cell";
      const label = document.createElement("span");
      label.textContent = partSourceLabel(part);
      const sublabel = document.createElement("small");
      sublabel.textContent = partPolicyLabel(part);
      fileCell.append(label, sublabel);

      const qtyCell = document.createElement("td");
      qtyCell.className = "part-quantity";
      const qtyLabel = document.createElement("span");
      qtyLabel.textContent = "Кол-во";
      const qtyInput = document.createElement("input");
      qtyInput.className = "qty-input";
      qtyInput.type = "number";
      qtyInput.min = "1";
      qtyInput.step = "1";
      qtyInput.value = String(placementCount(part.name));
      qtyInput.setAttribute("aria-label", `Количество: ${partSourceLabel(part)}`);
      qtyInput.addEventListener("click", (event) => event.stopPropagation());
      qtyInput.addEventListener("change", () => setPartQuantity(part.name, Number(qtyInput.value)));
      qtyCell.append(qtyLabel, qtyInput);

      const issuesCell = document.createElement("td");
      const issueCount = partImportIssues(part).length;
      issuesCell.textContent = issueCount ? `⚠ ${issueCount}` : "";
      issuesCell.title = `Предупреждения импорта: ${issueCount}`;
      issuesCell.className = `part-issues${issueCount ? " issue-count" : ""}`;

      const actionsCell = document.createElement("td");
      actionsCell.className = "part-actions";
      const addButton = partActionButton("+", () => addPartInstance(part.name));
      const removeButton = partActionButton("-", () => removePartInstance(part.name));
      const deleteButton = partActionButton("Del", () => deletePart(part.name));
      addButton.title = "Добавить экземпляр";
      removeButton.title = "Убрать экземпляр";
      deleteButton.title = `Удалить деталь: ${partSourceLabel(part)}`;
      deleteButton.setAttribute("aria-label", deleteButton.title);
      actionsCell.append(addButton, removeButton, deleteButton);

      row.append(fileCell, qtyCell, issuesCell, actionsCell);
      row.draggable = true;
      row.addEventListener("dragstart", (event) => {
        event.dataTransfer.effectAllowed = "copy";
        event.dataTransfer.setData("application/x-plasma-cam-part", part.name);
        event.dataTransfer.setData("text/plain", part.name);
      });
      row.addEventListener("click", () => selectPart(part.name));
      body.appendChild(row);
    }
  }

  function renderZonesList() {
    if (!zonesListEl || !project) return;
    if (!project.zones.length) {
      zonesListEl.textContent = "No zones";
      return;
    }
    zonesListEl.textContent = project.zones
      .map((zone) => {
        const prefix = zone.id === selectedZoneId ? "> " : "";
        return `${prefix}${zone.name || zone.type}: ${zone.x_mm.toFixed(1)}, ${zone.y_mm.toFixed(1)} / ${zone.width_mm.toFixed(1)}x${zone.height_mm.toFixed(1)}`;
      })
      .join("\n");
  }

  function updateLeadEditInfo() {
    if (!leadEditInfoEl || !project) return;
    const selected = selectedKey || "none";
    const autoLeads = project.lead_overrides.filter((item) => item.auto_generated).length;
    const manualLeads = project.lead_overrides.length - autoLeads;
    leadEditInfoEl.textContent = [
      `Mode ${editorMode}`,
      `Part ${selected}`,
      `Leads ${manualLeads} manual / ${autoLeads} auto`,
      `Tabs ${project.tabs.length}`,
    ].join("\n");
  }

  function updateNestingInfo() {
    if (!nestingInfoEl || !project) return;
    const result = project.nesting && project.nesting.last_result;
    if (!result) {
      nestingInfoEl.textContent = "No nesting run";
      return;
    }
    nestingInfoEl.textContent = [
      result.layout_mode === "compact" ? "Компактно от нуля" : "В линию вдоль X",
      `${result.successful_attempt_count}/${result.attempt_count} runs${result.time_limited ? " (time limit)" : ""}`,
      `Packing ${formatPercent(result.packing_utilization_percent)}, sheet ${formatPercent(result.sheet_utilization_percent)}`,
      `Used ${formatMm(result.used_width_mm)} x ${formatMm(result.used_height_mm)}, top free ${formatMm(result.top_free_height_mm)}`,
      `${result.geometry_engine || "nest"} ${formatMs(result.runtime_ms)}, workers ${formatCount(result.parallel_worker_count)}, ${formatValue(result.attempts_per_second, "-")} runs/s`,
      `Candidates ${formatCount(result.candidate_position_count)} / NFP ${formatCount(result.nfp_candidate_count)}, STRtree ${formatCount(result.spatial_index_query_count)}`,
      `Cache ${formatCount(result.cache_hit_count)} hit / ${formatCount(result.cache_miss_count)} miss`,
      `Auto leads ${formatCount(result.auto_lead_override_count || 0)}, hole fills ${formatCount(result.hole_filler_relocation_count || 0)}${result.lead_spacing_fallback_skipped ? `, lead spacing skipped: ${result.lead_spacing_fallback_skipped}` : ""}`,
      project.nesting.common_line_cutting ? "Common line: effective spacing 0 mm" : `Spacing ${formatMm(project.spacing_mm)}`,
      String(result.best_attempt || "best attempt"),
    ].join("\n");
  }

  function updateNestHistoryInfo() {
    if (!nestHistoryEl || !project) return;
    const history = project.nesting && Array.isArray(project.nesting.run_history)
      ? project.nesting.run_history
      : [];
    if (!history.length) {
      nestHistoryEl.textContent = "No run history";
      return;
    }
    nestHistoryEl.textContent = history
      .slice(-8)
      .reverse()
      .map((run) => {
        const flags = [
          run.time_limited ? "time limit" : "",
          run.lead_spacing_fallback ? "lead spacing" : "",
          run.lead_spacing_fallback_skipped ? `lead spacing skipped: ${run.lead_spacing_fallback_skipped}` : "",
          run.hole_filler_relocation_count ? `${formatCount(run.hole_filler_relocation_count)} hole fill` : "",
          run.common_line_cutting ? "common line" : "",
        ].filter(Boolean);
        const suffix = flags.length ? ` (${flags.join(", ")})` : "";
        return [
          `#${formatCount(run.run_id)} ${formatNestTime(run.created_at)}${suffix}`,
          `${formatPercent(run.packing_utilization_percent)} pack, ${formatPercent(run.sheet_utilization_percent)} sheet, ${formatMs(run.runtime_ms)}`,
          `${formatCount(run.successful_attempt_count)}/${formatCount(run.attempt_count)} runs, ${formatMm(run.used_width_mm)} x ${formatMm(run.used_height_mm)}, top ${formatMm(run.top_free_height_mm)}`,
          String(run.best_attempt || "best attempt"),
        ].join("\n");
      })
      .join("\n\n");
  }

  function formatPercent(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return `${Number(value).toFixed(1)}%`;
  }

  function formatMm(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return `${Number(value).toFixed(1)} mm`;
  }

  function formatMs(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return `${Number(value).toFixed(0)} ms`;
  }

  function formatCount(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return String(Math.round(Number(value)));
  }

  function formatNestTime(value) {
    if (!value) return "";
    return String(value).replace("T", " ").replace("Z", "");
  }

  function partActionButton(text, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      handler();
    });
    return button;
  }

  function setEditorMode(mode) {
    finishPanning();
    panMode = false;
    spacePan = false;
    updatePanCursor();
    editorMode = mode;
    draw();
  }

  function addZone(type) {
    const history = captureMutationHistory();
    syncProjectFromControls();
    const usable = usableSheetBounds();
    const width = type === "slat" ? 40 : type === "remnant" ? Math.min(300, usable.maxX - usable.minX) : 120;
    const height = type === "slat" ? Math.min(300, usable.maxY - usable.minY) : type === "remnant" ? Math.min(220, usable.maxY - usable.minY) : 70;
    const zone = normalizeZone({
      type,
      name: type === "pierce_keepout" ? "pierce keepout" : type,
      x_mm: usable.minX,
      y_mm: usable.minY,
      width_mm: Math.max(1, width),
      height_mm: Math.max(1, height),
      enabled: true,
    });
    project.zones.push(zone);
    selectedZoneId = zone.id;
    selectedKey = null;
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Add zone");
    draw();
    validateProject();
  }

  function deleteSelectedZone() {
    if (!selectedZoneId) return;
    const history = captureMutationHistory();
    project.zones = project.zones.filter((zone) => zone.id !== selectedZoneId);
    selectedZoneId = null;
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Delete zone");
    draw();
    validateProject();
  }

  function zoneById(id) {
    return project.zones.find((zone) => zone.id === id);
  }

  function hitTestZone(world) {
    for (let index = project.zones.length - 1; index >= 0; index -= 1) {
      const zone = project.zones[index];
      if (
        world.x >= zone.x_mm &&
        world.x <= zone.x_mm + zone.width_mm &&
        world.y >= zone.y_mm &&
        world.y <= zone.y_mm + zone.height_mm
      ) {
        return zone.id;
      }
    }
    return null;
  }

  function contourNameForSelection(contour) {
    return selectedKey && contour ? `${selectedKey}_${contour.name}` : "";
  }

  function nearestSelectedContourPoint(world) {
    const placement = placementByKey(selectedKey);
    const part = placement ? partDef(placement.part_name) : null;
    if (!placement || !part) return null;
    let best = null;
    for (const contour of partContours(part)) {
      const points = contourPoints(contour);
      for (const point of points) {
        const transformed = transformLocal(point, placement);
        const distance = Math.hypot(transformed.x - world.x, transformed.y - world.y);
        if (!best || distance < best.distance) {
          best = { contour, point: transformed, distance };
        }
      }
    }
    return best;
  }

  function setLeadPoint(world) {
    const nearest = nearestSelectedContourPoint(world);
    if (!nearest) {
      setStatus("Select part first");
      return;
    }
    const history = captureMutationHistory();
    const contourName = contourNameForSelection(nearest.contour);
    let override = project.lead_overrides.find((item) => item.contour_name === contourName);
    if (!override) {
      override = normalizeLeadOverride({ contour_name: contourName });
      project.lead_overrides.push(override);
    }
    override.start_x_mm = nearest.point.x;
    override.start_y_mm = nearest.point.y;
    override.lead_in_mode = controls.leadMode.value === "none" ? "line" : controls.leadMode.value;
    override.lead_in_mm = Number(controls.leadLength.value);
    override.lead_out_mm = Number(controls.leadOutLength.value);
    override.auto_generated = false;
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Lead point");
    draw();
    validateProject();
  }

  function addTabPoint(world) {
    const nearest = nearestSelectedContourPoint(world);
    if (!nearest) {
      setStatus("Select part first");
      return;
    }
    const history = captureMutationHistory();
    const contourName = contourNameForSelection(nearest.contour);
    project.tabs.push(
      normalizeTab({
        contour_name: contourName,
        x_mm: nearest.point.x,
        y_mm: nearest.point.y,
        length_mm: Number(controls.tabLength.value || 8),
      })
    );
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Tab point");
    draw();
    validateProject();
  }

  function clearLeads() {
    const history = captureMutationHistory();
    if (selectedKey) {
      project.lead_overrides = project.lead_overrides.filter((item) => !item.contour_name.startsWith(`${selectedKey}_`));
    } else {
      project.lead_overrides = [];
    }
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Clear leads");
    draw();
    validateProject();
  }

  function clearAutoLeads() {
    const history = captureMutationHistory();
    project.lead_overrides = project.lead_overrides.filter((item) => !item.auto_generated);
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Clear auto leads");
    draw();
    validateProject();
  }

  function acceptAutoLeads() {
    const history = captureMutationHistory();
    let accepted = 0;
    for (const override of project.lead_overrides) {
      if (override.auto_generated) {
        override.auto_generated = false;
        accepted += 1;
      }
    }
    if (accepted === 0) {
      setStatus("No auto leads to accept");
      return;
    }
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Accept auto leads");
    draw();
    validateProject();
    setStatus(`Accepted ${accepted} auto lead${accepted === 1 ? "" : "s"}`);
  }

  function clearTabs() {
    const history = captureMutationHistory();
    if (selectedKey) {
      project.tabs = project.tabs.filter((item) => !item.contour_name.startsWith(`${selectedKey}_`));
    } else {
      project.tabs = [];
    }
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Clear tabs");
    draw();
    validateProject();
  }

  function selectPart(partName) {
    const placement = project.placements.find((item) => item.part_name === partName);
    selectedKey = placement ? keyForPlacement(placement) : null;
    draw();
  }

  function setPartQuantity(partName, quantity) {
    const part = partDef(partName);
    if (!part) return;
    const history = captureMutationHistory();
    const desired = Math.max(1, Math.round(Number(quantity || 1)));
    let current = placementCount(partName);
    while (current < desired) {
      addPartInstance(partName, { redraw: false, history: false });
      current += 1;
    }
    while (current > desired) {
      removePartInstance(partName, { redraw: false, history: false });
      current -= 1;
    }
    syncPartQuantity(partName);
    rebuildProjectImportState();
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Part quantity");
    draw();
    validateProject();
  }

  function addTemplatePart(type) {
    if (!project) return;
    const history = captureMutationHistory();
    const usedNames = new Set(project.parts.map((part) => part.name));
    const baseName = {
      disk: "template_disk",
      plate: "template_plate",
      flange: "template_flange",
    }[type] || "template_part";
    const name = uniquePartName(baseName, usedNames);
    const part = templatePartFromType(type, name);
    project.parts.push(part);
    const placement = defaultPlacementForPart(part, nextInstance(part.name));
    placement.manual = false;
    project.placements.push(placement);
    syncPartQuantity(part.name);
    selectedKey = keyForPlacement(placement);
    selectedZoneId = null;
    rebuildProjectImportState();
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Add template");
    draw();
    validateProject();
    setStatus(`Added ${name}`);
  }

  function addPartInstance(partName, options = {}) {
    const part = partDef(partName);
    if (!part) return;
    const history = options.history === false ? null : captureMutationHistory();
    const instance = nextInstance(partName);
    const placement = defaultPlacementForPart(part, instance);
    project.placements.push(placement);
    syncPartQuantity(partName);
    selectedKey = keyForPlacement(placement);
    if (options.redraw === false) return;
    rebuildProjectImportState();
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Add part");
    draw();
    validateProject();
  }

  function addPartInstanceAt(partName, world) {
    const part = partDef(partName);
    if (!part) return;
    const history = captureMutationHistory();
    const instance = nextInstance(partName);
    const bounds = rotatedPartBounds(part, 0);
    const center = snapPlacementPoint(world);
    const placement = {
      part_name: partName,
      instance,
      dx: center.x - (bounds.minX + bounds.maxX) / 2,
      dy: center.y - (bounds.minY + bounds.maxY) / 2,
      rotation_deg: 0,
      manual: true,
    };
    project.placements.push(placement);
    syncPartQuantity(partName);
    rebuildProjectImportState();
    selectedKey = keyForPlacement(placement);
    selectedZoneId = null;
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Place part");
    draw();
    validateProject();
    setStatus(`Placed ${selectedKey}`);
  }

  function removePartInstance(partName, options = {}) {
    const history = options.history === false ? null : captureMutationHistory();
    const placements = project.placements
      .filter((placement) => placement.part_name === partName)
      .sort((left, right) => right.instance - left.instance);
    if (placements.length <= 1) {
      deletePart(partName, { ...options, history: false });
      pushHistoryState(history, "Remove part");
      return;
    }
    const removable = placements.find((placement) => !placement.locked) || placements[0];
    const removableKey = keyForPlacement(removable);
    project.placements = project.placements.filter((placement) => keyForPlacement(placement) !== removableKey);
    if (selectedKey === removableKey) {
      const next = project.placements.find((placement) => placement.part_name === partName);
      selectedKey = next ? keyForPlacement(next) : null;
    }
    syncPartQuantity(partName);
    if (options.redraw === false) return;
    rebuildProjectImportState();
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Remove part");
    draw();
    validateProject();
  }

  function deletePart(partName, options = {}) {
    const history = options.history === false ? null : captureMutationHistory();
    project.parts = project.parts.filter((part) => part.name !== partName);
    project.placements = project.placements.filter((placement) => placement.part_name !== partName);
    if (selectedKey) {
      const selected = placementByKey(selectedKey);
      if (!selected || selected.part_name === partName) {
        selectedKey = firstSelectablePlacementKey();
      }
    }
    rebuildProjectImportState();
    if (options.redraw === false) return;
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Delete part");
    draw();
    if (project.parts.length) {
      validateProject();
    } else {
      issuesEl.textContent = "No parts";
      setStatus("No parts");
    }
  }

  function clearSheet() {
    if (!project || autoNesting || importing || couponImporting) return;
    const history = captureMutationHistory();
    project = { ...project, parts: [], placements: [], zones: [], tabs: [], lead_overrides: [], auto_nest: false,
      nesting: { ...project.nesting, run_history: [] } };
    delete project.nesting.last_result;
    delete project.import;
    delete project.coupon_plan;
    selectedKey = null;
    selectedZoneId = null;
    dragging = null;
    editorMode = "select";
    validatedLayout = null;
    invalidateSimulation();
    rebuildProjectImportState();
    syncControlsFromProject();
    gcodeEl.value = "";
    issuesEl.textContent = "No parts";
    saveProject();
    pushHistoryState(history, "Очистить поле");
    draw();
    setStatus("Поле очищено — можно отменить через Undo");
  }

  function defaultPlacementForPart(part, instance, rotation = 0) {
    const bounds = rotatedPartBounds(part, rotation);
    const usable = usableSheetBounds();
    const spacing = project.spacing_mm;
    const clearance = spacing + 0.05;
    const margin = usable.minX;
    const xmax = usable.maxX;
    const ymax = usable.maxY;
    const width = bounds.width;
    const height = bounds.height;
    const occupied = project.placements
      .map((placement) => {
        const placementPart = partDef(placement.part_name);
        return placementPart ? placementWorldBounds(placementPart, placement) : null;
      })
      .filter(Boolean);

    for (let y = margin; y + height <= ymax + 0.001; y += Math.max(10, height + clearance)) {
      for (let x = margin; x + width <= xmax + 0.001; x += Math.max(10, Math.min(width + clearance, 80))) {
        const candidateBox = { minX: x, minY: y, maxX: x + width, maxY: y + height };
        if (!occupied.some((box) => boxesOverlap(candidateBox, box, clearance))) {
          return {
            part_name: part.name,
            instance,
            dx: x - bounds.minX,
            dy: y - bounds.minY,
            rotation_deg: rotation,
            manual: true,
          };
        }
      }
    }

    return {
      part_name: part.name,
      instance,
      dx: margin - bounds.minX,
      dy: margin - bounds.minY,
      rotation_deg: rotation,
      manual: true,
    };
  }

  function duplicateSelected() {
    const placement = placementByKey(selectedKey);
    if (!placement) return;
    const history = captureMutationHistory();
    const copy = {
      ...placement,
      instance: nextInstance(placement.part_name),
      dx: placement.dx + 30,
      dy: placement.dy + 30,
      locked: false,
      manual: true,
    };
    project.placements.push(copy);
    syncPartQuantity(copy.part_name);
    rebuildProjectImportState();
    selectedKey = keyForPlacement(copy);
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Duplicate");
    draw();
    validateProject();
  }

  function rotateSelected() {
    const placement = placementByKey(selectedKey);
    if (!placement || placement.locked) return;
    const history = captureMutationHistory();
    placement.rotation_deg = (placement.rotation_deg + 90) % 360;
    placement.manual = true;
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Rotate");
    draw();
    validateProject();
  }

  function mirrorSelected() {
    const placement = placementByKey(selectedKey);
    const part = placement ? partDef(placement.part_name) : null;
    if (!placement || !part || placement.locked) return;

    const history = captureMutationHistory();
    const oldKey = keyForPlacement(placement);
    const oldPartName = part.name;
    const usedNames = new Set(project.parts.map((item) => item.name));
    const mirroredName = uniquePartName(`${oldPartName}_mirrored`, usedNames);
    const mirroredPart = mirroredPartFrom(part, mirroredName);

    project.parts.push(mirroredPart);
    placement.part_name = mirroredName;
    placement.manual = true;
    project.lead_overrides = project.lead_overrides.filter((item) => !item.contour_name.startsWith(`${oldKey}_`));
    project.tabs = project.tabs.filter((item) => !item.contour_name.startsWith(`${oldKey}_`));

    if (placementCount(oldPartName) === 0) {
      project.parts = project.parts.filter((item) => item.name !== oldPartName);
    } else {
      syncPartQuantity(oldPartName);
    }
    syncPartQuantity(mirroredName);
    rebuildProjectImportState();
    selectedKey = keyForPlacement(placement);
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Mirror");
    draw();
    validateProject();
  }

  function applySelectedRotationControls() {
    const placement = placementByKey(selectedKey);
    const part = placement ? partDef(placement.part_name) : null;
    if (!part) return;
    const history = captureMutationHistory();
    part.grain_lock = Boolean(selectedGrainLockEl.checked);
    part.allow_hole_filler = Boolean(selectedAllowHoleFillerEl.checked);
    part.allow_hole_parent = Boolean(selectedAllowHoleParentEl.checked);
    part.allowed_rotations = part.grain_lock
      ? [0]
      : normalizeAllowedRotations(
          selectedRotationsEl.value
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          [0, 90, 180, 270]
        );
    rebuildProjectImportState();
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Part policy");
    draw();
    validateProject();
  }

  function nudgeSelected(event) {
    const placement = placementByKey(selectedKey);
    if (!placement || placement.locked) return false;
    const direction = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, 1],
      ArrowDown: [0, -1],
    }[event.key];
    if (!direction) return false;
    const history = captureMutationHistory();
    const multiplier = event.shiftKey ? 10 : event.altKey ? 0.1 : 1;
    const baseStep = project.manual_controls && project.manual_controls.snap_enabled ? manualSnapStep() : 1;
    const step = Math.max(0.1, baseStep * multiplier);
    placement.dx += direction[0] * step;
    placement.dy += direction[1] * step;
    placement.manual = true;
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Move");
    draw();
    validateProject();
    return true;
  }

  function lockSelected() {
    const placement = placementByKey(selectedKey);
    if (!placement) return;
    const history = captureMutationHistory();
    placement.locked = !placement.locked;
    saveProject();
    pushHistoryState(history, "Lock");
    draw();
  }

  function deleteSelected() {
    if (!selectedKey) return;
    const history = captureMutationHistory();
    const placement = placementByKey(selectedKey);
    const partName = placement ? placement.part_name : null;
    project.placements = project.placements.filter((placement) => keyForPlacement(placement) !== selectedKey);
    if (partName) {
      if (placementCount(partName) === 0) {
        project.parts = project.parts.filter((part) => part.name !== partName);
      } else {
        syncPartQuantity(partName);
      }
    }
    rebuildProjectImportState();
    selectedKey = null;
    invalidateSimulation();
    saveProject();
    pushHistoryState(history, "Delete");
    draw();
    validateProject();
  }

  function isEditableTarget(target) {
    if (!target || !target.tagName) return false;
    const tagName = target.tagName.toLowerCase();
    return tagName === "input" || tagName === "textarea" || tagName === "select" || Boolean(target.isContentEditable);
  }

  function handleKeyboard(event) {
    if (isEditableTarget(event.target)) return;
    const key = event.key.toLowerCase();
    const command = event.metaKey || event.ctrlKey;
    if (!command && !event.altKey && event.code === "Space" && !dragging
        && (event.target === document.body || event.target === canvas || canvas.matches(":hover"))) {
      event.preventDefault();
      spacePan = true;
      updatePanCursor();
      return;
    }
    if (!command && !event.altKey && key === "h" && !event.repeat) {
      event.preventDefault();
      togglePanMode();
      return;
    }
    if ((panMode || spacePan) && ["arrowleft", "arrowright", "arrowup", "arrowdown"].includes(key)) {
      event.preventDefault();
      if (panning) return;
      const step = event.shiftKey ? 100 : 25;
      viewState.panX += key === "arrowleft" ? step : key === "arrowright" ? -step : 0;
      viewState.panY += key === "arrowup" ? step : key === "arrowdown" ? -step : 0;
      saveViewState();
      drawViewChange();
      return;
    }
    if (command && !event.altKey && key === "z") {
      event.preventDefault();
      if (event.shiftKey) {
        redoHistory();
      } else {
        undoHistory();
      }
      return;
    }
    if (command && !event.altKey && key === "y") {
      event.preventDefault();
      redoHistory();
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "ArrowUp" || event.key === "ArrowDown") {
      if (nudgeSelected(event)) {
        event.preventDefault();
      }
      return;
    }
    if (event.key !== "Delete" && event.key !== "Backspace") return;
    if (selectedKey) {
      event.preventDefault();
      deleteSelected();
      return;
    }
    if (selectedZoneId) {
      event.preventDefault();
      deleteSelectedZone();
    }
  }

  function autoNestInstances() {
    const instances = [];
    for (const part of project.parts) {
      const explicit = project.placements
        .filter((placement) => placement.part_name === part.name)
        .sort((a, b) => a.instance - b.instance);
      const count = Math.max(Number(part.quantity || 0), explicit.length);
      for (let index = 0; index < count; index += 1) {
        const existing = explicit[index];
        instances.push({
          part,
          instance: existing ? existing.instance : index + 1,
          rotation_deg: existing ? existing.rotation_deg || 0 : 0,
          locked: existing ? Boolean(existing.locked) : false,
        });
      }
      part.quantity = count;
    }
    return instances;
  }

  async function autoNest() {
    if (autoNesting) return;
    const history = captureMutationHistory();
    let historyCommitted = false;
    const commitAutoNestHistory = () => {
      if (!historyCommitted) {
        pushHistoryState(history, "Auto nest");
        historyCommitted = true;
      }
    };
    syncProjectFromControls();
    syncAllPartQuantities();
    saveProject();
    autoNesting = true;
    setAutoNestButtonBusy(true);
    const startedAt = performance.now();
    autoNestTimer = setInterval(() => {
      setStatus(`Auto nesting ${((performance.now() - startedAt) / 1000).toFixed(0)}s`);
    }, 1000);
    setStatus("Auto nesting");
    try {
      const timeoutMs = (Math.max(1, Number(project.nesting.auto_nest_max_runtime_s || 12)) + autoNestUiTimeoutGraceS) * 1000;
      const result = await postJson("/api/auto-nest", project, { timeoutMs });
      if (result.error) {
        issuesEl.textContent = `${result.type}: ${result.error}`;
        setStatus("Auto nest failed");
        commitAutoNestHistory();
        return;
      }
      project = normalizeProject(result);
      syncAllPartQuantities();
      rebuildProjectImportState();
      invalidateSimulation();
      syncControlsFromProject();
      ensureSelectedPlacement();
      saveProject();
      commitAutoNestHistory();
      draw();
      const resultInfo = project.nesting && project.nesting.last_result;
      setStatus(resultInfo ? `Auto nest ${formatPercent(resultInfo.packing_utilization_percent)}` : "Auto nested");
      validateProject();
    } catch (error) {
      if (error.name === "AbortError") {
        const limit = Math.max(1, Number(project.nesting.auto_nest_max_runtime_s || 12));
        issuesEl.textContent = `Timeout: Auto nest exceeded ${limit}s budget plus ${autoNestUiTimeoutGraceS}s network grace`;
      } else {
        issuesEl.textContent = `${error.name || "Error"}: ${error.message || error}`;
      }
      setStatus("Auto nest failed");
      commitAutoNestHistory();
    } finally {
      if (autoNestTimer) {
        clearInterval(autoNestTimer);
        autoNestTimer = null;
      }
      autoNesting = false;
      setAutoNestButtonBusy(false);
    }
  }

  function setAutoNestButtonBusy(busy) {
    const button = document.getElementById("toolbarAutoNestBtn");
    if (!button) return;
    button.disabled = busy;
    button.title = busy ? "Nesting..." : "Auto nest";
    button.setAttribute("aria-busy", String(busy));
    updateHistoryControls();
  }

  function buildAutoNestAttempts(items) {
    const specs = [
      ["area", (left, right) => itemBBoxArea(right) - itemBBoxArea(left)],
      ["max-side", (left, right) => itemMaxSide(right) - itemMaxSide(left)],
      ["wide", (left, right) => itemBounds(right).width - itemBounds(left).width],
      ["tall", (left, right) => itemBounds(right).height - itemBounds(left).height],
      ["current", () => 0],
    ];
    const attempts = [];
    const seen = new Set();
    for (const [label, compare] of specs) {
      const sorted = [...items].sort((left, right) => {
        const result = compare(left, right);
        return result || left.part.name.localeCompare(right.part.name) || left.instance - right.instance;
      });
      const key = sorted.map((item) => `${item.part.name}_${item.instance}`).join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      attempts.push({ label, items: sorted });
    }
    return attempts.length ? attempts : [{ label: "empty", items: [] }];
  }

  function itemBounds(item) {
    return partBounds(item.part);
  }

  function itemBBoxArea(item) {
    const bounds = itemBounds(item);
    return bounds.width * bounds.height;
  }

  function itemMaxSide(item) {
    const bounds = itemBounds(item);
    return Math.max(bounds.width, bounds.height);
  }

  function packAutoNestAttempt(options) {
    const occupied = options.lockedBoxes.map((box) => ({ ...box }));
    const placements = options.lockedPlacements.map((placement) => ({ ...placement }));

    for (const item of options.items) {
      const candidate = bestPlacementForItem(item, occupied, options);
      if (!candidate) return null;
      placements.push(candidate.placement);
      occupied.push(candidate.box);
    }

    return {
      label: options.label,
      placements,
      occupied,
      score: autoNestScore(occupied, options.margin, options.margin),
    };
  }

  function bestPlacementForItem(item, occupied, options) {
    let best = null;
    for (const rotation of allowedRotationsForItem(item)) {
      const bounds = rotatedPartBounds(item.part, rotation);
      for (const position of autoNestCandidatePositions(bounds, occupied, options)) {
        const box = {
          minX: position.x,
          minY: position.y,
          maxX: position.x + bounds.width,
          maxY: position.y + bounds.height,
        };
        if (!boxWithinUsable(box, options)) continue;
        if (occupied.some((itemBox) => boxesOverlap(box, itemBox, options.spacing + 0.05))) continue;
        const placement = {
          part_name: item.part.name,
          instance: item.instance,
          dx: position.x - bounds.minX,
          dy: position.y - bounds.minY,
          rotation_deg: rotation,
          manual: false,
        };
        const score = placementCandidateScore(box, occupied, options);
        const candidate = { placement, box, score };
        if (!best || compareScore(candidate.score, best.score) < 0) {
          best = candidate;
        }
      }
    }
    return best;
  }

  function allowedRotationsForItem(item) {
    const raw = item.part.grain_lock
      ? [0]
      : Array.isArray(item.part.allowed_rotations) && item.part.allowed_rotations.length
      ? item.part.allowed_rotations
      : [0, 90, 180, 270];
    const values = [item.rotation_deg || 0, ...raw];
    const normalized = [];
    for (const value of values) {
      const angle = normalizeAngle(Number(value || 0));
      if (!normalized.some((existing) => Math.abs(existing - angle) < 0.001)) {
        normalized.push(angle);
      }
    }
    return normalized;
  }

  function autoNestCandidatePositions(bounds, occupied, options) {
    const width = bounds.width;
    const height = bounds.height;
    const clearance = options.spacing + 0.05;
    const xMin = options.margin;
    const yMin = options.margin;
    const xMax = options.xmax - width;
    const yMax = options.ymax - height;
    const xValues = new Set();
    const yValues = new Set();
    addCandidateValue(xValues, xMin, xMin, xMax);
    addCandidateValue(yValues, yMin, yMin, yMax);
    addCandidateValue(xValues, xMax, xMin, xMax);
    addCandidateValue(yValues, yMax, yMin, yMax);

    for (const box of occupied) {
      addCandidateValue(xValues, box.minX, xMin, xMax);
      addCandidateValue(xValues, box.maxX + clearance, xMin, xMax);
      addCandidateValue(xValues, box.minX - width - clearance, xMin, xMax);
      addCandidateValue(xValues, box.maxX - width, xMin, xMax);
      addCandidateValue(yValues, box.minY, yMin, yMax);
      addCandidateValue(yValues, box.maxY + clearance, yMin, yMax);
      addCandidateValue(yValues, box.minY - height - clearance, yMin, yMax);
      addCandidateValue(yValues, box.maxY - height, yMin, yMax);
    }

    const positions = [];
    for (const y of [...yValues].sort((left, right) => left - right)) {
      for (const x of [...xValues].sort((left, right) => left - right)) {
        positions.push({ x, y });
      }
    }
    return positions;
  }

  function addCandidateValue(values, rawValue, min, max) {
    if (!Number.isFinite(rawValue)) return;
    if (rawValue < min - 0.001 || rawValue > max + 0.001) return;
    values.add(Math.round(clamp(rawValue, min, max) * 1000) / 1000);
  }

  function boxWithinUsable(box, options) {
    return (
      box.minX >= options.margin - 0.001 &&
      box.minY >= options.margin - 0.001 &&
      box.maxX <= options.xmax + 0.001 &&
      box.maxY <= options.ymax + 0.001
    );
  }

  function placementCandidateScore(box, occupied, options) {
    const scoreBoxes = [...occupied, box];
    const used = autoNestScore(scoreBoxes, options.margin, options.margin);
    return [
      ...used,
      box.minY,
      box.minX,
      box.maxY,
      box.maxX,
    ];
  }

  function autoNestScore(boxes, marginX, marginY) {
    if (!boxes.length) return [0, 0, 0, 0, 0];
    const maxX = Math.max(...boxes.map((box) => box.maxX));
    const maxY = Math.max(...boxes.map((box) => box.maxY));
    const usedWidth = Math.max(0, maxX - marginX);
    const usedHeight = Math.max(0, maxY - marginY);
    return [
      usedHeight,
      usedWidth * usedHeight,
      maxX,
      usedWidth,
      maxY,
    ];
  }

  function compareAutoNestResults(left, right) {
    return compareScore(left.score, right.score);
  }

  function compareScore(left, right) {
    const length = Math.max(left.length, right.length);
    for (let index = 0; index < length; index += 1) {
      const delta = (left[index] || 0) - (right[index] || 0);
      if (Math.abs(delta) > 0.001) {
        return delta < 0 ? -1 : 1;
      }
    }
    return 0;
  }

  async function validateProject({ persist = true } = {}) {
    const validationStatusVersion = statusVersion;
    syncProjectFromControls();
    saveProject({ publish: persist });
    refreshCutSettings({ persist });
    const requestedProject = project;
    const requestedGeometry = layoutGeometrySignature();
    const result = await postJson("/api/validate", project);
    if (project !== requestedProject || requestedGeometry !== layoutGeometrySignature()) return;
    if (result.error) {
      issuesEl.textContent = `${result.type}: ${result.error}`;
      if (statusVersion === validationStatusVersion) {
        setStatus("Invalid");
      }
      return;
    }
    validatedLayout = {
      signature: requestedGeometry,
      possibleCollision: result.issues.some((issue) => issue.code === "part_collision" || issue.code === "layout_complexity"),
    };
    updateSelectedInfo();
    issuesEl.textContent = result.issues.length
      ? result.issues.map(formatIssueLine).join("\n")
      : "No issues";
    if (statusVersion === validationStatusVersion) {
      setStatus(result.issues.length ? "Issues" : "Valid");
    }
  }

  function formatIssueLine(issue) {
    const details = [];
    if (isFiniteNumberValue(issue.gap_mm)) {
      details.push(`gap ${Number(issue.gap_mm).toFixed(3)} mm`);
    }
    if (isFiniteNumberValue(issue.chain_length_mm)) {
      details.push(`chain ${Number(issue.chain_length_mm).toFixed(3)} mm`);
    }
    if (isFiniteNumberValue(issue.sheet_x) && isFiniteNumberValue(issue.sheet_y)) {
      details.push(`X${Number(issue.sheet_x).toFixed(3)} Y${Number(issue.sheet_y).toFixed(3)}`);
      if (isFiniteNumberValue(issue.target_sheet_x) && isFiniteNumberValue(issue.target_sheet_y)) {
        details.push(`to X${Number(issue.target_sheet_x).toFixed(3)} Y${Number(issue.target_sheet_y).toFixed(3)}`);
      }
    } else if (isFiniteNumberValue(issue.x) && isFiniteNumberValue(issue.y)) {
      details.push(`src X${Number(issue.x).toFixed(3)} Y${Number(issue.y).toFixed(3)}`);
      if (isFiniteNumberValue(issue.target_x) && isFiniteNumberValue(issue.target_y)) {
        details.push(`to src X${Number(issue.target_x).toFixed(3)} Y${Number(issue.target_y).toFixed(3)}`);
      }
    }
    const suffix = details.length ? ` (${details.join(", ")})` : "";
    return `${issue.code}: ${issue.message}${suffix}`;
  }

  async function refreshCutSettings({ persist = true } = {}) {
    if (!project) return;
    const requestedProject = project;
    const requestedSettings = JSON.stringify([project.cut, project.cut_chart, project.post.small_feature_source]);
    const result = await postJson("/api/cut-settings", project);
    if (project !== requestedProject || requestedSettings !== JSON.stringify([project.cut, project.cut_chart, project.post.small_feature_source])) return;
    if (result.error) {
      cutSettingsInfoEl.textContent = `${result.type}: ${result.error}`;
      return;
    }
    const smallRules =
      project.post.small_feature_source === "cut_chart"
        ? `Chart small: ${formatValue(result.small_hole_threshold_mm, "-")} / ${formatValue(result.small_shape_threshold_mm, "-")} mm, ${formatValue(result.small_hole_speed_percent, "-")}%`
        : `Manual small: ${project.post.small_hole_threshold_mm} / ${project.post.small_shape_threshold_mm} mm, ${project.post.small_hole_speed_percent}%`;
    cutSettingsInfoEl.textContent = [
      `${result.feed_rate_mode === "manual" ? "Manual" : "Auto"} ${result.feed_rate_mm_min} mm/min`,
      `${result.current_a} A, kerf ${result.kerf_width_mm} mm, nozzle ${result.nozzle_mm} mm`,
      `Pierce ${result.pierce_delay_s}s @ ${result.pierce_height_mm} mm`,
      `Cut ${result.cut_height_mm} mm, ${formatValue(result.cut_volts, "-")} V, THC ${result.thc_enabled ? "on" : "off"}`,
      smallRules,
      project.post.qtplasmac_material_mode === "fixed"
        ? `M190 P${project.post.qtplasmac_material_number}, M66 Q${project.post.qtplasmac_material_wait_s}`
        : "Temporary QtPlasmaC material",
    ].join("\n");
    if (project.cut.feed_rate_mode !== "manual") {
      project.cut.manual_feed_rate_mm_min = result.feed_rate_mm_min;
      controls.manualFeed.value = result.feed_rate_mm_min;
      saveProject({ publish: persist });
    }
    if (project.post.small_feature_source === "cut_chart") {
      project.post.small_hole_threshold_mm = Number(result.small_hole_threshold_mm ?? project.post.small_hole_threshold_mm);
      project.post.small_shape_threshold_mm = Number(result.small_shape_threshold_mm ?? project.post.small_shape_threshold_mm);
      project.post.small_hole_speed_percent = Number(result.small_hole_speed_percent ?? project.post.small_hole_speed_percent);
      project.post.small_hole_overburn_mm = Number(result.small_hole_overburn_mm ?? project.post.small_hole_overburn_mm);
      project.post.small_hole_torch_off_before_end_mm = Number(
        result.small_hole_torch_off_before_end_mm ?? project.post.small_hole_torch_off_before_end_mm
      );
      syncControlsFromProject();
      saveProject({ publish: persist });
    }
    markActiveCutChartRow(result);
  }

  async function exportGcode() {
    syncProjectFromControls();
    saveProject();
    const signature = captureHistoryState().signature;
    const review = await postJson("/api/review-report", project);
    if (review.error) {
      issuesEl.textContent = `${review.type}: ${review.error}`;
      setStatus("Export review failed");
      pendingExportApprovalSignature = null;
      return;
    }
    const report = review.report || {};
    const preflight = report.export_preflight || {};
    if (!preflight.can_export) {
      gcodeEl.value = JSON.stringify(report, null, 2);
      issuesEl.textContent = exportPreflightSummary(report);
      setStatus("Export failed");
      pendingExportApprovalSignature = null;
      return;
    }
    const warningCount = Number(preflight.warning_count || 0) + Number(preflight.gcode_validation_issue_count || 0);
    if (warningCount > 0 && pendingExportApprovalSignature !== signature) {
      gcodeEl.value = JSON.stringify(report, null, 2);
      issuesEl.textContent = [
        exportPreflightSummary(report),
        "Click Export NGC again to export this unchanged project.",
      ].join("\n");
      setStatus("Review export warnings");
      pendingExportApprovalSignature = signature;
      return;
    }
    pendingExportApprovalSignature = null;
    const result = await postJson("/api/export", project);
    if (result.error) {
      issuesEl.textContent = `${result.type}: ${result.error}`;
      setStatus("Export failed");
      return;
    }
    gcodeEl.value = result.gcode;
    downloadText(result.filename, result.gcode);
    setStatus(`Exported ${result.line_count} lines`);
  }

  async function exportOutlineGcode() {
    syncProjectFromControls();
    saveProject();
    const result = await postJson("/api/export-outline", project);
    if (result.error) {
      issuesEl.textContent = `${result.type}: ${result.error}`;
      setStatus("Outline failed");
      return;
    }
    gcodeEl.value = result.gcode;
    downloadText(result.filename, result.gcode);
    setStatus(`Outline ${result.line_count} lines`);
  }

  async function sendLinuxCnc() {
    syncProjectFromControls();
    saveProject();
    setStatus("Sending to LinuxCNC");
    const result = await postJson("/api/send-linuxcnc", project, { timeoutMs: 60000 });
    if (result.error) {
      issuesEl.textContent = `${result.type}: ${result.error}`;
      setStatus("LinuxCNC send failed");
      return;
    }
    const warnings = Array.isArray(result.warnings) ? result.warnings : [];
    const uploadedFiles = Array.isArray(result.files) ? result.files : [];
    const fileLines = uploadedFiles.map((file) => `File: ${file.filename} -> ${file.remote_path}`);
    issuesEl.textContent = [
      result.loaded ? `Loaded ${result.filename} into LinuxCNC` : `Uploaded ${result.filename}, but LinuxCNC did not load it`,
      result.outline_filename ? `Outline button file: ${result.outline_filename}` : null,
      `Remote: ${result.remote_path}`,
      `Bytes: ${result.byte_count}`,
      ...fileLines,
      result.load_error ? `LOAD FAILED: ${result.load_error}` : null,
      ...warnings.map((warning) => `WARNING: ${warning}`),
    ].filter(Boolean).join("\n");
    if (!result.loaded) {
      setStatus("LinuxCNC load failed");
      return;
    }
    setStatus(warnings.length ? "LinuxCNC loaded with warnings" : "Loaded into LinuxCNC");
  }

  async function exportReviewDxf() {
    syncProjectFromControls();
    saveProject();
    const result = await postJson("/api/export-dxf", project);
    if (result.error) {
      issuesEl.textContent = `${result.type}: ${result.error}`;
      setStatus("Review DXF failed");
      return;
    }
    gcodeEl.value = result.dxf;
    downloadText(result.filename, result.dxf, "application/dxf");
    setStatus(`Review DXF ${result.line_count} lines`);
  }

  async function reviewReport() {
    syncProjectFromControls();
    saveProject();
    const result = await postJson("/api/review-report", project);
    if (result.error) {
      issuesEl.textContent = `${result.type}: ${result.error}`;
      setStatus("Review failed");
      return;
    }
    const report = result.report || {};
    const text = JSON.stringify(report, null, 2);
    gcodeEl.value = text;
    issuesEl.textContent = reviewReportSummary(report);
    downloadText(result.filename, text, "application/json");
    setStatus("Review report");
  }

  async function previewCutOrder() {
    syncProjectFromControls();
    saveProject();
    const result = await postJson("/api/review-report", project);
    if (result.error) {
      cutOrderPreview = [];
      issuesEl.textContent = `${result.type}: ${result.error}`;
      setStatus("Cut order preview failed");
      updateCutOrderInfo();
      draw();
      return;
    }
    const report = result.report || {};
    const order = report.cut_order || {};
    if (!order.available || !Array.isArray(order.sequence)) {
      cutOrderPreview = [];
      issuesEl.textContent = order.error || "Cut order preview unavailable";
      setStatus("Cut order preview unavailable");
      updateCutOrderInfo();
      draw();
      return;
    }
    cutOrderPreview = order.sequence
      .filter((item) => item && item.entry && isFiniteNumberValue(item.entry.x) && isFiniteNumberValue(item.entry.y))
      .map((item) => ({
        sequence: Number(item.sequence || 0),
        name: String(item.name || ""),
        kind: String(item.kind || ""),
        group: String(item.group || ""),
        x: Number(item.entry.x),
        y: Number(item.entry.y),
        smallFeature: Boolean(item.small_feature),
    }));
    issuesEl.textContent = reviewReportSummary(report);
    setStatus(`Cut order preview ${cutOrderPreview.length} cuts`);
    updateCutOrderInfo();
    draw();
  }

  function clearCutOrderPreview() {
    cutOrderPreview = [];
    setStatus("Cut order preview cleared");
    updateCutOrderInfo();
    draw();
  }

  function reviewReportSummary(report) {
    const issues = Array.isArray(report.validation_issues) ? report.validation_issues : [];
    const warnings = Array.isArray(report.warnings) ? report.warnings : [];
    const issueSummary = report.issue_summary || {};
    const utilization = report.nesting && report.nesting.current_utilization
      ? report.nesting.current_utilization
      : {};
    const simulation = report.simulation_metrics || {};
    const preflight = report.export_preflight || {};
    const cam = report.cam_geometry || {};
    const dxfRepair = report.dxf_repair_plan || {};
    const checklist = report.operator_checklist || {};
    return [
      checklist.status ? `Checklist ${checklist.status}, warnings ${checklist.warning_count || 0}` : null,
      `Issues ${issues.length}, warnings ${issueSummary.warning_count ?? warnings.length}`,
      `Export ${preflight.can_export ? "ready" : "failed"}, G-code issues ${preflight.gcode_validation_issue_count || 0}`,
      dxfRepair.review_required
        ? `DXF review ${dxfRepair.review_required_count || 0} issue(s), ${dxfRepair.action_count || 0} action group(s)`
        : null,
      `Pierces ${simulation.pierce_count || 0}, cut ${formatMm(simulation.cut_length_mm || 0)}, rapid ${formatMm(simulation.rapid_length_mm || 0)}`,
      cam.centerline_fallback_count
        ? `Kerf centerline fallbacks ${cam.centerline_fallback_count}`
        : null,
      simulation.safe_travel_warning_count
        ? `Unsafe rapid warnings ${simulation.safe_travel_warning_count}, length ${formatMm(simulation.safe_travel_warning_length_mm || 0)}`
        : null,
      `Sheet ${formatPercent(utilization.sheet_utilization_percent || 0)}, packing ${formatPercent(utilization.packing_utilization_percent || 0)}`,
    ].filter(Boolean).join("\n");
  }

  function exportPreflightSummary(report) {
    const preflight = report.export_preflight || {};
    const lines = [
      `Export ${preflight.can_export ? "ready" : "failed"}`,
      `Warnings ${preflight.warning_count || 0}, G-code issues ${preflight.gcode_validation_issue_count || 0}`,
    ];
    const blockingCodes = Array.isArray(preflight.blocking_codes) ? preflight.blocking_codes.filter(Boolean) : [];
    const warningCodes = Array.isArray(preflight.warning_codes) ? preflight.warning_codes.filter(Boolean) : [];
    const gcodeCodes = Array.isArray(preflight.gcode_validation_codes) ? preflight.gcode_validation_codes.filter(Boolean) : [];
    if (blockingCodes.length) lines.push(`Blocking: ${blockingCodes.join(", ")}`);
    if (warningCodes.length) lines.push(`Warnings: ${warningCodes.join(", ")}`);
    if (gcodeCodes.length) lines.push(`G-code: ${gcodeCodes.join(", ")}`);
    if (preflight.error && preflight.error.message) {
      lines.push(`${preflight.error.type || "Error"}: ${preflight.error.message}`);
    }
    return lines.join("\n");
  }

  async function loadCutChart() {
    const response = await fetch("/api/cut-chart");
    const result = await response.json();
    cutChartProfile = result.profile || null;
    cutChart = (result.rows || []).map(normalizeCutChartRow).filter(Boolean);
    renderCutChart();
  }

  async function loadCouponResultsFile() {
    const file = couponResultsFileEl && couponResultsFileEl.files ? couponResultsFileEl.files[0] : null;
    if (!file) return;
    try {
      couponResultsInputEl.value = await file.text();
      couponResultsInfoEl.textContent = `Loaded ${file.name}`;
      setStatus("Coupon JSON loaded");
    } catch (error) {
      couponResultsInfoEl.textContent = `${error.name || "Error"}: ${error.message || error}`;
      setStatus("Coupon file failed");
    }
  }

  function parseCouponResultsPayload() {
    const raw = couponResultsInputEl ? couponResultsInputEl.value.trim() : "";
    if (!raw) {
      throw new Error("Coupon results JSON is empty");
    }
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return { results: parsed };
    }
    if (!parsed || typeof parsed !== "object") {
      throw new Error("Coupon results JSON must be an object or array");
    }
    return { ...parsed };
  }

  async function importCouponResults() {
    if (couponImporting || !project) return;
    let payload = null;
    try {
      payload = parseCouponResultsPayload();
    } catch (error) {
      couponResultsInfoEl.textContent = `${error.name || "Error"}: ${error.message || error}`;
      setStatus("Coupon JSON invalid");
      return;
    }

    const history = captureMutationHistory();
    couponImporting = true;
    updateHistoryControls();
    syncProjectFromControls();
    payload.project = project;
    setStatus("Importing coupon results");
    couponResultsInfoEl.textContent = "Importing";
    try {
      const result = await postJson("/api/import-coupon-results", payload);
      if (result.error) {
        const message = `${result.type || "Error"}: ${result.error}`;
        couponResultsInfoEl.textContent = message;
        issuesEl.textContent = message;
        setStatus("Coupon import failed");
        return;
      }
      const nextProject = normalizeProject(result.project || { ...project, cut_chart: result.cut_chart });
      project = nextProject;
      syncAllPartQuantities();
      rebuildProjectImportState();
      selectedKey = normalizedSelectedKey(selectedKey);
      invalidateSimulation();
      syncControlsFromProject();
      saveProject();
      pushHistoryState(history, "Import coupon results");
      renderCutChart();
      await validateProject();
      const couponIds = Array.isArray(result.coupon_ids) ? result.coupon_ids.filter(Boolean) : [];
      couponResultsInfoEl.textContent = [
        `Imported ${Number(result.imported_count || 0)} measured row(s)`,
        couponIds.length ? couponIds.join(", ") : null,
      ].filter(Boolean).join("\n");
      setStatus("Coupon results imported");
    } catch (error) {
      const message = `${error.name || "Error"}: ${error.message || error}`;
      couponResultsInfoEl.textContent = message;
      issuesEl.textContent = message;
      setStatus("Coupon import failed");
    } finally {
      couponImporting = false;
      updateHistoryControls();
    }
  }

  function activeCutChartRows() {
    return project && project.cut_chart && project.cut_chart.rows.length ? project.cut_chart.rows : cutChart;
  }

  function ensureProjectCutChart() {
    if (project.cut_chart && project.cut_chart.rows.length) return project.cut_chart;
    project.cut_chart = normalizeProjectCutChart({
      profile_id: "project-calibrated",
      base_profile_id: cutChartProfile ? cutChartProfile.profile_id : null,
      version: new Date().toISOString(),
      machine: cutChartProfile ? cutChartProfile.machine : "Fubag Plasma 40",
      source: "Project calibrated cut chart",
      rows: cutChart.map((row) => ({ ...row, notes: [...(row.notes || [])] })),
    });
    return project.cut_chart;
  }

  function updateCutChartCell(index, field, value) {
    const history = captureMutationHistory();
    const chart = ensureProjectCutChart();
    const row = chart.rows[index];
    if (!row) return;
    row[field] = value;
    chart.version = new Date().toISOString();
    saveProject();
    pushHistoryState(history, "Cut chart");
    renderCutChart();
    validateProject();
  }

  function resetProjectCutChart() {
    if (!project || !project.cut_chart) {
      setStatus("Starter chart already active");
      return;
    }
    const history = captureMutationHistory();
    project.cut_chart = null;
    saveProject();
    pushHistoryState(history, "Reset cut chart");
    renderCutChart();
    validateProject();
    setStatus("Starter chart active");
  }

  function currentCutChartProfileSnapshot() {
    if (!project) {
      throw new Error("No project loaded");
    }
    syncProjectFromControls();
    const sourceChart = project.cut_chart
      ? project.cut_chart
      : {
          profile_id: cutChartProfile ? cutChartProfile.profile_id : "fubag-plasma-40-starter",
          base_profile_id: null,
          version: cutChartProfile ? cutChartProfile.version : "starter",
          revision: cutChartProfile ? cutChartProfile.revision : "starter",
          updated_at: cutChartProfile ? cutChartProfile.updated_at : "",
          machine: cutChartProfile ? cutChartProfile.machine : "Fubag Plasma 40",
          source: cutChartProfile ? cutChartProfile.source : "Starter cut chart",
          notes: cutChartProfile ? cutChartProfile.notes || [] : [],
          rows: cutChart,
        };
    const snapshot = normalizeProjectCutChart(sourceChart);
    if (!snapshot) {
      throw new Error("Cut chart is empty");
    }
    return {
      ...snapshot,
      exported_at: new Date().toISOString(),
    };
  }

  function exportCutChartProfile() {
    try {
      const snapshot = currentCutChartProfileSnapshot();
      downloadText(
        `${fileSafeName(snapshot.profile_id || "cut_chart")}.cut-chart.json`,
        JSON.stringify(snapshot, null, 2),
        "application/json"
      );
      setStatus("Cut chart exported");
    } catch (error) {
      issuesEl.textContent = `${error.name || "Error"}: ${error.message || error}`;
      setStatus("Cut chart export failed");
    }
  }

  async function importCutChartProfileFile() {
    if (!project || !cutChartProfileFileEl || !cutChartProfileFileEl.files || !cutChartProfileFileEl.files[0]) return;
    const file = cutChartProfileFileEl.files[0];
    const history = captureMutationHistory();
    const previousCutChart = project.cut_chart ? JSON.parse(JSON.stringify(project.cut_chart)) : null;
    try {
      const parsed = JSON.parse(await file.text());
      const chart = normalizeProjectCutChart(parsed);
      if (!chart) {
        throw new Error("Cut chart profile has no valid rows");
      }
      project.cut_chart = {
        ...chart,
        imported_at: new Date().toISOString(),
        imported_from: file.name,
      };
      syncProjectFromControls();
      const settings = await postJson("/api/cut-settings", project);
      if (settings.error) {
        throw new Error(`Cut chart profile rejected: ${settings.error}`);
      }
      saveProject();
      pushHistoryState(history, "Import cut chart");
      renderCutChart();
      await validateProject();
      setStatus(`Cut chart imported ${file.name}`);
    } catch (error) {
      project.cut_chart = previousCutChart;
      saveProject();
      renderCutChart();
      issuesEl.textContent = `${error.name || "Error"}: ${error.message || error}`;
      setStatus("Cut chart import failed");
    } finally {
      cutChartProfileFileEl.value = "";
      updateHistoryControls();
    }
  }

  function renderCutChart() {
    const body = cutChartTableEl.querySelector("tbody");
    body.textContent = "";
    const rows = activeCutChartRows();
    for (const [index, row] of rows.entries()) {
      const tr = document.createElement("tr");
      tr.dataset.thickness = String(row.thickness_mm);
      tr.dataset.nozzle = String(row.nozzle_mm);
      tr.dataset.index = String(index);
      tr.append(
        cutChartCell(index, "thickness_mm", row.thickness_mm, "0.1"),
        cutChartCell(index, "nozzle_mm", row.nozzle_mm, "0.1"),
        cutChartCell(index, "current_a", row.current_a, "1"),
        cutChartCell(index, "feed_rate_mm_min", row.feed_rate_mm_min, "10"),
        cutChartCell(index, "kerf_width_mm", row.kerf_width_mm, "0.01"),
        cutChartCell(index, "pierce_delay_s", row.pierce_delay_s, "0.01"),
        cutChartCell(index, "cut_height_mm", row.cut_height_mm, "0.1"),
        cutChartCell(index, "arc_voltage_v", row.arc_voltage_v, "0.1"),
        cutChartCheckboxCell(index, row.thc_enabled),
        cutChartCell(index, "small_hole_threshold_mm", row.small_hole_threshold_mm, "0.1"),
        cutChartCell(index, "small_shape_threshold_mm", row.small_shape_threshold_mm, "0.1"),
        cutChartCell(index, "small_hole_speed_percent", row.small_hole_speed_percent, "1"),
        cutChartCell(index, "small_hole_overburn_mm", row.small_hole_overburn_mm, "0.1"),
        cutChartCell(index, "small_hole_torch_off_before_end_mm", row.small_hole_torch_off_before_end_mm, "0.1")
      );
      tr.addEventListener("click", () => {
        const history = captureMutationHistory();
        controls.thickness.value = row.thickness_mm;
        controls.nozzle.value = row.nozzle_mm;
        controls.feedMode.value = "auto";
        syncProjectFromControls();
        saveProject();
        pushHistoryState(history, "Cut settings");
        draw();
        validateProject();
      });
      body.appendChild(tr);
    }
    if (cutChartInfoEl) {
      const chart = project && project.cut_chart ? project.cut_chart : cutChartProfile;
      cutChartInfoEl.textContent = chart
        ? [
            project && project.cut_chart ? "Project chart" : "Starter chart",
            chart.machine || "Machine",
            chart.version ? `Version ${chart.version}` : null,
          ].filter(Boolean).join("\n")
        : "Starter chart";
    }
    if (project) {
      refreshCutSettings();
    }
  }

  function cutChartCell(index, field, value, step) {
    const cell = document.createElement("td");
    const input = document.createElement("input");
    input.className = "table-input";
    input.type = "number";
    input.step = step;
    input.min = "0";
    input.value = value === null || value === undefined ? "" : String(value);
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("change", () => {
      const nextValue = field === "arc_voltage_v" && input.value === "" ? null : Number(input.value);
      updateCutChartCell(index, field, nextValue);
    });
    cell.appendChild(input);
    return cell;
  }

  function cutChartCheckboxCell(index, checked) {
    const cell = document.createElement("td");
    const input = document.createElement("input");
    input.className = "table-check";
    input.type = "checkbox";
    input.checked = Boolean(checked);
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("change", () => updateCutChartCell(index, "thc_enabled", input.checked));
    cell.appendChild(input);
    return cell;
  }

  function markActiveCutChartRow(settings) {
    const rows = cutChartTableEl.querySelectorAll("tbody tr");
    rows.forEach((row) => {
      const active =
        Number(row.dataset.thickness) === Number(settings.thickness_mm) &&
        Number(row.dataset.nozzle) === Number(settings.nozzle_mm);
      row.classList.toggle("active", active);
    });
  }

  async function playSimulation() {
    syncProjectFromControls();
    saveProject();
    const requestedProject = project;
    const requestedSimulation = simulation;
    const result = await postJson("/api/simulate", project);
    if (project !== requestedProject || simulation !== requestedSimulation) return;
    if (result.error) {
      issuesEl.textContent = `${result.type}: ${result.error}`;
      setStatus("Simulation failed");
      return;
    }
    stopSimulation({ keepPath: false });
    simulation.data = result;
    simulation.points = flattenSimulation(result);
    simulation.currentTime = 0;
    simulation.currentPoint = simulation.points.length ? simulation.points[0] : null;
    simulation.running = true;
    simulation.startedAt = performance.now();
    simulation.elapsedBeforePause = 0;
    simulationInfoEl.textContent = simulationSummary(result);
    setStatus("Simulation");
    simulation.frameId = requestAnimationFrame(simulationTick);
    draw();
  }

  function stopSimulation(options = {}) {
    if (simulation.frameId) {
      cancelAnimationFrame(simulation.frameId);
    }
    const keepPath = Boolean(options.keepPath);
    simulation = keepPath && simulation.data ? { ...simulation, running: false, frameId: null } : emptySimulation();
    if (!keepPath) {
      simulationInfoEl.textContent = "Simulation idle";
    }
    draw();
  }

  function simulationTick(timestamp) {
    if (!simulation.running || !simulation.data) return;
    const playback = Math.max(1, Number(project.simulation.playback_rate || 1));
    const elapsed = (timestamp - simulation.startedAt) / 1000;
    simulation.currentTime = simulation.elapsedBeforePause + elapsed * playback;
    const total = simulation.data.estimated_total_s;
    if (simulation.currentTime >= total) {
      simulation.currentTime = total;
      simulation.currentPoint = simulation.points.length ? simulation.points[simulation.points.length - 1] : null;
      simulation.running = false;
      simulation.frameId = null;
      simulationInfoEl.textContent = `${simulationSummary(simulation.data)}\nDone`;
      setStatus("Simulation done");
      draw();
      return;
    }
    simulation.currentPoint = pointAtTime(simulation.points, simulation.currentTime);
    simulationInfoEl.textContent = `${simulationSummary(simulation.data)}\n${simulation.currentTime.toFixed(1)}s`;
    draw();
    simulation.frameId = requestAnimationFrame(simulationTick);
  }

  function flattenSimulation(data) {
    const points = [];
    let time = 0;
    for (const segment of data.segments || []) {
      const rawPoints = segment.points || [];
      if (segment.type === "pierce" && rawPoints.length === 1) {
        const point = rawPoints[0];
        if (!points.length || points[points.length - 1].x !== point.x || points[points.length - 1].y !== point.y) {
          points.push({ ...point, t: time, type: "pierce" });
        }
        time += Number(segment.duration_s || 0);
        points.push({ ...point, t: time, type: "pierce" });
        continue;
      }
      if (rawPoints.length < 2) continue;
      const segmentLength = Math.max(0.0001, Number(segment.length_mm || 0.0001));
      for (let index = 0; index < rawPoints.length; index += 1) {
        const point = rawPoints[index];
        if (index === 0) {
          if (!points.length) {
            points.push({ ...point, t: time });
          }
          continue;
        }
        const prev = rawPoints[index - 1];
        const length = Math.sqrt((point.x - prev.x) ** 2 + (point.y - prev.y) ** 2);
        time += Number(segment.duration_s || 0) * (length / segmentLength);
        points.push({ ...point, t: time, type: segment.type });
      }
    }
    return points;
  }

  function simulationSummary(data) {
    const unsafeRapid = (data.segments || []).filter((segment) => segment.safe_travel_warning);
    const pauses = (data.segments || []).filter((segment) => segment.operator_pause_before);
    return [
      `Cut ${data.estimated_cut_s.toFixed(1)}s, rapid ${data.estimated_rapid_s.toFixed(1)}s, pierce ${(data.estimated_pierce_s || 0).toFixed(1)}s`,
      unsafeRapid.length ? `Unsafe rapid warnings ${unsafeRapid.length}` : null,
      pauses.length ? `Остановки M0: ${pauses.length}. Перед продолжением освободить путь.` : null,
      `Feed ${data.feed_rate_mm_min} mm/min, x${project.simulation.playback_rate}`,
    ].filter(Boolean).join("\n");
  }

  function projectFileSnapshot() {
    if (!project) {
      throw new Error("No project loaded");
    }
    syncProjectFromControls();
    syncAllPartQuantities();
    rebuildProjectImportState();
    return {
      ...project,
      format: projectFormat,
      format_version: projectFormatVersion,
      saved_at: new Date().toISOString(),
    };
  }

  function saveProjectFile() {
    try {
      const snapshot = projectFileSnapshot();
      project = normalizeProject(snapshot);
      saveProject();
      downloadText(
        `${fileSafeName(project.name)}.kerfgrid.json`,
        JSON.stringify(snapshot, null, 2),
        "application/json"
      );
      setStatus("Project saved");
    } catch (error) {
      issuesEl.textContent = `${error.name || "Error"}: ${error.message || error}`;
      setStatus("Save failed");
    }
  }

  function importButtonClick() {
    pendingImportMode = "any";
    importFileEl.accept = importAcceptAny;
    importSelectedFile({ openPickerIfEmpty: true });
  }

  function openProjectFilePicker(event = null) {
    pendingImportMode = "project";
    importFileEl.accept = importAcceptProject;
    setStatus("Select project");
    if (event && event.isTrusted === false) {
      return;
    }
    importFileEl.click();
  }

  async function loadExample() {
    const history = project ? captureMutationHistory() : null;
    const response = await fetch("/api/example");
    project = normalizeProject(await response.json());
    syncAllPartQuantities();
    rebuildProjectImportState();
    selectedKey = firstSelectablePlacementKey();
    invalidateSimulation();
    syncControlsFromProject();
    gcodeEl.value = "";
    issuesEl.textContent = "";
    saveProject();
    pushHistoryState(history, "Reload demo");
    draw();
    validateProject();
  }

  async function loadInitialProject() {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw && !localStorage.getItem(migrationBackupKey)) localStorage.setItem(migrationBackupKey, raw);
      document.getElementById("localProjectBackupBtn").hidden = !localStorage.getItem(migrationBackupKey);
    } catch (error) {
      document.getElementById("localProjectBackupBtn").hidden = true;
    }
    clearPendingProjectRequest();
    await sharedWorkspace.start(async () => {
      const stored = loadStoredProject();
      if (stored) return stored;
      const response = await fetch("/api/example");
      if (!response.ok) throw new Error(`Example request failed: HTTP ${response.status}`);
      return normalizeProject(await response.json());
    });
  }

  async function importSelectedFile(options = {}) {
    if (importing) return;
    const file = importFileEl.files && importFileEl.files[0];
    const mode = pendingImportMode || "any";
    if (!file) {
      if (options.openPickerIfEmpty) {
        setStatus("Select file");
        if (mode === "any") importFileEl.accept = importAcceptAny;
        importFileEl.click();
      } else {
        setStatus("No file selected");
      }
      return;
    }
    const history = project ? captureMutationHistory() : null;
    importing = true;
    let importSummary = null;
    updateHistoryControls();
    setStatus(`Importing ${file.name}`);
    try {
      const content = await file.text();
      if (file.name.toLowerCase().endsWith(".json")) {
        project = parseProjectFile(content);
        syncAllPartQuantities();
        rebuildProjectImportState();
        importSummary = { added: project.parts.length, updated: 0, autoLeadsCleared: 0, openedProject: true };
      } else if (mode !== "project" && file.name.toLowerCase().endsWith(".dxf")) {
        syncProjectFromControls();
        const importPlan = buildDxfImportPlan(content);
        if (!importPlan) {
          issuesEl.textContent = importLayerMappingErrors.join("\n");
          setStatus("Layer map invalid");
          return;
        }
        const baseProject = {
          ...project,
          import_options: importPlan.importOptions,
        };
        const result = await sharedWorkspace.importDxf({
          filename: file.name,
          content: importPlan.content,
          base_project: baseProject,
          import_options: importPlan.importOptions,
          layer_mapping: importPlan.importOptions.layer_mapping,
        });
        if (result.error) {
          issuesEl.textContent = `${result.type}: ${result.error}`;
          setStatus("Import failed");
          return;
        }
        const uiImportOptions = importPlan.uiImportOptions || project.import_options || {};
        project = normalizeProject({ ...result.project, import_options: uiImportOptions });
        importSummary = { ...result.import_summary, autoLeadsCleared: result.import_summary.auto_leads_cleared };
      } else {
        issuesEl.textContent = mode === "project"
          ? `Project file must be .json: ${file.name}`
          : `Unsupported file type: ${file.name}`;
        setStatus("Import failed");
        return;
      }
      selectedKey = normalizedSelectedKey(selectedKey);
      invalidateSimulation();
      syncControlsFromProject();
      gcodeEl.value = "";
      issuesEl.textContent = "";
      saveProject();
      pushHistoryState(history, `Import ${file.name}`);
      draw();
      await validateProject();
      const importIssues = project.import && Array.isArray(project.import.issues) ? project.import.issues.length : 0;
      const importAction = importSummary && importSummary.openedProject
        ? `Opened ${file.name}`
        : importSummary && importSummary.updated
        ? `Updated ${importSummary.updated}, added ${importSummary.added}`
        : `Imported ${file.name}`;
      const leadAction = importSummary && importSummary.autoLeadsCleared
        ? `, cleared ${importSummary.autoLeadsCleared} auto lead(s)`
        : "";
      setStatus(importIssues ? `${importAction}${leadAction} with ${importIssues} issue(s)` : `${importAction}${leadAction}`);
    } catch (error) {
      issuesEl.textContent = `${error.name || "Error"}: ${error.message || error}`;
      setStatus("Import failed");
    } finally {
      importing = false;
      pendingImportMode = "any";
      importFileEl.accept = importAcceptAny;
      importFileEl.value = "";
      updateHistoryControls();
    }
  }

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function droppedPartName(event) {
    if (!event.dataTransfer) return "";
    return (
      event.dataTransfer.getData("application/x-plasma-cam-part") ||
      event.dataTransfer.getData("text/plain") ||
      ""
    ).trim();
  }

  function canAcceptPartDrop(event) {
    if (!event.dataTransfer) return false;
    const types = Array.from(event.dataTransfer.types || []);
    return types.includes("application/x-plasma-cam-part") || types.includes("text/plain");
  }

  canvas.addEventListener("mousedown", (event) => {
    if (!project || dragging) return;
    if (event.button === 1 || (event.button === 0 && (panMode || spacePan))) {
      event.preventDefault();
      canvas.focus({ preventScroll: true });
      panning = { x: event.clientX, y: event.clientY, panX: viewState.panX, panY: viewState.panY,
        kind: event.button === 1 ? "middle" : spacePan ? "space" : "hand" };
      updatePanCursor();
      return;
    }
    if (event.button !== 0) return;
    canvas.focus({ preventScroll: true });
    const screen = canvasPoint(event);
    const rotateKey = hitTestRotateHandle(screen);
    const world = screenToWorld(screen);
    if (editorMode === "lead") {
      setLeadPoint(world);
      return;
    }
    if (editorMode === "tab") {
      addTabPoint(world);
      return;
    }
    selectedKey = rotateKey || hitTest(world);
    selectedZoneId = selectedKey ? null : hitTestZone(world);
    const placement = placementByKey(selectedKey);
    if (rotateKey && placement && !placement.locked) {
      dragging = {
        mode: "rotate",
        key: selectedKey,
        view: { ...view },
        history: captureMutationHistory(),
      };
    } else if (placement && !placement.locked) {
      dragging = {
        mode: "move",
        key: selectedKey,
        offsetX: placement.dx - world.x,
        offsetY: placement.dy - world.y,
        view: { ...view },
        history: captureMutationHistory(),
      };
    } else if (selectedZoneId) {
      const zone = zoneById(selectedZoneId);
      dragging = {
        mode: "zone",
        id: selectedZoneId,
        offsetX: zone.x_mm - world.x,
        offsetY: zone.y_mm - world.y,
        view: { ...view },
        history: captureMutationHistory(),
      };
    } else {
      dragging = null;
    }
    draw();
  });

  canvas.addEventListener("dragover", (event) => {
    if (!canAcceptPartDrop(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });

  canvas.addEventListener("drop", (event) => {
    const partName = droppedPartName(event);
    if (!partName || !partDef(partName)) return;
    event.preventDefault();
    addPartInstanceAt(partName, screenToWorld(canvasPoint(event)));
  });

  canvas.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const world = screenToWorld(canvasPoint(event));
    if (dragging.mode === "zone") {
      const zone = zoneById(dragging.id);
      if (!zone) return;
      zone.x_mm = world.x + dragging.offsetX;
      zone.y_mm = world.y + dragging.offsetY;
      draw();
      return;
    }
    const placement = placementByKey(dragging.key);
    if (!placement || placement.locked) return;
    if (dragging.mode === "rotate") {
      const radians = Math.atan2(world.y - placement.dy, world.x - placement.dx);
      placement.rotation_deg = normalizeAngle((radians * 180) / Math.PI);
    } else {
      const snapped = snapPlacementPoint({
        x: world.x + dragging.offsetX,
        y: world.y + dragging.offsetY,
      });
      placement.dx = snapped.x;
      placement.dy = snapped.y;
    }
    placement.manual = true;
    draw();
  });

  window.addEventListener("mousemove", (event) => {
    if (!panning) return;
    if (!(event.buttons & (panning.kind === "middle" ? 4 : 1))) {
      finishPanning();
      return;
    }
    viewState.panX = panning.panX + event.clientX - panning.x;
    viewState.panY = panning.panY + event.clientY - panning.y;
    drawViewChange();
  });

  canvas.addEventListener("wheel", (event) => {
    if (!project) return;
    event.preventDefault();
    if (dragging || panning) return;
    canvas.focus({ preventScroll: true });
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1;
    zoomView(Math.exp(-clamp(event.deltaY * unit, -600, 600) * 0.0015), canvasPoint(event));
  }, { passive: false });

  window.addEventListener("mouseup", () => {
    if (panning) {
      finishPanning();
      return;
    }
    if (dragging) {
      const history = dragging.history;
      const label = dragging.mode === "rotate" ? "Rotate" : dragging.mode === "zone" ? "Move zone" : "Move";
      invalidateSimulation();
      saveProject();
      pushHistoryState(history, label);
      validateProject();
    }
    dragging = null;
  });

  for (const control of Object.values(controls)) {
    control.addEventListener("input", () => {
      beginControlHistory(control);
      syncProjectFromControls();
      if (control !== controls.simPlayback) {
        invalidateSimulation();
      }
      saveProject();
      draw();
    });
    control.addEventListener("change", () => {
      beginControlHistory(control);
      syncProjectFromControls();
      if (control !== controls.simPlayback) {
        invalidateSimulation();
      }
      saveProject();
      commitPendingControlHistory("Settings");
      draw();
      validateProject();
    });
  }

  document.getElementById("duplicateBtn").addEventListener("click", duplicateSelected);
  document.getElementById("rotateBtn").addEventListener("click", rotateSelected);
  document.getElementById("mirrorBtn").addEventListener("click", mirrorSelected);
  document.getElementById("lockBtn").addEventListener("click", lockSelected);
  document.getElementById("deleteBtn").addEventListener("click", deleteSelected);
  selectedRotationsEl.addEventListener("change", applySelectedRotationControls);
  selectedGrainLockEl.addEventListener("change", applySelectedRotationControls);
  selectedAllowHoleFillerEl.addEventListener("change", applySelectedRotationControls);
  selectedAllowHoleParentEl.addEventListener("change", applySelectedRotationControls);
  document.getElementById("reviewDxfBtn").addEventListener("click", exportReviewDxf);
  document.getElementById("previewCutOrderBtn").addEventListener("click", previewCutOrder);
  document.getElementById("clearCutOrderPreviewBtn").addEventListener("click", clearCutOrderPreview);
  document.getElementById("templateDiskBtn").addEventListener("click", () => addTemplatePart("disk"));
  document.getElementById("templatePlateBtn").addEventListener("click", () => addTemplatePart("plate"));
  document.getElementById("templateFlangeBtn").addEventListener("click", () => addTemplatePart("flange"));
  document.getElementById("stopSimBtn").addEventListener("click", () => stopSimulation());
  document.getElementById("loadExampleBtn").addEventListener("click", loadExample);
  importFileEl.accept = importAcceptAny;
  clearSheetBtn.addEventListener("click", clearSheet);
  [
    ["toolbarImportBtn", importButtonClick],
    ["toolbarOpenProjectBtn", openProjectFilePicker],
    ["toolbarSaveProjectBtn", saveProjectFile],
    ["toolbarAutoNestBtn", autoNest],
    ["toolbarValidateBtn", validateProject],
    ["toolbarExportBtn", exportGcode],
    ["toolbarSendLinuxCncBtn", sendLinuxCnc],
    ["toolbarOutlineBtn", exportOutlineGcode],
    ["toolbarSimBtn", playSimulation],
    ["toolbarReportBtn", reviewReport],
  ].forEach(([id, handler]) => {
    const button = document.getElementById(id);
    if (button) button.addEventListener("click", handler);
  });
  document.getElementById("addKeepoutBtn").addEventListener("click", () => addZone("keepout"));
  document.getElementById("addClampBtn").addEventListener("click", () => addZone("clamp"));
  document.getElementById("addDamagedBtn").addEventListener("click", () => addZone("damaged"));
  document.getElementById("addRemnantBtn").addEventListener("click", () => addZone("remnant"));
  document.getElementById("addPierceKeepoutBtn").addEventListener("click", () => addZone("pierce_keepout"));
  document.getElementById("addSlatBtn").addEventListener("click", () => addZone("slat"));
  document.getElementById("deleteZoneBtn").addEventListener("click", deleteSelectedZone);
  document.getElementById("selectModeBtn").addEventListener("click", () => setEditorMode("select"));
  document.getElementById("leadEditBtn").addEventListener("click", () => setEditorMode("lead"));
  document.getElementById("tabEditBtn").addEventListener("click", () => setEditorMode("tab"));
  document.getElementById("clearLeadsBtn").addEventListener("click", clearLeads);
  document.getElementById("acceptAutoLeadsBtn").addEventListener("click", acceptAutoLeads);
  document.getElementById("clearAutoLeadsBtn").addEventListener("click", clearAutoLeads);
  document.getElementById("clearTabsBtn").addEventListener("click", clearTabs);
  document.getElementById("resetCutChartBtn").addEventListener("click", resetProjectCutChart);
  document.getElementById("exportCutChartBtn").addEventListener("click", exportCutChartProfile);
  document.getElementById("importCouponResultsBtn").addEventListener("click", importCouponResults);
  document.getElementById("zoomOutBtn").addEventListener("click", () => zoomView(1 / 1.25));
  document.getElementById("zoomInBtn").addEventListener("click", () => zoomView(1.25));
  const applyZoomInput = () => {
    const percent = zoomPercentEl.valueAsNumber;
    if (Number.isFinite(percent)) setViewZoom(percent / 100);
    zoomPercentEl.value = String(Math.round(viewState.zoom * 1000) / 10);
  };
  zoomPercentEl.addEventListener("change", applyZoomInput);
  zoomPercentEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      applyZoomInput();
      zoomPercentEl.blur();
    }
  });
  panViewBtn.addEventListener("click", togglePanMode);
  document.getElementById("fitSheetBtn").addEventListener("click", fitSheetView);
  document.getElementById("fitPartsBtn").addEventListener("click", fitPartsView);
  if (undoBtn) undoBtn.addEventListener("click", undoHistory);
  if (redoBtn) redoBtn.addEventListener("click", redoHistory);
  importFileEl.addEventListener("change", () => importSelectedFile());
  if (cutChartProfileFileEl) cutChartProfileFileEl.addEventListener("change", importCutChartProfileFile);
  if (couponResultsFileEl) couponResultsFileEl.addEventListener("change", loadCouponResultsFile);
  window.addEventListener("keydown", handleKeyboard);
  window.addEventListener("keyup", (event) => {
    if (event.code !== "Space") return;
    spacePan = false;
    if (panning?.kind === "space") finishPanning();
    updatePanCursor();
  });
  window.addEventListener("blur", () => {
    spacePan = false;
    finishPanning();
  });
  window.addEventListener("resize", draw);
  document.getElementById("workspaceReloadBtn").addEventListener("click", () => sharedWorkspace.resolve(false));
  document.getElementById("workspaceKeepLocalBtn").addEventListener("click", () => sharedWorkspace.resolve(true));
  document.getElementById("localProjectBackupBtn").addEventListener("click", () => {
    const raw = localStorage.getItem(migrationBackupKey);
    if (raw) downloadText("kerfgrid-before-shared.kerfgrid.json", raw, "application/json");
  });

  setupTabs();
  loadCutChart();
  loadInitialProject();
})();
