// Frontend estático: sin build step, mismo origen que la API (sin CORS).
// Contrato consumido: GET /api/cases, GET /api/cases/{id}, POST /api/verify.
// Ver src/carrier_truth/adapters/inbound/http/presentation.py para los DTOs.
//
// Principio de esta capa: el color y el veredicto de cada dato SIEMPRE salen
// de `field.severity` / `report.outcome_severity`, que calcula el backend.
// Este archivo no vuelve a comparar valores por su cuenta — hacerlo llevó a
// un bug real: comparar el texto de "solicitado" contra "documento" por
// igualdad literal marcaba en rojo campos ya verificados, solo porque el
// backend añade contexto al texto (p. ej. "$47.50 mensual (mostrado por la
// UI)" vs "$47.50 mensual"). El backend ya decidió si algo cuadra; la UI solo
// lo pinta.

const caseListEl = document.getElementById("case-list");
const detailEl = document.getElementById("detail");
const refreshBtn = document.getElementById("refresh-btn");
const verifyForm = document.getElementById("verify-form");
const uploadErrorEl = document.getElementById("upload-error");

const SEVERITY_ICON = { ok: "✅", warn: "⚠️", danger: "⛔" };

const VERDICT_TITLE = {
  ok: "Puedes confiar en estos datos",
  warn: "Revisa esto antes de usarlo",
  danger: "Este documento no sirve como prueba",
};

let activeCaseId = null;

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function icon(severity) {
  return SEVERITY_ICON[severity] ?? "•";
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* el cuerpo no era JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

// --------------------------------------------------------------------------
// Lista de casos
// --------------------------------------------------------------------------

function clienteDe(report) {
  const campo = report.fields.find((f) => f.field === "cliente");
  return campo?.value || "(sin nombre en el documento)";
}

function pistaCorta(report) {
  if (report.outcome_severity === "ok") {
    return "Todo cuadra con el documento del carrier.";
  }
  if (report.unverified_fields.length > 0) {
    return `Sin confirmar: ${report.unverified_fields.join(", ")}.`;
  }
  return report.outcome_detail;
}

async function loadCaseList() {
  caseListEl.innerHTML = '<li class="case-list-empty">Cargando…</li>';
  try {
    const cases = await fetchJson("/api/cases");
    if (cases.length === 0) {
      caseListEl.innerHTML = '<li class="case-list-empty">Sin casos en el paquete de datos.</li>';
      detailEl.innerHTML = renderEmptyState();
      return;
    }
    caseListEl.innerHTML = "";
    for (const report of cases) {
      caseListEl.appendChild(renderCaseListItem(report));
    }
    // Mantiene la selección si sigue existiendo tras un refresco; si no hay
    // ninguna (primera carga), muestra el primer caso en vez de una pantalla
    // vacía: lo primero que ve la persona ya es un ejemplo completo.
    const activeSigueExistiendo = cases.some((c) => c.case_id === activeCaseId);
    await selectCase(activeSigueExistiendo ? activeCaseId : cases[0].case_id);
  } catch (err) {
    caseListEl.innerHTML = `<li class="case-list-empty">No se pudo cargar: ${escapeHtml(err.message)}</li>`;
  }
}

function renderCaseListItem(report) {
  const li = document.createElement("li");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "case-item" + (report.case_id === activeCaseId ? " active" : "");
  btn.dataset.caseId = report.case_id;
  btn.innerHTML = `
    <div class="case-row">
      <div class="case-id-line">
        <span class="case-id">${escapeHtml(report.case_id)}</span>
        <span class="case-name">${escapeHtml(clienteDe(report))}</span>
      </div>
      <span class="badge ${report.outcome_severity}">${icon(report.outcome_severity)}</span>
    </div>
    <span class="case-hint">${escapeHtml(pistaCorta(report))}</span>
  `;
  btn.addEventListener("click", () => selectCase(report.case_id));
  li.appendChild(btn);
  return li;
}

function markActiveInList() {
  for (const el of caseListEl.querySelectorAll(".case-item")) {
    el.classList.toggle("active", el.dataset.caseId === activeCaseId);
  }
}

async function selectCase(caseId) {
  activeCaseId = caseId;
  markActiveInList();
  detailEl.innerHTML = '<div class="empty-state">Verificando…</div>';
  try {
    const report = await fetchJson(`/api/cases/${encodeURIComponent(caseId)}`);
    renderReport(report);
  } catch (err) {
    detailEl.innerHTML = `<div class="empty-state">No se pudo verificar: ${escapeHtml(err.message)}</div>`;
  }
}

function renderEmptyState() {
  return '<div class="empty-state"><p>👈 Elige un caso a la izquierda para ver la verificación completa.</p></div>';
}

// --------------------------------------------------------------------------
// Procedencia: la línea exacta del documento, resaltada por posición
// --------------------------------------------------------------------------

function highlightSpan(snippet, span) {
  // Resalta la posición exacta que citó el backend (char_span), no la primera
  // coincidencia de texto: dos apariciones iguales en la misma línea (p. ej.
  // "$58.00" repetido en Base Premium y Premium) se distinguirían mal con un
  // simple `replace`, y el span es justo la prueba de precisión que da la API.
  const [a, b] = Array.isArray(span) ? span : [null, null];
  if (a == null || b == null || a < 0 || b > snippet.length || a >= b) {
    return escapeHtml(snippet);
  }
  return (
    escapeHtml(snippet.slice(0, a)) +
    `<mark>${escapeHtml(snippet.slice(a, b))}</mark>` +
    escapeHtml(snippet.slice(b))
  );
}

function renderEvidence(evidence, { summary = "📄 Ver la línea exacta del documento" } = {}) {
  if (!evidence) return "";
  return `
    <details class="evidence">
      <summary>${escapeHtml(summary)}</summary>
      <div class="evidence-body">
        <div class="locator">Página ${evidence.page}, línea ${evidence.line} del documento.</div>
        <div class="snippet">${highlightSpan(evidence.snippet, evidence.char_span)}</div>
        <div class="tech-note">regla técnica: ${escapeHtml(evidence.rule_id)}</div>
      </div>
    </details>
  `;
}

// --------------------------------------------------------------------------
// Un campo (cliente, carrier, cobertura, prima)
// --------------------------------------------------------------------------

function renderField(field) {
  const documentoVacio = field.value == null;
  const documentoValue = documentoVacio
    ? '<span class="v empty">no aparece en el documento</span>'
    : `<span class="v">${escapeHtml(field.value)}</span>`;

  const requestedBlock = field.requested != null
    ? `
      <div class="value-block">
        <span class="k">Se pidió</span>
        <span class="v">${escapeHtml(field.requested)}</span>
      </div>
    `
    : "";

  const caveatBox = field.caveats.length
    ? `
      <div class="caveat-box">
        <div class="caveat-title">⚠️ Ten en cuenta</div>
        ${field.caveats.map((c) => `<div>${escapeHtml(c)}</div>`).join("")}
      </div>
    `
    : "";

  const reasonsBlock = field.reasons.length
    ? `
      <div class="reasons">
        <div class="reasons-title">Por qué</div>
        ${field.reasons.map((r) => `<div class="reason-line">${escapeHtml(r.message)}</div>`).join("")}
      </div>
    `
    : "";

  const nextActionBlock = field.verified
    ? ""
    : `
      <div class="next-action">
        <span class="next-action-icon">👉</span>
        <span><strong>Qué hacer ahora</strong><span class="action-text">${escapeHtml(field.next_action)}</span></span>
      </div>
    `;

  return `
    <div class="field-card ${field.severity}">
      <div class="field-head">
        <span class="field-label">${icon(field.severity)} ${escapeHtml(field.label)}</span>
        <span class="badge ${field.severity}">${escapeHtml(field.status_label)}</span>
      </div>
      <div class="compare-grid">
        <div class="value-block">
          <span class="k">Dice el documento del carrier</span>
          ${documentoValue}
        </div>
        ${requestedBlock}
      </div>
      ${caveatBox}
      ${reasonsBlock}
      ${nextActionBlock}
      ${renderEvidence(field.evidence)}
    </div>
  `;
}

// --------------------------------------------------------------------------
// El veredicto general: lo primero y más grande que se ve del caso
// --------------------------------------------------------------------------

function renderVerdictBanner(report) {
  const sev = report.outcome_severity;
  const authorityNote = report.authority.is_authoritative
    ? ""
    : `
      <p class="verdict-note">
        Motivo: ${escapeHtml(report.authority.label)}.
        ${renderEvidence(report.authority.evidence, { summary: "📄 Ver dónde lo dice el documento" })}
      </p>
    `;

  return `
    <div class="verdict-banner ${sev}">
      <span class="verdict-icon">${icon(sev)}</span>
      <div>
        <p class="verdict-title">${escapeHtml(VERDICT_TITLE[sev] ?? "")}</p>
        <p class="verdict-detail">${escapeHtml(report.outcome_detail)}</p>
        <p class="verdict-count">${report.verified_count} de ${report.total_fields} datos verificados</p>
        ${authorityNote}
      </div>
    </div>
  `;
}

function renderReport(report) {
  const integrityBlock = report.integrity_warnings.length
    ? `
      <div class="integrity-warnings">
        <h3>🔎 El documento tiene una cifra que no cuadra</h3>
        <ul>${report.integrity_warnings.map((r) => `<li>${escapeHtml(r.message)}</li>`).join("")}</ul>
      </div>
    `
    : "";

  detailEl.innerHTML = `
    <div class="report-head">
      <div>
        <h2>${escapeHtml(clienteDe(report))}</h2>
        <div class="document-name">${escapeHtml(report.case_id)} · ${escapeHtml(report.document)}</div>
      </div>
    </div>
    ${renderVerdictBanner(report)}
    <div class="fields">
      ${report.fields.map(renderField).join("")}
    </div>
    ${integrityBlock}
  `;
}

// --------------------------------------------------------------------------
// Subir un PDF propio
// --------------------------------------------------------------------------

verifyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  uploadErrorEl.hidden = true;
  const submitBtn = verifyForm.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = "Verificando…";

  try {
    const formData = new FormData(verifyForm);
    const report = await fetchJson("/api/verify", {
      method: "POST",
      body: formData,
    });
    activeCaseId = null;
    markActiveInList();
    renderReport(report);
  } catch (err) {
    uploadErrorEl.innerHTML = `<span>⛔</span><span>${escapeHtml(err.message)}</span>`;
    uploadErrorEl.hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Verificar documento";
  }
});

refreshBtn.addEventListener("click", loadCaseList);

loadCaseList();
