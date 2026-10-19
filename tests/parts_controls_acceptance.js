async (page) => {
  const origin = "http://127.0.0.1:8765";
  const snapshot = await (await page.request.get(origin + "/api/workspace")).json();
  const context = await page.context().browser().newContext();
  const target = await context.newPage();
  const state = () => target.evaluate(() => JSON.parse(localStorage.getItem("kerfgrid.project.v1")));
  const saved = () => target.waitForFunction(() => document.getElementById("workspaceStatus").textContent === "Saved on server");
  let releaseSimulation;
  try {
    const fixture = await (await page.request.get(origin + "/api/example")).json();
    fixture.name = "parts-controls-acceptance";
    fixture.parts[0].source_file = "very_long_workshop_part_filename_".repeat(5) + ".dxf";
    fixture.parts[0].import_issues = [{code:"test_warning",message:"Import warning",blocking:false}];
    fixture.parts.push({...JSON.parse(JSON.stringify(fixture.parts[0])),name:"second_part",source_file:"second.dxf"});
    fixture.placements.push({...fixture.placements[0],part_name:"second_part",dx:700});
    fixture.zones = [{id:"zone-test",type:"clamp",x_mm:950,y_mm:450,width_mm:10,height_mm:10}];
    fixture.tabs = [{contour_name:"disk_1_outer",x_mm:450,y_mm:250,length_mm:2}];
    fixture.lead_overrides = [{contour_name:"disk_1_outer",start_x_mm:450,start_y_mm:250}];
    const response = await page.request.post(origin + "/api/workspace", {
      data:{expected_revision:snapshot.revision,project:fixture}
    });
    if (!response.ok()) throw new Error(await response.text());
    await target.goto(origin);
    await saved();
    await target.waitForFunction(() => document.querySelectorAll("#partsTable .part-actions").length === 2);
    const before = await state();
    for (const width of [1280, 900, 390]) {
      await target.setViewportSize({width,height:800});
      await target.locator("#partsTable").scrollIntoViewIfNeeded();
      const layout = await target.evaluate(() => {
        const panel = document.querySelector(".parts-panel");
        const wrap = document.querySelector(".parts-panel .table-wrap");
        const bounds = wrap.getBoundingClientRect();
        const actions = [...document.querySelectorAll("#partsTable .part-actions button")].map(button => {
          const rect = button.getBoundingClientRect();
          return rect.left >= bounds.left && rect.right <= bounds.right + 1 && rect.width >= 28;
        });
        return {overflow:wrap.scrollWidth-wrap.clientWidth,panelOverflow:panel.scrollWidth-panel.clientWidth,actions};
      });
      if (layout.overflow > 1 || layout.panelOverflow > 1 || layout.actions.some(value => !value)) {
        throw new Error(`Parts actions overflow at ${width}: ${JSON.stringify(layout)}`);
      }
    }
    await target.setViewportSize({width:1280,height:800});
    await target.locator(".parts-panel").screenshot({path:"output/playwright/parts-controls-desktop.png"});
    await target.locator("#partsTable .part-actions button:last-child").first().click();
    if ((await state()).parts.length !== 1) throw new Error("Delete did not remove the part");
    await target.locator("#undoBtn").click();
    if ((await state()).parts.length !== 2) throw new Error("Delete undo failed");
    await saved();
    let markRequested;
    const requested = new Promise(resolve => { markRequested = resolve; });
    const gate = new Promise(resolve => { releaseSimulation = resolve; });
    await target.route("**/api/simulate", async route => {
      const response = await route.fetch();
      markRequested();
      await gate;
      await route.fulfill({response});
    });
    await target.locator("#toolbarSimBtn").click();
    await Promise.race([requested,target.waitForTimeout(15000).then(() => { throw new Error("Simulation was not requested"); })]);
    await target.evaluate(() => { document.getElementById("gcode").value = "G0 X10 Y20"; });
    await target.locator("#clearSheetBtn").click();
    releaseSimulation();
    await target.waitForTimeout(300);
    const cleared = await state();
    for (const key of ["parts","placements","zones","tabs","lead_overrides"]) {
      if (cleared[key].length) throw new Error(`Clear left ${key}`);
    }
    if (JSON.stringify(cleared.sheet) !== JSON.stringify(before.sheet) || JSON.stringify(cleared.cut) !== JSON.stringify(before.cut)) {
      throw new Error("Clear changed sheet or process settings");
    }
    if (await target.locator("#gcode").inputValue()) throw new Error("Clear left stale G-code");
    if (await target.locator("#simulationInfo").textContent() !== "Simulation idle") throw new Error("Late response restored simulation");
    if (!await target.locator("#clearSheetBtn").isDisabled()) throw new Error("Clear should disable on an empty sheet");
    await target.locator("#undoBtn").click();
    const restored = await state();
    for (const key of ["parts","placements","zones","tabs","lead_overrides"]) {
      if (JSON.stringify(restored[key]) !== JSON.stringify(before[key])) throw new Error(`Undo did not restore ${key}`);
    }
    await target.locator("#redoBtn").click();
    await saved();
    const remote = await (await page.request.get(origin + "/api/workspace")).json();
    if (remote.project.parts.length || remote.project.zones.length) throw new Error("Clear did not persist on server");
    await target.reload();
    await saved();
    if ((await state()).parts.length) throw new Error("Parts returned after reload");
    const duplicates = ["importBtn","openProjectBtn","saveProjectBtn","autoNestBtn","validateBtn","exportBtn","outlineBtn","reviewReportBtn","simulateBtn"];
    for (const id of duplicates) {
      if (await target.locator("#"+id).count()) throw new Error(`Duplicated sidebar action remains: ${id}`);
    }
    await target.setViewportSize({width:1280,height:800});
    await target.screenshot({path:"output/playwright/parts-controls-empty.png",fullPage:true});
    return {widths:[1280,900,390],horizontal_scroll:false,delete_and_undo:true,clear_undo_redo:true,
      clear_persists:true,settings_preserved:true,late_simulation_discarded:true,duplicates_removed:true};
  } finally {
    if (releaseSimulation) releaseSimulation();
    await context.close();
    const latest = await (await page.request.get(origin + "/api/workspace")).json();
    await page.request.post(origin + "/api/workspace", {data:{expected_revision:latest.revision,project:snapshot.project}});
  }
}
