/* Bazel Practicum course runtime: layout, progress, the Bazel simulator, exercises, labs, quizzes. */
(() => {
  "use strict";

  const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.3/full/";
  const CDN = {
    prism: "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/",
    codemirror: "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/",
    mermaid: "https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js",
  };
  const STORE_KEY = "bazel-practicum:v1";
  const C = window.CURRICULUM || { parts: [], reference: [] };
  const body = document.body;
  const ROOT = body.dataset.root || "";
  const PAGE_ID = body.dataset.module || body.dataset.page || "";

  /* ---------------- utilities ---------------- */
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
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
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  function dedent(text) {
    const lines = text.replace(/\t/g, "    ").split("\n");
    while (lines.length && !lines[0].trim()) lines.shift();
    while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
    const indents = lines.filter((l) => l.trim()).map((l) => l.match(/^ */)[0].length);
    const min = indents.length ? Math.min(...indents) : 0;
    return lines.map((l) => l.slice(min)).join("\n");
  }
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[data-src="${src}"]`);
      if (existing) {
        if (existing.dataset.loaded) resolve();
        else existing.addEventListener("load", () => resolve(), { once: true });
        return;
      }
      const s = h("script", { src, "data-src": src });
      s.addEventListener("load", () => { s.dataset.loaded = "1"; resolve(); }, { once: true });
      s.addEventListener("error", () => reject(new Error(`failed to load ${src}`)), { once: true });
      document.head.append(s);
    });
  }
  function loadCss(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    // Library styles go before the page's own so course.css wins ties (e.g. CodeMirror's white background in dark mode).
    const link = h("link", { rel: "stylesheet", href });
    const first = document.head.querySelector("link[rel='stylesheet'], style");
    if (first) first.before(link);
    else document.head.append(link);
  }
  const icon = {
    menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>',
    sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
    chev: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 6l6 6-6 6"/></svg>',
    logo: '<svg class="logo" viewBox="0 0 32 32" aria-hidden="true"><rect x="9.5" y="3" width="13" height="11" rx="2.5" fill="#2e9e63"/><rect x="3" y="17" width="12.5" height="11" rx="2.5" fill="#1f7a4a"/><rect x="16.5" y="17" width="12.5" height="11" rx="2.5" fill="#43b97c"/><path d="M13 14v3M19 14v3" stroke="#1f7a4a" stroke-width="2" stroke-linecap="round"/></svg>',
  };

  /* ---------------- progress store ---------------- */
  const Store = {
    data: null,
    load() {
      if (this.data) return this.data;
      try { this.data = JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { this.data = {}; }
      for (const k of ["items", "quizzes", "exercises", "labs", "checklists", "notes", "visits"]) this.data[k] ||= {};
      return this.data;
    },
    save() {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(this.data)); } catch { /* storage unavailable: progress is session-only */ }
      document.dispatchEvent(new CustomEvent("pp:progress"));
    },
    get(section, key) { return this.load()[section][key]; },
    set(section, key, value) { this.load()[section][key] = value; this.save(); },
  };
  window.PPStore = Store;

  const allItems = () => C.parts.flatMap((p) => [...p.modules, ...p.projects].map((m) => ({ ...m, part: p })));
  const isDone = (id) => !!Store.get("items", id)?.done;

  /* ---------------- theme ---------------- */
  function currentTheme() {
    const forced = document.documentElement.dataset.theme;
    if (forced) return forced;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function applySavedTheme() {
    let saved = null;
    try { saved = localStorage.getItem(STORE_KEY + ":theme"); } catch { saved = null; }
    if (saved) document.documentElement.dataset.theme = saved;
  }
  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(STORE_KEY + ":theme", next); } catch { /* ignore */ }
    document.dispatchEvent(new CustomEvent("pp:theme", { detail: next }));
    updateThemeButton();
  }
  function updateThemeButton() {
    const b = $("#pp-theme");
    if (b) b.innerHTML = currentTheme() === "dark" ? icon.sun : icon.moon;
  }

  /* ---------------- shell: header, sidebar, toc, pager ---------------- */
  function progressText() {
    const items = allItems();
    return `${items.filter((m) => isDone(m.id)).length} / ${items.length} complete`;
  }
  function addFavicon() {
    if (document.querySelector("link[rel~='icon']")) return;
    const svg = icon.logo.replace('class="logo" ', 'xmlns="http://www.w3.org/2000/svg" ');
    document.head.append(h("link", { rel: "icon", href: "data:image/svg+xml," + encodeURIComponent(svg) }));
  }
  function buildShell() {
    addFavicon();
    const main = $("main") || h("main");
    const header = h("header", { class: "pp-header" },
      h("button", { class: "icon-btn pp-menu-btn", "aria-label": "Toggle navigation", html: icon.menu, onclick: () => body.classList.toggle("nav-open") }),
      h("a", { class: "pp-brand", href: ROOT + "index.html", html: `${icon.logo}<span>${esc(C.title)} <small>Bazel ${esc(C.bazel)}</small></span>` }),
      h("span", { class: "spacer" }),
      h("span", { class: "pp-progress-pill", id: "pp-progress-pill", text: progressText() }),
      h("button", { class: "icon-btn", id: "pp-theme", "aria-label": "Toggle dark mode", onclick: toggleTheme }),
    );
    const sidebar = h("nav", { class: "pp-sidebar", "aria-label": "Curriculum" });
    renderSidebar(sidebar);
    const contentWrap = h("div", { class: "pp-content-wrap" });
    const mainWrap = h("div", { class: "pp-main" }, contentWrap);
    main.replaceWith(h("div", { class: "pp-layout" }, sidebar, mainWrap));
    contentWrap.append(main);
    const toc = buildToc(main);
    if (toc) contentWrap.append(toc);
    body.prepend(header);
    updateThemeButton();
    document.addEventListener("pp:progress", () => {
      $("#pp-progress-pill").textContent = progressText();
      renderSidebar(sidebar);
    });
    mainWrap.addEventListener("click", () => body.classList.remove("nav-open"));
  }
  function renderSidebar(nav) {
    nav.innerHTML = "";
    const here = location.pathname.split("/").slice(-2).join("/");
    for (const part of C.parts) {
      const items = [...part.modules, ...part.projects];
      const containsCurrent = items.some((m) => m.id === PAGE_ID);
      const wrap = h("div", { class: "part" + (containsCurrent ? " open" : "") });
      const done = items.filter((m) => isDone(m.id)).length;
      wrap.append(h("button", {
        html: `<span class="num">${part.number}</span><span>${esc(part.title)} <span class="status">${done}/${items.length}</span></span><span class="chev">${icon.chev}</span>`,
        onclick: () => wrap.classList.toggle("open"),
      }));
      const ul = h("ul");
      for (const m of items) {
        const label = m.id.startsWith("m") ? m.id.slice(1) : m.id === "capstone" ? "★" : "P" + m.id.slice(1);
        ul.append(h("li", {}, h("a", {
          href: ROOT + m.href, class: m.id === PAGE_ID || m.href.endsWith(here) ? "current" : "",
          html: `<span class="mid">${esc(label)}</span><span>${esc(m.title.replace(/^Project \d+: /, ""))}</span>${isDone(m.id) ? '<span class="done">✓</span>' : ""}`,
        })));
      }
      wrap.append(ul);
      nav.append(wrap);
    }
    nav.append(h("div", { class: "side-title", text: "Reference" }));
    const ref = h("div", { class: "part open" });
    const ul = h("ul", { style: "padding-left:0" });
    for (const r of C.reference) {
      ul.append(h("li", {}, h("a", { href: ROOT + r.href, class: r.id === PAGE_ID ? "current" : "", html: `<span>${esc(r.title)}</span>` })));
    }
    ref.append(ul);
    nav.append(ref);
  }
  function buildToc(main) {
    const sections = $$(".lesson-section[id] > h2, .lesson-section[id] > header > h2", main);
    if (sections.length < 3) return null;
    const toc = h("aside", { class: "pp-toc" }, h("h4", { text: "On this page" }));
    const links = new Map();
    for (const h2 of sections) {
      const sec = h2.closest(".lesson-section");
      const a = h("a", { href: "#" + sec.id, text: h2.textContent });
      links.set(sec, a);
      toc.append(a);
    }
    const obs = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          links.forEach((a) => a.classList.remove("active"));
          links.get(e.target)?.classList.add("active");
        }
      }
    }, { rootMargin: "-20% 0px -70% 0px" });
    links.forEach((_, sec) => obs.observe(sec));
    return toc;
  }
  function buildModuleFooter(main) {
    const items = allItems();
    const idx = items.findIndex((m) => m.id === PAGE_ID);
    if (idx === -1) return;
    const item = items[idx];
    const footer = h("section", { class: "module-footer" });
    const box = h("div", { class: "complete-box" });
    const refresh = () => {
      const done = isDone(PAGE_ID);
      box.classList.toggle("is-done", done);
      const quizzes = $$(".quiz[data-id]", main).map((q) => Store.get("quizzes", q.dataset.id));
      const ex = $$(".exercise[data-id]", main);
      const solved = ex.filter((e) => Store.get("exercises", e.dataset.id)?.solved).length;
      const labs = $$(".lab[data-id]", main);
      const labsPassed = labs.filter((e) => Store.get("labs", e.dataset.id)?.passed).length;
      const quizText = quizzes.length ? quizzes.map((q) => (q ? `${Math.round(q.best * 100)}%` : "not taken")).join(", ") : "none";
      box.innerHTML = "";
      box.append(
        h("div", { style: "flex:1;min-width:220px" },
          h("strong", { text: done ? "You completed this " + (item.id.startsWith("m") ? "module" : "project") + "." : "Finished? Mark it complete to track your progress." }),
          h("div", { class: "status", text: `Exercises solved: ${solved}/${ex.length}${labs.length ? ` · Labs passed: ${labsPassed}/${labs.length}` : ""} · Quiz best: ${quizText}` })),
        h("button", {
          class: "btn " + (done ? "" : "ok"), text: done ? "Mark as not complete" : "Mark complete",
          onclick: () => { Store.set("items", PAGE_ID, done ? { done: false } : { done: true, at: new Date().toISOString() }); refresh(); },
        }),
      );
    };
    refresh();
    document.addEventListener("pp:progress", refresh);
    const notesKey = PAGE_ID;
    const notes = h("textarea", { placeholder: "Write what you learned, what confused you, and questions to revisit. Saved in this browser." });
    notes.value = Store.get("notes", notesKey) || "";
    let t;
    notes.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => Store.set("notes", notesKey, notes.value), 400); });
    footer.append(box, h("div", { class: "notes-box" }, h("h3", { text: "My notes" }), notes));
    const pager = h("nav", { class: "pager", "aria-label": "Module navigation" });
    if (idx > 0) pager.append(h("a", { class: "prev", href: ROOT + items[idx - 1].href, html: `<small>Previous</small>${esc(items[idx - 1].title)}` }));
    if (idx < items.length - 1) pager.append(h("a", { class: "next", href: ROOT + items[idx + 1].href, html: `<small>Next</small>${esc(items[idx + 1].title)}` }));
    footer.append(pager);
    main.append(footer);
    const visits = Store.get("visits", PAGE_ID) || 0;
    Store.set("visits", PAGE_ID, visits + 1);
  }

  /* ---------------- syntax highlighting ---------------- */
  async function highlightAll(root = document) {
    const blocks = $$("pre > code[class*='language-']", root).filter((c) => !c.dataset.hl);
    addCopyButtons(root);
    if (!blocks.length) return;
    try {
      await loadScript(CDN.prism + "prism.min.js");
      const langs = new Set(blocks.map((b) => (b.className.match(/language-(\w+)/) || [])[1]));
      if (langs.has("starlark")) langs.add("python");
      const extra = ["python", "go", "bash", "toml", "yaml", "json", "ini", "diff"].filter((l) => langs.has(l));
      for (const l of extra) await loadScript(`${CDN.prism}components/prism-${l}.min.js`);
      for (const b of blocks) {
        if (b.className.includes("language-shell") || b.className.includes("language-sh")) b.className = "language-bash";
        if (b.className.includes("language-starlark")) b.className = "language-python";
        window.Prism.highlightElement(b);
        b.dataset.hl = "1";
      }
    } catch { /* offline: plain code still readable */ }
  }
  function addCopyButtons(root) {
    for (const pre of $$("pre", root)) {
      if (pre.closest(".mermaid") || pre.classList.contains("output") || pre.classList.contains("mermaid") || $(".copy-btn", pre)) continue;
      const btn = h("button", { class: "copy-btn", text: "Copy", type: "button" });
      btn.addEventListener("click", async () => {
        const text = ($("code", pre) || pre).innerText;
        try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; } catch { btn.textContent = "Select & copy"; }
        setTimeout(() => (btn.textContent = "Copy"), 1400);
      });
      pre.append(btn);
    }
  }
  /* ---------------- editor ---------------- */
  let cmReady = null;
  function ensureCodeMirror() {
    if (!cmReady) {
      loadCss(CDN.codemirror + "codemirror.min.css");
      cmReady = loadScript(CDN.codemirror + "codemirror.min.js")
        .then(() => Promise.all([
          loadScript(CDN.codemirror + "mode/python/python.min.js"),
          loadScript(CDN.codemirror + "mode/go/go.min.js"),
          loadScript(CDN.codemirror + "mode/shell/shell.min.js"),
          loadScript(CDN.codemirror + "addon/edit/matchbrackets.min.js"),
          loadScript(CDN.codemirror + "addon/selection/active-line.min.js"),
        ]))
        .then(() => true)
        .catch(() => false);
    }
    return cmReady;
  }
  /** CodeMirror mode for a workspace path: Starlark files use Python's mode. */
  function modeFor(path) {
    if (/\.go$/.test(path)) return "go";
    if (/\.(sh|bash)$/.test(path) || path === ".bazelrc") return "shell";
    if (/(^|\/)(BUILD|BUILD\.bazel|MODULE\.bazel|WORKSPACE)$|\.(bzl|bazel|py)$/.test(path)) return "python";
    return null;
  }
  function langFor(path) {
    const m = modeFor(path);
    return m === "shell" ? "bash" : m || "none";
  }
  function makeEditor(host, code, { onRun, readOnly = false, mode = "python" } = {}) {
    const ta = h("textarea", { spellcheck: "false", autocapitalize: "off", autocomplete: "off" });
    ta.value = code;
    ta.readOnly = readOnly;
    ta.rows = Math.min(Math.max(code.split("\n").length + 1, 3), 26);
    host.append(ta);
    const handlers = [];
    let cm = null;
    ta.addEventListener("input", () => handlers.forEach((fn) => fn()));
    ta.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); onRun?.(); }
      else if (e.key === "Tab" && !e.shiftKey && !readOnly) { e.preventDefault(); ta.setRangeText("    ", ta.selectionStart, ta.selectionEnd, "end"); }
    });
    ensureCodeMirror().then((ok) => {
      if (!ok || !window.CodeMirror || !ta.isConnected) return;
      cm = window.CodeMirror.fromTextArea(ta, {
        mode, lineNumbers: true, indentUnit: 4, matchBrackets: true, styleActiveLine: !readOnly,
        viewportMargin: Infinity, readOnly,
        extraKeys: {
          "Ctrl-Enter": () => onRun?.(), "Cmd-Enter": () => onRun?.(),
          Tab: (c) => (c.somethingSelected() ? c.indentSelection("add") : c.replaceSelection("    ", "end")),
          "Shift-Tab": (c) => c.indentSelection("subtract"),
        },
      });
      cm.on("change", () => handlers.forEach((fn) => fn()));
    });
    return {
      getValue: () => (cm ? cm.getValue() : ta.value),
      setValue: (v) => (cm ? cm.setValue(v) : (ta.value = v)),
      onChange: (fn) => handlers.push(fn),
      refresh: () => cm?.refresh(),
    };
  }

  /* ---------------- the Bazel simulator (minibazel.py on Pyodide) ---------------- */
  const Sim = {
    ready: null,
    status: "idle",
    statusListeners: new Set(),
    setStatus(s) { this.status = s; this.statusListeners.forEach((fn) => fn(s)); },
    load() {
      if (!this.ready) {
        this.setStatus("loading");
        this.ready = (async () => {
          const mod = await import(PYODIDE_URL + "pyodide.mjs");
          const py = await mod.loadPyodide({ indexURL: PYODIDE_URL });
          const src = window.PP_SIM_SOURCE || (await (await fetch(ROOT + "assets/py/minibazel.py")).text());
          py.FS.writeFile("/home/pyodide/minibazel.py", src);
          py.runPython("import sys, json\nsys.path.insert(0, '/home/pyodide')\nimport minibazel");
          this.py = py;
          this.setStatus("ready");
          return py;
        })().catch((e) => { this.ready = null; this.setStatus("error"); throw e; });
      }
      return this.ready;
    },
    async call(code, vars) {
      try {
        const py = await this.load();
        for (const [k, v] of Object.entries(vars)) py.globals.set(k, v);
        return { value: JSON.parse(py.runPython(code)) };
      } catch (e) {
        return { error: `The Bazel simulator could not start (${String(e.message || e).split("\n")[0]}). Check your connection; the labs in the repository run real Bazel.` };
      }
    },
    /** Run a command line such as `bazel query //...` against the files. Returns {ok, output} or {error}. */
    async command(files, line) {
      const r = await this.call("_r = minibazel.Bazel(json.loads(_files)).run_command(_line)\njson.dumps({'ok': _r.ok, 'output': _r.output})", { _files: JSON.stringify(files), _line: line });
      return r.error ? r : r.value;
    },
    /** Run an exercise's checks. Returns {results:[{name, ok, msg}]} or {error}. */
    async check(files, tests) {
      const r = await this.call("json.dumps(minibazel.run_checks(json.loads(_files), _tests))", { _files: JSON.stringify(files), _tests: tests });
      return r.error ? r : { results: r.value };
    },
  };
  window.PPSim = Sim;

  function runtimeBadge() {
    const badge = h("span", { class: "status" });
    const update = (s) => {
      badge.textContent = s === "loading" ? "Starting the Bazel simulator…" : s === "error" ? "Simulator unavailable" : `Bazel ${C.bazel || "9"} · simulated`;
      badge.title = "Runs minibazel, the course's model of Bazel's loading and analysis phases, in your browser. Nothing is compiled.";
    };
    update(Sim.status);
    Sim.statusListeners.add(update);
    return badge;
  }
  function appendOut(outEl, text, cls) {
    if (!text) return;
    outEl.append(h("span", { class: cls || null, text }));
    outEl.scrollTop = outEl.scrollHeight;
  }

  /* ---------------- workspaces: the files of a sandbox or exercise ---------------- */
  /** Read `textarea.file[data-path]` children into [{path, content, readOnly, hidden}]. */
  function readFiles(el) {
    return $$(":scope > textarea.file, :scope > .files > textarea.file", el).map((t) => ({
      path: t.dataset.path,
      content: dedent(t.value) + (dedent(t.value) ? "\n" : ""),
      readOnly: t.hasAttribute("data-readonly"),
      hidden: t.hasAttribute("data-hidden"),
    }));
  }
  /** A tabbed editor over a workspace's files. Returns {files(), reset(next?), refresh()}. */
  function workspaceEditor(container, files, { onRun, saved } = {}) {
    const bar = h("div", { class: "file-tabs", role: "tablist" });
    const panes = h("div", { class: "file-panes" });
    const editors = new Map();
    const visible = files.filter((f) => !f.hidden);
    const hidden = files.filter((f) => f.hidden);
    let active = null;
    const activate = (path) => {
      active = path;
      for (const [p, ed] of editors) {
        ed.pane.hidden = p !== path;
        ed.tab.setAttribute("aria-selected", String(p === path));
        if (p === path) ed.editor.refresh();
      }
    };
    for (const f of visible) {
      const pane = h("div", { class: "editor-host" });
      const editor = makeEditor(pane, saved?.[f.path] ?? f.content.replace(/\n$/, ""), { onRun, readOnly: f.readOnly, mode: modeFor(f.path) });
      const tab = h("button", { type: "button", role: "tab", class: f.readOnly ? "ro" : "", title: f.readOnly ? "Read-only in this exercise" : "Editable", text: f.path, onclick: () => activate(f.path) });
      bar.append(tab);
      panes.append(pane);
      editors.set(f.path, { editor, pane, tab, file: f });
    }
    const tree = hidden.length ? h("div", { class: "file-tree", html: `Also in the workspace: ${hidden.map((f) => `<code>${esc(f.path)}</code>`).join(" ")}` }) : null;
    container.append(bar, panes);
    if (tree) container.append(tree);
    if (visible.length) activate((visible.find((f) => !f.readOnly) || visible[0]).path);
    return {
      files() {
        const out = {};
        for (const f of files) out[f.path] = editors.has(f.path) ? editors.get(f.path).editor.getValue() + "\n" : f.content;
        return out;
      },
      edited() {
        const out = {};
        for (const [p, ed] of editors) if (!ed.file.readOnly) out[p] = ed.editor.getValue();
        return out;
      },
      reset(next = {}) {
        for (const [p, ed] of editors) ed.editor.setValue((next[p] ?? ed.file.content).replace(/\n$/, ""));
      },
      onChange(fn) { for (const ed of editors.values()) ed.editor.onChange(fn); },
      show(path) { if (editors.has(path)) activate(path); },
    };
  }
  /** The command line under a workspace: an input, suggestions, Run, and an output panel. */
  function commandBar(el, ws, { predict = false } = {}) {
    const suggestions = (el.dataset.commands || el.dataset.command || "bazel build //...").split("|").map((c) => c.trim()).filter(Boolean);
    const input = h("input", { class: "cmd-input", type: "text", value: suggestions[0], spellcheck: "false", autocapitalize: "off", "aria-label": "Command" });
    const out = h("pre", { class: "output", "aria-live": "polite" });
    let predictInput = null;
    const verdict = h("span", { class: "verdict" });
    const run = async () => {
      if (predict && predictInput && !predictInput.value.trim()) { predictInput.focus(); verdict.textContent = "Write your prediction first, then run."; verdict.className = "verdict bad"; return; }
      out.innerHTML = "";
      appendOut(out, `$ ${input.value}\n`, "sys");
      runBtn.disabled = true;
      const res = await Sim.command(ws.files(), input.value);
      runBtn.disabled = false;
      if (res.error) { appendOut(out, res.error + "\n", "err"); return; }
      appendOut(out, (res.output || "(no output)") + "\n", res.ok ? null : "err");
      if (predict && predictInput) {
        const norm = (s) => s.replace(/\r/g, "").split("\n").map((l) => l.trim()).filter(Boolean).join("\n");
        const ok = norm(predictInput.value) === norm(res.output);
        verdict.textContent = ok ? "Your prediction matched." : "Not quite. Compare your prediction with the output and work out why.";
        verdict.className = "verdict " + (ok ? "ok" : "bad");
      }
    };
    const runBtn = h("button", { class: "btn primary small", text: predict ? "Run & compare" : "Run ▶", title: "Ctrl/Cmd + Enter", onclick: run });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); run(); } });
    const row = h("div", { class: "cmd-row" }, h("span", { class: "prompt", text: "$" }), input, runBtn);
    const chips = suggestions.length > 1 ? h("div", { class: "cmd-chips" }, suggestions.map((c) => h("button", { type: "button", class: "chip", text: c, onclick: () => { input.value = c; run(); } }))) : null;
    const parts = [row];
    if (chips) parts.push(chips);
    if (predict) {
      predictInput = h("textarea", { rows: 3, placeholder: "Predict the output before you run it…" });
      parts.push(h("div", { class: "predict-box" }, h("label", { text: "Your prediction" }), predictInput, verdict));
    }
    parts.push(out);
    return { parts, run, out };
  }

  /* ---------------- sandboxes (runnable workspaces) ---------------- */
  function mountRunnable(el) {
    const files = readFiles(el);
    el.innerHTML = "";
    el.classList.add("widget");
    const head = h("div", { class: "widget-head" },
      h("span", { class: "w-kind", text: "Sandbox" }),
      el.dataset.title ? h("span", { class: "w-title", text: el.dataset.title }) : null,
      h("span", { class: "spacer" }));
    el.append(head);
    const box = h("div", { class: "workspace" });
    el.append(box);
    let cmd;
    const ws = workspaceEditor(box, files, { onRun: () => cmd.run() });
    cmd = commandBar(el, ws, { predict: el.hasAttribute("data-predict") });
    head.append(runtimeBadge(), h("button", { class: "btn small", text: "Reset", onclick: () => { ws.reset(); cmd.out.innerHTML = ""; } }));
    el.append(...cmd.parts);
    if (el.hasAttribute("data-autorun")) cmd.run();
  }

  /* ---------------- exercises (graded by the simulator) ---------------- */
  function mountExercise(el) {
    const id = el.dataset.id;
    const prompt = $(".exercise-prompt", el);
    const files = readFiles(el);
    const testsEl = $("script.tests", el);
    const tests = dedent(testsEl ? testsEl.textContent : "");
    const details = $$(":scope > details", el);
    const saved = Store.get("exercises", id);
    el.innerHTML = "";
    el.classList.add("widget");
    if (saved?.solved) el.classList.add("solved");
    const head = h("div", { class: "widget-head" },
      h("span", { class: "w-kind", text: "Exercise" }),
      h("span", { class: "w-title", text: el.dataset.title || "" }),
      h("span", { class: "spacer" }));
    el.append(head);
    if (prompt) el.append(prompt);
    const box = h("div", { class: "workspace" });
    el.append(box);
    const results = h("ul", { class: "test-results" });
    let cmd;
    const ws = workspaceEditor(box, files, { onRun: () => check(), saved: saved?.files });
    let saveTimer;
    ws.onChange(() => { clearTimeout(saveTimer); saveTimer = setTimeout(() => Store.set("exercises", id, { ...(Store.get("exercises", id) || {}), files: ws.edited() }), 500); });
    const fail = (text) => results.append(h("li", { class: "fail" }, h("span", { text: "✗" }), h("span", { text })));
    const check = async () => {
      results.innerHTML = "";
      results.append(h("li", { class: "sys", text: "Loading your workspace and running the checks…" }));
      checkBtn.disabled = true;
      const res = await Sim.check(ws.files(), tests);
      checkBtn.disabled = false;
      results.innerHTML = "";
      if (res.error) { fail(res.error); return; }
      const parsed = res.results;
      const passed = parsed.filter((r) => r.ok).length;
      for (const r of parsed) {
        results.append(h("li", { class: r.ok ? "pass" : "fail" }, h("span", { text: r.ok ? "✓" : "✗" }), h("span", {}, r.name, r.msg ? h("span", { class: "msg", text: " — " + r.msg }) : null)));
      }
      const all = passed === parsed.length && passed > 0;
      results.append(h("li", { class: all ? "pass" : "fail" }, h("strong", { text: all ? `All ${passed} checks passed. Nice work.` : `${passed}/${parsed.length} checks passed.` })));
      if (all) {
        Store.set("exercises", id, { files: ws.edited(), solved: true, at: new Date().toISOString() });
        el.classList.add("solved");
      }
    };
    const checkBtn = h("button", { class: "btn ok small", text: "Check ✓", title: "Ctrl/Cmd + Enter", onclick: check });
    head.append(runtimeBadge(), checkBtn,
      h("button", { class: "btn small", text: "Reset", onclick: () => { ws.reset(); results.innerHTML = ""; cmd.out.innerHTML = ""; } }));
    el.append(results);
    cmd = commandBar(el, ws);
    const tryIt = h("details", { class: "try-commands" }, h("summary", { text: "Try commands against your workspace" }), ...cmd.parts);
    el.append(tryIt, ...details);
    highlightAll(el);
  }

  /* ---------------- local labs (graded by real Bazel in the repository) ---------------- */
  function mountLab(el) {
    const id = el.dataset.id;
    const prompt = $(".lab-prompt", el);
    const details = $$(":scope > details", el);
    el.innerHTML = "";
    el.classList.add("widget");
    const done = () => !!Store.get("labs", id)?.passed;
    el.classList.toggle("solved", done());
    const status = h("span", { class: "status" });
    const btn = h("button", { class: "btn small" });
    const refresh = () => {
      el.classList.toggle("solved", done());
      status.textContent = done() ? "Passed" : "Runs real Bazel on your machine";
      btn.textContent = done() ? "Mark as not passed" : "I passed this lab";
      btn.className = "btn small " + (done() ? "" : "ok");
    };
    btn.addEventListener("click", () => { Store.set("labs", id, done() ? { passed: false } : { passed: true, at: new Date().toISOString() }); refresh(); });
    const head = h("div", { class: "widget-head" },
      h("span", { class: "w-kind", text: "Lab" }),
      h("span", { class: "w-title", text: el.dataset.title || id }),
      h("span", { class: "spacer" }), status, btn);
    const cmds = h("pre", { "data-label": "Terminal, in your bazel-practicum clone" }, h("code", { class: "language-bash", text: `pixi run start ${id}     # copies the starter workspace to work/${id}/\npixi run grade ${id}     # runs the lab's checks with real Bazel` }));
    el.append(head);
    if (prompt) el.append(prompt);
    el.append(cmds, ...details);
    refresh();
    highlightAll(el);
  }

  /* ---------------- quizzes ---------------- */
  function mountQuiz(el) {
    const id = el.dataset.id;
    const dataEl = $("script[type='application/json']", el);
    let quiz;
    try { quiz = JSON.parse(dataEl.textContent); } catch (e) { el.textContent = "Quiz data is invalid: " + e.message; return; }
    const passScore = quiz.passScore ?? 0.7;
    el.innerHTML = "";
    el.classList.add("widget");
    const head = h("div", { class: "widget-head" },
      h("span", { class: "w-kind", text: "Quiz" }),
      h("span", { class: "w-title", text: quiz.title || "Check your understanding" }),
      h("span", { class: "spacer" }),
      h("span", { class: "status", text: `${quiz.questions.length} questions · pass at ${Math.round(passScore * 100)}%` }));
    el.append(head);
    const answered = new Map();
    const summary = h("div", { class: "quiz-summary" });
    const qEls = quiz.questions.map((q, i) => renderQuestion(q, i, (correct) => { answered.set(i, correct); updateSummary(); }));
    el.append(...qEls, summary);
    function updateSummary() {
      const correct = [...answered.values()].filter(Boolean).length;
      const total = quiz.questions.length;
      const pct = correct / total;
      summary.innerHTML = "";
      const ring = h("div", { class: "score-ring", style: `--p:${Math.round((answered.size ? correct / total : 0) * 100)}`, text: `${correct}/${total}` });
      const prev = Store.get("quizzes", id);
      let msg = `Answered ${answered.size} of ${total}.`;
      if (answered.size === total) {
        const passed = pct >= passScore;
        msg = passed ? `Passed with ${Math.round(pct * 100)}%. Review any you missed, then move on.` : `${Math.round(pct * 100)}%. Re-read the sections behind the questions you missed, then retake the quiz.`;
        Store.set("quizzes", id, { best: Math.max(pct, prev?.best ?? 0), last: pct, at: new Date().toISOString(), attempts: (prev?.attempts ?? 0) + 1 });
      }
      summary.append(ring, h("div", { style: "flex:1;min-width:200px" },
        h("div", { text: msg }),
        prev ? h("div", { class: "status", text: `Best so far: ${Math.round(prev.best * 100)}% over ${prev.attempts} attempt(s)` }) : null),
        h("button", { class: "btn small", text: "Retake quiz", onclick: () => { const fresh = h("div", { class: "quiz", "data-id": id }); fresh.append(h("script", { type: "application/json", text: JSON.stringify(quiz) })); el.replaceWith(fresh); mountQuiz(fresh); } }));
    }
    updateSummary();
    highlightAll(el);
  }
  function renderQuestion(q, i, onAnswer) {
    const type = q.type || "single";
    const wrap = h("div", { class: "quiz-q" },
      h("div", { class: "q-num", text: `Question ${i + 1}${type === "multi" ? " · select all that apply" : type === "output" ? " · type the exact output" : ""}` }),
      h("div", { class: "q-prompt", html: q.prompt }));
    if (q.code) wrap.append(h("pre", {}, h("code", { class: `language-${q.lang || "python"}`, text: dedent(q.code) })));
    const feedback = h("div", { class: "q-feedback" });
    let getAnswer;
    let optionEls = [];
    if (type === "single" || type === "multi") {
      const group = `q${Math.random().toString(36).slice(2)}`;
      const opts = h("div", { class: "q-options" });
      optionEls = q.options.map((o, idx) => {
        const input = h("input", { type: type === "multi" ? "checkbox" : "radio", name: group, value: idx });
        const label = h("label", { class: "q-option" }, input, h("span", { html: o }));
        opts.append(label);
        return label;
      });
      wrap.append(opts);
      getAnswer = () => optionEls.map((l, idx) => ($("input", l).checked ? idx : -1)).filter((x) => x >= 0);
    } else {
      const input = type === "output" ? h("textarea", { class: "q-text-input", rows: 3, placeholder: "Exact output…" }) : h("input", { class: "q-text-input", type: "text", placeholder: "Your answer…" });
      wrap.append(input);
      getAnswer = () => input.value;
    }
    const checkBtn = h("button", { class: "btn small primary", text: "Check answer" });
    checkBtn.addEventListener("click", () => {
      const ans = getAnswer();
      if ((Array.isArray(ans) && !ans.length) || (!Array.isArray(ans) && !ans.trim())) { feedback.className = "q-feedback show bad"; feedback.innerHTML = "<strong>Choose or type an answer first.</strong>"; return; }
      let correct;
      if (type === "single" || type === "multi") {
        const expected = type === "multi" ? [...q.answer].sort() : [q.answer];
        correct = JSON.stringify([...ans].sort()) === JSON.stringify(expected);
        optionEls.forEach((l, idx) => {
          if (expected.includes(idx)) l.classList.add("correct");
          else if (ans.includes(idx)) l.classList.add("incorrect");
          $("input", l).disabled = true;
        });
      } else {
        const norm = (s) => s.replace(/\r/g, "").split("\n").map((l) => l.trimEnd()).join("\n").trim();
        const accepted = (Array.isArray(q.answer) ? q.answer : [q.answer]).map((a) => (type === "text" ? norm(a).toLowerCase() : norm(a)));
        const given = type === "text" ? norm(ans).toLowerCase() : norm(ans);
        correct = accepted.includes(given);
        $(".q-text-input", wrap).disabled = true;
      }
      checkBtn.disabled = true;
      feedback.className = "q-feedback show " + (correct ? "ok" : "bad");
      const reveal = type === "output" || type === "text" ? `<p>Expected: <code>${esc(Array.isArray(q.answer) ? q.answer[0] : q.answer).replace(/\n/g, "<br>")}</code></p>` : "";
      feedback.innerHTML = `<strong>${correct ? "Correct." : "Not quite."}</strong>${correct ? "" : reveal}${q.explanation}`;
      highlightAll(feedback);
      onAnswer(correct);
    });
    wrap.append(h("div", { class: "btn-row" }, checkBtn), feedback);
    return wrap;
  }

  /* ---------------- flashcards ---------------- */
  function mountFlashcards(el) {
    let cards;
    try { cards = JSON.parse($("script[type='application/json']", el).textContent); } catch { return; }
    if (!Array.isArray(cards)) cards = cards.cards || [];
    el.innerHTML = "";
    el.classList.add("widget");
    let i = 0;
    const card = h("div", { class: "flashcard", tabindex: "0", role: "button", "aria-label": "Flip card" });
    const counter = h("span", { class: "status" });
    const show = () => {
      card.classList.remove("flipped");
      card.innerHTML = `<div class="face front"><small>Prompt</small><div>${cards[i].front}</div></div><div class="face back"><small>Answer</small><div>${cards[i].back}</div></div>`;
      counter.textContent = `${i + 1} / ${cards.length}`;
    };
    card.addEventListener("click", () => card.classList.toggle("flipped"));
    card.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); card.classList.toggle("flipped"); } });
    el.append(
      h("div", { class: "widget-head" }, h("span", { class: "w-kind", text: "Flashcards" }), h("span", { class: "w-title", text: el.dataset.title || "Review" }), h("span", { class: "spacer" }), counter),
      h("div", { class: "card-stage" }, card),
      h("div", { class: "viz-controls" },
        h("button", { class: "btn small", text: "← Prev", onclick: () => { i = (i - 1 + cards.length) % cards.length; show(); } }),
        h("button", { class: "btn small primary", text: "Flip", onclick: () => card.classList.toggle("flipped") }),
        h("button", { class: "btn small", text: "Next →", onclick: () => { i = (i + 1) % cards.length; show(); } }),
        h("button", { class: "btn small", text: "Shuffle", onclick: () => { cards.sort(() => Math.random() - 0.5); i = 0; show(); } })),
    );
    show();
  }

  /* ---------------- tabs, checklists, mermaid ---------------- */
  function mountTabs(el) {
    const tabs = $$(":scope > .tab", el);
    const bar = h("div", { class: "tab-bar", role: "tablist" });
    tabs.forEach((t, i) => {
      const b = h("button", { role: "tab", "aria-selected": i === 0 ? "true" : "false", text: t.dataset.label || `Tab ${i + 1}` });
      b.addEventListener("click", () => {
        tabs.forEach((x) => x.classList.remove("active"));
        $$("button", bar).forEach((x) => x.setAttribute("aria-selected", "false"));
        t.classList.add("active"); b.setAttribute("aria-selected", "true");
        t.querySelectorAll(".CodeMirror").forEach((cm) => cm.CodeMirror?.refresh());
      });
      bar.append(b);
      if (i === 0) t.classList.add("active");
    });
    el.prepend(bar);
  }
  function mountChecklist(el) {
    const id = el.dataset.id;
    const items = $$(":scope > li", el);
    const state = Store.get("checklists", id) || [];
    items.forEach((li, i) => {
      const box = h("input", { type: "checkbox" });
      box.checked = !!state[i];
      const span = h("span");
      while (li.firstChild) span.append(li.firstChild);
      li.append(box, span);
      li.classList.toggle("checked", box.checked);
      box.addEventListener("change", () => {
        const s = Store.get("checklists", id) || [];
        s[i] = box.checked;
        Store.set("checklists", id, s);
        li.classList.toggle("checked", box.checked);
      });
    });
  }
  async function renderMermaid(root = document) {
    const blocks = $$("pre.mermaid, div.mermaid", root);
    if (!blocks.length) return;
    blocks.forEach((b) => { b.dataset.mmd ||= b.textContent; });
    try {
      await loadScript(CDN.mermaid);
      window.mermaid.initialize({ startOnLoad: false, theme: currentTheme() === "dark" ? "dark" : "neutral", fontFamily: "Inter, system-ui, sans-serif", securityLevel: "strict" });
      for (const b of blocks) { b.removeAttribute("data-processed"); b.innerHTML = esc(b.dataset.mmd); }
      await window.mermaid.run({ nodes: blocks });
    } catch { /* diagrams fall back to their source text */ }
  }

  /* ---------------- home page ---------------- */
  function renderHome() {
    const map = $("#curriculum-map");
    if (!map) return;
    const draw = () => {
      map.innerHTML = "";
      for (const part of C.parts) {
        const items = [...part.modules, ...part.projects];
        const done = items.filter((m) => isDone(m.id)).length;
        const hours = Math.round(part.modules.reduce((a, m) => a + (m.minutes || 0), 0) / 60);
        map.append(h("article", { class: "part-card" },
          h("header", {}, h("span", { class: "tag", text: `Part ${part.number}` }), h("h3", { text: part.title }), h("span", { class: "level", text: `${part.level}${hours ? ` · ~${hours} h of lessons` : ""}` })),
          h("p", { style: "margin:0.4em 0 0;color:var(--fg-muted)", text: part.summary }),
          h("div", { class: "bar" }, h("i", { style: `width:${items.length ? (done / items.length) * 100 : 0}%` })),
          h("ul", { class: "module-list" }, items.map((m) => h("li", {}, h("a", { href: m.href, title: m.summary || "", html: `<span class="mid">${m.id === "capstone" ? "★" : m.id.toUpperCase()}</span>${esc(m.title)}${isDone(m.id) ? '<span class="done">✓</span>' : ""}` })))),
        ));
      }
      const all = allItems();
      const doneCount = all.filter((m) => isDone(m.id)).length;
      const stat = $("#progress-stats");
      if (stat) {
        const quizzes = Object.values(Store.load().quizzes);
        const avg = quizzes.length ? Math.round((quizzes.reduce((a, q) => a + q.best, 0) / quizzes.length) * 100) : 0;
        const solved = Object.values(Store.load().exercises).filter((e) => e.solved).length + Object.values(Store.load().labs).filter((e) => e.passed).length;
        const next = all.find((m) => !isDone(m.id));
        stat.innerHTML = `<div class="card"><h4>Completed</h4><div style="font-size:1.6rem;font-weight:800">${doneCount} / ${all.length}</div></div>
          <div class="card"><h4>Exercises &amp; labs passed</h4><div style="font-size:1.6rem;font-weight:800">${solved}</div></div>
          <div class="card"><h4>Average quiz best</h4><div style="font-size:1.6rem;font-weight:800">${quizzes.length ? avg + "%" : "—"}</div></div>
          <div class="card"><h4>Up next</h4>${next ? `<a href="${next.href}">${esc(next.title)}</a>` : "You finished everything."}</div>`;
      }
    };
    draw();
    document.addEventListener("pp:progress", draw);
    $("#export-progress")?.addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(Store.load(), null, 2)], { type: "application/json" });
      const a = h("a", { href: URL.createObjectURL(blob), download: `bazel-practicum-progress-${new Date().toISOString().slice(0, 10)}.json` });
      document.body.append(a); a.click(); a.remove();
    });
    $("#import-progress")?.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try { Store.data = JSON.parse(await file.text()); Store.load(); Store.save(); alertBox("Progress imported."); } catch { alertBox("That file is not a progress export."); }
    });
  }
  function alertBox(text) {
    const el = $("#progress-message");
    if (el) { el.textContent = text; setTimeout(() => (el.textContent = ""), 4000); }
  }

  /* ---------------- boot ---------------- */
  function mountComponents(root = document) {
    $$(".runnable", root).forEach(mountRunnable);
    $$(".exercise[data-id]", root).forEach(mountExercise);
    $$(".lab[data-id]", root).forEach(mountLab);
    $$(".quiz[data-id]", root).forEach(mountQuiz);
    $$(".flashcards", root).forEach(mountFlashcards);
    $$(".tabs", root).forEach(mountTabs);
    $$(".checklist[data-id]", root).forEach(mountChecklist);
    if (window.PPViz) $$(".viz[data-viz]", root).forEach((el) => { try { window.PPViz.mount(el); } catch (e) { el.textContent = `Visualizer failed: ${e.message}`; } });
  }
  // The single-file edition (body[data-engine="single"]) supplies its own shell and calls these directly.
  window.PPCourse = { Store, Sim, mount: mountComponents, highlightAll, renderMermaid, currentTheme, isDone, allItems };
  applySavedTheme();
  if (body.dataset.engine === "single") return;
  document.addEventListener("DOMContentLoaded", () => {
    const main = $("main");
    if (!main) return;
    buildShell();
    if (PAGE_ID === "home") renderHome();
    mountComponents();
    buildModuleFooter(main);
    highlightAll();
    renderMermaid();
    document.addEventListener("pp:theme", () => renderMermaid());
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  });
})();
