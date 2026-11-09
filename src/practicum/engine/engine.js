/* Single-file edition shell: hash routes, views, and progress on top of the course runtime in course.js. */
(() => {
  "use strict";
  const D = window.PP_DATA;
  const C = D.curriculum;
  const P = window.PPCourse;
  const Store = P.Store;
  const THEME_KEY = "bazel-practicum:v1:theme";

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const view = $("#view");

  /* ---------------- index ---------------- */
  const PAGES = D.pages;
  const BY_ID = {};
  for (const [path, pg] of Object.entries(PAGES)) BY_ID[pg.id] = path;
  const PARTS = C.parts;
  const ITEMS = PARTS.flatMap((p) => [...p.modules, ...p.projects].map((m) => ({ ...m, part: p })));
  const MODULES = ITEMS.filter((m) => /^m\d/.test(m.id));
  const PROJECTS = ITEMS.filter((m) => !/^m\d/.test(m.id));
  const REFS = C.reference || [];
  const itemById = (id) => ITEMS.find((m) => m.id === id);
  const pageOf = (id) => PAGES[BY_ID[id]];

  /* ---------------- progress ---------------- */
  const isDone = (id) => !!Store.get("items", id)?.done;
  const quizBest = (pg) => {
    const q = (pg?.quizzes || []).map((id) => Store.get("quizzes", id)).filter(Boolean);
    return q.length ? Math.max(...q.map((x) => x.best)) : null;
  };
  const solved = (pg) => (pg?.exercises || []).filter((id) => Store.get("exercises", id)?.solved || Store.get("labs", id)?.passed).length;
  const ticked = (pg) => Object.entries(pg?.checklists || {}).reduce((a, [id, n]) => a + Math.min(n, (Store.get("checklists", id) || []).filter(Boolean).length), 0);
  const tickTotal = (pg) => Object.values(pg?.checklists || {}).reduce((a, b) => a + b, 0);
  const started = (m) => { const pg = pageOf(m.id); return isDone(m.id) || quizBest(pg) !== null || solved(pg) > 0 || ticked(pg) > 0; };
  const statusOf = (m) => (isDone(m.id) ? "Complete" : started(m) ? "In progress" : "Not started");
  const partDone = (p) => [...p.modules, ...p.projects].filter((m) => isDone(m.id)).length;
  const partSize = (p) => p.modules.length + p.projects.length;
  const pct = (x) => (x === null ? "–" : Math.round(x * 100) + "%");
  const fmtMin = (n) => (!n ? "" : n < 60 ? `${n} min` : `~${Math.round((n / 60) * 2) / 2} h`);
  const nextItem = () => ITEMS.find((m) => !isDone(m.id));

  /* ---------------- links and routes ---------------- */
  let current = null;
  let currentBase = "index.html";
  let refreshCurrent = null;
  const isRoute = (r) => r === "home" || r === "projects" || r === "reference" || /^part-\d+$/.test(r) || r in BY_ID;
  function parseHash() {
    const raw = decodeURIComponent(location.hash.slice(1));
    const cut = raw.indexOf("/");
    return cut === -1 ? { route: raw || "home", anchor: "" } : { route: raw.slice(0, cut) || "home", anchor: raw.slice(cut + 1) };
  }
  function resolveLink(href, base) {
    if (!href) return null;
    if (/^(https?:|mailto:|data:|javascript:|\/\/)/i.test(href)) return { ext: href };
    if (href.startsWith("#")) {
      const frag = href.slice(1);
      if (isRoute(frag.split("/")[0])) return { hash: href };
      return { hash: `#${current}${frag ? "/" + frag : ""}` };
    }
    const u = new URL(href, "https://pp.invalid/" + base);
    const path = decodeURIComponent(u.pathname.slice(1));
    const pg = PAGES[path];
    const frag = u.hash.slice(1);
    if (pg) return { hash: `#${pg.id}${frag ? "/" + frag : ""}` };
    return { ext: D.siteUrl + path + u.hash };
  }
  function rewriteLinks(root, base) {
    for (const a of $$("a[href]", root)) {
      if (a.dataset.eng) continue;
      const r = resolveLink(a.getAttribute("href"), base);
      a.dataset.eng = "1";
      if (!r) continue;
      if (r.hash) a.setAttribute("href", r.hash);
      else { a.setAttribute("href", r.ext); a.target = "_blank"; a.rel = "noopener"; }
    }
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || a.dataset.eng || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const href = a.getAttribute("href");
    if (/^blob:|^data:/.test(href) || a.hasAttribute("download")) return;
    const r = resolveLink(href, currentBase);
    if (!r) return;
    e.preventDefault();
    if (r.ext) window.open(r.ext, "_blank", "noopener");
    else location.hash = r.hash;
  });
  function scrollToAnchor(anchor) {
    if (!anchor) return;
    requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView());
  }
  function route() {
    const { route: r, anchor } = parseHash();
    const target = isRoute(r) ? r : "home";
    if (target !== current) {
      current = target;
      draw(target);
      if (!anchor) window.scrollTo({ top: 0 });
    }
    scrollToAnchor(anchor);
  }
  window.addEventListener("hashchange", route);

  /* ---------------- shell ---------------- */
  const icon = {
    sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  };
  function tabFor(r) {
    if (r === "projects" || r === "reference" || r === "home") return r;
    if (/^part-\d+$/.test(r)) return r;
    const item = itemById(r);
    if (item) return /^m\d/.test(item.id) ? `part-${item.part.number}` : "projects";
    return "reference";
  }
  function renderTabs() {
    const on = tabFor(current);
    const b = (id, label, dot) => `<button data-go="${id}" aria-current="${on === id}">${dot === undefined ? "" : `<span class="dot ${dot ? "ok" : ""}"></span>`}${esc(label)}</button>`;
    $("#tabs").innerHTML = b("home", "Overview") + '<span class="sep"></span>' +
      PARTS.map((p) => b(`part-${p.number}`, `${p.number}. ${p.title}`, partDone(p) === partSize(p))).join("") +
      '<span class="sep"></span>' + b("projects", "Projects") + b("reference", "Reference");
    $("#tabs [aria-current='true']")?.scrollIntoView({ block: "nearest", inline: "center" });
  }
  $("#tabs").addEventListener("click", (e) => { const t = e.target.closest("[data-go]"); if (t) location.hash = t.dataset.go; });
  function updateMeter() { $("#meter").textContent = `${ITEMS.filter((m) => isDone(m.id)).length} / ${ITEMS.length} complete`; }
  function updateThemeButton() { $("#theme").innerHTML = P.currentTheme() === "dark" ? icon.sun : icon.moon; }
  $("#theme").addEventListener("click", () => {
    const next = P.currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(THEME_KEY, next); } catch { /* storage unavailable: theme lasts this visit only */ }
    updateThemeButton();
    P.renderMermaid(view);
  });
  function toast(text) {
    const el = $("#toast");
    el.textContent = text; el.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => (el.hidden = true), 2200);
  }
  document.addEventListener("pp:progress", () => { updateMeter(); renderTabs(); refreshCurrent?.(); });

  /* ---------------- shared pieces ---------------- */
  const pill = (p) => `<span class="lvl l${Math.min(5, Math.floor(p.number / 2))}">Part ${p.number} · ${esc(p.level)}</span>`;
  const meterline = (done, total) => `<div class="meterline"><div class="bar"><i style="width:${total ? (done / total) * 100 : 0}%"></i></div>${done}/${total}</div>`;
  const chk = (ok) => `<span class="chk ${ok ? "ok" : "no"}">${ok ? "✓" : "–"}</span>`;
  function itemRow(m) {
    const pg = pageOf(m.id);
    const ex = pg?.exercises.length || 0;
    const tt = tickTotal(pg);
    return `<tr><td class="num">${esc(m.id.toUpperCase())}</td>
      <td><a class="e-link" href="#${m.id}">${esc(m.title)}</a>${m.summary ? `<div class="muted" style="font-size:.82rem">${esc(m.summary)}</div>` : ""}</td>
      <td class="num">${fmtMin(m.minutes)}</td><td class="num">${pct(quizBest(pg))}</td>
      <td class="num">${ex ? `${solved(pg)}/${ex}` : "–"}</td><td class="num">${tt ? `${ticked(pg)}/${tt}` : "–"}</td><td>${chk(isDone(m.id))}</td></tr>`;
  }
  const itemTable = (items) => `<div class="tbl"><table><thead><tr><th>No</th><th>Module</th><th>Time</th><th>Quiz</th><th>Exercises</th><th>Checklist</th><th>Done</th></tr></thead><tbody>${items.map(itemRow).join("")}</tbody></table></div>`;
  function parseContent(html) {
    const t = document.createElement("template");
    t.innerHTML = html;
    return t.content;
  }
  function heroOf(frag) {
    const hero = $(".lesson-hero, .home-hero", frag);
    const out = {
      eyebrow: hero ? $(".eyebrow", hero)?.textContent.trim() || "" : "",
      title: hero ? $("h1", hero)?.innerHTML || "" : "",
      lede: hero ? $(".lede", hero)?.innerHTML || "" : "",
      objectives: hero ? $$(".objectives li", hero).map((li) => li.innerHTML) : [],
      extra: hero ? $$(".btn-row, .callout", hero) : [],
    };
    hero?.remove();
    return out;
  }
  function runInlineScripts(root) {
    for (const old of $$("script", root)) {
      const type = (old.getAttribute("type") || "").trim();
      if (type && type !== "text/javascript" && type !== "module") continue;
      const s = document.createElement("script");
      if (type) s.type = type;
      s.textContent = old.textContent;
      old.replaceWith(s);
    }
  }
  function activate(root, base) {
    rewriteLinks(root, base);
    P.mount(root);
    runInlineScripts(root);
    P.highlightAll(root);
    P.renderMermaid(root);
    rewriteLinks(root, base);
  }
  function finishBox(item, pg) {
    const box = document.createElement("div");
    const notes = document.createElement("div");
    notes.className = "notes stack";
    notes.style.gap = ".4rem";
    notes.innerHTML = `<span class="eyebrow">My notes · saved in this browser</span><textarea placeholder="Write what you learned, what confused you, and questions to revisit."></textarea>`;
    const ta = $("textarea", notes);
    ta.value = Store.get("notes", item.id) || "";
    let t;
    ta.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => Store.set("notes", item.id, ta.value), 400); });
    const refresh = () => {
      const done = isDone(item.id);
      const ex = pg.exercises.length, tt = tickTotal(pg);
      box.className = "complete" + (done ? " is-done" : "");
      box.innerHTML = `<div style="flex:1;min-width:220px"><b>${done ? `You completed this ${/^m\d/.test(item.id) ? "module" : "project"}.` : "Finished? Mark it complete to track your progress."}</b>
        <div class="muted" style="font-size:.88rem">Exercises solved ${ex ? `${solved(pg)}/${ex}` : "–"} · Quiz best ${pct(quizBest(pg))} · Checklist ${tt ? `${ticked(pg)}/${tt}` : "–"}</div></div>
        <button class="e-btn ${done ? "" : "primary"}" type="button">${done ? "Mark as not complete" : "Mark complete"}</button>`;
      $("button", box).addEventListener("click", () => {
        Store.set("items", item.id, done ? { done: false } : { done: true, at: new Date().toISOString() });
        if (!done) toast("Marked complete");
      });
      const st = $("[data-status]");
      if (st) st.textContent = statusOf(item);
    };
    refresh();
    refreshCurrent = refresh;
    const wrap = document.createElement("div");
    wrap.className = "stack";
    wrap.append(box, notes);
    return wrap;
  }
  function pager(prev, next) {
    const a = (it, cls, lab) => `<a class="e-btn ${cls}" href="#${it.id}">${lab === "prev" ? "← " : ""}${esc(it.title)}${lab === "next" ? " →" : ""}</a>`;
    return `<nav class="pager">${prev ? a(prev, "", "prev") : "<span></span>"}${next ? a(next, "primary", "next") : "<span></span>"}</nav>`;
  }

  /* ---------------- views ---------------- */
  function draw(r) {
    refreshCurrent = null;
    currentBase = "index.html";
    if (r === "home") viewHome();
    else if (r === "projects") viewProjects();
    else if (r === "reference") viewReference();
    else if (/^part-\d+$/.test(r)) viewPart(PARTS.find((p) => `part-${p.number}` === r) || PARTS[0]);
    else {
      const path = BY_ID[r];
      const pg = PAGES[path];
      currentBase = path;
      if (pg.kind === "module") viewModule(itemById(r), pg);
      else if (pg.kind === "project") viewProject(itemById(r), pg);
      else viewRefPage(REFS.find((x) => x.id === r) || { id: r, title: pg.title }, pg);
    }
    renderTabs();
    updateMeter();
    const titles = { home: "", projects: "Projects", reference: "Reference" };
    const it = itemById(r);
    const label = r in titles ? titles[r] : /^part-/.test(r) ? `Part ${r.slice(5)}` : it ? `${it.id.toUpperCase()} · ${it.title}` : REFS.find((x) => x.id === r)?.title || "";
    document.title = label ? `${label} · ${C.title}` : C.title;
  }

  function viewHome() {
    const home = parseContent(PAGES["index.html"].html);
    const hero = heroOf(home);
    const how = $("#how", home);
    const exTotal = Object.values(PAGES).reduce((a, p) => a + p.exercises.length, 0);
    const next = nextItem();
    const anyDone = ITEMS.some((m) => isDone(m.id));
    view.innerHTML = `<section class="sheet"><div class="hero">
      <div class="stack" style="gap:.6rem"><span class="eyebrow">Self-paced practicum · ${MODULES.length} modules · ${exTotal} graded exercises and labs · ${PROJECTS.length} capstone${PROJECTS.length === 1 ? "" : "s"}</span>
        <h1 class="e-h e-h1">${esc(C.title)}</h1>
        <p class="lede">${hero.lede}</p>
        <div class="e-btns" style="margin-top:.6rem"><a class="e-btn primary" href="#${(next || MODULES[0]).id}">${anyDone ? "Continue" : "Start with Module 00"}</a>
          <a class="e-btn" href="#ref-roadmap">Roadmap</a><a class="e-btn" href="#reference">Reference</a></div></div>
      <div class="los"><span class="eyebrow">The path · tap a part</span>
        <div class="chain" role="group" aria-label="Parts" style="grid-template-columns:repeat(${Math.min(4, PARTS.length)},minmax(0,1fr))">${PARTS.map((p, i) => `<button type="button" data-part="${i}" aria-pressed="${i === 0}"><small>${String(p.number).padStart(2, "0")}</small>${esc(p.title.split(" · ")[0])}</button>`).join("")}</div>
        <div class="loscard" id="partcard"></div></div></div></section>

      <section class="section" style="margin-top:2rem"><div class="sec-head"><h2 class="e-h e-h2">Your progress</h2><span class="muted">Saved in this browser.</span></div>
        <div class="stats" id="stats"></div>
        <div class="e-btns"><button class="e-btn" type="button" id="export">Export progress</button><label class="e-btn">Import progress<input type="file" id="import" accept="application/json"></label></div></section>

      <section class="section"><div class="sec-head"><h2 class="e-h e-h2">How this course works</h2></div><div class="lesson" id="how-slot"></div></section>

      <section class="section"><div class="sec-head"><h2 class="e-h e-h2">Learning path</h2></div>
        <div class="path">${PARTS.map((p) => `<div class="stage">${pill(p)}<h3><a class="e-link" href="#part-${p.number}">${esc(p.title)}</a></h3><p>${esc(p.summary)}</p>${meterline(partDone(p), partSize(p))}</div>`).join("")}</div></section>

      <section class="section"><div class="sec-head"><h2 class="e-h e-h2">Progress register</h2></div>${itemTable(ITEMS)}
        <p class="muted" style="font-size:.88rem">Mark each module complete at the end of its page. Quiz, exercise, and checklist results save as you go.</p></section>`;
    if (how) { $("h2", how)?.remove(); $("#how-slot").append(...how.childNodes); }
    const card = $("#partcard");
    const setPart = (i) => {
      const p = PARTS[i];
      const hours = Math.round(p.modules.reduce((a, m) => a + (m.minutes || 0), 0) / 60);
      $$("[data-part]").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.part === i)));
      card.innerHTML = `<span class="eyebrow">Part ${p.number} · ${esc(p.level)}</span><div class="big">${esc(p.title)}</div><p style="margin:0">${esc(p.summary)}</p>
        <div class="kv"><div><span class="k">Modules</span>${p.modules.length}${p.projects.length ? ` + ${p.projects.length} project${p.projects.length > 1 ? "s" : ""}` : ""}</div><div><span class="k">Lessons</span>${hours ? `~${hours} h` : "–"}</div>
        <div style="grid-column:1/-1"><span class="k">Progress</span>${meterline(partDone(p), partSize(p))}</div></div>
        <div><a class="e-btn primary" href="#part-${p.number}">Open part ${p.number}</a></div>`;
    };
    $$("[data-part]").forEach((b) => b.addEventListener("click", () => setPart(+b.dataset.part)));
    const stats = () => {
      const quizzes = Object.values(Store.load().quizzes);
      const avg = quizzes.length ? Math.round((quizzes.reduce((a, q) => a + q.best, 0) / quizzes.length) * 100) + "%" : "–";
      const solvedAll = Object.values(Store.load().exercises).filter((e) => e.solved).length;
      const nx = nextItem();
      $("#stats").innerHTML = `<div class="stat"><span class="eyebrow">Completed</span><span class="v">${ITEMS.filter((m) => isDone(m.id)).length} / ${ITEMS.length}</span></div>
        <div class="stat"><span class="eyebrow">Exercises solved</span><span class="v">${solvedAll} / ${exTotal}</span></div>
        <div class="stat"><span class="eyebrow">Average quiz best</span><span class="v">${avg}</span></div>
        <div class="stat"><span class="eyebrow">Up next</span>${nx ? `<a class="e-link" href="#${nx.id}">${esc(nx.title)}</a>` : "You finished everything."}</div>`;
    };
    stats();
    refreshCurrent = stats;
    setPart(Math.max(0, PARTS.findIndex((p) => partDone(p) < partSize(p))));
    bindBackup();
    activate(view, "index.html");
  }
  function bindBackup() {
    $("#export")?.addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(Store.load(), null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `bazel-practicum-progress-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.append(a); a.click(); a.remove();
    });
    $("#import")?.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try { Store.data = JSON.parse(await file.text()); Store.load(); Store.save(); toast("Progress imported"); draw(current); }
      catch { toast("That file is not a progress export"); }
    });
  }

  function viewPart(p) {
    const i = PARTS.indexOf(p);
    const hours = Math.round(p.modules.reduce((a, m) => a + (m.minutes || 0), 0) / 60);
    const prev = PARTS[i - 1], next = PARTS[i + 1];
    view.innerHTML = `<section class="sheet stack" style="gap:.8rem">
      <span class="eyebrow">Part ${p.number} of ${PARTS[PARTS.length - 1].number}</span>
      <h1 class="e-h e-h1">${esc(p.title)}</h1><p class="lede">${esc(p.summary)}</p>
      <div class="memo"><div><span class="k">Level</span><span class="v">${esc(p.level)}</span></div><div><span class="k">Modules</span><span class="v">${p.modules.length}</span></div>
        <div><span class="k">Lessons</span><span class="v">${hours ? `~${hours} h` : "–"}</span></div><div><span class="k">Done</span><span class="v">${partDone(p)}/${partSize(p)}</span></div></div>
      ${p.modules.length ? `<div class="section" style="margin-top:1.2rem"><div class="sec-head"><span class="tag">Modules</span></div>${itemTable(p.modules)}</div>` : ""}
      ${p.projects.length ? `<div class="section"><div class="sec-head"><span class="tag">Projects</span></div>${itemTable(p.projects)}</div>` : ""}
    </section>
    <nav class="pager">${prev ? `<a class="e-btn" href="#part-${prev.number}">← Part ${prev.number}: ${esc(prev.title)}</a>` : "<span></span>"}${next ? `<a class="e-btn primary" href="#part-${next.number}">Part ${next.number}: ${esc(next.title)} →</a>` : `<a class="e-btn primary" href="#projects">Projects →</a>`}</nav>`;
    refreshCurrent = () => { if (current === `part-${p.number}`) { const y = scrollY; viewPart(p); scrollTo(0, y); } };
  }

  const SPECIAL = [["practice", "e-lab", "Interactive lab"], ["quiz", "e-quiz", "Quiz"], ["mini-project", "e-project", "Section project"], ["recap", "e-review", "Review"]];
  function viewModule(m, pg) {
    const frag = parseContent(pg.html);
    const hero = heroOf(frag);
    const tops = Array.from(frag.children);
    const special = Object.fromEntries(SPECIAL.map(([sid]) => [sid, tops.find((el) => el.id === sid)]));
    const learn = tops.filter((el) => !Object.values(special).includes(el));
    const idx = MODULES.indexOf(m);
    const learnToc = learn.filter((el) => el.id && $("h2", el)).map((el) => `<a href="#${m.id}/${el.id}">${esc($("h2", el).textContent)}</a>`).join("");
    const chips = [["e-learn", "Learn"], ...SPECIAL.filter(([sid]) => special[sid]).map(([, wid, lab]) => [wid, lab]), ["e-finish", "Finish"]]
      .map(([id, lab]) => `<a href="#${m.id}/${id}">${lab}</a>`).join("");
    view.innerHTML = `<article class="sheet">
      <span class="eyebrow">${esc(hero.eyebrow || `Part ${m.part.number} · ${m.part.title}`)} · ${idx + 1} of ${MODULES.length}</span>
      <h1 class="e-h e-h1" style="margin-top:.3rem">${hero.title || esc(m.title)}</h1>
      <p class="lede" style="margin-top:.6rem">${hero.lede || esc(m.summary)}</p>
      <div class="memo"><div><span class="k">Module</span><span class="v">${esc(m.id.toUpperCase())}</span></div><div><span class="k">Part</span><span class="v">${m.part.number} · ${esc(m.part.level)}</span></div>
        <div><span class="k">Time</span><span class="v">${fmtMin(m.minutes) || "–"} + project</span></div><div><span class="k">Status</span><span class="v" data-status>${statusOf(m)}</span></div></div>
      <div class="section" style="margin-top:1.8rem"><div class="sec-head"><span class="tag">Objectives</span></div>
        ${hero.objectives.length ? `<ul class="objectives-list">${hero.objectives.map((o) => `<li>→ ${o}</li>`).join("")}</ul>` : ""}
        <div class="toc">${chips}</div>${learnToc ? `<span class="eyebrow">In the lesson</span><div class="toc">${learnToc}</div>` : ""}</div>
      <div class="section" id="e-learn"><div class="sec-head"><span class="tag">Learn</span></div><div class="lesson" data-slot="learn"></div></div>
      ${SPECIAL.filter(([sid]) => special[sid]).map(([sid, wid, lab]) => `<div class="section" id="${wid}"><div class="sec-head"><span class="tag">${lab}</span><h3>${esc($("h2", special[sid])?.textContent || lab)}</h3></div><div class="lesson" data-slot="${sid}"></div></div>`).join("")}
      <div class="section" id="e-finish"><div class="sec-head"><span class="tag">Finish</span></div><div data-slot="finish"></div></div>
    </article>${pager(MODULES[idx - 1], MODULES[idx + 1] || PROJECTS.find((p) => p.part.number === m.part.number))}`;
    $("[data-slot='learn']").append(...learn);
    for (const [sid] of SPECIAL) {
      const sec = special[sid];
      if (!sec) continue;
      $("h2", sec)?.remove();
      $(`[data-slot='${sid}']`).append(sec);
    }
    $("[data-slot='finish']").append(finishBox(m, pg));
    Store.set("visits", m.id, (Store.get("visits", m.id) || 0) + 1);
    activate(view, BY_ID[m.id]);
  }

  function viewProject(item, pg) {
    const frag = parseContent(pg.html);
    const hero = heroOf(frag);
    const idx = PROJECTS.indexOf(item);
    view.innerHTML = `<article class="sheet">
      <span class="eyebrow">${esc(hero.eyebrow || `Part ${item.part.number} · Project`)}</span>
      <h1 class="e-h e-h1" style="margin-top:.3rem">${hero.title || esc(item.title)}</h1>
      <p class="lede" style="margin-top:.6rem">${hero.lede || esc(item.summary)}</p>
      <div class="memo"><div><span class="k">Project</span><span class="v">${esc(item.id === "capstone" ? "Capstone" : item.id.toUpperCase())}</span></div><div><span class="k">Part</span><span class="v">${item.part.number} · ${esc(item.part.level)}</span></div>
        <div><span class="k">Graded with</span><span class="v">pixi run grade ${esc(item.id)}</span></div><div><span class="k">Status</span><span class="v" data-status>${statusOf(item)}</span></div></div>
      ${hero.objectives.length ? `<div class="section" style="margin-top:1.8rem"><div class="sec-head"><span class="tag">Objectives</span></div><ul class="objectives-list">${hero.objectives.map((o) => `<li>→ ${o}</li>`).join("")}</ul></div>` : ""}
      <div class="section"><div class="sec-head"><span class="tag">Brief</span></div><div class="lesson" data-slot="body"></div></div>
      <div class="section" id="e-finish"><div class="sec-head"><span class="tag">Finish</span></div><div data-slot="finish"></div></div>
    </article>${pager(PROJECTS[idx - 1], PROJECTS[idx + 1])}`;
    $("[data-slot='body']").append(...hero.extra, frag);
    $("[data-slot='finish']").append(finishBox(item, pg));
    Store.set("visits", item.id, (Store.get("visits", item.id) || 0) + 1);
    activate(view, BY_ID[item.id]);
  }

  function viewProjects() {
    view.innerHTML = `<section class="sheet stack" style="gap:.6rem"><span class="eyebrow">Build on your own machine</span><h1 class="e-h e-h1">Projects</h1>
      <p class="lede">Each level ends with a capstone in the bazel-practicum repository, graded by real Bazel. Start one with <code>pixi run start c1</code>, then check it with <code>pixi run grade c1</code>.</p></section>
      <div class="stack" style="gap:1rem;margin-top:1.25rem">${PROJECTS.map((it) => {
        const pg = pageOf(it.id);
        const tt = tickTotal(pg);
        return `<article class="cap"><div class="cap-head"><div class="stack" style="gap:.3rem"><span class="domain">${esc(it.id === "capstone" ? "Capstone" : it.id.toUpperCase())} · Part ${it.part.number} · ${esc(it.part.title)}</span><h2 class="e-h e-h2">${esc(it.title)}</h2></div>
          <span class="lvl l${isDone(it.id) ? 0 : 3}">${statusOf(it)}</span></div>
          <p>${esc(it.summary || "")}</p>${tt ? meterline(ticked(pg), tt) : ""}
          <div><a class="e-btn primary" href="#${it.id}">Open the brief</a></div></article>`;
      }).join("")}</div>`;
  }

  function viewReference() {
    view.innerHTML = `<section class="sheet stack"><span class="eyebrow">Keep these open while you work</span><h1 class="e-h e-h1">Reference</h1>
      <div class="path">${REFS.map((r) => `<div class="stage"><span class="eyebrow">Reference</span><h3><a class="e-link" href="#${r.id}">${esc(r.title)}</a></h3>${r.summary ? `<p>${esc(r.summary)}</p>` : ""}</div>`).join("")}</div>
      <div class="section"><div class="sec-head"><span class="tag">Backup</span><h3>Your progress</h3></div>
        <p class="muted" style="max-width:68ch">Progress, exercise code, quiz scores, and notes live in this browser. Export a backup to move them to another computer.</p>
        <div class="e-btns"><button class="e-btn" type="button" id="export">Export progress</button><label class="e-btn">Import progress<input type="file" id="import" accept="application/json"></label></div></div>
      <div class="section"><div class="sec-head"><span class="tag">About</span><h3>This edition</h3></div>
        <p style="max-width:68ch">A single-file edition of <a href="${esc(D.repoUrl)}" target="_blank" rel="noopener">bazel-practicum</a> v${esc(D.version)}, generated with <code>pixi run bundle</code>. Sandboxes and exercises run a Bazel simulator in your browser on Pyodide, so the first one needs a network connection to load Python. Labs and capstones run real Bazel in a clone of the repository. The multi-page site is at <a href="${esc(D.siteUrl)}" target="_blank" rel="noopener">${esc(D.siteUrl)}</a>; both editions share progress when served from the same site.</p></div></section>`;
    bindBackup();
  }

  function viewRefPage(ref, pg) {
    const frag = parseContent(pg.html);
    const hero = heroOf(frag);
    const others = REFS.filter((r) => r.id !== ref.id).map((r) => `<a href="#${r.id}">${esc(r.title)}</a>`).join("");
    view.innerHTML = `<article class="sheet">
      <span class="eyebrow">${esc(hero.eyebrow || "Reference")}</span>
      <h1 class="e-h e-h1" style="margin-top:.3rem">${hero.title || esc(ref.title)}</h1>
      ${hero.lede ? `<p class="lede" style="margin-top:.6rem">${hero.lede}</p>` : ""}
      <div class="section" style="margin-top:1.4rem"><div class="toc">${others}</div></div>
      <div class="section"><div class="lesson" data-slot="body"></div></div></article>
      <nav class="pager"><a class="e-btn" href="#reference">← All reference</a><span></span></nav>`;
    $("[data-slot='body']").append(...hero.extra, frag);
    activate(view, BY_ID[ref.id]);
  }

  /* ---------------- boot ---------------- */
  updateThemeButton();
  route();
})();
