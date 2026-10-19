export class SharedWorkspace {
  constructor({ onProject, onState, isBusy, pollMs = 1500 }) {
    this.onProject = onProject;
    this.onState = onState;
    this.isBusy = isBusy;
    this.pollMs = pollMs;
    this.revision = null;
    this.pending = null;
    this.saving = false;
    this.loading = false;
    this.applying = false;
    this.conflict = null;
    this.files = [];
    this.timer = null;
  }

  async request(path, payload = null) {
    const response = await fetch(path, payload === null ? { cache: "no-store" } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || `HTTP ${response.status}`);
      error.workspace = data.workspace || null;
      throw error;
    }
    return data;
  }

  adopt(snapshot, apply = true) {
    this.revision = snapshot.revision;
    if (snapshot.files) this.files = snapshot.files;
    if (apply && snapshot.project) {
      this.applying = true;
      try { this.onProject(snapshot.project); } finally { this.applying = false; }
    }
    this.onState({ status: "Saved on server", files: this.files, conflict: false });
  }

  async start(initialProject) {
    this.loading = true;
    try {
      let snapshot = await this.request("/api/workspace");
      if (!snapshot.project) {
        try {
          snapshot = await this.request("/api/workspace", {
            expected_revision: snapshot.revision, project: await initialProject(),
          });
        } catch (error) {
          if (!error.workspace) throw error;
          snapshot = error.workspace;
        }
      }
      this.adopt(snapshot);
    } catch (error) {
      this.onState({ status: "Server unavailable - local draft", files: this.files, conflict: false });
      this.applying = true;
      try { this.onProject(await initialProject()); } finally { this.applying = false; }
    } finally {
      this.loading = false;
      this.timer = setInterval(() => this.refresh(), this.pollMs);
    }
  }

  queue(project) {
    if (this.applying) return;
    this.pending = JSON.parse(JSON.stringify(project));
    this.onState({ status: "Saving…", files: this.files, conflict: Boolean(this.conflict) });
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.flush(), 250);
  }

  async flush() {
    if (this.saving || this.loading || this.conflict || !this.pending) return;
    this.saving = true;
    try {
      while (this.pending && !this.conflict) {
        const pending = this.pending;
        if (this.revision === null) {
          const snapshot = await this.request("/api/workspace");
          if (snapshot.project) {
            this.conflict = snapshot;
            this.onState({ status: "Server has another project - choose which to keep", files: snapshot.files, conflict: true });
            break;
          }
          this.revision = snapshot.revision;
        }
        const snapshot = await this.request("/api/workspace", { expected_revision: this.revision, project: pending });
        this.adopt(snapshot, false);
        if (this.pending === pending) this.pending = null;
      }
    } catch (error) {
      this.conflict = error.workspace;
      this.onState({ status: this.conflict ? "Changed elsewhere - local changes kept" : "Not saved - server unavailable",
        files: this.conflict?.files || this.files, conflict: Boolean(this.conflict) });
    } finally {
      this.saving = false;
    }
  }

  async refresh() {
    if (this.saving || this.loading || this.conflict || this.isBusy()) return;
    if (this.pending) {
      await this.flush();
      return;
    }
    this.loading = true;
    try {
      const snapshot = await this.request(`/api/workspace?after_revision=${this.revision ?? -1}`);
      if (!snapshot.unchanged && !this.pending && !this.isBusy()) this.adopt(snapshot);
    } catch (error) {
      this.onState({ status: "Server unavailable", files: this.files, conflict: false });
    } finally {
      this.loading = false;
    }
  }

  async resolve(useLocal) {
    if (!this.conflict) return;
    const snapshot = await this.request("/api/workspace");
    this.conflict = null;
    this.revision = snapshot.revision;
    if (useLocal && this.pending) {
      await this.flush();
    } else {
      this.pending = null;
      this.loading = true;
      this.adopt(snapshot);
      this.loading = false;
    }
  }

  async importDxf(payload) {
    clearTimeout(this.saveTimer);
    while (this.saving) await new Promise((resolve) => setTimeout(resolve, 25));
    await this.flush();
    if (this.conflict || this.pending || this.revision === null) throw new Error("Save or resolve local changes before importing");
    try {
      const snapshot = await this.request("/api/workspace/import-dxf", {
        ...payload, expected_revision: this.revision,
        request_id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      });
      if (this.pending) {
        this.conflict = snapshot;
        this.onState({ status: "Import saved - local changes kept separately", files: snapshot.files, conflict: true });
        throw new Error("Import saved on server; resolve changes made during import");
      }
      this.loading = true;
      this.adopt(snapshot);
      return snapshot;
    } catch (error) {
      if (error.workspace) {
        this.conflict = error.workspace;
        this.onState({ status: "Changed elsewhere - retry import after reloading", files: error.workspace.files, conflict: true });
      }
      throw error;
    } finally {
      this.loading = false;
    }
  }
}
