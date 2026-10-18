/* Twitter Monitor dashboard frontend */
const $ = (id) => document.getElementById(id);

async function refresh() {
  try {
    const status = await (await fetch("/api/status")).json();
    $("status-summary").textContent =
      `Watched accounts: ${status.watches.length} · Total uploads: ${status.total_uploads}`;
    const runs = status.last_runs
      .map((r) => `${r.finished_at || r.started_at} [${r.status}]\n  ${r.summary || ""}`)
      .join("\n\n") || "— no runs yet —";
    $("last-runs").textContent = runs;
  } catch (e) {
    $("status-summary").textContent = "status unavailable";
  }

  try {
    const data = await (await fetch("/api/uploads?limit=200")).json();
    renderCounts(data.counts, data.watches);
    renderGallery(data.uploads, $("username-filter").value);
  } catch (e) { /* ignore */ }
}

function renderCounts(counts, watches) {
  const list = $("counts-list");
  if (!watches.length) { list.innerHTML = "<li>No watched accounts</li>"; return; }
  list.innerHTML = watches
    .map((u) => `<li>@${u}: <strong>${counts[u] || 0}</strong></li>`)
    .join("");
}

function renderGallery(uploads, username) {
  const gallery = $("gallery");
  const filtered = username ? uploads.filter((u) => u.username === username) : uploads;
  if (!filtered.length) {
    gallery.innerHTML = `<div class="empty">No images downloaded yet.</div>`;
    return;
  }
  gallery.innerHTML = filtered
    .map((u) => `
      <div class="figure" title="${u.image_url || ""}">
        <img src="/archive/twitter/${u.username}/${u.local_filename}" loading="lazy" alt="@${u.username}" />
        <figcaption>@${u.username} · ${u.uploaded_at}</figcaption>
      </div>`)
    .join("");
}

function populateFilter(watches) {
  const sel = $("username-filter");
  const keep = sel.value;
  sel.innerHTML = `<option value="">All accounts</option>` +
    watches.map((u) => `<option value="${u}">@${u}</option>`).join("");
  sel.value = keep;
}

$("watch-add").addEventListener("click", async () => {
  const username = $("watch-input").value.trim();
  if (!username) return;
  await fetch("/api/watch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
  $("watch-input").value = "";
  refresh();
});

$("poll-now").addEventListener("click", async () => {
  $("poll-now").disabled = true;
  const res = await fetch("/api/poll-now", { method: "POST" });
  const data = await res.json().catch(() => ({}));
  try {
    const st = await (await fetch("/api/status")).json();
    populateFilter(st.watches);
  } catch (e) {}
  $("poll-now").disabled = false;
  refresh();
  if (data.summary) $("last-runs").textContent = data.summary;
});

$("username-filter").addEventListener("change", async (e) => {
  const data = await (await fetch("/api/uploads?limit=500")).json();
  renderGallery(data.uploads, e.target.value);
});

refresh();
setInterval(refresh, 15000);