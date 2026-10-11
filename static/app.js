const form = document.getElementById('listing-form');
const submitButton = document.getElementById('submit-listing');
const mainContent = document.querySelector('.main-content');
const state = { rules: [], products: [], submissions: [], decisions: [], run: null, stage: 'intake', dataset: 'rules' };
const stages = ['intake', 'extraction', 'policy', 'routing'];
const stageNames = { intake: 'Receive listing', extraction: 'Extract attributes', policy: 'Match policy', routing: 'Policy decisions' };
const escapeHtml = (value) => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');

function keyValueRows(object) {
  const entries = Object.entries(object || {});
  if (!entries.length) return '<tr><td colspan="2" class="empty-cell">No properties.</td></tr>';
  return entries.map(([key, value]) => {
    const display = typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? 'NULL');
    return `<tr><th scope="row">${escapeHtml(key)}</th><td class="property-value">${escapeHtml(display)}</td></tr>`;
  }).join('');
}

function formPayload() {
  return {
    vendor_id: document.getElementById('vendor_id').value,
    title: document.getElementById('title').value,
    declared_category: document.getElementById('declared_category').value,
    price: Number(document.getElementById('price').value || 0),
    description: document.getElementById('description').value,
    seller_metadata: { seller_notes: document.getElementById('seller_notes').value },
  };
}

function renderInspector(stage = state.stage) {
  state.stage = stage;
  document.querySelectorAll('.flow-node[data-stage]').forEach((node) => node.classList.toggle('selected', node.dataset.stage === stage));
  document.getElementById('inspector-stage').textContent = stageNames[stage];
  const content = document.getElementById('inspector-content');
  const run = state.run;
  if (stage === 'intake') {
    const payload = run?.raw_payload || formPayload();
    content.innerHTML = `<div class="inspector-caption">${run ? 'Received input' : 'Current form values'}</div><table class="data-table property-table"><thead><tr><th>field</th><th>value</th></tr></thead><tbody>${keyValueRows(payload)}</tbody></table>`;
  } else if (stage === 'extraction') {
    const features = run?.stage_data?.extraction?.properties || null;
    const waiting = { normalized_product_type: 'waiting', risk_signals: 'waiting', is_obfuscated_or_ambiguous: 'waiting', confidence_score: 'waiting', reason_codes: 'waiting' };
    content.innerHTML = `<div class="inspector-caption">Normalized listing attributes</div><table class="data-table property-table"><thead><tr><th>field</th><th>value</th></tr></thead><tbody>${keyValueRows(features || waiting)}</tbody></table>`;
  } else if (stage === 'policy') {
    const matchIds = new Set(run?.stage_data?.policy?.properties?.matched_rule_ids || []);
    const matchedType = run?.stage_data?.extraction?.properties?.normalized_product_type;
    const rules = run ? state.rules.filter((rule) => matchIds.has(rule.id)) : state.rules;
    const products = run && matchedType ? state.products.filter((item) => item.normalized_product_type === matchedType) : state.products;
    const ruleTables = rules.map((rule) => `<table class="data-table property-table record-table"><thead><tr><th>field</th><th>value</th></tr></thead><tbody>${keyValueRows({ id: rule.id, policy_version_id: rule.policy_version_id, rule_name: rule.rule_name, rule_type: rule.rule_type, condition_json: rule.condition_json, severity: rule.severity, is_active: rule.is_active })}</tbody></table>`).join('');
    const productTables = products.map((item) => `<table class="data-table property-table record-table"><thead><tr><th>field</th><th>value</th></tr></thead><tbody>${keyValueRows(item)}</tbody></table>`).join('');
    content.innerHTML = `<div class="inspector-caption">${run ? 'Matched policy_rules' : 'Active policy_rules'} · ${rules.length} records</div>${ruleTables || '<div class="inspector-empty">No matching policy rule.</div>'}<div class="inspector-caption secondary-caption">${run ? 'Matching prohibited_products' : 'prohibited_products'} · ${products.length} records</div>${productTables || '<div class="inspector-empty">No prohibited product match.</div>'}`;
  } else {
    const properties = run?.stage_data?.routing?.properties;
    const fields = properties || { decision: 'waiting', status: 'waiting', policy_version: 'waiting', review_queue_id: 'NULL', catalog_write: 'waiting' };
    content.innerHTML = `<div class="inspector-caption">Catalog disposition</div><table class="data-table property-table"><thead><tr><th>field</th><th>value</th></tr></thead><tbody>${keyValueRows(fields)}</tbody></table>`;
  }
}

function setStageStatus(stage, status) {
  document.querySelectorAll(`.flow-node[data-stage="${stage}"]`).forEach((node) => {
    node.classList.remove('running', 'complete', 'reject', 'review', 'allow', 'not-reached');
    if (status !== 'waiting') node.classList.add(status);
    node.querySelector('.flow-state').textContent = status;
    const label = [...node.querySelectorAll('.flow-title')].map((part) => part.textContent).join(' ');
    node.setAttribute('aria-label', `${label}, ${status}`);
  });
}

function setDecisionAnswers(decision) {
  const answers = {
    prohibited: { status: decision === 'reject' ? 'reject' : 'complete', text: decision === 'reject' ? 'Yes' : 'No' },
    ambiguous: decision === 'reject'
      ? { status: 'not-reached', text: 'not reached' }
      : { status: decision === 'review' ? 'review' : 'allow', text: decision === 'review' ? 'Yes' : 'No' },
  };
  document.querySelectorAll('[data-decision-node]').forEach((node) => {
    const answer = answers[node.dataset.decisionNode];
    node.classList.remove('running', 'complete', 'reject', 'review', 'allow', 'not-reached');
    node.classList.add(answer.status);
    node.querySelector('.flow-state').textContent = answer.text;
    const label = [...node.querySelectorAll('.flow-title')].map((part) => part.textContent).join(' ');
    node.setAttribute('aria-label', `${label} ${answer.text}`);
  });
}

function setOutcome(decision) {
  const outcome = decision === 'reject' ? 'reject' : decision === 'review' ? 'review' : decision === 'allow' ? 'allow' : null;
  const activeBranches = outcome === 'reject' ? ['reject'] : outcome ? ['shared', outcome] : [];
  document.querySelectorAll('.outcome-node').forEach((node) => {
    const active = node.dataset.outcome === outcome;
    node.classList.toggle('active', active);
    node.querySelector('.outcome-state').textContent = active ? 'selected' : 'not selected';
  });
  document.querySelectorAll('.flow-connector[data-branch], .branch-label[data-branch]').forEach((branch) => {
    const active = activeBranches.includes(branch.dataset.branch);
    branch.classList.toggle('active', active);
    branch.classList.toggle('route-review', active && outcome === 'review');
    branch.classList.toggle('route-allow', active && outcome === 'allow');
  });
}
function resetRun() {
  state.run = { raw_payload: formPayload(), stage_data: {} };
  document.getElementById('run-state').textContent = 'Evaluating';
  document.getElementById('trace-count').textContent = '0 steps';
  document.getElementById('trace-table-body').innerHTML = '';
  stages.forEach((stage) => setStageStatus(stage, 'waiting'));
  setOutcome(null);
  setStageStatus('intake', 'running');
  renderInspector(state.stage);
}

function showStep(event, index) {
  const { stage, title, detail, properties } = event;
  state.run.stage_data[stage] = { title, detail, properties };
  setStageStatus(stage, 'complete');
  const nextStage = stages[stages.indexOf(stage) + 1];
  if (nextStage) setStageStatus(nextStage, 'running');
  if (stage === 'policy') {
    state.run.decision = properties.decision;
    state.run.policy_version = properties.policy_version;
    state.run.matched_rule_ids = properties.matched_rule_ids;
    state.run.reason_codes = properties.reason_codes;
  }
  if (stage === 'routing') {
    Object.assign(state.run, properties);
    setStageStatus('routing', 'complete');
    setDecisionAnswers(properties.decision);
    setOutcome(properties.decision);
  }
  document.getElementById('trace-count').textContent = `${index + 1} ${index === 0 ? 'step' : 'steps'}`;
  document.getElementById('trace-table-body').insertAdjacentHTML('beforeend', `<tr><td>${String(index + 1).padStart(2, '0')}</td><td>${escapeHtml(stageNames[stage])}</td><td><span class="trace-event">${escapeHtml(title)}</span><div class="event-detail">${escapeHtml(detail)}</div></td></tr>`);
  if (stage === state.stage) renderInspector(stage);
}

function finishRun(result) {
  Object.assign(state.run, result);
  const decision = result.decision;
  document.getElementById('run-state').textContent = `${decision} · ${result.policy_version}`;
  renderInspector(state.stage);
}

function renderDataset(dataset = state.dataset) {
  state.dataset = dataset;
  document.querySelectorAll('.dataset-tab').forEach((tab) => {
    const active = tab.dataset.dataset === dataset;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  const name = document.getElementById('dataset-name');
  const head = document.getElementById('dataset-head');
  const body = document.getElementById('dataset-body');
  let columns = [];
  let rows = [];
  if (dataset === 'rules') {
    name.textContent = 'policy_rules';
    columns = ['id', 'policy_version_id', 'rule_name', 'rule_type', 'condition_json', 'severity', 'is_active'];
    rows = state.rules;
  } else if (dataset === 'products') {
    name.textContent = 'prohibited_products';
    columns = ['id', 'policy_version_id', 'normalized_product_type', 'category', 'risk_level', 'is_active'];
    rows = state.products;
  } else {
    name.textContent = 'listing_submissions LEFT JOIN moderation_decisions';
    columns = ['submission_created_at', 'submission_id', 'vendor_id', 'status', 'decision', 'policy_version', 'matched_rule_ids', 'reason_codes', 'review_queue_id', 'decision_created_at'];
    rows = state.submissions.map((submission) => {
      const decision = state.decisions.find((item) => item.submission_id === submission.submission_id) || {};
      let extracted = {};
      try { extracted = JSON.parse(submission.extracted_payload || '{}'); } catch (error) { console.error('Invalid extracted_payload JSON', error); }
      return { submission_created_at: submission.created_at, submission_id: submission.submission_id, vendor_id: submission.vendor_id, status: submission.status, product_type: extracted.normalized_product_type, decision: decision.decision, policy_version: decision.policy_version, matched_rule_ids: decision.matched_rule_ids, reason_codes: decision.reason_codes, review_queue_id: decision.review_queue_id, decision_created_at: decision.created_at };
    });
    columns = ['submission_created_at', 'submission_id', 'vendor_id', 'product_type', 'status', 'decision', 'policy_version', 'matched_rule_ids', 'reason_codes', 'review_queue_id', 'decision_created_at'];
  }
  document.getElementById('database-count').textContent = `${rows.length} rows`;
  head.innerHTML = `<tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr>`;
  body.innerHTML = rows.length ? rows.map((row) => `<tr>${columns.map((column) => `<td class="${column === 'condition_json' || column.endsWith('_ids') || column === 'reason_codes' ? 'json-value' : ['id', 'policy_version_id', 'submission_id'].includes(column) || column.endsWith('_created_at') ? 'mono' : ''}">${escapeHtml(formatCell(row[column]))}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${columns.length}" class="empty-cell">No rows in ${escapeHtml(name.textContent)}.</td></tr>`;
}

function formatCell(value) {
  if (value === undefined || value === null || value === '') return 'NULL';
  if (typeof value !== 'string') return JSON.stringify(value);
  try { return JSON.stringify(JSON.parse(value)); } catch { return value; }
}

async function refreshData() {
  const [historyResponse, policyResponse] = await Promise.all([fetch('/api/listings/history?limit=100'), fetch('/api/policies')]);
  if (!historyResponse.ok) throw new Error(`History request failed: ${historyResponse.status}`);
  if (!policyResponse.ok) throw new Error(`Policy request failed: ${policyResponse.status}`);
  const [history, policy] = await Promise.all([historyResponse.json(), policyResponse.json()]);
  state.submissions = history.submissions || [];
  state.decisions = history.decisions || [];
  state.rules = policy.rules || [];
  state.products = policy.prohibited_products || [];
  renderDataset();
  if (state.stage === 'policy') renderInspector('policy');
}

function handleStreamEvent(message, index) {
  if (message.type === 'step') {
    showStep(message, index);
    return true;
  }
  if (message.type === 'complete') {
    finishRun(message.result);
    return false;
  }
  if (message.type === 'error') throw new Error(message.message);
  throw new Error(`Unknown stream message: ${message.type}`);
}

async function readEvaluationStream(response) {
  if (!response.ok || !response.body) throw new Error(`Evaluation request failed: ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let index = 0;
  let completed = false;
  while (!completed) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const messages = buffer.split('\n\n');
    buffer = messages.pop() || '';
    for (const frame of messages) {
      const line = frame.split('\n').find((item) => item.startsWith('data: '));
      if (!line) continue;
      const message = JSON.parse(line.slice(6));
      completed = !handleStreamEvent(message, index);
      if (message.type === 'step') {
        index += 1;
        await new Promise((resolve) => window.setTimeout(resolve, 50));
      }
      if (completed) break;
    }
    if (done && !completed) throw new Error('Evaluation stream ended before a result was returned.');
  }
}

function setView(view) {
  mainContent.dataset.view = view;
  document.querySelectorAll('.rail-button').forEach((button) => button.classList.toggle('active', button.dataset.view === view));
  if (view === 'rules') renderDataset('rules');
  if (view === 'submissions') renderDataset('submissions');
  if (view === 'workbench') document.getElementById('vendor_id').focus({ preventScroll: true });
  if (view === 'pipeline') renderInspector(state.stage);
}

form.addEventListener('input', () => {
  if (!state.run) renderInspector('intake');
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  resetRun();
  submitButton.disabled = true;
  submitButton.textContent = 'Evaluating…';
  try {
    const response = await fetch('/api/listings/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state.run.raw_payload) });
    await readEvaluationStream(response);
    await refreshData();
  } catch (error) {
    document.getElementById('run-state').textContent = 'Evaluation failed';
    document.getElementById('trace-table-body').insertAdjacentHTML('beforeend', `<tr><td colspan="3" class="error-cell">${escapeHtml(error.message)}</td></tr>`);
    console.error('Listing evaluation failed', error);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = 'Evaluate listing';
  }
});

document.querySelectorAll('.flow-node[data-stage]').forEach((node) => {
  node.addEventListener('click', () => renderInspector(node.dataset.stage));
  node.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      renderInspector(node.dataset.stage);
    }
  });
});
document.querySelectorAll('.dataset-tab').forEach((tab) => tab.addEventListener('click', () => renderDataset(tab.dataset.dataset)));
document.querySelectorAll('.rail-button').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));

function enableResizing() {
  document.querySelectorAll('.splitter').forEach((splitter) => {
    splitter.addEventListener('pointerdown', (event) => {
      event.preventDefault();
      splitter.setPointerCapture(event.pointerId);
      const mode = splitter.dataset.resize;
      const root = document.documentElement;
      const workspace = document.querySelector('.upper-workspace').getBoundingClientRect();
      const move = (moveEvent) => {
        if (mode === 'submission') root.style.setProperty('--submission-width', `${Math.max(220, Math.min(480, moveEvent.clientX - workspace.left - 3))}px`);
        else if (mode === 'inspector') root.style.setProperty('--inspector-width', `${Math.max(250, Math.min(520, workspace.right - moveEvent.clientX - 4))}px`);
        else root.style.setProperty('--database-height', `${Math.max(220, Math.min(window.innerHeight - 250, window.innerHeight - moveEvent.clientY - 12))}px`);
      };
      const stop = () => {
        splitter.removeEventListener('pointermove', move);
        splitter.removeEventListener('pointerup', stop);
      };
      splitter.addEventListener('pointermove', move);
      splitter.addEventListener('pointerup', stop);
    });
  });
}

enableResizing();
renderInspector('intake');
refreshData().catch((error) => {
  document.getElementById('dataset-body').innerHTML = `<tr><td class="error-cell">${escapeHtml(error.message)}</td></tr>`;
  console.error('Database load failed', error);
});






