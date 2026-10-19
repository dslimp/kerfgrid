async (page) => {
  const browser = page.context().browser();
  const origin = "http://127.0.0.1:8765";
  const current = await (await page.request.get(origin + "/api/workspace")).json();
  const contexts = [await browser.newContext(), await browser.newContext()];
  let result;
  let stage = "load shared project";
  try {
    await contexts[1].addInitScript(() => {
      localStorage.setItem("kerfgrid.project.v1", JSON.stringify({
        format: "kerfgrid-project", format_version: 2, name: "stale-browser",
        sheet: { width_mm: 17, height_mm: 19 }, parts: [], placements: [],
      }));
    });
    const [a, b] = await Promise.all(contexts.map((context) => context.newPage()));
    await Promise.all([a.goto(origin), b.goto(origin)]);
    for (const target of [a, b]) {
      await target.waitForFunction(() => document.getElementById("workspaceStatus").textContent === "Saved on server");
      const width = await target.locator("#sheetWidth").inputValue();
      if (Number(width) !== current.project.sheet.width_mm) throw new Error("Browser did not load authoritative server project");
    }
    stage = "save width on first browser";
    await a.locator("#sheetWidth").fill("613");
    await a.locator("#sheetWidth").press("Tab");
    await a.waitForFunction(() => document.getElementById("workspaceStatus").textContent === "Saved on server");
    stage = "receive width on second browser";
    await b.waitForFunction(() => document.getElementById("sheetWidth").value === "613");
    await b.route("**/api/workspace?**", (route) => route.abort());
    stage = "save newer width";
    await a.locator("#sheetWidth").fill("619");
    await a.locator("#sheetWidth").press("Tab");
    await a.waitForFunction(() => document.getElementById("workspaceStatus").textContent === "Saved on server");
    stage = "stale write conflict";
    await b.locator("#sheetHeight").fill("777");
    await b.locator("#sheetHeight").press("Tab");
    await b.locator("#workspaceConflict").waitFor({ state: "visible" });
    const protectedState = await (await a.request.get(origin + "/api/workspace")).json();
    if (protectedState.project.sheet.width_mm !== 619 || protectedState.project.sheet.height_mm === 777) {
      throw new Error("Stale edit overwrote server state");
    }
    const draft = await b.evaluate(() => JSON.parse(localStorage.getItem("kerfgrid.project.v1")));
    if (draft.sheet.height_mm !== 777) throw new Error("Unsaved draft lost on conflict");
    stage = "resolve stale write";
    await b.locator("#workspaceReloadBtn").click();
    await b.locator("#workspaceConflict").waitFor({ state: "hidden" });
    await b.unroute("**/api/workspace?**");
    const resetRevision = await (await a.request.get(origin + "/api/workspace")).json();
    const fixture = await (await a.request.get(origin + "/api/example")).json();
    await a.request.post(origin + "/api/workspace", {
      data: { expected_revision: resetRevision.revision, project: fixture },
    });
    const content = ["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
      "0", "SECTION", "2", "ENTITIES", "0", "LWPOLYLINE", "8", "0", "90", "6", "70", "1",
      "10", "-60", "20", "0", "10", "30.5", "20", "0", "10", "30.5", "20", "-10",
      "10", "60", "20", "-10", "10", "60", "20", "24.293520995850216", "10", "-60", "20", "49.80030839625286",
      "0", "ENDSEC", "0", "EOF", ""].join("\n");
    stage = "upload DXF by API";
    const uploadedResponse = await a.request.post(origin + "/api/workspace/import-dxf", {
      data: { filename: "shared-api-eave-test.dxf", content, quantity: 1, thickness_mm: 4, request_id: "browser-test-" + Date.now() },
    });
    if (!uploadedResponse.ok()) throw new Error(await uploadedResponse.text());
    const uploaded = await uploadedResponse.json();
    stage = "receive API upload in both browsers";
    for (const target of [a, b]) {
      await target.waitForFunction(() => document.querySelector("#partsTable").textContent.includes("shared-api-eave-test.dxf"));
      if (await target.locator("#partsTable tbody tr").count() !== 1) throw new Error("Expected one uploaded part");
      if (await target.locator("#partsTable tbody input").inputValue() !== "1") throw new Error("Expected quantity 1");
      if (await target.locator("#thickness").inputValue() !== "4") throw new Error("Thickness not shared");
      await target.locator("#workspaceFiles a").filter({ hasText: "shared-api-eave-test.dxf" }).waitFor();
    }
    const raw = await a.request.get(origin + "/api/workspace/files/" + uploaded.file_id);
    if (await raw.text() !== content) throw new Error("Original DXF changed");
    await a.locator("#fitPartsBtn").click();
    await a.screenshot({ path: "output/playwright/shared-workspace-2026-10-14.png" });
    result = { browsers: 2, shared_edits: true, stale_write_protected: true, local_draft_kept: true,
      agent_upload_visible: true, quantity: 1, thickness_mm: 4, original_dxf_preserved: true };
  } catch (error) {
    throw new Error(`${stage}: ${error.message}`);
  } finally {
    for (const context of contexts) await context.close();
    const latest = await (await page.request.get(origin + "/api/workspace")).json();
    await page.request.post(origin + "/api/workspace", {
      data: { expected_revision: latest.revision, project: current.project },
    });
  }
  return result;
}
