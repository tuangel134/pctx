// Run with NODE_PATH pointing to an installed Playwright package.
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");

(async () => {
  const artifactTag = (await fs.readFile(path.resolve(__dirname, '../pyproject.toml'), 'utf8'))
    .match(/^version = "([^"]+)"/m)[1].replace(/\.0$/, '');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "pctx-ui-"));
  const project = path.join(directory, "Proyecto de prueba");
  await fs.mkdir(project);
  await fs.writeFile(
    path.join(project, "package.json"),
    JSON.stringify({
      name: "Proyecto de prueba",
      scripts: { test: "node --test" },
      dependencies: { express: "5" },
    }),
  );
  await fs.writeFile(
    path.join(project, "app.js"),
    "export const answer = 1;\n",
  );
  const proc = spawn(
    "python3",
    ["-m", "pctx", "--root", project, "gui", "--no-browser"],
    {
      cwd: path.resolve(__dirname, ".."),
      env: {
        ...process.env,
        PCTX_CONFIG_DIR: path.join(directory, "registry"),
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      let output = "";
      const timer = setTimeout(
        () => reject(new Error("GUI launch timeout")),
        15000,
      );
      proc.stdout.on("data", (chunk) => {
        output += chunk;
        const match = output.match(/http:\/\/127\.0\.0\.1:\d+\/#token=[\w-]+/);
        if (match) {
          clearTimeout(timer);
          resolve(match[0]);
        }
      });
      proc.on("exit", (code) => {
        clearTimeout(timer);
        reject(new Error("GUI exited " + code));
      });
    });
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(url);
    await page.waitForSelector("#empty:not([hidden])");
    await page
      .getByRole("button", { name: "Abrir mi primer proyecto" })
      .click();
    await page.locator("#new-path").fill(project);
    await page.getByRole("button", { name: "Elegir carpeta…" }).click();
    await page.getByRole("button", { name: "Usar esta carpeta" }).click();
    await page.locator("#project-form > .button-row button.primary").click();
    await page.waitForSelector("#workspace:not([hidden])");
    await page.waitForFunction(() =>
      document.querySelector("#notice").textContent.includes("Proyecto listo"),
    );
    await page.locator('[data-tab="tasks"]').click();
    await page.locator("#task-form [name=title]").fill("Implementar login");
    await page
      .locator("#task-form [name=acceptance]")
      .fill("Prueba de acceso correcta");
    await page
      .locator("#task-form [name=next_actions]")
      .fill("Validar en otro IDE");
    await page.locator("#task-form button.primary").click();
    await page.waitForFunction(() =>
      document.querySelector("#notice").textContent.includes("Avance guardado"),
    );
    await page.locator('[data-tab="plan"]').click();
    await page.waitForFunction(() => document.querySelector('#plan-summary').textContent.includes('Pendiente'));
    await page.locator('#plan-form [name=title]').fill('Meta de continuidad');
    await page.locator('#plan-form [name=kind]').selectOption('goal');
    await page.locator('#plan-form [name=criteria]').fill('Todos los subpuntos comprobados');
    await page.locator('#plan-form button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Punto guardado'));
    const goalId = (await page.locator('#plan-detail-info').textContent()).split(' · ')[0];
    await page.locator('#plan-new').click();
    await page.locator('#plan-form [name=title]').fill('Corregir bug aislado');
    await page.locator('#plan-form [name=kind]').selectOption('bug');
    await page.locator('#plan-form [name=parent]').fill(goalId);
    await page.locator('#plan-form [name=criteria]').fill('App exporta la respuesta esperada');
    await page.locator('#plan-form [name=difficulty]').selectOption('easy');
    await page.locator('#plan-form [name=difficulty_reason]').fill('Un archivo y una comprobación concreta');
    await page.locator('#plan-form [name=risk]').selectOption('high');
    await page.locator('#plan-form button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Punto guardado'));
    const bugId = (await page.locator('#plan-detail-info').textContent()).split(' · ')[0];
    await page.locator('#coord-session').fill('Browser AI A');
    await page.locator('#coord-form [name=paths]').fill('app.js');
    await page.locator('#coord-form [name=summary]').fill('Preparing isolated bug fix');
    await page.locator('#coord-form button.primary').click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Tarea y zonas reservadas'));
    assert.match(await page.locator('#coord-items').textContent(),/Trabajando.*Browser AI A/s);
    assert.match(await page.locator(`[data-plan-id="${bugId}"]`).textContent(),/Trabajando: Browser AI A/);
    assert.equal(await page.locator(`[data-plan-id="${bugId}"] input[type=checkbox]`).isDisabled(),true);
    // Wrong cooperative identity cannot renew another worker's reservation.
    await page.locator('#coord-session').fill('Browser AI B');
    await page.getByRole('button',{name:'Renovar y guardar checkpoint'}).click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('another session'));
    await page.locator('#coord-form button.primary').click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Reservation conflict'));
    await page.locator('#coord-session').fill('Browser AI A');
    await page.locator('#coord-form [name=summary]').fill('<img src=x onerror=alert(1)> Fix drafted; review pending');
    await page.getByRole('button',{name:'Renovar y guardar checkpoint'}).click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Reserva renovada'));
    assert.match(await page.locator('#coord-items').textContent(),/Fix drafted; review pending/);
    assert.equal(await page.locator('#coord-items img').count(),0);
    assert.match(await page.locator('#plan-detail-info').textContent(),/Revisiones: 0/);
    await page.getByRole('button',{name:'Historial de reserva'}).click();
    await page.waitForSelector('#coord-history:not([hidden])');
    assert.match(await page.locator('#coord-history').textContent(),/Revisión 2.*Browser AI A/s);
    assert.match(await page.locator('#coord-history').textContent(),/Revisión 1.*Preparing isolated bug fix/s);
    await page.screenshot({path:path.resolve(__dirname,`../validation/coordination-desktop-${artifactTag}.png`),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.resolve(__dirname,`../validation/coordination-mobile-${artifactTag}.png`),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('#coord-form [name=summary]').fill('Fix checkpoint handed off; next worker should review');
    await page.getByRole('button',{name:'Liberar con traspaso'}).click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Reserva liberada'));
    assert.match(await page.locator('#coord-items').textContent(),/Liberada/);
    assert.equal(await page.locator(`[data-plan-id="${bugId}"] input[type=checkbox]`).isDisabled(),false);

    await page.locator('#plan-filters [name=difficulty]').selectOption('easy');
    await page.locator('#plan-filters [name=ready]').check();
    await page.locator('#plan-filters button').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Filtros aplicados'));
    assert.equal(await page.locator('#plan-items .plan-item').count(), 1);
    assert.match(await page.locator('#plan-items').textContent(), /Fácil.*Riesgo: Alto.*Revisiones: 0/);
    // An open child blocks the parent's checkbox.
    await page.locator('#plan-filters [name=difficulty]').selectOption('');
    await page.locator('#plan-filters [name=ready]').uncheck();
    await page.locator('#plan-filters button').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Filtros aplicados'));
    await page.locator(`[data-plan-id="${goalId}"] input[type=checkbox]`).check();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('unfinished children'));
    assert.equal(await page.locator(`[data-plan-id="${goalId}"] input[type=checkbox]`).isChecked(), false);
    await page.locator(`[data-plan-id="${bugId}"] input[type=checkbox]`).check();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Marcar hecho no cuenta'));
    assert.match(await page.locator(`[data-plan-id="${bugId}"]`).textContent(), /Hecho.*Revisiones: 0/);
    await page.locator(`[data-plan-id="${bugId}"]`).getByRole('button',{name:'Detalle y revisiones'}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Detalle del punto cargado') || document.querySelector('#notice').textContent.includes('Revisión registrada una vez'));
    await page.locator('#plan-status [name=status]').selectOption('verified');
    await page.locator('#plan-status button').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('review missing'));
    await page.locator('#plan-review [name=reviewer]').fill('Chromium smoke');
    await page.locator('#plan-review [name=summary]').fill('Se comprobó el resultado del módulo app');
    await page.locator('#plan-review [name=outcome]').selectOption('failed');
    await page.locator('#plan-review [name=evidence]').fill('app.js');
    await page.locator('#plan-review button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Revisión registrada una vez'));
    assert.match(await page.locator('#plan-detail-info').textContent(), /Por revisar.*Revisiones: 1.*Falló/);
    await page.locator('#plan-review [name=reviewer]').fill('Chromium smoke');
    await page.locator('#plan-review [name=summary]').fill('Se repitió la comprobación y pasó el criterio');
    await page.locator('#plan-review [name=evidence]').fill('app.js');
    await page.locator('#plan-review [name=covered]').check();
    await page.locator('#plan-review button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Revisión registrada una vez'));
    assert.match(await page.locator('#plan-detail-info').textContent(), /Revisiones: 2.*Pasó/);
    await page.locator('#plan-status [name=status]').selectOption('verified');
    await page.locator('#plan-status button').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Estado guardado con sus comprobaciones'));
    assert.match(await page.locator('#plan-detail-info').textContent(), /Verificado/);
    await page.locator('#plan-history').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Historial consultado'));
    assert.match(await page.locator('#plan-history-text').textContent(), /Falló/);
    assert.match(await page.locator('#plan-history-text').textContent(), /Pasó/);
    assert.match(await page.locator('#plan-detail-info').textContent(), /Revisiones: 2/);
    await page.locator('#plan-form [name=title]').fill('<img src=x onerror=alert(1)> Bug corregido');
    await page.locator('#plan-form button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Punto guardado'));
    assert.match(await page.locator('#plan-detail-info').textContent(), /Por revisar/);
    assert.equal(await page.locator('#plan-items img').count(), 0);
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:path.resolve(__dirname,`../validation/checklists-desktop-${artifactTag}.png`),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.resolve(__dirname,`../validation/checklists-mobile-${artifactTag}.png`),fullPage:true});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No mobile checklist overflow');
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('[data-tab="knowledge"]').click();
    await page
      .locator("#record-form [name=statement]")
      .fill("El módulo app exporta la respuesta inicial.");
    await page.locator("#record-form [name=evidence]").fill("app.js");
    await page.locator("#record-form button.primary").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("Conocimiento guardado"),
    );
    assert.match(
      await fs.readFile(path.join(project, "PROJECT_CONTEXT.md"), "utf8"),
      /respuesta inicial/,
    );
    await fs.writeFile(path.join(project, ".project-context/records/constraint.ui-budget.json"),
      JSON.stringify({id: "constraint.ui-budget", type: "constraint", scope: "project",
        state: "user_asserted", statement: "Preserve the signed release. ".repeat(300)}));
    await page.locator('[data-tab="context"]').click();
    await page.locator('#context-form [name=task]').fill('Implementar login');
    const traceBeforeBrief = await fs.readFile(path.join(project, '.project-context/work/TASKS.json'), 'utf8');
    await page.locator('#brief-form [name=role]').fill('W7');
    await page.locator('#brief-form [name=budget]').fill('800');
    await page.locator('#brief-form button').click();
    await page.waitForFunction(()=>document.querySelector('#brief-text').textContent.includes('PCTX brief · W7'));
    const sharedBrief = await page.locator('#brief-text').textContent();
    assert.match(sharedBrief,/\[global\] Implementar login/);
    assert.match(sharedBrief,/\[global\] Validar en otro IDE/);
    assert.match(sharedBrief,/Sin datos específicos para W7/);
    assert.ok(Math.ceil(sharedBrief.length/4)<=800);
    assert.equal(await fs.readFile(path.join(project, '.project-context/work/TASKS.json'), 'utf8'),traceBeforeBrief);
    await page.locator('#brief-form [name=role]').fill('W4');
    await page.locator('#brief-form [name=budget]').fill('800');
    await page.locator('#brief-form button').click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Brief generado'));
    assert.match(await page.locator('#notice').textContent(),/esenciales incompletos/);
    const workerBrief=await page.locator('#brief-text').textContent();
    assert.match(workerBrief,/PCTX brief.*W4/);assert.match(workerBrief,/Objetivo:/);assert.match(workerBrief,/Últimos cambios:/);
    assert.ok(Math.ceil(workerBrief.length/4)<=800);
    await page.context().grantPermissions(['clipboard-read','clipboard-write']);
    await page.locator('#copy-brief').click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Copiado'));
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),workerBrief);
    await page.locator('#context-form [name=budget]').fill('256');
    await page.locator('#context-form button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Contexto esencial incompleto'));
    assert.match(await page.locator('#context-text').textContent(), /INCOMPLETE/);
    await page.locator('#context-report').click();
    await page.waitForSelector('#context-report-text:not([hidden])');
    const selection = JSON.parse(await page.locator('#context-report-text').textContent());
    assert.ok(selection.essential_omitted.includes('constraint.ui-budget'));
    await page.locator('#read-form [name=reference]').fill('constraint.ui-budget');
    await page.locator('#read-form button').click();
    await page.waitForSelector('#read-text:not([hidden])');
    assert.match(await page.locator('#read-text').textContent(), /Preserve the signed release/);
    await fs.mkdir(path.join(project, 'docs'));
    await fs.writeFile(path.join(project, 'docs/continuity.md'), 'Cookie authentication renewal policy.\nPreserve the browser session.\n');
    await page.locator('#lookup-form [name=query]').fill('cookie authentication');
    await page.locator('#lookup-form [name=kind]').selectOption('document');
    await page.locator('#lookup-form [name=budget]').fill('512');
    await page.locator('#lookup-form button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Búsqueda completada'));
    assert.match(await page.locator('#lookup-results').textContent(), /renewal policy/);
    assert.match(await page.locator('#lookup-summary').textContent(), /ephemeral:stale/);
    await page.getByRole('button', {name: 'Leer fragmento exacto'}).first().click();
    await page.waitForSelector('#knowledge-detail:not([hidden])');
    assert.match(await page.locator('#knowledge-detail').textContent(), /Exact current fragment/);
    await page.getByRole('button', {name: 'Ver conexiones'}).first().click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Conexiones de la fuente'));
    assert.match(await page.locator('#knowledge-detail').textContent(), /file:docs\/continuity.md/);
    await page.locator('#knowledge-index').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Índice preparado'));
    await page.locator('#lookup-form button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Búsqueda completada'));
    if (!(await page.locator('#lookup-summary').textContent()).includes('persistent:fresh')) {
      const diagnose = require('node:child_process').spawnSync('python3',['-c',
        "import sys,sqlite3,json;from pathlib import Path;from pctx.knowledge import inventory;root=Path(sys.argv[1]);data=inventory(root);db=sqlite3.connect(root/'.project-context/.cache/knowledge.sqlite3');old={r[0].split('@')[0]:r[0] for r in db.execute('SELECT ref FROM search')};new={r['source']:r['ref'] for r in data['chunks']};print(json.dumps({'changed_sources':[s for s in old.keys()|new.keys() if old.get(s)!=new.get(s)],'db_digest':dict(db.execute('SELECT key,value FROM meta')).get('digest'),'current_digest':data['digest']}))",project],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});
      process.stderr.write(diagnose.stdout + diagnose.stderr);
    }
    assert.match(await page.locator('#lookup-summary').textContent(), /persistent:fresh/);
    await page.screenshot({path: path.resolve(__dirname, `../validation/lookup-desktop-${artifactTag}.png`), fullPage: true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path: path.resolve(__dirname, `../validation/lookup-mobile-${artifactTag}.png`), fullPage: true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.setViewportSize({width:1440,height:1000});
    await fs.unlink(path.join(project, 'docs/continuity.md'));
    await page.getByRole('button', {name: 'Leer fragmento exacto'}).first().click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Fragment unavailable'));
    await page.locator('[data-tab="knowledge"]').click();
    await page.locator("#watch").check();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("Seguimiento activado"),
    );
    await fs.writeFile(
      path.join(project, "app.js"),
      "export const answer = 2;\n",
    );
    const deadline = Date.now() + 18000;
    let stale = false;
    while (Date.now() < deadline) {
      const files = await fs.readdir(
        path.join(project, ".project-context/records"),
      );
      for (const file of files) {
        const r = JSON.parse(
          await fs.readFile(
            path.join(project, ".project-context/records", file),
            "utf8",
          ),
        );
        if (r.statement.includes("respuesta inicial") && r.state === "stale")
          stale = true;
      }
      if (stale) break;
      await new Promise((r) => setTimeout(r, 300));
    }
    assert.ok(stale, "Watcher must mark changed evidence stale");
    await page.locator("#watch").uncheck();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("Seguimiento detenido"),
    );
    await page.locator("#refresh").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("Contexto actualizado"),
    );
    await page.locator('[data-tab="knowledge"]').click();
    let historicalCard = page.locator('.record').filter({hasText: 'El módulo app exporta la respuesta inicial.'});
    await historicalCard.getByRole('button', {name: 'Revisar evidencia y candidatos'}).click();
    await historicalCard.locator('pre').waitFor();
    assert.match(await historicalCard.locator('pre').textContent(), /expected_hash/);
    assert.match(await historicalCard.locator('pre').textContent(), /evidence:changed/);
    page.once('dialog', d => d.accept());
    await historicalCard.getByRole('button', {name: 'Confirmar con evidencia actual'}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Revisión guardada'));
    page.once('dialog', async d => {
      page.once('dialog', next => next.accept());
      await d.accept('El módulo app exporta la respuesta corregida.');
    });
    await historicalCard.getByRole('button', {name: 'Corregir afirmación'}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Corrección guardada'));
    // Use the corrected card for the historical restoration below.
    historicalCard = page.locator('.record').filter({hasText: 'El módulo app exporta la respuesta corregida.'});
    await historicalCard.getByRole('button', {name: 'Historial', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Historial disponible'));
    await historicalCard.getByRole('button', {name: 'Ver revisión 1', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Revisión y diferencias disponibles'));
    assert.match(await historicalCard.locator('pre').textContent(), /respuesta inicial/);
    page.once('dialog', dialog => dialog.accept());
    await historicalCard.getByRole('button', {name: 'Restaurar esta revisión'}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Revisión restaurada'));
    await page.locator('[data-tab="integrations"]').click();
    await page.locator("#client").selectOption("cursor");
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("Configuración preparada"),
    );
    await page.locator("#install-config").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("Configuración instalada"),
    );
    assert.ok(
      JSON.parse(
        await fs.readFile(path.join(project, ".cursor/mcp.json"), "utf8"),
      ).mcpServers.pctx,
    );
    await page.locator("#probe").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("MCP local responde"),
    );
    await page
      .getByRole("button", { name: "Preparar PCTX portable para MCP Master" })
      .click();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("PCTX portable creado"),
    );
    assert.match(
      await page.locator("#guide-text").textContent(),
      /\.runtime\/pctx.pyz/,
    );
    await page
      .context()
      .grantPermissions(["clipboard-read", "clipboard-write"]);
    await page
      .getByRole("button", { name: "Copiar instrucciones para la IA" })
      .click();
    await page.waitForFunction(() =>
      document.querySelector("#notice").textContent.includes("Copiado"),
    );
    assert.match(
      await page.evaluate(() => navigator.clipboard.readText()),
      /forja_call_workspace_tool/,
    );
    await page.locator('[data-tab="architecture"]').click();
    await page.locator("#architecture-form [name=source]").fill("api");
    await page.locator("#architecture-form [name=target]").fill("database");
    await page.locator("#architecture-form [name=label]").fill("consulta");
    await page.locator("#architecture-form button.primary").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("Conexión guardada"),
    );
    assert.match(
      await fs.readFile(path.join(project, "architecture.md"), "utf8"),
      /consulta/,
    );
    await page.locator('[data-tab="tasks"]').click();
    await page.getByRole('button', {name: 'Ver cambios desde checkpoint'}).click();
    await page.locator('[data-differences]').waitFor();
    assert.match(await page.locator('[data-differences]').textContent(), /app.js/);
    await page.locator("#finish-task").click();
    await page.waitForFunction(() =>
      document.querySelector("#notice").textContent.includes("Sesión cerrada"),
    );
    const tasks = JSON.parse(
      await fs.readFile(
        path.join(project, ".project-context/work/TASKS.json"),
        "utf8",
      ),
    );
    assert.equal(tasks.history.at(-1).status, "paused");
    assert.deepEqual(tasks.history.at(-1).next_actions, [
      "Validar en otro IDE",
    ]);
    await page
      .getByRole("button", { name: "Retomar última tarea pendiente" })
      .click();
    await page.waitForFunction(() =>
      document.querySelector("#notice").textContent.includes("Tarea retomada"),
    );
    assert.equal(
      await page.locator("#task-form [name=next_actions]").inputValue(),
      "Validar en otro IDE",
    );
    await page.locator("#finish-task").click();
    await page.waitForFunction(() =>
      document.querySelector("#notice").textContent.includes("Sesión cerrada"),
    );
    await page.locator('[data-tab="health"]').click();
    await page.locator("#doctor").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#notice")
        .textContent.includes("Diagnóstico completado"),
    );
    assert.match(
      await page.locator("#health-result").textContent(),
      /0 errores/,
    );
    await page.getByRole('button', {name: 'Crear respaldo privado'}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Respaldo privado creado'));
    const backupView = page.locator('section').filter({has: page.getByRole('heading', {name: 'Respaldos y recuperación'})}).locator('pre');
    const backup = JSON.parse(await backupView.textContent());
    await page.locator('[data-tab="knowledge"]').click();
    await page.locator('#record-form [name=statement]').fill('Registro temporal posterior al respaldo.');
    await page.locator('#record-form button.primary').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Conocimiento guardado'));
    await page.locator('[data-tab="health"]').click();
    await page.getByRole('textbox', {name: 'Ruta del respaldo'}).fill(backup.path);
    await page.getByRole('button', {name: 'Previsualizar restauración'}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Previsualización lista'));
    const restorePreview = JSON.parse(await backupView.textContent());
    assert.ok(restorePreview.removed.some(p => p.startsWith('records/')));
    page.once('dialog', d => d.accept());
    await page.getByRole('button', {name: 'Restaurar respaldo', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Respaldo restaurado'));
    const restored = JSON.parse(await backupView.textContent());
    assert.ok(restored.ok);
    await fs.unlink(backup.path); await fs.unlink(restored.pre_restore_backup);
    const out = path.resolve(__dirname, "../validation");
    await fs.mkdir(out, { recursive: true });
    await page.locator('[data-tab="overview"]').click();
    await page.screenshot({
      path: path.join(out, "dashboard-desktop.png"),
      fullPage: true,
    });
    await page.locator('[data-tab="architecture"]').click();
    await page.screenshot({
      path: path.join(out, "dashboard-architecture.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('[data-tab="overview"]').click();
    await page.screenshot({
      path: path.join(out, "dashboard-mobile.png"),
      fullPage: true,
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
      "No horizontal overflow on mobile overview",
    );
    assert.deepEqual(errors, [], "No browser runtime errors");
    await page.locator("#shutdown").click();
    await page.waitForFunction(() =>
      document.querySelector("#notice").textContent.includes("Panel apagado"),
    );
    await new Promise((resolve, reject) => {
      if (proc.exitCode !== null) return resolve();
      const t = setTimeout(
        () => reject(new Error("Shutdown did not exit")),
        15000,
      );
      proc.once("exit", () => {
        clearTimeout(t);
        resolve();
      });
    });
    const report = {
      passed: true,
      flows: [
        'W7 brief retains labelled shared task context without worker assignment',
        'budgeted role-specific worker brief in browser',
        'copy worker brief without altering coordinator task',
        'reserve task and file area in browser',
        'working task visibly unavailable to other AI',
        'wrong session renewal rejected',
        'duplicate reservation rejected',
        'renew checkpoint without adding reviews',
        'reservation history and DOM injection protection',
        'desktop and mobile reservation layout',
        'release with handoff makes task available',
        "goal and nested bug creation",
        "explicit difficulty reason and separate high risk",
        "ready easy work filter",
        "parent completion blocked by open child",
        "checkbox completion preserves zero reviews",
        "verification rejected without evidence review",
        "failed review updates checklist state and count",
        "passed review covers acceptance criteria",
        "explicit verification with current evidence",
        "history distinguishes edits and work reviews",
        "editing invalidates verification",
        "checklist DOM injection protection",
        "desktop and mobile checklist layout",
        "folder picker and initialize",
        "task checkpoint",
        "record evidence",
        "automatic stale detection",
        "bounded context with essential omission warning",
        "explained selection and exact omission report",
        "progressive record expansion",
        "unified document lookup with token budget",
        "exact live document expansion",
        "knowledge graph navigation",
        "explicit disposable index rebuild",
        "deleted document reference rejected",
        "retrieval desktop and mobile layout",
        "record history inspection",
        "historical revision comparison",
        "guarded restoration as a new inferred revision",
        "current evidence hash inspection",
        "explicit human evidence confirmation",
        "correction preserves history",
        "content differences from checkpoint",
        "private backup creation",
        "restore preview and guarded application",
        "stop watcher",
        "refresh",
        "install Cursor configuration",
        "real stdio MCP probe",
        "portable runtime generation",
        "copy Master MCP instructions",
        "architecture edit",
        "handoff preserves pending work",
        "resume pending task",
        "diagnostics",
        "desktop and mobile rendering",
        "shutdown",
      ],
      browserErrors: errors,
    };
    await fs.writeFile(
      path.join(out, "ui-report.json"),
      JSON.stringify(report, null, 2) + "\n",
    );
    console.log(JSON.stringify(report, null, 2));
  } finally {
    if (browser) await browser.close();
    if (proc.exitCode === null) proc.kill("SIGTERM");
    await fs.rm(directory, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
