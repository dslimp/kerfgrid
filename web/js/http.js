export async function postJson(url, payload, options = {}) {
  const controller = options.timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), options.timeoutMs) : null;
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller ? controller.signal : undefined,
    });
    const text = await response.text();
    const data = text ? JSON.parse(text) : {};
    if (!response.ok && !data.error) {
      data.error = response.statusText || `HTTP ${response.status}`;
      data.type = "HTTPError";
    }
    return data;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export function downloadText(filename, text, type = "text/plain") {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function fileSafeName(value) {
  return String(value || "kerfgrid_project")
    .trim()
    .replace(/[^a-z0-9._-]+/gi, "_")
    .replace(/^_+|_+$/g, "") || "kerfgrid_project";
}
