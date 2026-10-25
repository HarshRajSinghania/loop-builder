// Settings (team, folders, pool, team theme): one dialog for the events home and the editor.
"use strict";

document.body.insertAdjacentHTML("beforeend", `
<dialog id="settings">
  <form method="dialog" class="export">
    <h2>Settings</h2>
    <label class="lbl">Team name<input id="set-team" class="field" placeholder="e.g. Riverside Swim & Dive"></label>
    <label class="lbl">DisplayLink Plus template folder<span class="row"><input id="set-templates" class="field mono grow"><button class="btn" type="button" data-pick="set-templates">Choose…</button></span><span id="template-count" class="muted"></span></label>
    <label class="lbl">Default export folder<span class="row"><input id="set-export" class="field mono grow" placeholder="Where WMVs and PNGs go, e.g. the DisplayLink Plus video folder"><button class="btn" type="button" data-pick="set-export">Choose…</button></span></label>
    <div class="grid">
      <label class="lbl">Lanes in your pool<select id="set-lanes" class="field"><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option><option>7</option><option>8</option><option>9</option><option>10</option></select></label>
      <label class="lbl">First lane is numbered<select id="set-first" class="field"><option value="1">1</option><option value="0">0</option></select></label>
    </div>
    <fieldset class="group">
      <legend class="label">Team theme</legend>
      <p class="muted">New events start with these colours and a copy of your logo. Each event can change its own from Theme… in the editor.</p>
      <div class="lbl">Team logo (PNG with transparency)
        <span class="row"><span class="logo-box"><img id="logo" alt="Team logo" hidden></span><button class="btn" type="button" id="logo-pick">Choose a picture…</button><input type="file" id="logo-file" accept="image/png,image/webp,image/jpeg" hidden></span></div>
      <div class="look-row"><div class="grid" id="team-colours"></div><img id="look-preview" class="look-preview" alt="A sample welcome card in the team theme"></div>
    </fieldset>
    <p id="settings-status" class="warn" aria-live="polite"></p>
    <p class="row"><span id="version" class="muted"></span><button class="btn" type="button" id="open-about">About Loop Builder…</button></p>
    <div class="row end"><span class="muted grow">Changes are saved when you close Settings.</span><button class="btn btn-primary" value="close">Done</button></div>
  </form>
</dialog>
<dialog id="about">
  <form method="dialog" class="export">
    <h2>About Loop Builder</h2>
    <p id="about-version"></p>
    <p class="muted">Builds video loops for DisplayLink Plus scoreboards: welcome cards, countdowns, QR codes,
      pictures and lane assignments, exported as WMV files for the DisplayLink Plus PC.</p>
    <p id="about-links" class="row"></p>
    <p class="muted"><b>Privacy.</b> Loop Builder keeps your events and pictures on this computer. It doesn't collect
      or send anything about you or your events. <span id="about-update"></span></p>
    <p class="muted"><b>License.</b> Loop Builder is open source under the Apache License 2.0. The app also contains
      other open-source software, including FFmpeg with x264 under the GNU GPL, so the app as a whole is
      distributed under GPL v3; the source code is on GitHub.</p>
    <details><summary>Third-party notices</summary><pre id="about-notices" class="raw"></pre></details>
    <div class="row end"><button class="btn btn-primary" value="close">Close</button></div>
  </form>
</dialog>`);

let settingsHome = null; // /api/home when the dialog opened
let settingsSaved = null;
const showLogo = () => { const img = $("#logo"); img.hidden = !settingsHome.settings.logo; if (settingsHome.settings.logo) img.src = `/api/team/logo?t=${Date.now()}`; };
// Open Settings; `onSaved` runs after changes are saved: when it closes (Done, Esc), and straight away for a new
// team logo.
async function openSettings(onSaved) {
  settingsHome = await api("/api/home");
  settingsSaved = onSaved;
  const s = settingsHome.settings;
  $("#set-team").value = s.team || "";
  $("#set-templates").value = s.templates || "";
  $("#set-export").value = s.export_dir || "";
  $("#set-lanes").value = String(s.pool_lanes ?? 8);
  $("#set-first").value = String(s.first_lane ?? 1);
  $("#template-count").textContent = !s.templates ? "Not set yet"
    : settingsHome.templates_found ? `${settingsHome.template_count} templates found` : "Folder not found";
  $("#template-count").className = "muted";
  $("#settings-status").textContent = "";
  $("#version").textContent = `Loop Builder ${settingsHome.version}`;
  showLogo();
  const look = s.theme || DEFAULTS;
  $("#team-colours").replaceChildren(...COLOURS.map(([k, name]) => el("label", { class: "swatch-field" },
    el("input", { type: "color", id: `team-${k}`, value: look[k] || DEFAULTS[k], "aria-label": `Team ${name.toLowerCase()} colour`,
      on: { input: previewLook } }),
    el("span", {}, name))));
  previewLook();
  $("#settings").showModal();
}
// About: version, links, privacy and licenses. Links open in the system browser.
$("#open-about").addEventListener("click", async () => {
  const a = await api("/api/about");
  const link = (href, text) => el("a", { class: "btn", href, target: "_blank", rel: "noopener" }, text);
  $("#about-version").textContent = `Version ${a.version} · ${a.copyright}`;
  $("#about-links").replaceChildren(link(a.project, "Project page"), link(`${a.project}#readme`, "User guide"),
    link(`${a.project}/issues/new/choose`, "Report a problem"), link(`${a.project}/releases`, "All versions"));
  $("#about-update").textContent = a.update_check
    ? "At start it asks GitHub whether a newer version is available; nothing else is sent." : "";
  $("#about-notices").textContent = a.notices || "See THIRD_PARTY_NOTICES.md in the project.";
  $("#about").showModal();
});
// The template folder's line follows the field as it's typed or picked, so a wrong folder shows before Settings closes.
let countTimer = null;
function countTemplates() {
  clearTimeout(countTimer);
  countTimer = setTimeout(async () => {
    const folder = $("#set-templates").value.trim(), note = $("#template-count");
    if (!folder) { note.textContent = "Not set yet"; note.className = "muted"; return; }
    try {
      const { found, count } = await api(`/api/templates/count?folder=${encodeURIComponent(folder)}`);
      note.textContent = !found ? "Folder not found" : count ? `${count} templates found` : "No .tpl templates in this folder";
      note.className = found && count ? "muted" : "warn";
    } catch (err) { /* keep the last line */ }
  }, 300);
}
$("#set-templates").addEventListener("input", countTemplates);
$("#settings").querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", async () => {
  if (await pickFolder($(`#${b.dataset.pick}`)) && b.dataset.pick === "set-templates") countTemplates();
}));
// A sample welcome card in the chosen colours, drawn by the real renderer as you pick them.
const teamLook = () => Object.fromEntries(COLOURS.map(([k]) => [k, $(`#team-${k}`).value.toUpperCase()]));
let lookTimer = null;
function previewLook() {
  clearTimeout(lookTimer);
  lookTimer = setTimeout(async () => {
    const res = await fetch("/api/settings/preview", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme: teamLook() }) });
    if (res.ok) $("#look-preview").src = URL.createObjectURL(await res.blob());
  }, 150);
}
$("#logo-pick").addEventListener("click", () => $("#logo-file").click()); // a button, so Tab reaches it
$("#logo-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  try { await upload("/api/settings/logo", file); settingsHome.settings.logo = true; showLogo(); previewLook(); }
  catch (err) { $("#settings-status").textContent = err.message; return; }
  if (settingsSaved) await settingsSaved(); // the logo is kept straight away, so the page behind catches up now
});
// Closing saves what changed, however it closes, like the logo (kept as soon as it's picked). Only changed
// settings are sent, so a template folder that's missing on this computer doesn't block a new team name.
$("#settings").addEventListener("close", async () => {
  const s = settingsHome.settings, before = s.theme || DEFAULTS, look = teamLook();
  const now = { team: $("#set-team").value.trim(), templates: $("#set-templates").value.trim(), export_dir: $("#set-export").value.trim(),
    pool_lanes: Number($("#set-lanes").value), first_lane: Number($("#set-first").value) };
  const changes = Object.fromEntries(Object.entries(now).filter(([k, v]) => v !== (s[k] ?? (k === "pool_lanes" ? 8 : k === "first_lane" ? 1 : ""))));
  if (Object.entries(look).some(([k, v]) => v !== (before[k] || DEFAULTS[k]).toUpperCase())) changes.theme = look;
  if (!Object.keys(changes).length) return;
  let problem = null, folderRefused = false;
  try { await api("/api/settings", "PUT", changes); }
  catch (err) { // a folder that isn't there: keep the rest, put the folder back and say why, so closing again works
    problem = `${err.message}. The template folder wasn't changed.`;
    folderRefused = true;
    delete changes.templates;
    $("#set-templates").value = s.templates || "";
    try { if (Object.keys(changes).length) await api("/api/settings", "PUT", changes); }
    catch (again) { problem = again.message; folderRefused = false; Object.keys(changes).forEach((k) => delete changes[k]); }
  }
  Object.assign(s, changes);
  if (problem) { // reopen at once, the reason where it can be seen once: beside the folder (which gets focus), else below
    $("#settings").showModal();
    if (folderRefused) { const note = $("#template-count"); note.textContent = problem; note.className = "warn"; $("#set-templates").focus(); }
    else $("#settings-status").textContent = problem;
  }
  if (Object.keys(changes).length && settingsSaved) await settingsSaved(); // then the page behind catches up
});
