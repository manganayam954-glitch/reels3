// Frontend logic — call backend extract endpoint and render formats.

const I18N = {
  id: {
    tagline: "Download Reels dari YouTube, Instagram, Facebook, TikTok, Douyin. Tanpa login, tanpa watermark, tanpa drama.",
    placeholder: "Tempel URL video di sini...",
    btn: "Ambil video",
    btn_loading: "Sedang ambil...",
    footer1: "Dibangun dengan rantai broker publik. Tanpa akun. Tanpa tracking.",
    dev_by: "Dikembangkan oleh",
    error_label: "Gagal:",
    error_default: "Tidak ada video yang bisa diambil dari URL itu.",
    no_format: "Tidak ada format tersedia.",
    download: "Download",
    via: "via",
  },
  en: {
    tagline: "Download Reels from YouTube, Instagram, Facebook, TikTok, Douyin. No login, no watermark, no drama.",
    placeholder: "Paste a video URL here...",
    btn: "Fetch video",
    btn_loading: "Fetching...",
    footer1: "Built with a public broker chain. No accounts. No tracking.",
    dev_by: "Developed by",
    error_label: "Failed:",
    error_default: "Couldn't extract a video from that URL.",
    no_format: "No formats available.",
    download: "Download",
    via: "via",
  },
  ja: {
    tagline: "YouTube・Instagram・Facebook・TikTok・Douyin の動画を保存。ログイン不要、ウォーターマークなし、面倒なし。",
    placeholder: "動画の URL を貼り付け...",
    btn: "取得",
    btn_loading: "取得中...",
    footer1: "公開ブローカーで動作。アカウント不要、トラッキングなし。",
    dev_by: "開発者",
    error_label: "エラー:",
    error_default: "この URL から動画を取得できませんでした。",
    no_format: "利用できる形式がありません。",
    download: "ダウンロード",
    via: "経由",
  },
  zh: {
    tagline: "下载 YouTube、Instagram、Facebook、TikTok、抖音 的视频。免登录,无水印,无烦恼。",
    placeholder: "在此粘贴视频链接...",
    btn: "获取视频",
    btn_loading: "获取中...",
    footer1: "使用公共代理链构建。无需账号,不做追踪。",
    dev_by: "开发者",
    error_label: "失败:",
    error_default: "无法从该链接提取视频。",
    no_format: "没有可用的格式。",
    download: "下载",
    via: "来源",
  },
};

let currentLang = localStorage.getItem("reels3_lang") || (navigator.language || "id").slice(0, 2);
if (!I18N[currentLang]) currentLang = "id";

function t(key) { return (I18N[currentLang] && I18N[currentLang][key]) || I18N.id[key] || key; }

function applyTranslations() {
  document.documentElement.lang = currentLang;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
}

const form = document.getElementById("form");
const urlInput = document.getElementById("url");
const submitBtn = document.getElementById("submit-btn");
const btnText = submitBtn.querySelector(".btn-text");
const btnSpinner = submitBtn.querySelector(".btn-spinner");
const resultEl = document.getElementById("result");
const errorEl = document.getElementById("error");
const langSelect = document.getElementById("lang-select");

langSelect.value = currentLang;
applyTranslations();
langSelect.addEventListener("change", () => {
  currentLang = langSelect.value;
  localStorage.setItem("reels3_lang", currentLang);
  applyTranslations();
});

// Default to same-origin if served by FastAPI; allow override via ?api=...
const apiBase = new URLSearchParams(location.search).get("api") || "";

function setLoading(on) {
  submitBtn.disabled = on;
  btnText.textContent = on ? t("btn_loading") : t("btn");
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
  errorEl.innerHTML = `<strong>${escapeHtml(t("error_label"))}</strong> ${escapeHtml(msg)}`;
}

function showResult(data) {
  errorEl.hidden = true;
  resultEl.hidden = false;
  const platformBadge = `<span class="badge ${data.platform.slice(0,2)}">${escapeHtml(data.platform)}</span>`;
  const broker = data.broker ? `<span class="broker">${escapeHtml(t("via"))} ${escapeHtml(data.broker)}</span>` : "";
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
        <a href="${dlUrl}" download>${escapeHtml(t("download"))}</a>
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
      ${formatRows || '<p class="uploader">' + escapeHtml(t("no_format")) + '</p>'}
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
      showError(data.error || t("error_default"));
      return;
    }
    showResult(data);
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    setLoading(false);
  }
});
