/* Visualizer core: registry, widget shell, SVG helpers, and a frame player. Visualizers live in viz-*.js. */
(() => {
  "use strict";
  const registry = new Map();
  const SVG_NS = "http://www.w3.org/2000/svg";

  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  function s(tag, attrs = {}, ...children) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "text") el.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    }
    for (const c of children.flat()) if (c) el.append(c);
    return el;
  }

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const randInt = (lo, hi) => lo + Math.floor(Math.random() * (hi - lo + 1));
  const shuffle = (arr) => { const a = [...arr]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const parseList = (text, numeric = true) => String(text).split(/[\s,]+/).filter(Boolean).map((x) => (numeric ? Number(x) : x)).filter((x) => !numeric || Number.isFinite(x));

  /**
   * Build the standard widget chrome.
   * Returns { root, head, stage, controls, log, legend, setLog(text), setLegend([[label, color]]) }.
   */
  function shell(el, { title = "", kind = "Visualizer" } = {}) {
    el.innerHTML = "";
    el.classList.add("widget");
    const head = h("div", { class: "widget-head" }, h("span", { class: "w-kind", text: kind }), h("span", { class: "w-title", text: title }), h("span", { class: "spacer" }));
    const stage = h("div", { class: "viz-stage" });
    const legend = h("div", { class: "viz-legend" });
    const controls = h("div", { class: "viz-controls" });
    const log = h("div", { class: "viz-log", "aria-live": "polite" });
    el.append(head, stage, legend, controls, log);
    return {
      root: el, head, stage, controls, log, legend,
      setLog(text) { log.innerHTML = text; },
      setLegend(items) { legend.innerHTML = items.map(([label, color]) => `<span><i style="background:${color}"></i>${esc(label)}</span>`).join(""); },
    };
  }

  function button(label, onClick, cls = "btn small") { return h("button", { class: cls, type: "button", text: label, onclick: onClick }); }
  function input(attrs = {}) { return h("input", { type: "text", ...attrs }); }
  function select(options, value, onChange) {
    const el = h("select", {}, options.map(([v, label]) => h("option", { value: v, text: label ?? v })));
    el.value = value;
    el.addEventListener("change", () => onChange(el.value));
    return el;
  }
  function label(text, control) { return h("label", { style: "display:inline-flex;gap:6px;align-items:center" }, text, control); }

  /**
   * Frame player. `frames` is an array of snapshots; `render(frame, index)` draws one.
   * Adds ⏮ ◀ ▶(play) ▶| controls and a speed slider into `controls`. Returns { load(frames), go(i), index(), stop() }.
   */
  function player(controls, render, { speed = 500 } = {}) {
    let frames = [];
    let i = 0;
    let timer = null;
    let delay = speed;
    const counter = h("span", { class: "status" });
    const playBtn = button("Play ▶", () => toggle(), "btn small primary");
    const update = () => {
      if (!frames.length) { counter.textContent = ""; return; }
      render(frames[i], i);
      counter.textContent = `step ${i + 1}/${frames.length}`;
    };
    const go = (n) => { i = Math.max(0, Math.min(frames.length - 1, n)); update(); };
    const stop = () => { if (timer) { clearInterval(timer); timer = null; } playBtn.textContent = "Play ▶"; };
    const toggle = () => {
      if (timer) { stop(); return; }
      if (i >= frames.length - 1) i = 0;
      playBtn.textContent = "Pause ❚❚";
      timer = setInterval(() => { if (i >= frames.length - 1) stop(); else go(i + 1); }, delay);
    };
    const speedEl = h("input", { type: "range", min: 1, max: 10, value: 6, "aria-label": "Speed", title: "Speed" });
    speedEl.addEventListener("input", () => { delay = Math.round(1600 / Number(speedEl.value) ** 1.3); if (timer) { stop(); toggle(); } });
    delay = Math.round(1600 / 6 ** 1.3);
    controls.append(
      button("⏮", () => { stop(); go(0); }),
      button("◀", () => { stop(); go(i - 1); }),
      playBtn,
      button("▶|", () => { stop(); go(i + 1); }),
      label("speed", speedEl),
      counter,
    );
    return { load(f, start = 0) { stop(); frames = f; i = start; update(); }, go, index: () => i, stop, frames: () => frames, toggle };
  }

  /** Draw a simple node-link tree laid out by in-order position. node = { id, label, left, right, cls } or { children: [] }. */
  function layoutBinaryTree(root) {
    const pos = new Map();
    let x = 0;
    let maxDepth = 0;
    const walk = (n, d) => {
      if (!n) return;
      walk(n.left, d + 1);
      pos.set(n, { x: x++, y: d });
      maxDepth = Math.max(maxDepth, d);
      walk(n.right, d + 1);
    };
    walk(root, 0);
    return { pos, width: x, depth: maxDepth + 1 };
  }

  function layoutTree(root, childrenOf = (n) => n.children || []) {
    const pos = new Map();
    let leaf = 0;
    let maxDepth = 0;
    const walk = (n, d) => {
      const kids = childrenOf(n);
      maxDepth = Math.max(maxDepth, d);
      if (!kids.length) { pos.set(n, { x: leaf++, y: d }); return; }
      kids.forEach((k) => walk(k, d + 1));
      const xs = kids.map((k) => pos.get(k).x);
      pos.set(n, { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: d });
    };
    walk(root, 0);
    return { pos, width: Math.max(leaf, 1), depth: maxDepth + 1 };
  }

  function mount(el) {
    const name = el.dataset.viz;
    const factory = registry.get(name);
    if (!factory) { el.textContent = `Unknown visualizer: ${name}`; return; }
    let config = {};
    if (el.dataset.config) {
      try { config = JSON.parse(el.dataset.config); } catch (e) { el.textContent = `Bad data-config for ${name}: ${e.message}`; return; }
    }
    factory(el, config, api);
  }

  const api = { h, s, css, esc, sleep, randInt, shuffle, parseList, shell, button, input, select, label, player, layoutBinaryTree, layoutTree };

  function registerViz(name, factory) { registry.set(name, factory); }

  window.PPViz = { registry, registerViz, mount, api };
  window.registerViz = registerViz;
})();
