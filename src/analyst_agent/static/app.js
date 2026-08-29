// AI Data Analyst Agent Frontend Logic
let selectedDataset = 'superstore';
let selectedFile = null;
let currentJobId = null;
let timerInterval = null;
let startTime = 0;

document.addEventListener('DOMContentLoaded', () => {
  initPresets();
  initUpload();
  initPromptPills();
  initActions();
});

// Load sample presets
async function initPresets() {
  const grid = document.getElementById('presetGrid');
  try {
    const res = await fetch('/api/datasets/samples');
    if (!res.ok) throw new Error('Failed to load samples');
    const samples = await res.json();
    grid.replaceChildren();

    samples.forEach((sample, idx) => {
      const card = document.createElement('div');
      card.className = `preset-card ${idx === 0 ? 'active' : ''}`;
      card.dataset.id = sample.id;

      const title = document.createElement('div');
      title.className = 'preset-card-title';
      title.textContent = `📁 ${sample.name}`;

      const desc = document.createElement('div');
      desc.className = 'preset-card-desc';
      desc.textContent = sample.description;

      const meta = document.createElement('div');
      meta.className = 'preset-card-meta';
      meta.textContent = `${sample.rows} hàng • Cột: ${sample.columns.slice(0, 4).join(', ')}...`;

      card.appendChild(title);
      card.appendChild(desc);
      card.appendChild(meta);

      card.addEventListener('click', () => {
        document.querySelectorAll('.preset-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        selectedDataset = sample.id;
        selectedFile = null;
        document.getElementById('selectedFileName').textContent = `Đã chọn bộ mẫu: ${sample.name}`;
      });

      grid.appendChild(card);
    });
  } catch (err) {
    console.error('Could not fetch dataset presets', err);
  }
}

// Upload & Drag-Drop Handling
function initUpload() {
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('csvFileInput');
  const label = document.getElementById('selectedFileName');

  dropZone.addEventListener('click', () => fileInput.click());

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });

  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files.length > 0) {
      handleFile(fileInput.files[0]);
    }
  });

  function handleFile(file) {
    if (!file.name.toLowerCase().endsWith('.csv')) {
      alert('Vui lòng chọn file định dạng .CSV!');
      return;
    }
    selectedFile = file;
    selectedDataset = null;
    document.querySelectorAll('.preset-card').forEach(c => c.classList.remove('active'));
    label.textContent = `✓ File đã nạp: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  }
}

// Prompt pills
function initPromptPills() {
  const input = document.getElementById('questionInput');
  document.querySelectorAll('.pill-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      input.value = btn.dataset.query;
      input.focus();
    });
  });
}

// Actions & Event Streaming
function initActions() {
  const btnStart = document.getElementById('btnStartAnalysis');
  const qInput = document.getElementById('questionInput');

  btnStart.addEventListener('click', async () => {
    const question = qInput.value.trim();
    if (!question) {
      alert('Vui lòng nhập câu hỏi phân tích!');
      return;
    }

    resetUI();
    btnStart.disabled = true;
    startTimer();

    const formData = new FormData();
    formData.append('question', question);
    if (selectedFile) {
      formData.append('file', selectedFile);
    } else if (selectedDataset) {
      formData.append('dataset_name', selectedDataset);
    }

    try {
      const res = await fetch('/api/analysis/start', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Không thể bắt đầu phân tích');
      }

      const data = await res.json();
      currentJobId = data.job_id;
      connectEventStream(data.job_id);
    } catch (err) {
      btnStart.disabled = false;
      stopTimer();
      alert('Lỗi: ' + err.message);
    }
  });

  // Modal resume
  const btnSubmitClarification = document.getElementById('btnSubmitClarification');
  const modalAnswerInput = document.getElementById('modalAnswerInput');
  const modal = document.getElementById('clarificationModal');

  btnSubmitClarification.addEventListener('click', async () => {
    const answer = modalAnswerInput.value.trim();
    if (!answer) return;

    modal.classList.remove('active');
    try {
      await fetch(`/api/analysis/${currentJobId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer }),
      });
    } catch (err) {
      console.error('Failed to resume', err);
    }
  });
}

function resetUI() {
  document.querySelectorAll('.node-item').forEach(n => {
    n.classList.remove('running', 'completed');
    n.querySelector('.node-status').textContent = 'Chờ...';
  });
  setNodeState('node_planner', 'running', 'Đang lập kế hoạch...');

  const stepsContainer = document.getElementById('stepsContainer');
  stepsContainer.replaceChildren();

  const reportContent = document.getElementById('reportContent');
  reportContent.replaceChildren();
  const p = document.createElement('p');
  p.className = 'empty-state';
  p.textContent = 'Đang thực thi chu trình phân tích...';
  reportContent.appendChild(p);

  document.getElementById('tokenDisplay').textContent = '0';
  document.getElementById('costDisplay').textContent = '$0.0000';
}

function startTimer() {
  startTime = Date.now();
  const timer = document.getElementById('timerDisplay');
  clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    timer.textContent = `${elapsed}s`;
  }, 100);
}

function stopTimer() {
  clearInterval(timerInterval);
}

function setNodeState(nodeId, stateClass, statusText) {
  const node = document.getElementById(nodeId);
  if (!node) return;
  node.classList.remove('running', 'completed');
  if (stateClass) node.classList.add(stateClass);
  if (statusText) node.querySelector('.node-status').textContent = statusText;
}

function connectEventStream(jobId) {
  const evtSource = new EventSource(`/api/analysis/${jobId}/stream`);

  evtSource.addEventListener('job_started', () => {
    setNodeState('node_planner', 'running', 'Lập kế hoạch');
  });

  evtSource.addEventListener('clarification_needed', (e) => {
    const data = JSON.parse(e.data);
    const modal = document.getElementById('clarificationModal');
    document.getElementById('modalQuestionText').textContent = data.data.clarification_question || data.message;
    document.getElementById('modalAnswerInput').value = '';
    modal.classList.add('active');
    setNodeState('node_planner', 'running', 'Chờ người dùng làm rõ');
  });

  evtSource.addEventListener('completed', async () => {
    evtSource.close();
    stopTimer();
    document.getElementById('btnStartAnalysis').disabled = false;
    markAllNodesCompleted();
    await fetchAndRenderFinalResult(jobId);
  });

  evtSource.addEventListener('error', (e) => {
    console.error('SSE event error', e);
    evtSource.close();
    stopTimer();
    document.getElementById('btnStartAnalysis').disabled = false;
  });
}

function markAllNodesCompleted() {
  ['node_planner', 'node_inspector', 'node_executor', 'node_critic', 'node_chart', 'node_reporter', 'node_verifier'].forEach(id => {
    setNodeState(id, 'completed', 'Hoàn tất ✓');
  });
}

async function fetchAndRenderFinalResult(jobId) {
  try {
    const res = await fetch(`/api/analysis/${jobId}/result`);
    if (!res.ok) throw new Error('Cannot fetch result');
    const result = await res.json();

    // Render Steps Log
    renderSteps(result.analysis_log || []);

    // Render Metrics
    renderMetrics(result.node_metrics || []);

    // Render Report
    renderReport(result);
  } catch (err) {
    console.error('Render error', err);
  }
}

function renderSteps(steps) {
  const container = document.getElementById('stepsContainer');
  container.replaceChildren();

  if (steps.length === 0) {
    const p = document.createElement('p');
    p.className = 'empty-state';
    p.textContent = 'Không có bước truy vấn SQL/Python nào được thực thi.';
    container.appendChild(p);
    return;
  }

  steps.forEach((step, idx) => {
    const card = document.createElement('div');
    card.className = 'step-card';

    const header = document.createElement('div');
    header.className = 'step-card-header';

    const title = document.createElement('div');
    title.className = 'step-instruction';
    title.textContent = `Bước ${idx + 1}: ${step.instruction}`;

    const badge = document.createElement('span');
    badge.className = 'step-badge';
    badge.textContent = (step.tool || 'SQL').toUpperCase();

    header.appendChild(title);
    header.appendChild(badge);
    card.appendChild(header);

    if (step.code) {
      const code = document.createElement('pre');
      code.className = 'code-block';
      code.textContent = step.code;
      card.appendChild(code);
    }

    if (step.metrics && Object.keys(step.metrics).length > 0) {
      const pillList = document.createElement('div');
      pillList.className = 'metrics-pill-list';
      Object.entries(step.metrics).forEach(([k, v]) => {
        const pill = document.createElement('span');
        pill.className = 'metric-pill';
        pill.textContent = `${k}: ${v}`;
        pillList.appendChild(pill);
      });
      card.appendChild(pillList);
    }

    container.appendChild(card);
  });
}

function renderMetrics(nodeMetrics) {
  let totalTokens = 0;
  let totalCost = 0;

  nodeMetrics.forEach(m => {
    totalTokens += m.total_tokens || 0;
    totalCost += m.estimated_cost_usd || 0;
  });

  document.getElementById('tokenDisplay').textContent = totalTokens.toLocaleString();
  document.getElementById('costDisplay').textContent = `$${totalCost.toFixed(4)}`;
}

function renderReport(result) {
  const container = document.getElementById('reportContent');
  container.replaceChildren();

  const report = result.final_report;
  if (!report) {
    const text = document.createElement('p');
    text.className = 'report-summary-text';
    text.textContent = result.final_answer || 'Không thể tạo báo cáo.';
    container.appendChild(text);
    return;
  }

  // Summary Section
  const summarySec = document.createElement('div');
  summarySec.className = 'report-section-block';
  const summaryTitle = document.createElement('div');
  summaryTitle.className = 'report-section-title';
  summaryTitle.textContent = 'Tổng quan & Phát hiện chính';
  const summaryP = document.createElement('p');
  summaryP.className = 'report-summary-text';
  summaryP.textContent = report.summary;
  summarySec.appendChild(summaryTitle);
  summarySec.appendChild(summaryP);
  container.appendChild(summarySec);

  // Key Findings
  if (report.key_findings && report.key_findings.length > 0) {
    const findSec = document.createElement('div');
    findSec.className = 'report-section-block';
    const findTitle = document.createElement('div');
    findTitle.className = 'report-section-title';
    findTitle.textContent = 'Chi tiết các phát hiện (Có kiểm chứng nguồn)';

    const ul = document.createElement('ul');
    ul.className = 'finding-list';
    report.key_findings.forEach(f => {
      const li = document.createElement('li');
      li.className = 'finding-item';

      const claimSpan = document.createElement('span');
      claimSpan.textContent = f.claim;

      const citeSpan = document.createElement('span');
      citeSpan.className = 'citation-tag';
      citeSpan.textContent = `Nguồn: [${f.citation_step_ids.join(', ')}]`;

      li.appendChild(claimSpan);
      li.appendChild(citeSpan);
      ul.appendChild(li);
    });

    findSec.appendChild(findTitle);
    findSec.appendChild(ul);
    container.appendChild(findSec);
  }

  // Root Causes
  if (report.root_causes && report.root_causes.length > 0) {
    const causeSec = document.createElement('div');
    causeSec.className = 'report-section-block';
    const causeTitle = document.createElement('div');
    causeTitle.className = 'report-section-title';
    causeTitle.textContent = 'Nguyên nhân gốc rễ (Root Causes)';

    const ul = document.createElement('ul');
    ul.className = 'finding-list';
    report.root_causes.forEach(rc => {
      const li = document.createElement('li');
      li.className = 'finding-item';
      li.style.borderLeftColor = '#ef4444';

      const claimSpan = document.createElement('span');
      claimSpan.textContent = rc.claim;

      const citeSpan = document.createElement('span');
      citeSpan.className = 'citation-tag';
      citeSpan.textContent = `[${rc.citation_step_ids.join(', ')}]`;

      li.appendChild(claimSpan);
      li.appendChild(citeSpan);
      ul.appendChild(li);
    });

    causeSec.appendChild(causeTitle);
    causeSec.appendChild(ul);
    container.appendChild(causeSec);
  }

  // Charts
  if (result.charts && result.charts.length > 0) {
    const chartSec = document.createElement('div');
    chartSec.className = 'report-section-block';
    const chartTitle = document.createElement('div');
    chartTitle.className = 'report-section-title';
    chartTitle.textContent = 'Biểu đồ trực quan hóa';

    result.charts.forEach(chart => {
      const chartWrap = document.createElement('div');
      chartWrap.className = 'chart-container';

      const img = document.createElement('img');
      img.className = 'chart-img';
      img.src = `/api/analysis/${result.job_id}/charts/${chart.path.split('/').pop()}`;
      img.alt = chart.title || 'Biểu đồ phân tích';

      chartWrap.appendChild(img);
      chartSec.appendChild(chartWrap);
    });

    container.appendChild(chartSec);
  }

  // Recommendations
  if (report.recommendations && report.recommendations.length > 0) {
    const recSec = document.createElement('div');
    recSec.className = 'report-section-block';
    const recTitle = document.createElement('div');
    recTitle.className = 'report-section-title';
    recTitle.textContent = 'Đề xuất & Hành động tiếp theo';

    const ul = document.createElement('div');
    ul.className = 'recommendation-list';
    report.recommendations.forEach(r => {
      const item = document.createElement('div');
      item.className = 'recommendation-item';

      const bullet = document.createElement('span');
      bullet.className = 'recommendation-bullet';
      bullet.textContent = '✓';

      const text = document.createElement('span');
      text.textContent = r;

      item.appendChild(bullet);
      item.appendChild(text);
      ul.appendChild(item);
    });

    recSec.appendChild(recTitle);
    recSec.appendChild(ul);
    container.appendChild(recSec);
  }
}
