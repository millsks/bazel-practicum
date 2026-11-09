/* Bazel visualizers: the three build phases, and incremental rebuilds over a target graph. */
(() => {
  "use strict";
  const registerViz = window.registerViz;
  if (!registerViz) return;
  const NS = "http://www.w3.org/2000/svg";
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") el.textContent = v; else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
    }
    kids.flat().forEach((c) => c != null && el.append(c instanceof Node ? c : document.createTextNode(c)));
    return el;
  };
  const s = (tag, attrs = {}) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };
  const shell = (el, title) => {
    el.classList.add("widget");
    el.innerHTML = "";
    const body = h("div", { class: "widget-body" });
    el.append(h("div", { class: "widget-head" }, h("span", { class: "w-kind", text: "Visualizer" }), h("span", { class: "w-title", text: title })), body);
    return body;
  };

  /* ---------------- phases: loading → analysis → execution ---------------- */
  const PHASES = [
    { name: "Loading", what: "Bazel reads MODULE.bazel, then evaluates the BUILD files of the packages your target patterns need, running their Starlark (and any .bzl files they load). The result is a graph of targets: rules and the files they mention.", sees: ["MODULE.bazel", "app/BUILD.bazel", "lib/BUILD.bazel"], makes: ["//app:hello", "//lib:greet", "//app:hello.py", "//lib:greet.py"], errors: "name 'py_binary' is not defined · no such attribute · syntax errors · glob matched nothing" },
    { name: "Analysis", what: "For each target, in a configuration (your flags: -c opt, --platforms, select() values), the rule's implementation runs. It checks dependencies (do they exist, are they visible, do they provide PyInfo?) and declares actions: commands with exact inputs and outputs. Nothing runs yet.", sees: ["//app:hello", "//lib:greet", "configuration: fastbuild, linux_x86_64"], makes: ["action: write launcher for //app:hello", "action: build runfiles tree"], errors: "no such target · not visible · missing mandatory providers · select() matched nothing · cycles" },
    { name: "Execution", what: "Bazel runs only the actions whose outputs are needed and whose inputs changed. Each action's key is a hash of its command and input contents, so an unchanged action is a cache hit (local or remote) and does not run. Tests are actions too, so passing tests are cached.", sees: ["action keys (hashes of inputs + command)", "the action cache", "a remote cache, if configured"], makes: ["bazel-bin/app/hello", "bazel-bin/app/hello.runfiles/", "bazel-testlogs/…"], errors: "missing input file · a command failed · a test failed or timed out" },
  ];
  registerViz("phases", (el) => {
    const body = shell(el, "The three phases of every build");
    const rail = h("div", { class: "phase-rail" });
    const card = h("div", { class: "phase-card" });
    let i = 0;
    const show = () => {
      rail.innerHTML = "";
      PHASES.forEach((p, k) => rail.append(h("button", { type: "button", class: "phase-step" + (k === i ? " on" : k < i ? " done" : ""), text: `${k + 1} · ${p.name}`, onclick: () => { i = k; show(); } })));
      const p = PHASES[i];
      card.innerHTML = "";
      card.append(
        h("p", { text: p.what }),
        h("div", { class: "phase-cols" },
          h("div", {}, h("h5", { text: "Works from" }), h("ul", {}, p.sees.map((x) => h("li", {}, h("code", { text: x }))))),
          h("div", {}, h("h5", { text: "Produces" }), h("ul", {}, p.makes.map((x) => h("li", {}, h("code", { text: x })))))),
        h("p", { class: "phase-errors" }, h("strong", { text: "Errors you meet here: " }), p.errors));
    };
    const nav = h("div", { class: "viz-controls" },
      h("button", { class: "btn small", type: "button", text: "← Back", onclick: () => { i = Math.max(0, i - 1); show(); } }),
      h("button", { class: "btn small primary", type: "button", text: "Next →", onclick: () => { i = Math.min(PHASES.length - 1, i + 1); show(); } }));
    body.append(rail, card, nav);
    show();
  });

  /* ---------------- buildgraph: what rebuilds when a file changes ---------------- */
  const DEFAULT_GRAPH = {
    title: "Change a file, see what Bazel re-runs",
    nodes: [
      { id: "greet.py", kind: "file", x: 0, y: 0 },
      { id: "fmt.py", kind: "file", x: 0, y: 1 },
      { id: "main.py", kind: "file", x: 0, y: 2 },
      { id: "greet_test.py", kind: "file", x: 0, y: 3 },
      { id: "//lib:greet", kind: "rule", x: 1, y: 0.5, deps: ["greet.py", "fmt.py"] },
      { id: "//app:hello", kind: "rule", x: 2, y: 1.5, deps: ["main.py", "//lib:greet"] },
      { id: "//lib:greet_test", kind: "test", x: 2, y: 3, deps: ["greet_test.py", "//lib:greet"] },
    ],
  };
  registerViz("buildgraph", (el, config) => {
    const g = config && config.nodes ? config : DEFAULT_GRAPH;
    const body = shell(el, g.title || DEFAULT_GRAPH.title);
    const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
    const users = {};
    g.nodes.forEach((n) => (n.deps || []).forEach((d) => (users[d] ||= []).push(n.id)));
    const W = 640, colW = 220, rowH = 64, pad = 20;
    const maxY = Math.max(...g.nodes.map((n) => n.y));
    const svg = s("svg", { viewBox: `0 0 ${W} ${pad * 2 + (maxY + 1) * rowH}`, class: "diagram buildgraph", role: "img", "aria-label": "Target graph" });
    const pos = (n) => ({ x: pad + n.x * colW, y: pad + n.y * rowH });
    for (const n of g.nodes) for (const d of n.deps || []) {
      const a = pos(byId[d]), b = pos(n);
      svg.append(s("path", { d: `M${a.x + 170},${a.y + 18} C${a.x + 200},${a.y + 18} ${b.x - 30},${b.y + 18} ${b.x},${b.y + 18}`, fill: "none", stroke: "var(--viz-edge)", "stroke-width": 1.5, "marker-end": "url(#bg-arrow)" }));
    }
    const defs = s("defs");
    const marker = s("marker", { id: "bg-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    marker.append(s("path", { d: "M0,0 L10,5 L0,10 z", fill: "var(--viz-edge)" }));
    defs.append(marker);
    svg.prepend(defs);
    const boxes = {};
    for (const n of g.nodes) {
      const p = pos(n);
      const grp = s("g", { class: "bg-node", "data-kind": n.kind });
      const rect = s("rect", { x: p.x, y: p.y, width: 170, height: 36, rx: 7, fill: "var(--viz-node)", stroke: "var(--border-strong)", "stroke-width": 1.5 });
      const label = s("text", { x: p.x + 85, y: p.y + 23, "text-anchor": "middle", "font-size": 12.5, "font-family": "var(--font-mono)", fill: "var(--fg)" });
      label.textContent = (n.kind === "test" ? "🧪 " : "") + n.id;
      grp.append(rect, label);
      if (n.kind === "file") { grp.style.cursor = "pointer"; grp.addEventListener("click", () => edit(n.id)); }
      svg.append(grp);
      boxes[n.id] = rect;
    }
    const log = h("p", { class: "status", text: "Click a source file to edit it, then build. Green = cache hit (skipped). Red = re-runs." });
    const paint = (dirty) => {
      for (const [id, r] of Object.entries(boxes)) {
        const n = byId[id];
        const isDirty = dirty.has(id);
        r.setAttribute("fill", isDirty ? "color-mix(in srgb, var(--bad) 22%, var(--viz-node))" : n.kind === "file" ? "var(--viz-node)" : "color-mix(in srgb, var(--ok) 18%, var(--viz-node))");
        r.setAttribute("stroke", isDirty ? "var(--bad)" : "var(--border-strong)");
      }
    };
    const affected = (id) => {
      const out = new Set([id]);
      const stack = [id];
      while (stack.length) for (const u of users[stack.pop()] || []) if (!out.has(u)) { out.add(u); stack.push(u); }
      return out;
    };
    function edit(id) {
      const dirty = affected(id);
      paint(dirty);
      const rules = [...dirty].filter((x) => byId[x].kind !== "file");
      const tests = rules.filter((x) => byId[x].kind === "test");
      const cached = g.nodes.filter((n) => n.kind !== "file" && !dirty.has(n.id)).map((n) => n.id);
      log.textContent = `You edited ${id}. Bazel re-runs actions for: ${rules.join(", ") || "nothing"}. ` +
        `Cache hits: ${cached.join(", ") || "none"}.` + (tests.length ? ` bazel test re-runs ${tests.join(", ")}; every other test reports (cached) PASSED.` : " No test depends on it, so every test result stays (cached).");
    }
    paint(new Set());
    body.append(svg, log, h("div", { class: "viz-controls" }, h("button", { class: "btn small", type: "button", text: "Reset", onclick: () => { paint(new Set()); log.textContent = "Click a source file to edit it."; } })));
  });
})();
