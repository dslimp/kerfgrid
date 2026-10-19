export function setupSettingsDialog({ dialog, onOpen, onClose }) {
  const tabs = [...dialog.querySelectorAll("[data-settings-tab]")];
  const panels = [...dialog.querySelectorAll('[role="tabpanel"]')];
  let opener = null;
  let activeTab = tabs[0].dataset.settingsTab;

  function selectTab(key, focus = false) {
    if (!tabs.some(tab => tab.dataset.settingsTab === key)) return;
    activeTab = key;
    tabs.forEach(tab => {
      const selected = tab.dataset.settingsTab === key;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    panels.forEach(panel => { panel.hidden = panel.id !== `settings-panel-${key}`; });
    dialog.querySelector(".settings-body").scrollTop = 0;
  }

  function close() {
    if (!dialog.open) return;
    if (dialog.contains(document.activeElement)) document.activeElement.blur();
    dialog.close();
  }

  document.querySelectorAll("[data-settings-open]").forEach(button => {
    button.addEventListener("click", () => {
      opener = button;
      selectTab(button.dataset.settingsOpen || activeTab);
      onOpen?.();
      dialog.showModal();
      tabs.find(tab => tab.dataset.settingsTab === activeTab).focus();
    });
  });
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab.dataset.settingsTab));
    tab.addEventListener("keydown", event => {
      let next = index;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      selectTab(tabs[next].dataset.settingsTab, true);
    });
  });
  dialog.querySelector("#settingsCloseBtn").addEventListener("click", close);
  dialog.querySelector("#settingsDoneBtn").addEventListener("click", close);
  dialog.querySelector("#importCutChartBtn").addEventListener("click", () => {
    dialog.querySelector("#cutChartProfileFile").click();
  });
  dialog.addEventListener("cancel", event => {
    event.preventDefault();
    close();
  });
  dialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const focusable = [...dialog.querySelectorAll("button, a[href], input, select, textarea, [tabindex]")]
      .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.addEventListener("close", () => {
    onClose?.();
    opener?.focus({ preventScroll: true });
  });
  dialog.querySelectorAll("[data-settings-exit]").forEach(button => button.addEventListener("click", close));
  dialog.querySelector("#chartSmallFeatures").addEventListener("change", event => {
    dialog.querySelector("#cutChartTable").classList.toggle("show-small-features", event.target.checked);
  });
}
