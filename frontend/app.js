// Frontend logic — call backend extract endpoint and render formats.

const form = document.getElementById("form");
const urlInput = document.getElementById("url");
const submitBtn = document.getElementById("submit-btn");
const btnText = submitBtn.querySelector(".btn-text");
const btnSpinner = submitBtn.querySelector(".btn-spinner");
const resultEl = document.getElementById("result");
const errorEl = document.getElementById("error");

// Default to same-origin if served by FastAPI; allow override via ?api=...
const apiBase = new URLSearchParams(location.search).get("api") || "";

function setLoading(on) {
  submitBtn.disabled = on;
  btnText.textContent = on ? "Sedang ambil..." : "Ambil video";
  btnSpinner.hidden = !on;
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtBytes(n) {
  if (!n) return "";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0; let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${u[i]}`;
}

function showError(msg) {
  resultEl.hidden = true;
  errorEl.hidden = false;
  errorEl.innerHTML = `<strong>Gagal:</strong> ${escapeHtml(msg)}`;
}

function showResult(data) {
  errorEl.hidden = true;
  resultEl.hidden = false;
  const platformBadge = `<span class="badge ${data.platform.slice(0,2)}">${escapeHtml(data.platform)}</span>`;
  const broker = data.broker ? `<span class="broker">via ${escapeHtml(data.broker)}</span>` : "";
  const thumb = data.thumbnail ? `<img src="${escapeHtml(data.thumbnail)}" alt="" referrerpolicy="no-referrer" />` : "";
  const uploader = data.uploader ? `<p class="uploader">@${escapeHtml(data.uploader)}</p>` : "";

  // Title vs description: many platforms put the caption in `title`. Show both.
  const rawTitle = (data.title || `${data.platform}-video`).trim();
  const isLongCaption = rawTitle.length > 80 || rawTitle.includes("\n");
  const titleText = isLongCaption ? rawTitle.slice(0, 80).replace(/\n.*/, "") + "…" : rawTitle;
  const descBlock = isLongCaption ? `<div class="desc">${escapeHtml(rawTitle)}</div>` : "";

  const safeTitle = rawTitle.replace(/[^\w\-. ]+/g, "_").slice(0, 80) || `${data.platform}-video`;

  let durationLabel = "";
  if (data.duration) {
    const s = Math.round(data.duration);
    const mm = Math.floor(s / 60);
    const ss = (s % 60).toString().padStart(2, "0");
    durationLabel = `<span class="meta-tag">⏱ ${mm}:${ss}</span>`;
  }

  const formatRows = data.formats.map((f) => {
    const dlUrl = `${apiBase}/api/download?url=${encodeURIComponent(f.url)}&filename=${encodeURIComponent(safeTitle + "." + (f.ext || "mp4"))}`;
    const sizeTag = f.filesize ? `<span class="meta-tag">${fmtBytes(f.filesize)}</span>` : "";
    return `
      <div class="format-row">
        <div><span class="q">${escapeHtml(f.quality)}</span>${sizeTag}</div>
        <a href="${dlUrl}" download>Download</a>
      </div>`;
  }).join("");

  resultEl.innerHTML = `
    <div class="meta">
      ${thumb}
      <div class="meta-text">
        <h2 class="title">${escapeHtml(titleText)}</h2>
        ${uploader}
        <div class="meta-tags">${platformBadge} ${broker} ${durationLabel}</div>
        ${descBlock}
      </div>
    </div>
    <div class="formats">
      ${formatRows || '<p class="uploader">Tidak ada format tersedia.</p>'}
    </div>
  `;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;

  setLoading(true);
  resultEl.hidden = true;
  errorEl.hidden = true;
  try {
    const r = await fetch(`${apiBase}/api/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await r.json();
    if (!data.ok) {
      showError(data.error || "Tidak ada video yang bisa diambil dari URL itu.");
      return;
    }
    showResult(data);
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    setLoading(false);
  }
});
