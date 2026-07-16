const viewRoot = document.querySelector("#view");
const toastEl = document.querySelector("#toast");
const noticeEl = document.querySelector("#notice");

const state = {
  config: null,
  project: null,
  view: "concept",
  finalMode: "final",
  pollTimer: null,
  toastTimer: null,
  busy: false,
};

const STAGE_RANK = {
  DRAFT: 0,
  PLANNING: 1,
  PLAN_READY: 2,
  STORYBOARD_GENERATING: 3,
  STORYBOARD_REVIEW: 4,
  VIDEO_GENERATING: 5,
  VIDEO_REVIEW: 6,
  ASSEMBLING: 7,
  COMPLETED: 8,
  PARTIALLY_COMPLETED: 5,
  FAILED: 0,
  CANCELLED: 0,
};

const VIEW_RANK = { concept: 0, plan: 2, storyboard: 3, production: 5, final: 6 };
const ACTIVE_JOBS = new Set(["QUEUED", "GENERATING", "POLLING", "DOWNLOADING", "VERIFYING"]);
const esc = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const error = new Error(payload?.detail || payload || `Request failed (${response.status})`);
    error.status = response.status;
    error.code = payload?.code;
    throw error;
  }
  return payload;
}

function notify(message, type = "success") {
  clearTimeout(state.toastTimer);
  toastEl.textContent = message;
  toastEl.className = `toast visible ${type === "error" ? "error" : ""}`;
  state.toastTimer = setTimeout(() => { toastEl.className = "toast"; }, 4200);
}

function formatSaved(value) {
  if (!value) return "—";
  const date = new Date(value);
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 5) return "JUST NOW";
  if (seconds < 60) return `${seconds}S AGO`;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatCny(value) {
  if (value == null) return "— CNY";
  return `${Number(value).toFixed(2)} CNY`;
}

function latestJob(kind, shotId = null) {
  if (!state.project) return null;
  return [...state.project.jobs]
    .reverse()
    .find((job) => job.kind === kind && (shotId == null || job.shotId === shotId)) || null;
}

function asset(shot, kind) {
  return shot.assets?.find((item) => item.kind === kind && item.isCurrent) || null;
}

function currentReport(phase) {
  return state.project?.consistencyReports?.find((item) => item.phase === phase)?.report || null;
}

function updateChrome() {
  const project = state.project;
  document.querySelector("#provider-label").textContent = state.config
    ? `${state.config.provider.toUpperCase()} PROVIDER`
    : "PROVIDER";
  document.querySelector("#project-kicker").textContent = project ? "ACTIVE PRODUCTION" : "NEW PRODUCTION";
  document.querySelector("#project-heading").textContent = project?.title || "Create a short film";
  document.querySelector("#stage-label").textContent = project?.stage || "DRAFT";
  document.querySelector("#saved-label").textContent = formatSaved(project?.savedAt);
  document.querySelector("#budget-label").textContent = formatCny(project?.budget?.estimatedCostCny);
  const rank = project ? STAGE_RANK[project.stage] ?? 0 : 0;
  document.querySelectorAll(".stage-link").forEach((button) => {
    const view = button.dataset.view;
    const allowed = view === "concept" || Boolean(project && (view === "plan" ? project.plan : rank >= VIEW_RANK[view]));
    button.disabled = !allowed;
    button.classList.toggle("active", view === state.view);
    button.classList.toggle("complete", allowed && VIEW_RANK[view] < rank);
  });
  const real = state.config?.realMode;
  if (real) {
    noticeEl.textContent = "REAL QWEN MODE — storyboard and video buttons start paid media calls only after explicit confirmation.";
    noticeEl.classList.add("visible");
  } else {
    noticeEl.textContent = "MOCK MODE — the complete workflow is safe to run; no paid Qwen Cloud calls will be made.";
    noticeEl.classList.add("visible");
  }
}

function render() {
  updateChrome();
  const renderers = {
    concept: renderConcept,
    plan: renderPlan,
    storyboard: renderStoryboard,
    production: renderProduction,
    final: renderFinal,
  };
  viewRoot.innerHTML = renderers[state.view]();
  viewRoot.onclick = handleAction;
  viewRoot.onsubmit = handleSubmit;
  schedulePolling();
}

function activeProjectCard() {
  if (!state.project) return "";
  return `
    <div class="panel" style="margin-bottom:20px">
      <div class="panel-body" style="display:flex;justify-content:space-between;align-items:center;gap:20px">
        <div>
          <span class="section-kicker">Active production · ${esc(state.project.stage)}</span>
          <h3 style="margin:5px 0 3px">${esc(state.project.title)}</h3>
          <p style="margin:0;color:var(--muted)">${esc(state.project.storyPrompt)}</p>
        </div>
        <div class="button-group">
          <button class="btn" data-action="resume-project">Resume production</button>
          <button class="btn ghost" data-action="new-production">Start another</button>
        </div>
      </div>
    </div>`;
}

function renderConcept() {
  return `
    <div class="page-intro">
      <div>
        <span class="section-kicker">Concept development</span>
        <h2>One prompt.<br />A controlled production.</h2>
        <p>VideoForge turns an open-ended idea into a controlled six-shot film, with human approval gates before either media-generation stage.</p>
      </div>
    </div>
    ${activeProjectCard()}
    <div class="concept-layout">
      <form class="form-panel" id="create-project-form">
        <div class="field-grid">
          <div class="field full">
            <label for="project-title">Project title <em>Working title</em></label>
            <input id="project-title" name="title" value="The Third Exposure" maxlength="120" required />
          </div>
          <div class="field full">
            <label for="story-prompt">Main story prompt <em>One character · one location · one reveal</em></label>
            <textarea id="story-prompt" name="storyPrompt" maxlength="2000" required>A woman finds a Polaroid photograph of herself sleeping in her bedroom, but she lives alone.</textarea>
            <div class="char-count">Planning is a non-media action</div>
          </div>
          <div class="field">
            <label for="genre">Genre</label>
            <select id="genre" name="genre">
              ${["Psychological horror", "Science fiction", "Drama", "Mystery", "Dark comedy"].map((item) => `<option>${item}</option>`).join("")}
            </select>
          </div>
          <div class="field">
            <label for="visual-style">Visual style</label>
            <select id="visual-style" name="visualStyle">
              ${["Cinematic realism", "Analog horror", "Graphic novel", "Stop-motion miniature", "Muted European drama"].map((item) => `<option>${item}</option>`).join("")}
            </select>
          </div>
          <div class="field">
            <label for="aspect">Aspect ratio</label>
            <select id="aspect" name="aspectRatio"><option>16:9</option><option>9:16</option><option>1:1</option></select>
          </div>
          <div class="field">
            <label for="duration">Target duration</label>
            <select id="duration" name="targetDurationSeconds"><option value="30">≈ 30 seconds · 6 shots</option><option value="24">≈ 24 seconds · 6 shots</option><option value="18">≈ 18 seconds · 6 shots</option></select>
          </div>
        </div>
        <div class="button-row split">
          <span class="paid-note"><strong>0 media calls</strong> · editable before generation</span>
          <div class="button-group">
            <button class="btn ghost" type="button" data-action="load-demo">Load demo project</button>
            <button class="btn primary" type="submit">Generate production plan →</button>
          </div>
        </div>
      </form>
      <aside class="panel strategy-panel">
        <span class="section-kicker">The showrunner method</span>
        <h3>Lock the world before it moves.</h3>
        <p>Identity, set design, lighting, palette, and camera language are frozen in approved images. Wan receives only motion instructions.</p>
        <div class="pipeline">
          <div class="pipeline-step"><strong>Narrative direction</strong><span>Three achievable dramatic beats</span></div>
          <div class="pipeline-step"><strong>Immutable visual bible</strong><span>One source of continuity truth</span></div>
          <div class="pipeline-step"><strong>Approved keyframes</strong><span>Human checkpoint before animation</span></div>
          <div class="pipeline-step"><strong>Restrained motion</strong><span>One action, one camera instruction</span></div>
          <div class="pipeline-step"><strong>Verified final cut</strong><span>FFmpeg normalization and assembly</span></div>
        </div>
        <div class="quote-block">“Treat generation like a film set—not a slot machine.”</div>
      </aside>
    </div>`;
}

function inputField(label, path, value, options = {}) {
  const { full = false, textarea = true, compact = true, readonly = false } = options;
  const control = textarea
    ? `<textarea class="${compact ? "compact" : ""}" data-plan="${esc(path)}" ${readonly ? "readonly" : ""}>${esc(value)}</textarea>`
    : `<input data-plan="${esc(path)}" value="${esc(value)}" ${readonly ? "readonly" : ""} />`;
  return `<div class="field ${full ? "full" : ""}"><label>${esc(label)}</label>${control}</div>`;
}

function shotEditor(shot) {
  const fields = [
    ["Narrative purpose", "narrativePurpose"], ["Framing", "framing"],
    ["Camera angle", "cameraAngle"], ["Subject position", "subjectPosition"],
    ["Primary action", "subjectAction"], ["Environment state", "environmentState"],
    ["Environment motion", "environmentMotion"], ["Camera motion", "cameraMotion"],
    ["Key prop state", "propState"], ["Image-specific delta", "imageDelta"],
  ];
  return `
    <article class="shot-plan-card" data-shot-editor="${esc(shot.id)}">
      <div class="shot-plan-head">
        <div><span class="shot-number">SHOT ${String(shot.order).padStart(2, "0")}</span><div class="shot-purpose">${esc(shot.narrativePurpose)}</div></div>
        <span class="status-pill">${shot.durationSeconds}s · seeds locked</span>
      </div>
      <div class="shot-plan-body">
        <div class="field-grid">
          ${fields.map(([label, key], index) => `<div class="field ${key === "imageDelta" ? "full" : ""}"><label>${label}</label><textarea class="compact" data-shot-key="${key}">${esc(shot[key])}</textarea></div>`).join("")}
          <div class="field"><label>Duration seconds</label><input type="number" min="2" max="5" data-shot-key="durationSeconds" value="${shot.durationSeconds}" /></div>
          <div class="field"><label>Image / video seed</label><input readonly value="${shot.imageSeed} / ${shot.videoSeed}" /></div>
        </div>
        <label class="section-kicker" style="display:block;margin-top:16px">Compiled image prompt · immutable bible + editable delta</label>
        <div class="compiled-prompt">${esc(shot.imagePrompt)}</div>
        <label class="section-kicker" style="display:block;margin-top:14px">Compiled motion-only prompt</label>
        <div class="compiled-prompt" style="max-height:100px">${esc(shot.motionPrompt)}</div>
      </div>
    </article>`;
}

function renderPlan() {
  const plan = state.project?.plan;
  if (!plan) return emptyState("No plan yet", "Return to Concept and generate a production plan.", "concept");
  const bible = plan.visualBible;
  return `
    <div class="page-intro">
      <div><span class="section-kicker">Showrunner plan</span><h2>${esc(plan.title)}</h2><p>Every creative decision remains editable. Saving recompiles the exact shared bible into every image prompt.</p></div>
      <span class="status-pill ${state.project.planApproved ? "approved" : ""}">${state.project.planApproved ? "Plan approved" : "Awaiting approval"}</span>
    </div>
    <div class="plan-summary">
      <div class="panel"><div class="panel-header"><div><h3>Story direction</h3><p>Three visual beats, one dramatic turn</p></div></div><div class="panel-body">
        ${inputField("Title", "title", plan.title, { textarea: false, full: true })}
        ${inputField("Logline", "logline", plan.logline, { full: true })}
      </div></div>
      <div class="panel"><div class="panel-header"><div><h3>Emotional progression</h3><p>Audience experience across the cut</p></div></div><div class="panel-body">
        ${inputField("Intended emotion", "intendedEmotion", plan.intendedEmotion, { full: true })}
        <div class="emotion-arc"><span>SETUP</span><i></i><span>ESCALATE</span><i></i><span>REVEAL</span></div>
      </div></div>
    </div>
    <div class="plan-sections">
      <details class="collapsible" open><summary>Narrative structure <span class="section-kicker">6-SHOT ARC</span></summary><div class="collapsible-content"><div class="field-grid three">
        ${inputField("Beginning", "narrative.setup", plan.narrative.setup)}
        ${inputField("Escalation", "narrative.escalation", plan.narrative.escalation)}
        ${inputField("Final reveal", "narrative.resolution", plan.narrative.resolution)}
      </div></div></details>
      <details class="collapsible" open><summary>Immutable visual bible <span class="section-kicker">SHARED VERBATIM</span></summary><div class="collapsible-content"><div class="bible-grid">
        ${inputField("Character identity", "visualBible.characterIdentity", bible.characterIdentity)}
        ${inputField("Face and hair", "visualBible.faceAndHair", bible.faceAndHair)}
        ${inputField("Wardrobe", "visualBible.wardrobe", bible.wardrobe)}
        ${inputField("Important prop", "visualBible.importantProp", bible.importantProp)}
        ${inputField("Environment", "visualBible.environment", bible.environment)}
        ${inputField("Time of day", "visualBible.timeOfDay", bible.timeOfDay)}
        ${inputField("Lighting direction", "visualBible.lighting", bible.lighting)}
        ${inputField("Colour palette", "visualBible.palette", bible.palette)}
        ${inputField("Camera language", "visualBible.cameraLanguage", bible.cameraLanguage)}
        ${inputField("Texture / visual medium", "visualBible.visualStyle", bible.visualStyle)}
        ${inputField("Negative constraints", "visualBible.negativePrompt", bible.negativePrompt, { full: true })}
      </div></div></details>
      <details class="collapsible" open><summary>Shot list <span class="section-kicker">${plan.shots.length} CONTROLLED SHOTS</span></summary><div class="collapsible-content shot-plan-list">${plan.shots.map(shotEditor).join("")}</div></details>
    </div>
    <div class="checkpoint">
      <div><h3>Human approval gate 01</h3><p>Save the plan, then approve ${plan.shots.length} paid image calls. Videos will not start automatically.</p></div>
      <div class="button-group"><button class="btn" data-action="save-plan">Save edits</button><button class="btn primary" data-action="approve-plan">Approve Plan & Generate Storyboard · ${plan.shots.length} image calls →</button></div>
    </div>`;
}

function jobPill(job, approved = false) {
  if (approved) return `<span class="status-pill approved">Approved</span>`;
  const status = job?.status || "NOT STARTED";
  return `<span class="status-pill ${status.toLowerCase()}">${esc(status.replaceAll("_", " "))}</span>`;
}

function renderConsistency(report) {
  if (!report) return "";
  const score = (value) => value == null ? "—" : `${Math.round(value * 100)}%`;
  return `<div class="report-strip">
    <div class="report-score"><span>Character</span><strong>${score(report.characterConsistencyScore)}</strong></div>
    <div class="report-score"><span>Environment</span><strong>${score(report.environmentConsistencyScore)}</strong></div>
    <div class="report-score"><span>Palette</span><strong>${score(report.paletteConsistencyScore)}</strong></div>
    <div class="report-score"><span>Prop</span><strong>${score(report.propConsistencyScore)}</strong></div>
    <div class="report-differences"><strong>Visible differences:</strong> ${(report.visibleDifferences || []).map(esc).join(" · ") || "None reported"}</div>
  </div>`;
}

function storyboardCard(shot) {
  const image = asset(shot, "image");
  const job = latestJob("image", shot.id);
  const busy = job && ACTIVE_JOBS.has(job.status);
  const failed = job?.status === "FAILED";
  const visual = image
    ? `<img src="${esc(image.localUrl)}" alt="Storyboard ${esc(shot.id)}" />`
    : `<div class="skeleton"></div>${busy ? `<div class="shot-overlay"><div><div class="spinner"></div><p>${esc(job.status)}</p></div></div>` : ""}`;
  return `<article class="shot-card ${shot.imageApproved ? "approved" : ""} ${failed ? "failed" : ""}">
    <div class="shot-image">${visual}</div>
    <div class="shot-card-head"><div><span class="shot-number">SHOT ${String(shot.order).padStart(2, "0")}</span><h3>${esc(shot.narrativePurpose)}</h3></div>${jobPill(job, shot.imageApproved)}</div>
    <div class="shot-card-body">
      <div class="shot-meta"><div><span>Seed</span><strong>${shot.imageSeed}</strong></div><div><span>Model</span><strong>${esc(state.config.models.image)}</strong></div></div>
      <div class="prompt-preview">${esc(shot.imagePrompt)}</div>
      ${failed ? `<div class="job-error">${esc(job.errorMessage)}</div>` : ""}
      <div class="button-row">
        <button class="btn small ghost" data-action="edit-shot" data-shot="${shot.id}">Edit prompt</button>
        <button class="btn small" data-action="regenerate-image" data-shot="${shot.id}" ${busy ? "disabled" : ""}>Regenerate image</button>
        <button class="btn small primary" data-action="approve-image" data-shot="${shot.id}" ${!image || busy || shot.imageApproved ? "disabled" : ""}>${shot.imageApproved ? "Approved" : "Approve image"}</button>
      </div>
    </div>
  </article>`;
}

function renderStoryboard() {
  if (!state.project?.plan) return emptyState("No storyboard plan", "Generate a plan first.", "concept");
  const approved = state.project.shots.filter((shot) => shot.imageApproved).length;
  const allReady = approved === state.project.shots.length;
  const report = currentReport("storyboard");
  return `
    <div class="page-intro"><div><span class="section-kicker">Storyboard review</span><h2>Freeze the visual world.</h2><p>Approve each keyframe before any animation spend. Regeneration is always a deliberate user action.</p></div><span class="status-pill ${allReady ? "approved" : ""}">${approved} / ${state.project.shots.length} approved</span></div>
    ${renderConsistency(report)}
    <div class="storyboard-grid">${state.project.shots.map(storyboardCard).join("")}</div>
    <div class="checkpoint"><div><h3>Human approval gate 02</h3><p>${allReady ? "All keyframes are locked. Wan will animate these exact first frames." : `Review identity, wardrobe, prop, lighting, and room geometry in all ${state.project.shots.length} frames.`}</p></div><div class="button-group"><button class="btn" data-action="check-consistency" ${state.project.shots.some((shot) => !asset(shot, "image")) ? "disabled" : ""}>Run consistency check</button><button class="btn primary" data-action="generate-videos" ${allReady ? "" : "disabled"}>Generate Videos · ${state.project.shots.length} × ${state.project.shots[0]?.durationSeconds || 5}s clips →</button></div></div>`;
}

function jobProgress(job) {
  const steps = ["QUEUED", "GENERATING", "POLLING", "DOWNLOADING", "VERIFYING", "COMPLETED"];
  const index = job ? steps.indexOf(job.status) : -1;
  return `<div class="progress-track">${steps.map((step, i) => `<span class="progress-node ${i < index || job?.status === "COMPLETED" ? "done" : i === index ? "active" : ""}" title="${step}"></span>`).join("")}</div>`;
}

function productionCard(shot) {
  const image = asset(shot, "image");
  const video = asset(shot, "video");
  const job = latestJob("video", shot.id);
  const failed = job?.status === "FAILED";
  const tech = video?.metadata?.technical;
  return `<article class="shot-card ${failed ? "failed" : ""}">
    <div class="shot-image">${video ? `<video controls preload="metadata" poster="${esc(image?.localUrl || "")}" src="${esc(video.localUrl)}"></video>` : image ? `<img src="${esc(image.localUrl)}" alt="Source keyframe ${shot.id}" />${job && ACTIVE_JOBS.has(job.status) ? `<div class="shot-overlay"><div><div class="spinner"></div><p>${esc(job.status)}</p></div></div>` : ""}` : `<div class="skeleton"></div>`}</div>
    <div class="shot-card-head"><div><span class="shot-number">SHOT ${String(shot.order).padStart(2, "0")}</span><h3>${esc(shot.narrativePurpose)}</h3></div>${jobPill(job)}</div>
    <div class="shot-card-body">
      ${jobProgress(job)}
      <p class="prompt-preview">${esc(shot.motionPrompt)}</p>
      <div class="shot-meta"><div><span>Duration</span><strong>${shot.durationSeconds}s</strong></div><div><span>Seed / resolution</span><strong>${shot.videoSeed} · 720P</strong></div></div>
      ${tech ? `<div class="tech-list"><span>H.264 <b>${tech.checks.codecH264 ? "PASS" : "FAIL"}</b></span><span>30 fps <b>${tech.checks.fpsAbout30 ? "PASS" : "FAIL"}</b></span><span>720P <b>${tech.checks.resolution720p ? "PASS" : "FAIL"}</b></span><span>Duration <b>${Number(tech.durationSeconds).toFixed(2)}s</b></span></div>` : ""}
      ${failed ? `<div class="job-error">${esc(job.errorMessage)}</div><button class="btn small danger" data-action="retry-video" data-shot="${shot.id}">Retry failed shot</button>` : ""}
    </div>
  </article>`;
}

function renderProduction() {
  if (!state.project?.shots?.length) return emptyState("Nothing in production", "Approve a storyboard first.", "storyboard");
  const videos = state.project.shots.filter((shot) => asset(shot, "video")).length;
  const complete = videos === state.project.shots.length;
  return `
    <div class="page-intro"><div><span class="section-kicker">Wan production</span><h2>Animate only what was approved.</h2><p>Each task persists independently. A failed shot can be retried without touching the successful keyframes or clips.</p></div><span class="status-pill ${complete ? "completed" : "generating"}">${videos} / ${state.project.shots.length} complete</span></div>
    <div class="production-grid">${state.project.shots.map(productionCard).join("")}</div>
    <div class="checkpoint"><div><h3>Individual shots remain canonical</h3><p>${complete ? "All clips passed technical verification. Assembly is optional and never hides individual outputs." : "Generation continues in the background and survives browser refresh."}</p></div><button class="btn primary" data-action="assemble" ${complete ? "" : "disabled"}>Assemble Final Preview →</button></div>`;
}

function elapsedProduction() {
  const jobs = state.project?.jobs || [];
  const starts = jobs.map((job) => job.startedAt).filter(Boolean).map(Date.parse);
  const ends = jobs.map((job) => job.completedAt).filter(Boolean).map(Date.parse);
  if (!starts.length || !ends.length) return "—";
  const seconds = Math.round((Math.max(...ends) - Math.min(...starts)) / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function generationLedger() {
  const jobs = state.project?.jobs || [];
  return `<div class="panel ledger-panel">
    <div class="panel-header"><div><h3>Generation ledger</h3><p>Exact paid-work boundary and reproducibility metadata</p></div></div>
    <div class="ledger-list">
      ${jobs.map((job) => `<div class="ledger-row">
        <span>${esc((job.shotId || "final").toUpperCase())}</span>
        <strong>${esc(job.kind.toUpperCase())}</strong>
        <code>${esc(job.model)}</code>
        <code>${job.seed ?? "—"}</code>
        <code title="${esc(job.promptHash || "")}">${job.promptHash ? esc(job.promptHash.slice(0, 10)) + "…" : "—"}</code>
        <em>${job.estimatedCost == null ? "local" : `${Number(job.estimatedCost).toFixed(3)} CNY`}</em>
        <b class="${job.status === "COMPLETED" ? "pass" : ""}">${esc(job.status)}</b>
      </div>`).join("")}
    </div>
  </div>`;
}

function renderFinal() {
  if (!state.project) return emptyState("No final cut", "Create a production first.", "concept");
  const finalAsset = state.project.finalAssets?.[0];
  const videos = state.project.shots.map((shot) => asset(shot, "video")).filter(Boolean);
  const retries = state.project.jobs.reduce((total, job) => total + (job.retryCount || 0), 0);
  const downloads = [
    ...state.project.shots.flatMap((shot) => shot.assets || []),
    ...(state.project.finalAssets || []),
  ];
  const player = state.finalMode === "final"
    ? finalAsset
      ? `<div class="final-player"><video controls preload="metadata" src="${esc(finalAsset.localUrl)}"></video></div>`
      : `<div class="empty-state"><div><h3>Final assembly not available</h3><p>Individual shots remain accessible. Assemble when all clips are complete.</p>${videos.length === state.project.shots.length ? `<button class="btn primary" data-action="assemble">Assemble with FFmpeg</button>` : ""}</div></div>`
    : `<div class="individual-strip">${videos.map((video, i) => `<video controls preload="metadata" src="${esc(video.localUrl)}" aria-label="Shot ${i + 1}"></video>`).join("")}</div>`;
  return `
    <div class="page-intro"><div><span class="section-kicker">Final cut</span><h2>${esc(state.project.title)}</h2><p>A deliberately simple editorial preview. Original shots are preserved regardless of assembly status.</p></div>${jobPill(latestJob("assembly"))}</div>
    <div class="view-toggle"><button class="${state.finalMode === "final" ? "active" : ""}" data-action="final-mode" data-mode="final">Assembled preview</button><button class="${state.finalMode === "individual" ? "active" : ""}" data-action="final-mode" data-mode="individual">Individual shots</button></div>
    <div class="final-layout">
      <div>${player}${generationLedger()}</div>
      <aside class="panel"><div class="panel-header"><div><h3>Production report</h3><p>Inspectable generation record</p></div></div><div class="panel-body">
        <div class="summary-list">
          <div class="summary-row"><span>Models</span><strong>${esc(state.config.models.image)}<br />${esc(state.config.models.video)}</strong></div>
          <div class="summary-row"><span>Provider</span><strong>${esc(state.project.provider.toUpperCase())}</strong></div>
          <div class="summary-row"><span>Shots completed</span><strong>${videos.length} / ${state.project.shots.length}</strong></div>
          <div class="summary-row"><span>Estimated budget</span><strong>${formatCny(state.project.budget?.estimatedCostCny)}</strong></div>
          <div class="summary-row"><span>Retries</span><strong>${retries}</strong></div>
          <div class="summary-row"><span>Generation time</span><strong>${elapsedProduction()}</strong></div>
          <div class="summary-row"><span>Consistency method</span><strong>Approved first-frame lock</strong></div>
        </div>
        <div class="download-list">${downloads.map((item) => `<a class="download-link" href="${esc(item.localUrl)}" download><span>${item.kind.toUpperCase()} ${item.shotId ? item.shotId.replace("shot-", "") : "CUT"}</span><span>DOWNLOAD ↓</span></a>`).join("") || `<p style="color:var(--muted)">No assets yet.</p>`}</div>
      </div></aside>
    </div>`;
}

function emptyState(title, detail, target) {
  return `<div class="empty-state"><div><h3>${esc(title)}</h3><p>${esc(detail)}</p><button class="btn" data-action="go-view" data-view="${target}">Go back</button></div></div>`;
}

function setByPath(object, path, value) {
  const parts = path.split(".");
  let current = object;
  while (parts.length > 1) current = current[parts.shift()];
  current[parts[0]] = value;
}

function collectPlan() {
  const plan = structuredClone(state.project.plan);
  document.querySelectorAll("[data-plan]").forEach((element) => {
    setByPath(plan, element.dataset.plan, element.value.trim());
  });
  document.querySelectorAll("[data-shot-editor]").forEach((card) => {
    const shot = plan.shots.find((item) => item.id === card.dataset.shotEditor);
    card.querySelectorAll("[data-shot-key]").forEach((element) => {
      shot[element.dataset.shotKey] = element.dataset.shotKey === "durationSeconds"
        ? Number(element.value)
        : element.value.trim();
    });
  });
  return plan;
}

async function savePlan() {
  const plan = collectPlan();
  state.project = await api(`/api/projects/${state.project.id}/plan`, {
    method: "PATCH",
    body: JSON.stringify(plan),
  });
  localStorage.setItem("videoforge-project", state.project.id);
  notify("Plan saved and prompts safely recompiled.");
  render();
}

async function paidBody(actionLabel) {
  if (!state.config.realMode) return { confirmPaidCalls: false };
  const budget = formatCny(state.project?.budget?.estimatedCostCny);
  const confirmed = window.confirm(`${actionLabel}\n\nThis starts paid Qwen Cloud media calls. Project estimate: ${budget}. Continue?`);
  if (!confirmed) throw new Error("Paid generation cancelled by user.");
  return { confirmPaidCalls: true };
}

async function runAction(button, callback) {
  if (state.busy) return;
  state.busy = true;
  const original = button?.textContent;
  if (button) { button.disabled = true; button.textContent = "Working…"; }
  try {
    await callback();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    state.busy = false;
    if (button && button.isConnected) { button.disabled = false; button.textContent = original; }
  }
}

async function handleSubmit(event) {
  if (event.target.id !== "create-project-form") return;
  event.preventDefault();
  const submitter = event.submitter;
  await runAction(submitter, async () => {
    const data = Object.fromEntries(new FormData(event.target));
    data.targetDurationSeconds = Number(data.targetDurationSeconds);
    data.shotCount = 6;
    state.project = await api("/api/projects", { method: "POST", body: JSON.stringify(data) });
    localStorage.setItem("videoforge-project", state.project.id);
    state.project = await api(`/api/projects/${state.project.id}/plan`, { method: "POST", body: "{}" });
    state.view = "plan";
    notify("Production plan ready. No media credits spent.");
    render();
  });
}

async function handleAction(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const projectId = state.project?.id;
  if (action === "go-view") { state.view = button.dataset.view; return render(); }
  if (action === "resume-project") {
    state.view = suggestedView(state.project);
    return render();
  }
  if (action === "new-production") {
    state.project = null;
    state.view = "concept";
    localStorage.removeItem("videoforge-project");
    return render();
  }
  if (action === "load-demo") return runAction(button, async () => {
    state.project = await api("/api/demo-project", { method: "POST", body: "{}" });
    localStorage.setItem("videoforge-project", state.project.id);
    state.view = "plan";
    notify("Polished demo plan loaded in mock-safe mode.");
    render();
  });
  if (action === "save-plan") return runAction(button, savePlan);
  if (action === "approve-plan") return runAction(button, async () => {
    await savePlan();
    state.project = await api(`/api/projects/${projectId}/plan/approve`, { method: "POST", body: "{}" });
    const confirmation = await paidBody(`Generate ${state.project.shots.length} storyboard keyframes?`);
    await api(`/api/projects/${projectId}/storyboard`, { method: "POST", body: JSON.stringify(confirmation) });
    state.view = "storyboard";
    await refreshProject(true);
    notify("Storyboard generation started. Videos remain gated.");
  });
  if (action === "edit-shot") {
    state.view = "plan";
    render();
    setTimeout(() => document.querySelector(`[data-shot-editor="${button.dataset.shot}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
    return;
  }
  if (action === "regenerate-image") return runAction(button, async () => {
    const confirmation = await paidBody(`Regenerate ${button.dataset.shot} keyframe?`);
    await api(`/api/shots/${button.dataset.shot}/image/regenerate?project_id=${projectId}`, { method: "POST", body: JSON.stringify(confirmation) });
    await refreshProject(true);
    notify("Image regeneration queued as an explicit creative retry.");
  });
  if (action === "approve-image") return runAction(button, async () => {
    state.project = await api(`/api/shots/${button.dataset.shot}/image/approve?project_id=${projectId}`, { method: "POST", body: "{}" });
    notify(`${button.dataset.shot} approved.`);
    render();
  });
  if (action === "check-consistency") return runAction(button, async () => {
    await api(`/api/projects/${projectId}/consistency-check`, { method: "POST", body: "{}" });
    await refreshProject(true);
    notify("Storyboard consistency report complete. No automatic regeneration was triggered.");
  });
  if (action === "generate-videos") return runAction(button, async () => {
    const confirmation = await paidBody(`Generate ${state.project.shots.length} Wan 2.7 clips from the approved keyframes?`);
    await api(`/api/projects/${projectId}/videos`, { method: "POST", body: JSON.stringify(confirmation) });
    state.view = "production";
    await refreshProject(true);
    notify("All video tasks submitted with bounded concurrency.");
  });
  if (action === "retry-video") return runAction(button, async () => {
    const confirmation = await paidBody(`Retry failed ${button.dataset.shot} video?`);
    await api(`/api/shots/${button.dataset.shot}/video/retry?project_id=${projectId}`, { method: "POST", body: JSON.stringify(confirmation) });
    await refreshProject(true);
    notify("Independent shot retry queued.");
  });
  if (action === "assemble") return runAction(button, async () => {
    await api(`/api/projects/${projectId}/assemble`, { method: "POST", body: "{}" });
    state.view = "final";
    await refreshProject(true);
    notify("FFmpeg final preview assembly started.");
  });
  if (action === "final-mode") {
    state.finalMode = button.dataset.mode;
    return render();
  }
}

function suggestedView(project) {
  const rank = STAGE_RANK[project.stage] ?? 0;
  if (rank >= 6) return "final";
  if (rank >= 5) return "production";
  if (rank >= 3) return "storyboard";
  if (project.plan) return "plan";
  return "concept";
}

async function refreshProject(forceRender = false) {
  if (!state.project?.id) return;
  try {
    const updated = await api(`/api/projects/${state.project.id}`);
    const oldSignature = JSON.stringify({ stage: state.project.stage, jobs: state.project.jobs.map((job) => [job.id, job.status]), approvals: state.project.shots.map((shot) => shot.imageApproved), finals: state.project.finalAssets?.length });
    const newSignature = JSON.stringify({ stage: updated.stage, jobs: updated.jobs.map((job) => [job.id, job.status]), approvals: updated.shots.map((shot) => shot.imageApproved), finals: updated.finalAssets?.length });
    state.project = updated;
    if (forceRender || oldSignature !== newSignature) render();
    else updateChrome();
  } catch (error) {
    if (error.status === 404) {
      localStorage.removeItem("videoforge-project");
      state.project = null;
      state.view = "concept";
      render();
    }
  }
}

function schedulePolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
  if (!state.project) return;
  const hasActive = state.project.jobs.some((job) => ACTIVE_JOBS.has(job.status));
  if (hasActive) state.pollTimer = setInterval(() => refreshProject(), 700);
}

document.querySelectorAll(".stage-link").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.disabled) return;
    state.view = button.dataset.view;
    render();
  });
});

async function init() {
  try {
    state.config = await api("/api/config");
    const projectId = localStorage.getItem("videoforge-project");
    if (projectId) {
      try {
        state.project = await api(`/api/projects/${projectId}`);
        state.view = suggestedView(state.project);
      } catch (_) {
        localStorage.removeItem("videoforge-project");
      }
    }
    render();
  } catch (error) {
    viewRoot.innerHTML = `<div class="empty-state"><div><h3>VideoForge could not start</h3><p>${esc(error.message)}</p></div></div>`;
    notify(error.message, "error");
  }
}

init();
