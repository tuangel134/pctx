"use strict";
const $ = (id) => document.getElementById(id);
const token =
  new URLSearchParams(location.hash.slice(1)).get("token") ||
  sessionStorage.getItem("pctx-token") ||
  "";
if (token) sessionStorage.setItem("pctx-token", token);
history.replaceState(null, "", location.pathname);
let current = "",
  state = null,
  tab = "overview",
  busy = false,
  contextPack = false,
  lastContextRequest = null,
  lastContextDigest = null,
  loadRevision = 0;
const titles = {
  overview: "Vista general",
  context: "Contexto",
  tasks: "Tareas y continuidad",
  plan: "Metas y checklists",
  architecture: "Arquitectura",
  knowledge: "Conocimiento",
  integrations: "Conectar una IA",
  health: "Diagnóstico",
};
const statusLabels = {
  active: "En curso",
  paused: "Pausada",
  blocked: "Bloqueada",
  done: "Completada",
  interrupted: "Interrumpida",
  verified: "Verificado",
  user_asserted: "Confirmado por ti",
  inferred: "Inferido",
  stale: "Obsoleto",
  superseded: "Sustituido",
  unknown: "Desconocido",
};
async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || "No se pudo completar la operación");
  return data;
}
function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
  $("notice").hidden = !text;
}
async function run(operation) {
  if (busy) return;
  busy = true;
  document.body.classList.add("busy");
  notice("Trabajando…");
  try {
    await operation();
  } catch (error) {
    notice(error.message, true);
  } finally {
    busy = false;
    document.body.classList.remove("busy");
  }
}
async function action(name, args = {}) {
  return api("/api/action", { id: current, action: name, args });
}
const lines = (text) =>
  text
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function showTab(name) {
  tab = name;
  document
    .querySelectorAll("[data-page]")
    .forEach((n) => (n.hidden = n.dataset.page !== name));
  document
    .querySelectorAll("[data-tab]")
    .forEach((n) => n.classList.toggle("selected", n.dataset.tab === name));
  $("page-title").textContent = titles[name];
  if (name === "plan" && current) run(() => loadPlan());
}
document
  .querySelectorAll("[data-tab]")
  .forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
document
  .querySelectorAll("[data-go]")
  .forEach((b) => b.addEventListener("click", () => showTab(b.dataset.go)));
function projectDialog() {
  $("project-error").textContent = "";
  $("project-dialog").showModal();
  $("new-path").focus();
}
const browseButton = node("button", "Elegir carpeta…", "secondary");
browseButton.type = "button";
$("new-path").after(browseButton);
const folders = node("div", undefined, "folder-list");
folders.hidden = true;
browseButton.after(folders);
async function browse(path = "") {
  const result = await api("/api/folders?path=" + encodeURIComponent(path));
  folders.hidden = false;
  folders.replaceChildren(node("p", result.path));
  const choose = node("button", "Usar esta carpeta", "primary");
  choose.type = "button";
  choose.onclick = () => {
    $("new-path").value = result.path;
    folders.hidden = true;
  };
  folders.append(choose);
  for (const item of [
    { name: "↑ Carpeta superior", path: result.parent },
    ...result.folders,
  ]) {
    const b = node("button", item.name, "secondary");
    b.type = "button";
    b.onclick = () => run(() => browse(item.path));
    folders.append(b);
  }
}
browseButton.onclick = () => run(() => browse($("new-path").value));
const resumeButton = node(
  "button",
  "Retomar última tarea pendiente",
  "secondary",
);
resumeButton.type = "button";
$("finish-task").after(resumeButton);
resumeButton.onclick = () =>
  run(async () => {
    await action("pctx_task_resume");
    await load();
    notice("Tarea retomada con sus criterios, bloqueos y siguientes pasos.");
  });
const portableButton = node(
  "button",
  "Preparar PCTX portable para MCP Master",
  "secondary",
);
portableButton.type = "button";
$("copy-guide").before(portableButton);
portableButton.onclick = () =>
  run(async () => {
    const result = await action("portable");
    await load();
    notice(
      "PCTX portable creado en " +
        result.path +
        ". Copia ahora las instrucciones para tu IA.",
    );
  });
$("add-project").onclick = projectDialog;
$("welcome-add").onclick = projectDialog;
$("cancel-project").onclick = () => $("project-dialog").close();
async function listProjects(selected) {
  const { projects } = await api("/api/projects");
  const previous =
    selected || current || sessionStorage.getItem("pctx-project");
  $("project").replaceChildren();
  for (const p of projects) {
    const option = node(
      "option",
      p.name + (p.available ? "" : " (no disponible)"),
    );
    option.value = p.id;
    option.disabled = !p.available;
    $("project").append(option);
  }
  current =
    projects.find((p) => p.id === previous && p.available)?.id ||
    projects.find((p) => p.available)?.id ||
    "";
  $("project").value = current;
  $("workspace").hidden = !current;
  $("empty").hidden = !!current;
  $("refresh").disabled = !current;
  $("watch").disabled = !current;
  if (current) {
    sessionStorage.setItem("pctx-project", current);
    await load();
  }
}
$("project").onchange = () =>
  run(async () => {
    current = $("project").value;
    sessionStorage.setItem("pctx-project", current);
    await load();
    notice("Proyecto abierto.");
  });
$("project-form").onsubmit = async (event) => {
  event.preventDefault();
  const f = new FormData(event.target);
  await run(async () => {
    try {
      const result = await api("/api/projects", {
        path: f.get("path"),
        initialize: f.has("initialize"),
      });
      $("project-dialog").close();
      await listProjects(result.id);
      notice("Proyecto listo. La memoria se guarda en su propia carpeta.");
    } catch (e) {
      $("project-error").textContent = e.message;
      throw e;
    }
  });
};
async function load(resetForms = true) {
  if (!current) return;
  const identity = current,
    revision = ++loadRevision;
  const nextState = await api("/api/state?id=" + encodeURIComponent(identity));
  if (identity !== current || revision !== loadRevision) return;
  state = nextState;
  $("project-path").textContent = state.root;
  $("project-name").textContent = state.manifest.name;
  $("metric-files").textContent = state.scan.files;
  $("metric-records").textContent = state.records.length;
  $("metric-review").textContent = state.records.filter((r) =>
    ["inferred", "stale", "unknown"].includes(r.state),
  ).length;
  $("metric-time").textContent = state.scan.at
    ? new Date(state.scan.at).toLocaleString("es-MX", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Sin analizar";
  $("scan-note").textContent = state.scan.truncated
    ? "Análisis parcial: límite de 10 000 archivos"
    : "Hechos derivados del proyecto";
  $("watch").checked = state.watch.running;
  const active = state.tasks.active;
  $("active-title").textContent = active?.title || "Sin tarea activa";
  $("active-status").textContent = active
    ? statusLabels[active.status]
    : "Puedes preparar una tarea desde Contexto o registrar el próximo objetivo.";
  $("active-next").replaceChildren(
    ...(active?.next_actions || []).map((x) => node("li", x)),
  );
  resumeButton.hidden =
    !!active || !state.tasks.history.some((t) => t.status !== "done");
  if (resetForms) {
    const f = $("task-form");
    f.elements.title.value = active?.title || "";
    f.elements.acceptance.value = (active?.acceptance || []).join("\n");
    f.elements.next_actions.value = (active?.next_actions || []).join("\n");
    f.elements.blockers.value = (active?.blockers || []).join("\n");
    f.elements.status.value = active?.status || "active";
  }
  const docs = await Promise.all(
    ["PROJECT_CONTEXT.md", "TASKS.md", "architecture.md"].map((name) =>
      api("/api/document?id=" + identity + "&name=" + encodeURIComponent(name)),
    ),
  );
  if (identity !== current || revision !== loadRevision) return;
  if (resetForms || !contextPack) $("context-text").textContent = docs[0].text;
  if (resetForms) {
    lastLookup = null;
    $("lookup-results").replaceChildren();
    $("lookup-summary").textContent = "";
    $("lookup-more").hidden = true;
    $("knowledge-detail").hidden = true;
    lastContextRequest = null;
    lastContextDigest = null;
    $("context-report").disabled = true;
    $("context-report-text").hidden = true;
    $("read-text").hidden = true;
  }
  $("tasks-text").textContent = docs[1].text;
  $("architecture-text").textContent = docs[2].text;
  $("guide-text").textContent = state.guide;
  renderRecords();
  renderGraph();
  await loadConfig();
  if (tab === "plan") await loadPlan();
  if (state.refresh.status === "running" || state.refresh.status === "error")
    notice(
      "La última actualización no terminó. Usa Actualizar contexto para regenerar las vistas; los errores de memoria se mostrarán sin sobrescribirla.",
      true,
    );
  if (state.watch.error) notice("Seguimiento: " + state.watch.error, true);
}
$("refresh").onclick = () =>
  run(async () => {
    const result = await action("refresh");
    await load();
    notice(
      "Contexto actualizado. " +
        result.changes.changed.length +
        " archivos cambiados; " +
        result.scan.stale_records.length +
        " registros pasaron a revisión.",
    );
  });
$("watch").onchange = () =>
  run(async () => {
    const enabled = $("watch").checked;
    await action("watch", { enabled });
    notice(
      enabled
        ? "Seguimiento activado mientras el panel esté encendido. Revisa archivos cada 5 segundos."
        : "Seguimiento detenido.",
    );
  });
$("context-form").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  run(async () => {
    const request = {
      task: f.get("task"),
      budget: Number(f.get("budget")),
    };
    const result = await action("pctx_context", request);
    await load();
    contextPack = true;
    lastContextRequest = request;
    lastContextDigest = result.structuredContent?.record_digest;
    $("context-report").disabled = false;
    $("context-report-text").hidden = true;
    $("context-text").textContent = result.content
      .map((x) => x.text)
      .join("\n");
    notice(
      result.structuredContent?.essential_complete === false
        ? "Contexto esencial incompleto. Revisa las omisiones antes de continuar."
        : "Tarea preparada y registrada. Este paquete contiene el contexto seleccionado.",
    );
  });
};
$("context-report").onclick = () => run(async () => {
  if (!lastContextRequest) return;
  const result = await action("pctx_context_report", lastContextRequest);
  const report = JSON.parse(result.content[0].text);
  $("context-report-text").textContent = JSON.stringify(report, null, 2);
  $("context-report-text").hidden = false;
  notice(report.record_digest === lastContextDigest
    ? "Selección y omisiones disponibles."
    : "La memoria cambió desde el paquete. Este informe describe la selección actual.");
});
$("read-form").onsubmit = (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  run(async () => {
    const result = await action("pctx_read", { [form.get("kind")]: form.get("reference") });
    $("read-text").textContent = result.content.map(x => x.text).join("\n");
    $("read-text").hidden = false;
    notice("Contexto ampliado desde la memoria actual.");
  });
};
function taskArgs() {
  const f = new FormData($("task-form"));
  return {
    title: f.get("title"),
    status: f.get("status"),
    acceptance: lines(f.get("acceptance")),
    next_actions: lines(f.get("next_actions")),
    blockers: lines(f.get("blockers")),
  };
}
$("task-form").onsubmit = (e) => {
  e.preventDefault();
  run(async () => {
    await action("pctx_task_update", taskArgs());
    await load();
    notice("Avance guardado. La siguiente sesión puede recuperarlo.");
  });
};
$("finish-task").onclick = () => {
  if (!$("task-form").reportValidity()) return;
  run(async () => {
    const a = taskArgs();
    await action("pctx_finish", {
      objective: a.title,
      acceptance: a.acceptance,
      next_actions: a.next_actions,
      blockers: a.blockers,
    });
    await load();
    notice(
      "Sesión cerrada. El handoff conserva los resultados, bloqueos y siguientes pasos.",
    );
  });
};
function renderRecords() {
  if (!state) return;
  const q = $("record-search").value.toLowerCase(),
    filter = $("record-state").value;
  $("records").replaceChildren();
  const records = state.records.filter(
    (r) =>
      (!q ||
        (r.statement + " " + r.id + " " + r.scope).toLowerCase().includes(q)) &&
      (!filter ||
        (filter === "review"
          ? ["stale", "inferred", "unknown"].includes(r.state)
          : r.state === filter)),
  );
  for (const r of records) {
    const card = node("article", undefined, "record"),
      head = node("div", undefined, "record-head");
    head.append(
      node("span", statusLabels[r.state] || r.state, "pill " + r.state),
      node("span", r.type + " · " + r.scope),
    );
    card.append(head, node("p", r.statement), node("small", r.id));
    if (r.evidence?.length)
      card.append(
        node(
          "small",
          "Evidencia: " + r.evidence.map((e) => e.path || e.kind).join(", "),
        ),
      );
    if (r.stale_reason) card.append(node("small", r.stale_reason));
    const historyButton = node("button", "Historial", "secondary");
    const historyView = node("div");
    historyButton.onclick = () => run(async () => {
      const result = await action("pctx_history", { id: r.id });
      const history = JSON.parse(result.content[0].text);
      historyView.replaceChildren();
      if (history.legacy) historyView.append(node("p", "Este registro aún no tiene revisiones guardadas."));
      for (const revision of history.revisions) {
        const inspect = node("button", "Ver revisión " + revision.revision, "secondary");
        inspect.onclick = () => run(async () => {
          const detailResult = await action("pctx_history", {id: r.id, revision: revision.revision, compare: history.current_revision});
          const detail = JSON.parse(detailResult.content[0].text);
          const preview = node("pre", JSON.stringify({record: detail.record, changes: detail.changes}, null, 2), "document");
          historyView.querySelectorAll("pre, [data-restore]").forEach(n => n.remove());
          historyView.append(preview);
          if (r.origin !== "scanner" && !r.id.startsWith("work.")) {
            const restore = node("button", "Restaurar esta revisión", "secondary");
            restore.dataset.restore = "true";
            restore.onclick = () => {
              if (!confirm("¿Restaurar el contenido mostrado como una nueva revisión? Quedará pendiente de verificar con la evidencia actual.")) return;
              run(async () => {
                await action("pctx_record_restore", {id: r.id, revision: revision.revision, expected_revision: history.current_revision});
                await load();
                notice("Revisión restaurada. Comprueba la evidencia actual.");
              });
            };
            historyView.append(restore);
          }
          notice("Revisión y diferencias disponibles.");
        });
        historyView.append(inspect);
      }
      notice("Historial disponible.");
    });
    card.append(historyButton, historyView);
    if (r.origin !== "scanner" && r.state !== "superseded") {
      const row = node("div", undefined, "button-row");
      for (const [state, label] of [
        ["user_asserted", "Confirmar con evidencia actual"],
        ["superseded", "Marcar sustituido"],
      ]) {
        const b = node("button", label, "secondary");
        b.onclick = () => {
          if (
            state === "user_asserted" &&
            !confirm(
              "¿Has revisado esta afirmación y sus archivos? Se registrará como confirmada por ti con la evidencia actual.",
            )
          )
            return;
          run(async () => {
            const extra = {};
            if (state === 'superseded') {
              extra.replacement_id = prompt('ID del registro que sustituye a ' + r.id + ':');
              if (!extra.replacement_id) return;
              if (!confirm('Sustituir ' + r.id + ' por ' + extra.replacement_id + ' conservando el historial?')) return;
            }
            await action("review", { id: r.id, state, expected_revision: r.current_revision, ...extra });
            await load();
            notice("Revisión guardada.");
          });
        };
        row.append(b);
      }
      const inspectEvidence = node('button', 'Revisar evidencia y candidatos', 'secondary');
      inspectEvidence.onclick = () => run(async () => {
        const response = await action('pctx_review_queue', {limit: 500});
        const queue = JSON.parse(response.content[0].text);
        historyView.replaceChildren(node('pre', JSON.stringify(queue, null, 2), 'document'));
      });
      const correction = node('button', 'Corregir afirmación', 'secondary');
      correction.onclick = () => {
        const statement = prompt('Nueva afirmación (se conservará el historial):', r.statement);
        if (!statement || statement === r.statement) return;
        if (!confirm('Guardar esta corrección como inferida?\n' + statement)) return;
        run(async () => {
          await action('review', {id: r.id, action: 'correct', statement, expected_revision: r.current_revision});
          await load(); notice('Corrección guardada; requiere revisión.');
        });
      };
      row.append(inspectEvidence, correction);
      card.append(row);
    }
    $("records").append(card);
  }
  if (!records.length)
    $("records").append(
      node("p", "No hay registros que coincidan con el filtro."),
    );
}
$("record-search").oninput = renderRecords;
$("record-state").onchange = renderRecords;
$("record-form").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  run(async () => {
    await action("pctx_record_update", {
      type: f.get("type"),
      scope: f.get("scope"),
      statement: f.get("statement"),
      evidence: f
        .get("evidence")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    });
    e.target.reset();
    await load();
    notice("Conocimiento guardado como inferido, pendiente de revisión.");
  });
};
const svgNS = "http://www.w3.org/2000/svg";
function svgNode(tag, attrs, text) {
  const n = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text) n.textContent = text;
  return n;
}
function renderGraph() {
  if (!state) return;
  const a = state.architecture,
    allNodes = [...a.generated.nodes, ...a.custom.nodes],
    map = new Map(allNodes.map((n) => [n.id, n]));
  const allEdges = [...a.generated.edges, ...a.custom.edges];
  const query = $("graph-filter").value.toLowerCase();
  const matching = new Set(
    [...map.values()]
      .filter((n) => (n.id + " " + n.label).toLowerCase().includes(query))
      .map((n) => n.id),
  );
  const edges = allEdges.filter(
    (e) => !query || matching.has(e.source) || matching.has(e.target),
  );
  const ids = new Set(edges.flatMap((e) => [e.source, e.target]));
  const nodes = [...map.values()]
    .filter((n) => ids.has(n.id) || matching.has(n.id))
    .slice(0, 18);
  const positions = new Map();
  const graph = $("graph");
  graph.replaceChildren();
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1) - Math.PI / 2;
    positions.set(n.id, {
      x: 500 + 350 * Math.cos(angle),
      y: 270 + 215 * Math.sin(angle),
    });
  });
  for (const e of edges) {
    const s = positions.get(e.source),
      t = positions.get(e.target);
    if (s && t) {
      const line = svgNode("path", {
        d: `M ${s.x} ${s.y} Q 500 270 ${t.x} ${t.y}`,
        class: "edge",
      });
      line.append(
        svgNode("title", {}, e.source + " → " + e.target + ": " + e.label),
      );
      graph.append(line);
    }
  }
  for (const n of nodes) {
    const p = positions.get(n.id),
      g = svgNode("g", {});
    g.append(
      svgNode("rect", {
        x: p.x - 71,
        y: p.y - 15,
        width: 142,
        height: 30,
        rx: 7,
      }),
      svgNode(
        "text",
        { x: p.x, y: p.y + 4, "text-anchor": "middle" },
        n.label.length > 19 ? n.label.slice(0, 17) + "…" : n.label,
      ),
      svgNode("title", {}, n.label),
    );
    graph.append(g);
  }
  $("graph-note").textContent =
    `Vista compacta: ${nodes.length} de ${map.size} componentes. Las conexiones dirigidas aparecen abajo; busca un componente para enfocarlo.`;
  $("connections").replaceChildren(
    ...edges
      .slice(0, 80)
      .map((e) =>
        node(
          "div",
          (map.get(e.source)?.label || e.source) +
            " → " +
            (map.get(e.target)?.label || e.target) +
            " · " +
            e.label,
          "connection",
        ),
      ),
  );
}
$("graph-filter").oninput = renderGraph;
$("architecture-form").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target),
    source = f.get("source"),
    target = f.get("target");
  run(async () => {
    const known = new Set(
      [
        ...state.architecture.generated.nodes,
        ...state.architecture.custom.nodes,
      ].map((n) => n.id),
    );
    await action("pctx_architecture_update", {
      nodes: [source, target]
        .filter((id, i, arr) => !known.has(id) && arr.indexOf(id) === i)
        .map((id) => ({ id, label: id, kind: "custom" })),
      edges: [{ source, target, label: f.get("label") }],
      notes: f.get("note") ? [f.get("note")] : [],
    });
    await load();
    notice("Conexión guardada en la arquitectura.");
  });
};
async function copy(text) {
  await navigator.clipboard.writeText(text);
  notice("Copiado al portapapeles.");
}
$("copy-context").onclick = () =>
  run(() => copy($("context-text").textContent));
$("copy-architecture").onclick = () =>
  run(() => copy($("architecture-text").textContent));
$("copy-guide").onclick = () => run(() => copy(state.guide));
$("copy-config").onclick = () => run(() => copy($("config-text").textContent));
async function loadConfig() {
  const identity = current,
    client = $("client").value,
    readOnly = $("read-only").checked;
  const c = await api(
    "/api/config?id=" +
      identity +
      "&client=" +
      client +
      "&read_only=" +
      readOnly,
  );
  if (
    identity !== current ||
    client !== $("client").value ||
    readOnly !== $("read-only").checked
  )
    return;
  $("config-text").textContent = JSON.stringify(c.config, null, 2);
  $("config-path").textContent = c.path
    ? "Archivo: " + c.path
    : "Copia esta configuración en un cliente compatible con MCP stdio.";
  $("install-config").disabled = !c.path;
}
$("client").onchange = () =>
  run(async () => {
    await loadConfig();
    notice("Configuración preparada.");
  });
$("read-only").onchange = $("client").onchange;
$("install-config").onclick = () =>
  run(async () => {
    const r = await action("install", {
      client: $("client").value,
      read_only: $("read-only").checked,
    });
    await load();
    notice(
      "Configuración instalada. Reinicia o recarga el cliente." +
        (r.backup ? " Copia anterior: " + r.backup : ""),
    );
  });
$("probe").onclick = () =>
  run(async () => {
    const result = await action("probe");
    $("probe-result").hidden = false;
    $("probe-result").textContent = JSON.stringify(result, null, 2);
    if (!result.ok) { notice("El diagnóstico MCP falló: " + result.error); return; }
    notice(
      "MCP local responde correctamente. La conexión dentro de tu IDE se comprueba en ese cliente.",
    );
  });
$("doctor").onclick = () =>
  run(async () => {
    const r = await action("doctor");
    const box = $("health-result");
    box.replaceChildren(
      node("strong", r.ok ? "Memoria legible" : "Se necesita atención"),
      node(
        "p",
        `${r.records} registros · ${r.errors || 0} errores · ${r.warnings || 0} advertencias`,
      ),
    );
    for (const finding of r.findings) {
      const el = node("div", undefined, "finding");
      el.append(
        node("b", finding.level.toUpperCase() + " · " + finding.code),
        node(
          "span",
          finding.message + (finding.path ? " · " + finding.path : ""),
        ),
      );
      box.append(el);
    }
    notice("Diagnóstico completado.");
  });
$("shutdown").onclick = () =>
  run(async () => {
    await api("/api/shutdown", {});
    notice(
      "Panel apagado. Puedes cerrar esta pestaña. Los procesos MCP iniciados por tus IDEs siguen bajo su control.",
    );
    document
      .querySelectorAll("button,input,select,textarea")
      .forEach((n) => (n.disabled = true));
  });
// Refresh saved views after watcher updates, without replacing in-progress forms.
setInterval(async () => {
  if (!current || busy || !state?.watch.running) return;
  try {
    const identity = current;
    const latest = await api("/api/state?id=" + identity);
    if (identity !== current || busy) return;
    if (latest.watch.error) notice("Seguimiento: " + latest.watch.error, true);
    if (latest.scan.at !== state.scan.at) {
      await load(false);
      notice(
        "Contexto actualizado automáticamente. Se conservaron los formularios que estás editando.",
      );
    }
  } catch {}
}, 8000);
run(async () => {
  await listProjects();
  notice("");
});

const differencesButton = node('button', 'Ver cambios desde checkpoint', 'secondary');
differencesButton.onclick = () => run(async () => {
  const response = await action('pctx_differences', {});
  const preview = node('pre', JSON.stringify(JSON.parse(response.content[0].text), null, 2), 'document');
  differencesButton.parentNode.querySelector('[data-differences]')?.remove();
  preview.dataset.differences = 'true'; differencesButton.after(preview);
});
$('task-form').append(differencesButton);
differencesButton.type = 'button';

const recoveryPanel = node('section', undefined, 'card');
recoveryPanel.append(node('h3', 'Respaldos y recuperación'));
const recoveryResult = node('pre', undefined, 'document'); recoveryResult.hidden = true;
const backupCreate = node('button', 'Crear respaldo privado', 'secondary');
backupCreate.onclick = () => run(async () => {
  const result = await action('backup_create');
  recoveryResult.textContent = JSON.stringify(result, null, 2); recoveryResult.hidden = false;
  notice('Respaldo privado creado.');
});
const backupPath = node('input'); backupPath.placeholder = 'Ruta absoluta del respaldo .zip';
backupPath.setAttribute('aria-label', 'Ruta del respaldo');
const backupPreview = node('button', 'Previsualizar restauración', 'secondary');
const backupApply = node('button', 'Restaurar respaldo', 'secondary'); backupApply.hidden = true;
let restoration = null;
backupPath.oninput = () => {restoration = null; backupApply.hidden = true;};
backupPreview.onclick = () => run(async () => {
  const path = backupPath.value.trim();
  const preview = await action('backup_preview', {path}); restoration = {path, preview};
  recoveryResult.textContent = JSON.stringify(preview, null, 2); recoveryResult.hidden = false;
  backupApply.hidden = false; notice('Previsualización lista; aún no se ha restaurado.');
});
backupApply.onclick = () => {
  if (!restoration) return;
  if (!confirm('Restaurar los cambios mostrados? Se creará un respaldo previo y se reemplazará la memoria actual.')) return;
  run(async () => {
    const result = await action('backup_restore', {path:restoration.path, expected_state:restoration.preview.expected_state});
    restoration = null; backupApply.hidden = true; await load();
    recoveryResult.textContent = JSON.stringify(result, null, 2); notice('Respaldo restaurado.');
  });
};
recoveryPanel.append(backupCreate, backupPath, backupPreview, backupApply, recoveryResult);
$('health-result').after(recoveryPanel);

let lastLookup = null;
function knowledgePayload(response) {
  if (response.isError) throw new Error(response.content[0].text);
  return JSON.parse(response.content[0].text);
}
async function retrieveKnowledge(request) {
  const result = knowledgePayload(await action('pctx_lookup', request));
  lastLookup = {...request, offset: result.next_offset};
  $('lookup-summary').textContent = `${result.results.length} fragmentos; ${result.approximate_tokens} / ${result.budget} tokens aproximados. Índice: ${result.index_state}. ` +
    (result.truncated ? 'Hay resultados pendientes o fragmentos que requieren más presupuesto. ' : '') +
    (result.coverage.files_truncated || result.coverage.limited_sources || result.coverage.architecture_limited ? 'Cobertura limitada: revisa los límites de archivos, documentos y arquitectura.' : '');
  const cards = result.results.map(fragment => {
    const card = node('article', undefined, 'card');
    card.append(node('h3', fragment.source), node('p', `${fragment.state} · líneas ${fragment.lines.join('–')} · ${fragment.reasons.join(', ')}`), node('pre', fragment.text, 'document'));
    const controls = node('div', undefined, 'button-row');
    for (const [label, tool] of [['Leer fragmento exacto', 'pctx_expand'], ['Ver conexiones', 'pctx_neighbors']]) {
      const button = node('button', label, 'secondary');
      button.onclick = () => run(async () => {
        const detail = knowledgePayload(await action(tool, {reference: fragment.ref, budget: request.budget}));
        $('knowledge-detail').textContent = JSON.stringify(detail, null, 2);
        $('knowledge-detail').hidden = false;
        notice(tool === 'pctx_expand' ? 'Fragmento verificado contra la fuente actual.' : 'Conexiones de la fuente actual.');
      });
      controls.append(button);
    }
    card.append(controls);
    return card;
  });
  $('lookup-results').replaceChildren(...cards);
  $('lookup-more').hidden = result.next_offset === null;
  $('knowledge-detail').hidden = true;
  notice('Búsqueda completada sin guardar la consulta.');
}
$('lookup-form').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    const form = new FormData(event.target), model = $('lookup-model').value.trim();
    await retrieveKnowledge({query: form.get('query'), kind: form.get('kind'),
      budget: Number(form.get('budget')), limit: Number(form.get('limit')),
      mode: $('lookup-mode').value, ...(model ? {model} : {})});
  });
};
$('lookup-more').onclick = () => run(() => retrieveKnowledge(lastLookup));
$('knowledge-index').onclick = () => run(async () => {
  const model = $('lookup-model').value.trim();
  const result = await action('index', model ? {model} : {});
  notice(`Índice preparado: ${result.chunks} fragmentos. ${result.vectors ? 'Vectores locales disponibles.' : 'Texto y conexiones disponibles.'}`);
});

// Checklists load bounded pages independently of the full knowledge/history view.
const planLabels = {pending:'Pendiente', in_progress:'En curso', done:'Hecho', needs_review:'Por revisar', blocked:'Bloqueado', verified:'Verificado', cancelled:'Cancelado'};
const planDifficulty = {unknown:'Sin clasificar', easy:'Fácil', medium:'Medio', intermediate:'Intermedio', hard:'Difícil', very_hard:'Súper difícil'};
const planRisk = {unknown:'Sin clasificar', low:'Bajo', medium:'Medio', high:'Alto'};
const planKinds = {goal:'Meta', task:'Tarea', bug:'Bug', check:'Verificación'};
const planOutcomes = {passed:'Pasó', failed:'Falló', blocked:'Bloqueada', inconclusive:'No concluyente'};
let planProject = '', planOffset = 0, planNext = null, planSelected = null, planEdit = null, planSerial = 0, planHistoryOffset = 0, planReviewEvent = null;
function newPlan() {
  $('coord-task').value = '';
  planEdit = null;
  $('plan-form').reset();
  $('plan-form').elements.priority.value = 'normal';
  $('plan-form').elements.kind.value = 'task';
  $('plan-edit-title').textContent = 'Nuevo punto';
}
function planArgs() {
  const f = $('plan-filters').elements, args = {action:'list', limit:20, budget:6000, offset:planOffset};
  for (const key of ['status','kind','difficulty','risk','parent','goal']) if (f[key].value.trim()) args[key] = f[key].value.trim();
  if (f.ready.checked) args.ready = true;
  return args;
}
async function loadPlan() {
  const identity = current, serial = ++planSerial;
  if (planProject !== identity) {
    planProject = identity; planOffset = 0; planSelected = null; planReviewEvent = null;
    $('plan-filters').reset(); newPlan(); $('plan-detail').hidden = true;
    $('plan-review').reset(); $('plan-history-text').replaceChildren();
    coordOffset = 0; $('coord-task').value = ''; $('coord-history').hidden = true; $('coord-history-more').hidden = true;
  }
  const [summary, result] = await Promise.all([
    action('pctx_plan', {action:'summary', budget:1500}).then(knowledgePayload),
    action('pctx_plan', planArgs()).then(knowledgePayload)
  ]);
  if (identity !== current || serial !== planSerial) return;
  $('plan-summary').textContent = Object.entries(summary.counts).map(([key,n]) => `${planLabels[key]}: ${n}`).join(' · ');
  planNext = result.next_offset;
  const cards = result.items.map(item => {
    const card = node('article', undefined, 'card plan-item');
    card.dataset.planId = item.id;
    const label = node('label', undefined, 'watch-label');
    const check = node('input'); check.type = 'checkbox'; check.checked = ['done','verified'].includes(item.status);
    check.setAttribute('aria-label', `Marcar hecho: ${item.title}`); check.disabled = item.status === 'cancelled' || item.working;
    check.onchange = () => run(async () => {
      try {
        await action('pctx_plan_update', {action:'status', id:item.id, expected_revision:item.current_revision, status:check.checked ? 'done':'pending'});
        await loadPlan(); notice('Estado guardado. Marcar hecho no cuenta como revisión.');
      } catch (error) {check.checked = !check.checked; throw error;}
    });
    label.append(check, node('strong', item.title));
    card.append(label, node('p', `${planKinds[item.kind]} · ${planLabels[item.status]} · ${planDifficulty[item.difficulty]} · Riesgo: ${planRisk[item.risk]} · Revisiones: ${item.review_count} (${planOutcomes[item.last_outcome] || 'ninguna'})`), node('p', `${item.id} · Responsable: ${item.owner || 'sin asignar'} · ${item.ready ? 'Listo para empezar' : 'Consulta requisitos/estado'} · Subpuntos: ${item.children}`,'hint'));
    if (item.working) card.append(node('p', 'Trabajando: ' + item.reservations.slice(0,4).map(r => `${r.session_id} · vence ${new Date(r.expires_at*1000).toLocaleString()}`).join('; '), 'hint'));
    if (item.children) card.append(node('p', Object.entries(item.progress).filter(([,n]) => n).map(([k,n]) => `${planLabels[k]}: ${n}`).join(' · ')));
    const controls = node('div', undefined, 'button-row');
    const inspect = node('button','Detalle y revisiones','secondary');
    inspect.onclick = () => run(() => inspectPlan(item.id)); controls.append(inspect);
    if (item.children) {
      const descend = node('button','Ver subpuntos','secondary');
      descend.onclick = () => run(async () => {$('plan-filters').elements.parent.value = item.id; planOffset = 0; await loadPlan(); notice('Subpuntos de ' + item.title);}); controls.append(descend);
    }
    card.append(controls); return card;
  });
  $('plan-items').replaceChildren(...(cards.length ? cards : [node('p','No hay puntos que coincidan con estos filtros.')]));
  $('plan-prev').hidden = planOffset === 0; $('plan-next').hidden = planNext === null;
  $('plan-next').disabled = planNext === planOffset;
  await loadCoordination();
  $('plan-page').textContent = `${result.items.length} de ${result.total} puntos coincidentes · ${result.tokens_estimate}/${result.budget} tokens aproximados. ${result.truncated ? 'Hay puntos pendientes de consultar.' : ''}`;
}
async function inspectPlan(id) {
  const identity = current;
  const result = knowledgePayload(await action('pctx_plan', {action:'detail', id, budget:16000}));
  if (identity !== current) return;
  if (!result.detail) throw new Error(result.warning || 'El detalle necesita más presupuesto');
  const item = result.detail;
  $('coord-task').value = item.id;
  planSelected = item; planEdit = item; planHistoryOffset = 0; planReviewEvent = null;
  $('plan-detail').hidden = false;
  $('plan-detail-title').textContent = item.title;
  $('plan-detail-info').textContent = `${item.id} · ${planLabels[item.status]} · ${item.difficulty_label} · Riesgo: ${planRisk[item.risk]} · Revisiones: ${item.review_count} · Última: ${item.last_review ? `${planOutcomes[item.last_review.outcome]}, ${item.last_review.reviewer}, ${item.last_review.at}` : 'ninguna'}`;
  $('plan-description').textContent = `${item.description}\nDificultad: ${item.difficulty_reason || 'Sin clasificar'}\nDependencias: ${item.dependencies.join(', ') || 'ninguna'}\nPadre: ${item.parent || 'raíz'}\n${item.risk === 'high' ? 'Seguridad/datos: exige una revisión independiente adecuada.' : ''}`;
  $('plan-criteria').replaceChildren(...item.criteria.map(c => node('li', `${item.current_passed_criteria.includes(c.id) ? '☑':'☐'} ${c.text}`)));
  $('plan-warning').textContent = item.warnings.join('; ');
  $('plan-status').elements.status.value = item.status;
  $('plan-status').elements.reason.value = item.reason;
  const f = $('plan-form').elements;
  for (const k of ['title','kind','description','priority','owner','difficulty','difficulty_reason','risk']) f[k].value = item[k];
  f.parent.value = item.parent || ''; f.dependencies.value = item.dependencies.join('\n'); f.criteria.value = item.criteria.map(c=>c.text).join('\n');
  $('plan-edit-title').textContent = 'Editar: ' + item.title;
  $('plan-review').reset();
  const field = $('plan-review-criteria'); field.replaceChildren(node('legend','Criterios realmente comprobados'));
  for (const c of item.criteria) {
    const label = node('label', undefined, 'watch-label'), input = node('input'); input.type = 'checkbox'; input.value = c.id; input.name = 'covered'; label.append(input, node('span',c.text)); field.append(label);
  }
  $('plan-history-text').replaceChildren(); $('plan-history-more').hidden = true;
  if (item.last_review) $('plan-history-text').append(node('p',item.last_review.summary), ...item.evidence.map(e=>node('p',`${e.path || e.ref || e.branch}: ${e.status === 'current' ? 'Vigente' : 'Cambió o no está disponible'}`,'hint')));
  notice('Detalle del punto cargado.');
}
$('plan-new').onclick = () => {newPlan(); $('plan-form').elements.title.focus();};
$('plan-filters').onsubmit = e => {e.preventDefault(); run(async () => {planOffset=0; await loadPlan(); notice('Filtros aplicados.');});};
$('plan-next').onclick = () => run(async () => {if (planNext !== null) planOffset=planNext; await loadPlan(); notice('Página siguiente.');});
$('plan-prev').onclick = () => run(async () => {planOffset=Math.max(0, planOffset-20); await loadPlan(); notice('Página anterior.');});
$('plan-form').onsubmit = e => {
  e.preventDefault(); run(async () => {
    const f = e.target.elements, args = {action:planEdit ? 'edit':'create'};
    for (const key of ['title','kind','description','priority','owner','difficulty','difficulty_reason','risk']) args[key]=f[key].value.trim();
    args.parent = f.parent.value.trim() || 'root';
    if (!planEdit && args.parent === 'root') delete args.parent;
    args.criteria = lines(f.criteria.value); args.dependencies = lines(f.dependencies.value);
    if (planEdit) {args.id=planEdit.id; args.expected_revision=planEdit.current_revision; Object.assign(args, planLeaseCredentials(planEdit));}
    const saved = knowledgePayload(await action('pctx_plan_update', args));
    await load(false); await inspectPlan(saved.id); notice('Punto guardado con dificultad y riesgo separados.');
  });
};
$('plan-status').onsubmit = e => {
  e.preventDefault(); run(async () => {
    if (!planSelected) return;
    await action('pctx_plan_update', {action:'status', id:planSelected.id, expected_revision:planSelected.current_revision, status:e.target.elements.status.value, reason:e.target.elements.reason.value.trim(), ...planLeaseCredentials(planSelected)});
    await load(false); await inspectPlan(planSelected.id); notice('Estado guardado con sus comprobaciones.');
  });
};
$('plan-review').onsubmit = e => {
  e.preventDefault(); run(async () => {
    if (!planSelected) return;
    const f=e.target.elements;
    const values = {...planLeaseCredentials(planSelected), action:'review', id:planSelected.id, expected_revision:planSelected.current_revision, outcome:f.outcome.value, summary:f.summary.value.trim(), reviewer:f.reviewer.value.trim(), evidence:lines(f.evidence.value), covered_criteria:[...e.target.querySelectorAll('[name=covered]:checked')].map(c=>c.value)};
    const signature = JSON.stringify(values);
    if (!planReviewEvent || planReviewEvent.signature !== signature) planReviewEvent = {signature, id:crypto.randomUUID()};
    await action('pctx_plan_update', {...values, event_id:planReviewEvent.id});
    const id=planSelected.id; await load(false); await inspectPlan(id);
    notice('Revisión registrada una vez. Usa Cambiar estado para verificar cuando cumpla todos los criterios.');
  });
};
async function planHistory(append=false) {
  if (!planSelected) return;
  const id=planSelected.id, identity=current;
  const result = knowledgePayload(await action('pctx_plan', {action:'history', id, offset:append ? planHistoryOffset:0, limit:10, budget:10000}));
  if (identity !== current || planSelected?.id !== id) return;
  if (!append) $('plan-history-text').replaceChildren();
  for (const event of result.items) {
    const card=node('article', undefined, 'card');
    card.append(node('h4',`Revisión del registro ${event.revision} · ${event.at} · ${planLabels[event.status]}`));
    if (event.review) card.append(node('p',`${planOutcomes[event.review.outcome]} · ${event.review.reviewer}: ${event.review.summary}`), node('p',`Criterios: ${event.review.criteria.join(', ') || 'ninguno'} · Evidencia: ${event.review.evidence.map(x=>x.path).join(', ') || 'ninguna'}`));
    else card.append(node('p','Cambio de registro; no añade una revisión del trabajo.'));
    $('plan-history-text').append(card);
  }
  planHistoryOffset=result.next_offset; $('plan-history-more').hidden=planHistoryOffset===null;
  $('plan-history-more').disabled=planHistoryOffset===result.offset;
  notice('Historial consultado; el contador no cambia.');
}
$('plan-history').onclick=()=>run(()=>planHistory());
$('plan-history-more').onclick=()=>run(()=>planHistory(true));

// Session identity is a public cooperative label, never an authentication token.
let coordOffset=0, coordNext=null, coordSerial=0, coordHistoryId=null, coordHistoryOffset=null;
$('coord-session').value='panel-' + crypto.randomUUID();
function planLeaseCredentials(item) {
  const lease=(item.reservations || []).find(r=>r.session_id===$('coord-session').value.trim());
  return lease ? {session_id:lease.session_id, lease_id:lease.id}:{};
}
async function loadCoordination() {
  const identity=current, serial=++coordSerial;
  const args={action:'list', offset:coordOffset, limit:10, budget:6000};
  if ($('coord-filter').value) args.status=$('coord-filter').value;
  const result=knowledgePayload(await action('pctx_coordination',args));
  if (identity!==current || serial!==coordSerial) return;
  coordNext=result.next_offset;
  const labels={active:'Trabajando',expired:'Vencida',released:'Liberada',clock_anomaly:'Revisar reloj: reserva retenida'};
  $('coord-items').replaceChildren(...result.items.map(r=>{
    const card=node('article',undefined,'card coord-item'); card.dataset.leaseId=r.id;
    card.append(node('strong',`${labels[r.status]} · ${r.task_id}`),node('p',`Sesión: ${r.session_id} · Vence: ${new Date(r.expires_at*1000).toLocaleString()}`),node('p',r.paths.join(', ')),node('p',r.summary || 'Sin checkpoint todavía','hint'));
    const buttons=node('div',undefined,'button-row');
    for (const [verb,label] of [['renew','Renovar y guardar checkpoint'],['release','Liberar con traspaso']]) {
      const button=node('button',label,'secondary'); button.disabled=verb==='renew' ? r.status!=='active':r.state==='released';
      button.onclick=()=>run(async()=>{
        const f=$('coord-form').elements;
        const values={action:verb,id:r.id,session_id:f.session_id.value.trim(),expected_revision:r.current_revision,summary:f.summary.value.trim()};
        if (verb==='renew') values.ttl=Number(f.ttl.value);
        await action('pctx_coordination_update',values); await loadPlan(); if (planSelected) await inspectPlan(planSelected.id); notice(verb==='renew'?'Reserva renovada y checkpoint guardado.':'Reserva liberada con traspaso.');
      }); buttons.append(button);
    }
    const history=node('button','Historial de reserva','secondary');
    history.onclick=()=>run(async()=>{
      coordHistoryId=r.id; coordHistoryOffset=0; $('coord-history').replaceChildren(); await loadCoordinationHistory();
    }); buttons.append(history); card.append(buttons); return card;
  }));
  $('coord-count').textContent=`${result.items.length} de ${result.total} reservas · ${result.tokens_estimate}/${result.budget} tokens aprox. ${result.truncated?'Hay más reservas por consultar.':''}`;
  $('coord-prev').hidden=coordOffset===0; $('coord-next').hidden=coordNext===null; $('coord-next').disabled=coordNext===coordOffset;
}
$('coord-form').onsubmit=e=>{e.preventDefault();run(async()=>{
  const f=e.target.elements;
  if (!f.task_id.value) throw new Error('Abre el detalle de una tarea antes de reservar.');
  await action('pctx_coordination_update',{action:'claim',session_id:f.session_id.value.trim(),task_id:f.task_id.value,paths:lines(f.paths.value),ttl:Number(f.ttl.value),summary:f.summary.value.trim()});
  coordOffset=0; await loadPlan(); await inspectPlan(f.task_id.value); notice('Tarea y zonas reservadas. Renueva antes del vencimiento.');
});};
$('coord-refresh').onclick=()=>run(async()=>{await loadPlan();notice('Reservas actualizadas con su vigencia real.');});
$('coord-filter').onchange=()=>run(async()=>{coordOffset=0;await loadCoordination();});
$('coord-next').onclick=()=>run(async()=>{if(coordNext!==null)coordOffset=coordNext;await loadCoordination();});
$('coord-prev').onclick=()=>run(async()=>{coordOffset=Math.max(0,coordOffset-10);await loadCoordination();});

async function loadCoordinationHistory() {
  const identity=current;
  const result=knowledgePayload(await action('pctx_coordination',{action:'history',id:coordHistoryId,offset:coordHistoryOffset || 0,limit:10,budget:6000}));
  if (identity!==current) return;
  $('coord-history').hidden=false;
  for (const r of result.items) {
    const card=node('article',undefined,'card');
    card.append(node('strong',`Revisión ${r.revision} · ${r.session_id} · ${r.state==='held'?'Reserva registrada':'Liberada'}`),node('p',r.summary || 'Sin checkpoint'),node('p',`Registrada: ${r.at} · Vencimiento registrado: ${new Date(r.expires_at*1000).toLocaleString()}`,'hint'));
    $('coord-history').append(card);
  }
  coordHistoryOffset=result.next_offset; $('coord-history-more').hidden=coordHistoryOffset===null; $('coord-history-more').disabled=coordHistoryOffset===result.offset;
  notice(`Historial de reserva cargado: ${result.total} revisiones. ${result.truncated?'Hay más páginas.':''}`);
}
$('coord-history-more').onclick=()=>run(loadCoordinationHistory);

$('brief-form').onsubmit=e=>{e.preventDefault();run(async()=>{
  const f=e.target.elements,args={budget:Number(f.budget.value)};
  if(f.role.value.trim())args.role=f.role.value.trim();
  const result=await action('pctx_brief',args);
  $('brief-text').textContent=result.content.map(c=>c.text || '').join('\n');$('brief-text').hidden=false;$('copy-brief').hidden=false;
  const incomplete=result.structuredContent?.essential_complete===false;
  notice(incomplete?'Brief generado con esenciales incompletos; amplía el contexto antes de trabajar.':'Brief generado con presupuesto y rol; la lectura no cambia la tarea global.',incomplete);
});};
$('copy-brief').onclick=()=>run(()=>copy($('brief-text').textContent));
