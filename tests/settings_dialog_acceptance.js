async (page) => {
  const origin = "http://127.0.0.1:8765";
  const snapshot = await (await page.request.get(origin + "/api/workspace")).json();
  const context = await page.context().browser().newContext({viewport:{width:1280,height:800}});
  const target = await context.newPage();
  const errors = [];
  target.on("pageerror", error => errors.push(error.message));
  const state = () => target.evaluate(() => JSON.parse(localStorage.getItem("kerfgrid.project.v1")));
  const saved = () => target.waitForFunction(() => document.getElementById("settingsSyncStatus").textContent === "Saved on server");
  const selectTab = key => target.locator(`#settings-tab-${key}`).click();
  const rowSelector = '#cutChartTable tr[data-thickness="3"][data-nozzle="0.9"]';
  try {
    const fixture = await (await page.request.get(origin + "/api/example")).json();
    fixture.name = "settings-dialog-acceptance";
    fixture.cut_chart = null;
    const response = await page.request.post(origin + "/api/workspace", {
      data:{expected_revision:snapshot.revision,project:fixture}
    });
    if (!response.ok()) throw new Error(await response.text());
    await target.goto(origin);
    await saved();
    await target.waitForFunction(() => document.querySelectorAll("#cutChartTable tbody tr").length > 0);
    const before = await state();
    const ids = await target.evaluate(() => [...document.querySelectorAll("[id]")].map(node => node.id));
    if (ids.length !== new Set(ids).size) throw new Error("Duplicate control IDs");
    for (const id of ["nestAttempts","materialMode","leadClearance","cutOrderStrategy","cutChartTable","importLayerMode","templateOuterDia"]) {
      if (!await target.locator(`#settingsDialog #${id}`).count()) throw new Error(`Advanced control remains in sidebar: ${id}`);
    }
    for (const id of ["sheetWidth","partsTable","selectedInfo","nestLayoutMode","spacing","safeTravel","thickness","feedMode","leadLength"]) {
      if (!await target.locator(`.sidebar #${id}`).count()) throw new Error(`Daily control moved out of sidebar: ${id}`);
    }
    await target.locator("#settingsBtn").click();
    if (!await target.locator("#settingsDialog").evaluate(node => node.matches(":modal"))) throw new Error("Settings are not modal");
    if (!await target.locator(rowSelector).evaluate(node => node.classList.contains("active"))) throw new Error("Current cut row is not highlighted");
    await target.locator("#settings-tab-chart").press("ArrowRight");
    if (!await target.locator("#settings-panel-cutting").isVisible()) throw new Error("Arrow tab selection failed");
    await target.keyboard.press("End");
    if (!await target.locator("#settings-panel-stock").isVisible()) throw new Error("End tab selection failed");
    await target.keyboard.press("Home");
    await target.locator("#settings-panel-chart").focus();
    for (const key of ["h","Delete","ArrowDown","Control+z"]) await target.keyboard.press(key);
    if (JSON.stringify(await state()) !== JSON.stringify(before)) throw new Error("Modal keys changed the drawing");
    if (await target.locator("#panViewBtn").getAttribute("aria-pressed") !== "false") throw new Error("Modal H activated pan");
    await target.locator("#settingsDoneBtn").focus();
    await target.keyboard.press("Tab");
    if (!await target.evaluate(() => document.getElementById("settingsDialog").contains(document.activeElement))) throw new Error("Focus escaped modal");
    for (const width of [1280, 900, 390]) {
      await target.setViewportSize({width,height:800});
      for (const key of ["chart","cutting","nesting","order","import","stock"]) {
        await selectTab(key);
        const layout = await target.evaluate(() => {
          const dialog = document.getElementById("settingsDialog");
          const rect = dialog.getBoundingClientRect();
          const body = dialog.querySelector(".settings-body");
          return {left:rect.left,right:rect.right,bottom:rect.bottom,top:rect.top,
            overflow:body.scrollWidth-body.clientWidth,footer:dialog.querySelector(".settings-footer").getBoundingClientRect().bottom};
        });
        if (layout.left < 0 || layout.right > width+1 || layout.top < 0 || layout.bottom > 801 || layout.overflow > 1 || layout.footer > 801) {
          throw new Error(`Settings overflow ${key} at ${width}: ${JSON.stringify(layout)}`);
        }
      }
    }
    await target.setViewportSize({width:1280,height:800});
    await selectTab("chart");
    const tableWidth = await target.locator(".chart-table-wrap").evaluate(node => ({overflow:node.scrollWidth-node.clientWidth,width:node.clientWidth}));
    if (tableWidth.width < 1000 || tableWidth.overflow > 1) throw new Error(`Chart remains narrow: ${JSON.stringify(tableWidth)}`);
    const row = target.locator(rowSelector);
    const feed = row.locator('[data-field="feed_rate_mm_min"]');
    await feed.fill("1267");
    await feed.press("Tab");
    const nextField = await target.evaluate(() => document.activeElement.dataset.field);
    if (nextField !== "kerf_width_mm") throw new Error(`Chart lost Tab focus after editing: ${nextField}`);
    await saved();
    if (!(await state()).cut_chart.rows.some(row => row.thickness_mm === 3 && row.nozzle_mm === 0.9 && row.feed_rate_mm_min === 1267)) throw new Error("Chart edit not saved");
    await target.locator("#chartSmallFeatures").check();
    const small = row.locator('[data-field="small_hole_threshold_mm"]');
    await small.fill("77");
    await small.press("Tab");
    const earlyOff = row.locator('[data-field="small_hole_torch_off_before_end_mm"]');
    await earlyOff.fill("0.7");
    await earlyOff.press("Escape");
    if (await target.locator("#settingsDialog").evaluate(node => node.open)) throw new Error("Escape did not close modal");
    await saved();
    const edited = (await state()).cut_chart.rows.find(row => row.thickness_mm === 3 && row.nozzle_mm === 0.9);
    if (edited.small_hole_threshold_mm !== 77 || edited.small_hole_torch_off_before_end_mm !== 0.7) throw new Error("Escape lost active cell edit");
    if (!await target.locator("#settingsBtn").evaluate(node => document.activeElement === node)) throw new Error("Focus not restored to opener");
    await target.locator("#undoBtn").click();
    if ((await state()).cut_chart.rows.find(row => row.thickness_mm === 3 && row.nozzle_mm === 0.9).small_hole_torch_off_before_end_mm === 0.7) throw new Error("Chart edit is not undoable");
    await target.locator('.tab-btn[data-tab="cut"]').click();
    await target.locator('.sidebar [data-settings-open="chart"]').click();
    if (!await target.locator("#settings-panel-chart").isVisible()) throw new Error("Cut Chart shortcut failed");
    const undoneRow = (await state()).cut_chart.rows.find(row => row.thickness_mm === 3 && row.nozzle_mm === 0.9);
    if (Number(await row.locator('[data-field="small_hole_torch_off_before_end_mm"]').inputValue()) !== undoneRow.small_hole_torch_off_before_end_mm) throw new Error("Chart still displays the undone value");
    const firstRow = target.locator("#cutChartTable tbody tr").first();
    await firstRow.locator('[data-field="thickness_mm"]').fill("0.85");
    await firstRow.locator('[data-field="thickness_mm"]').press("Tab");
    await target.evaluate(() => { document.getElementById("gcode").value = "stale preview"; });
    await firstRow.locator("button").click();
    await saved();
    if ((await state()).cut.thickness_mm !== 0.85) throw new Error("Row selection used stale values after editing");
    if (await target.locator("#gcode").inputValue()) throw new Error("Chart selection kept stale G-code");
    const chooser = target.waitForEvent("filechooser");
    await target.locator("#importCutChartBtn").click();
    await (await chooser).setFiles([]);
    await target.locator("#chartSmallFeatures").uncheck();
    await target.locator(".chart-table-wrap").evaluate(node => { node.scrollLeft = 0; node.scrollTop = 0; });
    await target.screenshot({path:"output/playwright/settings-chart.png"});
    await selectTab("nesting");
    await target.locator("#nestAttempts").fill("37");
    await target.locator("#settingsDoneBtn").click();
    await saved();
    if ((await state()).nesting.auto_nest_attempts !== 37) throw new Error("Advanced setting not saved");
    await target.reload();
    await saved();
    await target.locator("#settingsBtn").click();
    await selectTab("nesting");
    if (await target.locator("#nestAttempts").inputValue() !== "37") throw new Error("Advanced settings lost after reload");
    await target.screenshot({path:"output/playwright/settings-nesting.png"});
    const remoteBefore = await (await page.request.get(origin + "/api/workspace")).json();
    const external = JSON.parse(JSON.stringify(remoteBefore.project));
    external.name = "settings-concurrent-change";
    const otherSave = await page.request.post(origin + "/api/workspace", {
      data:{expected_revision:remoteBefore.revision,project:external}
    });
    if (!otherSave.ok()) throw new Error("Could not seed concurrent change");
    await target.waitForTimeout(1700);
    if ((await state()).name === external.name) throw new Error("Open modal adopted another browser's job");
    await target.locator("#nestAttempts").fill("38");
    await target.locator("#nestAttempts").press("Tab");
    await target.locator("#settingsConflict").waitFor({state:"visible"});
    if ((await state()).nesting.auto_nest_attempts !== 38) throw new Error("Conflict discarded local draft");
    await target.locator("#settingsKeepLocalBtn").click();
    await saved();
    const resolved = await (await page.request.get(origin + "/api/workspace")).json();
    if (resolved.project.nesting.auto_nest_attempts !== 38 || resolved.project.name !== fixture.name) throw new Error("Modal conflict resolution failed");
    const serverChoice = JSON.parse(JSON.stringify(resolved.project));
    serverChoice.cut_chart.rows[0].feed_rate_mm_min = 2222;
    const serverSave = await page.request.post(origin + "/api/workspace", {data:{expected_revision:resolved.revision,project:serverChoice}});
    if (!serverSave.ok()) throw new Error("Could not seed server chart choice");
    await target.locator("#nestAttempts").fill("39");
    await target.locator("#nestAttempts").press("Tab");
    await target.locator("#settingsConflict").waitFor({state:"visible"});
    await target.locator("#settingsReloadBtn").click();
    await saved();
    await selectTab("chart");
    if (Number(await target.locator('#cutChartTable tbody tr [data-field="feed_rate_mm_min"]').first().inputValue()) !== 2222) throw new Error("Server choice did not refresh the chart");
    await selectTab("stock");
    const partCount = (await state()).parts.length;
    await target.locator("#templateDiskBtn").click();
    if (await target.locator("#settingsDialog").evaluate(node => node.open)) throw new Error("Template did not return to field");
    if ((await state()).parts.length !== partCount+1) throw new Error("Template control stopped working");
    await target.locator("#settingsBtn").click();
    await selectTab("order");
    await target.locator("#settingsCloseBtn").click();
    await target.screenshot({path:"output/playwright/settings-sidebar.png"});
    if (errors.length) throw new Error(errors.join("\n"));
    return {modal:true,tabs:6,widths:[1280,900,390],daily_sidebar:true,chart_wide:true,
      keyboard_isolation:true,focus_trap:true,tab_between_cells:true,escape_commits:true,
      chart_undo:true,chart_undo_refreshes_cells:true,chart_select_edited_row:true,chart_import_picker:true,
      advanced_settings_persist:true,modal_conflict_resolution:true,template_returns_to_field:true};
  } finally {
    await context.close();
    const latest = await (await page.request.get(origin + "/api/workspace")).json();
    const restored = await page.request.post(origin + "/api/workspace", {data:{expected_revision:latest.revision,project:snapshot.project}});
    if (!restored.ok()) throw new Error("Could not restore workspace after settings test");
  }
}
