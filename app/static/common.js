// Helpers shared by the home and editor pages.
"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "on") Object.entries(v).forEach(([ev, fn]) => node.addEventListener(ev, fn));
    else if (k === "value") node.value = v;
    else if (k === "checked") node.checked = !!v;
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...kids.flat().filter((k) => k != null && k !== false));
  return node;
};
const clock = (s) => (s == null ? "—" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);
const api = async (url, method = "GET", body) => {
  const res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error((data && data.detail) || `${res.status}`);
  return data;
};
const upload = async (url, file) => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(url, { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `${res.status}`);
  return data;
};

// The app window offers the system's own pickers; a browser tab (developer use) falls back to typing a path.
const native = () => (window.pywebview && window.pywebview.api) || null;
async function pickFolder(input) {
  if (!native()) { input.focus(); return null; }
  const folder = await native().pick_folder(input.value || "");
  if (folder) input.value = folder;
  return folder;
}

// Theme colours by role (Settings → Team theme, and each event's own theme in the editor).
const COLOURS = [["primary", "Primary", "bars, outlines"], ["accent", "Accent", "accent lines"], ["text", "Text", ""],
  ["muted", "Muted", "sublabels, captions"], ["background", "Background", ""]];
const DEFAULTS = { primary: "#CC0202", accent: "#F0C878", text: "#FFFFFF", muted: "#AAAAAA", background: "#000000" };
