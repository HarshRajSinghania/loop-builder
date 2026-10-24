// Events home: setup, new events from starters, the event list, import/duplicate/package, settings.
"use strict";

let home;
const status = (text) => { $("#status").textContent = text; };
const today = () => new Date().toISOString().slice(0, 10);
const edited = (t) => {
  const mins = Math.round((Date.now() / 1000 - t) / 60);
  if (mins < 1) return "edited just now";
  if (mins < 60) return `edited ${mins} min ago`;
  if (mins < 60 * 24) return `edited ${Math.round(mins / 60)} h ago`;
  return `edited ${new Date(t * 1000).toLocaleDateString()}`;
};

async function load() {
  home = await api("/api/home");
  $("#team").textContent = home.settings.team || "";
  $("#setup").hidden = home.templates_found;
  $("#version").textContent = `Loop Builder ${home.version}`;
  if (home.update) {
    $("#update").hidden = false;
    $("#update").replaceChildren(`Loop Builder ${home.update.version} is available (you have ${home.version}). `,
      el("a", { href: home.update.url, target: "_blank", rel: "noopener" }, "Download it"));
  }
  $("#folder").textContent = `Events are saved on this computer in ${home.folder}.`;
  $("#starters").replaceChildren(...home.starters.map((s) => el("button", { class: "starter", type: "button",
    on: { click: () => create(s.id) } }, s.title, el("small", {}, s.about))));
  renderEvents();
}

function renderEvents() {
  const q = $("#search").value.trim().toLowerCase();
  const list = home.events.filter((e) => !q || e.name.toLowerCase().includes(q));
  $("#events").replaceChildren(...(list.length ? list.map((e) => el("li", { class: "ev" },
    el("img", { src: `/api/events/${encodeURIComponent(e.slug)}/thumb.png?t=${e.edited}`, alt: "", loading: "lazy" }),
    el("div", { class: "ev-main" },
      el("a", { href: "#", class: "ev-name", on: { click: (ev) => { ev.preventDefault(); openEvent(e.slug); } } }, e.name),
      el("span", { class: "muted" }, [e.date, edited(e.edited)].filter(Boolean).join(" · ")),
      el("span", { class: "row" }, e.loops.map((l) => el("span", { class: "chip" }, `${l.name} · ${l.slides} slide${l.slides === 1 ? "" : "s"}`)))),
    el("div", { class: "row" },
      el("button", { class: "btn btn-primary", type: "button", on: { click: () => openEvent(e.slug) } }, "Open"),
      el("button", { class: "btn", type: "button", on: { click: () => duplicate(e) } }, "Duplicate"),
      el("button", { class: "btn", type: "button", on: { click: () => savePackage(e) } }, "Save as .loopevent…"))))
    : [el("li", { class: "muted" }, q ? "No events match." : "No events yet. Start one above.")]));
}

async function openEvent(slug) {
  try { await api(`/api/events/${encodeURIComponent(slug)}/open`, "POST"); location.href = "/edit"; }
  catch (err) { status(`Couldn't open: ${err.message}`); }
}

async function create(starter) {
  const name = $("#new-name").value.trim();
  if (!name) { $("#new-name").focus(); status("Give the event a name first."); return; }
  try {
    const { slug } = await api("/api/events", "POST", { name, date: $("#new-date").value || today(), starter });
    openEvent(slug);
  } catch (err) { status(`Not created: ${err.message}`); }
}

async function duplicate(e) {
  const name = `${e.name} (copy)`;
  try { const { slug } = await api(`/api/events/${encodeURIComponent(e.slug)}/duplicate`, "POST", { name, date: today() });
    status(`Made “${name}”. Rename it in the event.`); await load(); return slug;
  } catch (err) { status(`Not copied: ${err.message}`); return null; }
}

async function savePackage(e) {
  const fileName = `${e.name}.loopevent`;
  if (native()) {
    const path = await native().save_file(fileName, "");
    if (!path) return;
    try { const { file } = await api(`/api/events/${encodeURIComponent(e.slug)}/package`, "POST", { path }); status(`Saved ${file}`); }
    catch (err) { status(`Not saved: ${err.message}`); }
  } else {
    location.href = `/api/events/${encodeURIComponent(e.slug)}/package`; // browser tab: a download
  }
}

$("#import-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  try { const { slug } = await upload("/api/events/import", file); status("Imported."); await load(); openEvent(slug); }
  catch (err) { status(err.message); }
});
$("#search").addEventListener("input", renderEvents);
$("#new-date").value = today();

// First run: the template folder
$("#setup-pick").addEventListener("click", () => pickFolder($("#setup-folder")));
$("#setup-save").addEventListener("click", async () => {
  try { await api("/api/settings", "PUT", { templates: $("#setup-folder").value.trim() }); status("Template folder saved."); load(); }
  catch (err) { status(err.message); }
});

// Settings
document.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => pickFolder($(`#${b.dataset.pick}`))));
const showLogo = () => { const img = $("#logo"); img.hidden = !home.settings.logo; if (home.settings.logo) img.src = `/api/team/logo?t=${Date.now()}`; };
$("#open-settings").addEventListener("click", () => {
  $("#set-team").value = home.settings.team || "";
  $("#set-templates").value = home.settings.templates || "";
  $("#set-export").value = home.settings.export_dir || "";
  $("#set-lanes").value = String(home.settings.pool_lanes ?? 8);
  $("#set-first").value = String(home.settings.first_lane ?? 1);
  $("#template-count").textContent = home.templates_found ? `${home.template_count} templates found` : "Folder not found";
  $("#settings-status").textContent = "";
  showLogo();
  const look = home.settings.theme || DEFAULTS;
  $("#team-colours").replaceChildren(...COLOURS.map(([k, name, hint]) => el("label", { class: "swatch-field" },
    el("input", { type: "color", id: `team-${k}`, value: look[k] || DEFAULTS[k], "aria-label": `Team ${name.toLowerCase()} colour`,
      on: { input: previewLook } }),
    el("span", {}, name))));
  previewLook();
  $("#settings").showModal();
});
// A sample welcome card in the chosen colours, drawn by the real renderer as you pick them.
const teamLook = () => Object.fromEntries(COLOURS.map(([k]) => [k, $(`#team-${k}`).value.toUpperCase()]));
let previewTimer = null;
function previewLook() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const res = await fetch("/api/settings/preview", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: teamLook() }) });
    if (res.ok) $("#look-preview").src = URL.createObjectURL(await res.blob());
  }, 150);
}
$("#logo-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  try { await upload("/api/settings/logo", file); home.settings.logo = true; showLogo(); previewLook(); }
  catch (err) { $("#settings-status").textContent = err.message; }
});
$("#settings-save").addEventListener("click", async () => {
  try {
    await api("/api/settings", "PUT", { team: $("#set-team").value.trim(), templates: $("#set-templates").value.trim(),
      export_dir: $("#set-export").value.trim(), pool_lanes: Number($("#set-lanes").value), first_lane: Number($("#set-first").value),
      theme: teamLook() });
    $("#settings").close(); status("Settings saved."); load();
  } catch (err) { $("#settings-status").textContent = err.message; }
});

load();
