// Frontend estático: sin build step, mismo origen que la API (sin CORS).
// Contrato consumido: GET /api/cases, GET /api/cases/{id}, POST /api/verify.
// Ver src/carrier_truth/adapters/inbound/http/presentation.py para los DTOs.

const caseListEl = document.getElementById("case-list");
const detailEl = document.getElementById("detail");
const refreshBtn = document.getElementById("refresh-btn");
const verifyForm = document.getElementById("verify-form");
const uploadErrorEl = document.getElementById("upload-error");

let activeCaseId = null;

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* body no era JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

async function loadCaseList() {
  caseListEl.innerHTML = '<li class="case-list-empty">Cargando…</li>';
  try {
    const cases = await fetchJson("/api/cases");
    if (cases.length === 0) {
      caseListEl.innerHTML = '<li class="case-list-empty">Sin casos en el paquete de datos.</li>';
      return;
    }
    caseListEl.innerHTML = "";
    for (const report of cases) {
      caseListEl.appendChild(renderCaseListItem(report));
    }
  } catch (err) {
    caseListEl.innerHTML = `<li class="case-list-empty">Error cargando casos: ${escapeHtml(err.message)}</li>`;
  }
}

function renderCaseListItem(report) {
  const li = document.createElement("li");
  li.className = "case-item" + (report.case_id === activeCaseId ? " active" : "");
  li.dataset.caseId = report.case_id;
  li.innerHTML = `
    <span class="case-id">${escapeHtml(report.case_id)}</span>
    <span class="badge ${report.outcome_severity}">${escapeHtml(report.outcome_label)}</span>
  `;
  li.addEventListener("click", () => selectCase(report.case_id));
  return li;
}

async function selectCase(caseId) {
  activeCaseId = caseId;
  for (const li of caseListEl.querySelectorAll(".case-item")) {
    li.classList.toggle("active", li.dataset.caseId === caseId);
  }
  detailEl.innerHTML = '<div class="empty-state">Verificando…</div>';
  try {
    const report = await fetchJson(`/api/cases/${encodeURIComponent(caseId)}`);
    renderReport(report);
  } catch (err) {
    detailEl.innerHTML = `<div class="empty-state">Error: ${escapeHtml(err.message)}</div>`;
  }
}

function renderReason(reason, severity) {
  const cls = severity === "danger" ? " danger-text" : "";
  return `<div class="reason-line${cls}">${escapeHtml(reason.message)}</div>`;
}

function renderEvidence(evidence) {
  if (!evidence) return "";
  return `
    <details class="evidence">
      <summary>Ver procedencia</summary>
      <div class="evidence-body">
        <div class="locator">${escapeHtml(evidence.locator)} · regla <code>${escapeHtml(evidence.rule_id)}</code></div>
        <div class="snippet">${highlightMatch(evidence.snippet, evidence.matched_text)}</div>
      </div>
    </details>
  `;
}

function highlightMatch(snippet, matchedText) {
  const safeSnippet = escapeHtml(snippet);
  if (!matchedText) return safeSnippet;
  const safeMatch = escapeHtml(matchedText);
  if (!safeSnippet.includes(safeMatch)) return safeSnippet;
  return safeSnippet.replace(safeMatch, `<mark>${safeMatch}</mark>`);
}

function renderField(field) {
  const mismatch =
    field.requested != null && field.value != null && field.requested !== field.value;

  const requestedBlock = field.requested != null
    ? `
      <div class="value-block">
        <span class="k">Solicitado</span>
        <span class="v">${escapeHtml(field.requested)}</span>
      </div>
    `
    : "";

  const valueBlock = `
    <div class="value-block">
      <span class="k">Documento del carrier</span>
      <span class="v${mismatch ? " mismatch" : ""}">${field.value != null ? escapeHtml(field.value) : "—"}</span>
    </div>
  `;

  const caveats = field.caveats.length
    ? `<div class="reasons">${field.caveats.map((c) => `<div class="reason-line">${escapeHtml(c)}</div>`).join("")}</div>`
    : "";

  const reasons = field.reasons.length
    ? `<div class="reasons">${field.reasons.map((r) => renderReason(r, field.severity)).join("")}</div>`
    : "";

  return `
    <div class="field-card">
      <div class="field-head">
        <span class="field-label">${escapeHtml(field.label)}</span>
        <span class="badge ${field.severity}">${escapeHtml(field.status_label)}</span>
      </div>
      <div class="field-values">
        ${valueBlock}
        ${requestedBlock}
      </div>
      ${caveats}
      ${reasons}
      <div class="next-action"><strong>Siguiente paso:</strong> ${escapeHtml(field.next_action)}</div>
      ${renderEvidence(field.evidence)}
    </div>
  `;
}

function renderReport(report) {
  const integrityBlock = report.integrity_warnings.length
    ? `
      <div class="integrity-warnings">
        <h3>Advertencias de integridad del documento</h3>
        <ul>${report.integrity_warnings.map((r) => `<li>${escapeHtml(r.message)}</li>`).join("")}</ul>
      </div>
    `
    : "";

  detailEl.innerHTML = `
    <div class="report-head">
      <div>
        <h2>${escapeHtml(report.case_id)}</h2>
        <div class="document-name">${escapeHtml(report.document)}</div>
      </div>
      <span class="badge ${report.outcome_severity}">${escapeHtml(report.outcome_label)}</span>
    </div>
    <div class="outcome-detail">
      ${escapeHtml(report.outcome_detail)}
      <div style="margin-top:6px; color:var(--text-dim); font-size:12px;">
        ${report.verified_count} de ${report.total_fields} campos verificados.
      </div>
    </div>
    <div class="authority-line">
      <span class="badge ${report.authority.is_authoritative ? "ok" : "danger"}">
        ${report.authority.is_authoritative ? "Fuente autoritativa" : "Fuente no autoritativa"}
      </span>
      ${escapeHtml(report.authority.label)}
      ${renderEvidence(report.authority.evidence)}
    </div>
    <div class="fields">
      ${report.fields.map(renderField).join("")}
    </div>
    ${integrityBlock}
  `;
}

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
    for (const li of caseListEl.querySelectorAll(".case-item")) {
      li.classList.remove("active");
    }
    renderReport(report);
  } catch (err) {
    uploadErrorEl.textContent = err.message;
    uploadErrorEl.hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Verificar";
  }
});

refreshBtn.addEventListener("click", loadCaseList);

loadCaseList();
