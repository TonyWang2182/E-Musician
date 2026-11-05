"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const embedded = new URLSearchParams(window.location.search).get("embedded") === "1";
  document.body.classList.toggle("embedded", embedded);
  $("collapse").hidden = !embedded;
  $("standalone-footer").hidden = embedded;
  $("project-details").open = !embedded && window.innerWidth >= 920;
  if (embedded) text("scope-note", "上下文来自当前 DAW 工程。收起侧栏会保留输入内容，不会关闭工程。");
  const sessionTokenKey = "e-musician-session-token";
  let token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
  try {
    if (token) sessionStorage.setItem(sessionTokenKey, token);
    else token = sessionStorage.getItem(sessionTokenKey) || "";
  } catch (_) { /* A restricted browser can still use the in-memory launch token. */ }
  if (window.location.hash) history.replaceState(null, "", window.location.pathname + window.location.search);
  let state = null, inFlight = false, mutating = false, online = false, stopped = false, timer = null;
  let connectionError = false;
  let messageSignature = "", trackSignature = "", localNotice = "";
  let capabilitySignature = "", analysisPreviewSignature = "";
  let providerSignature = "", providers = [], settingsDirty = false, formProviderId = null;
  let shownPlanId = null, followResponse = false, submittedScope = null;
  let notePreviewSignature = "", notePreviewPlanId = null, notePreviewNotes = [], notePreviewPage = 0;
  const notePreviewPageSize = 50;
  let nativeVisible = true;
  const busyPhases = new Set(["planning", "paused", "applying"]);
  const phaseText = {idle: "准备就绪", planning: "正在生成方案", paused: "已暂停", ready: "等待你确认", applying: "正在应用并检查", done: "已完成", error: "需要处理", cancelled: "已停止"};
  const executionStages = ["preflight", "submitting", "verifying", "done"];
  const stageText = {preflight: "正在检查方案", submitting: "正在提交修改", verifying: "正在核对结果", done: "已完成核对"};
  function text(id, value) { $(id).textContent = value == null ? "" : String(value); }
  function element(tag, value, className) {
    const node = document.createElement(tag);
    if (value != null) node.textContent = String(value);
    if (className) node.className = className;
    return node;
  }
  function notice(value) { text("notice", value || ""); $("notice").hidden = !value; }
  function readablePlan(plan) {
    return Array.isArray(plan?.changes) && plan.changes.length > 0
      && plan.changes.every((change) => typeof change === "string" && change.trim());
  }
  function changeItem(change) {
    const row = element("li");
    if (typeof change !== "string") { row.textContent = "此项缺少可读说明，请放弃并重新生成方案。"; return row; }
    // Highlight the action word without inferring which objects will be deleted.
    const pattern = /删除|移除|\b(?:delete|remove)\b/gi;
    let offset = 0;
    for (const match of change.matchAll(pattern)) {
      row.append(document.createTextNode(change.slice(offset, match.index)), element("strong", match[0], "change-action"));
      offset = match.index + match[0].length;
    }
    row.append(document.createTextNode(change.slice(offset)));
    return row;
  }
  function renderNotePreviewPage() {
    if (!$("note-previews").open || !notePreviewNotes.length) return;
    const start = notePreviewPage * notePreviewPageSize;
    const end = Math.min(start + notePreviewPageSize, notePreviewNotes.length);
    const content = document.createDocumentFragment();
    let group = null, list = null;
    const number = (value) => typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
    for (const item of notePreviewNotes.slice(start, end)) {
      if (group !== item.group) {
        group = item.group;
        const section = element("section", null, "note-preview-group");
        section.append(element("h4", item.label));
        list = element("ol", null, "note-preview-list");
        list.start = item.index + 1; section.append(list); content.append(section);
      }
      const row = element("li", null, "note-preview-row"), heading = element("div", null, "note-preview-heading");
      heading.append(element("span", `音符 ${item.index + 1}`), element("strong", `MIDI 音高 ${number(item.note.pitch)}`));
      const values = element("dl");
      for (const [key, label, unit] of [["start_beats", "起点", " 拍"], ["length_beats", "长度", " 拍"], ["velocity", "力度", ""], ["channel", "通道", ""]]) {
        const field = element("div");
        field.append(element("dt", label), element("dd", number(item.note[key]) + unit)); values.append(field);
      }
      row.append(heading, values); list.append(row);
    }
    $("note-preview-rows").replaceChildren(content);
    $("note-preview-pager").hidden = notePreviewNotes.length <= notePreviewPageSize;
    text("note-preview-page", `第 ${start + 1}–${end} 个，共 ${notePreviewNotes.length} 个`);
    $("note-preview-prev").disabled = notePreviewPage === 0;
    $("note-preview-next").disabled = end === notePreviewNotes.length;
  }
  function renderNotePreviews(plan) {
    const signature = JSON.stringify([plan?.id, plan?.note_previews]);
    if (signature === notePreviewSignature) return;
    notePreviewSignature = signature;
    const details = $("note-previews"), retainOpen = details.open && notePreviewPlanId === plan?.id;
    notePreviewPlanId = plan?.id ?? null;
    notePreviewNotes = [];
    for (const [group, preview] of (Array.isArray(plan?.note_previews) ? plan.note_previews : []).entries()) {
      if (!Array.isArray(preview?.notes)) continue;
      const label = typeof preview.label === "string" && preview.label.trim() ? preview.label : "新增音符的片段";
      preview.notes.forEach((note, index) => notePreviewNotes.push({group, label, index, note: note || {}}));
    }
    notePreviewPage = 0;
    details.hidden = !notePreviewNotes.length;
    details.open = retainOpen && notePreviewNotes.length > 0;
    $("note-preview-rows").replaceChildren();
    $("note-preview-pager").hidden = true;
    text("note-preview-summary", `新增音符明细（${notePreviewNotes.length}）`);
    if (details.open) renderNotePreviewPage();
  }
  $("note-previews").addEventListener("toggle", () => {
    if ($("note-previews").open && !$("note-preview-rows").childElementCount) renderNotePreviewPage();
  });
  for (const [id, offset] of [["note-preview-prev", -1], ["note-preview-next", 1]]) $(id).addEventListener("click", () => {
    if ($(id).disabled || !$("note-previews").open) return;
    notePreviewPage = Math.max(0, Math.min(Math.ceil(notePreviewNotes.length / notePreviewPageSize) - 1, notePreviewPage + offset));
    renderNotePreviewPage();
    $("note-preview-rows").scrollIntoView({block: "start"});
  });
  function currentProviderEntry() { return providers.find((entry) => entry.id === $("provider").value); }
  function providerReady(entry) { return entry && (entry.adapter_ready ?? entry.implemented) !== false; }
  function populateProviderFields(entry) {
    if (!entry) return;
    formProviderId = entry.id || $("provider").value;
    $("model").value = entry.model || entry.default_model || "";
    $("base-url").value = entry.base_url || "";
    $("reasoning-setting").hidden = entry.id !== "openai";
    $("reasoning-hint").hidden = entry.id !== "openai";
    $("reasoning-effort").value = entry.reasoning_effort || "medium";
    $("model-options").replaceChildren(...(Array.isArray(entry.models) ? entry.models : []).map((value) => {
      const option = document.createElement("option"); option.value = String(value); return option;
    }));
    text("key-state", entry.configured ? "本机已配置" : "尚未配置");
    text("provider-status", !providerReady(entry) ? "此服务尚未接入，暂不可选择。" : entry.configured ? "已配置本机密钥；模型可用性以实际请求为准。" : "此服务还没有密钥，请展开“连接与密钥”配置。");
    $("connection-settings").open = providerReady(entry) && !entry.configured;
  }
  function renderProviders() {
    providers = Array.isArray(state.providers) && state.providers.length ? state.providers : [{...state.provider, id: state.provider?.id || "kimi", label: state.provider?.label || "Kimi", adapter_ready: true}];
    const active = state.provider || {}, signature = JSON.stringify(providers);
    const selected = settingsDirty ? $("provider").value : active.id || providers[0]?.id;
    if (signature !== providerSignature) {
      providerSignature = signature;
      $("provider").replaceChildren(...providers.map((entry) => {
        const option = document.createElement("option"); option.value = entry.id;
        option.textContent = `${entry.label || entry.id}${!providerReady(entry) ? " · 待接入" : !entry.configured ? " · 未配置" : ""}`;
        option.disabled = !providerReady(entry); return option;
      }));
    }
    if (!settingsDirty) {
      $("provider").value = selected;
      if ($("settings").hidden || formProviderId !== selected) populateProviderFields({...currentProviderEntry(), ...(selected === active.id || !active.id ? active : {})});
    } else if (providers.some((entry) => entry.id === selected)) $("provider").value = selected;
    const label = active.label || providers.find((entry) => entry.id === active.id)?.label || active.id || "Kimi";
    text("current-model", active.model ? `${label} · ${active.model}` : "选择模型");
    $("current-model").title = $("current-model").textContent;
  }
  function scopeContext() {
    const snapshot = state?.snapshot || {}, context = snapshot.selection_context;
    const tracks = Array.isArray(snapshot.tracks) ? snapshot.tracks : [];
    const clips = tracks.flatMap((track) => track.clips || []);
    const pills = [];
    const add = (label) => { const pill = element("span", label, "context-pill"); pill.title = label; pills.push(pill); };
    if ($("scope").value === "project") {
      add("整个工程"); add(`${tracks.length} 条轨道`);
      text("scope-hint", "范围已扩大到整个工程；修改仍需你确认。");
    } else if (context?.notes_truncated) {
      const count = Number(context.note_count);
      add(Number.isSafeInteger(count) && count > 0 ? `${count} 个音符 · 超出上限` : "音符选择超出上限");
      text("scope-hint", "单次选择最多 2000 个音符；请缩小选区后重试。");
    } else if (!context?.available) {
      add("完整选区不可用");
      text("scope-hint", "当前 DAW 未提供完整选区；可先提问，或明确切换到整个工程。");
    } else {
      const trackIds = Array.isArray(context.track_ids) ? context.track_ids : [];
      const clipIds = Array.isArray(context.clip_ids) ? context.clip_ids : [];
      const notes = Array.isArray(context.note_ids) ? context.note_ids : [];
      if (trackIds.length) add(trackIds.length === 1 ? `轨道：${tracks.find((t) => t.id === trackIds[0])?.name || trackIds[0]}` : `${trackIds.length} 条轨道`);
      const focusedTrack = !trackIds.length && context.focus === "track" && context.active_track_id;
      if (focusedTrack) add(`轨道：${tracks.find((t) => t.id === focusedTrack)?.name || focusedTrack}`);
      if (clipIds.length) add(clipIds.length === 1 ? `片段：${clips.find((c) => c.id === clipIds[0])?.name || clipIds[0]}` : `${clipIds.length} 个片段`);
      if (context.note_clip_id) add(notes.length ? `${notes.length} 个音符` : "未选中音符");
      const range = context.time_range;
      const hasRange = range?.active && Number.isFinite(range.start_seconds) && Number.isFinite(range.end_seconds);
      if (hasRange) add(`选区 ${Number(range.start_seconds.toFixed(3))}–${Number(range.end_seconds.toFixed(3))} 秒`);
      const hasSelection = trackIds.length || focusedTrack || clipIds.length || notes.length || hasRange;
      if (!pills.length) add("尚未选择对象");
      text("scope-hint", hasSelection ? "只针对当前选择；发送后改变选区，需要重新生成。" : "先在 DAW 选择对象，或明确切换到整个工程。");
    }
    $("context-pills").replaceChildren(...pills);
  }
  function armPoll() {
    clearTimeout(timer);
    if (!stopped && token && nativeVisible) timer = setTimeout(refresh, busyPhases.has(state?.phase) ? 1000 : 2500);
  }
  async function request(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {method: body === undefined ? "GET" : "POST", headers: {"X-Agent-Token": token, ...(body === undefined ? {} : {"Content-Type": "application/json"})}, body: body === undefined ? undefined : JSON.stringify(body), credentials: "omit", cache: "no-store", redirect: "error", signal: controller.signal});
      const data = await response.json();
      if (!response.ok || data.error && !data.phase) throw new Error(data.error || `请求失败（HTTP ${response.status}）`);
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("连接超时。先刷新状态确认结果，再决定是否重试。");
      if (error instanceof TypeError) throw new Error("无法连接本机助手。请确认启动窗口仍在运行，再点击刷新。");
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function busy() { return mutating || state?.busy === true || busyPhases.has(state?.phase); }
  function renderProgress(working) {
    const phase = state?.phase, progress = state?.progress || {}, stage = progress.stage;
    const activeIndex = executionStages.indexOf(stage);
    const showStages = (phase === "applying" && activeIndex >= 0)
      || (phase === "done" && stage === "done" && Number.isInteger(progress.total) && progress.total > 0);
    $("execution-stages").hidden = !showStages;
    for (const item of $("execution-stages").children) {
      const index = executionStages.indexOf(item.dataset.stage);
      const current = showStages && index === activeIndex;
      item.dataset.status = showStages && (stage === "done" || index < activeIndex) ? "complete" : "pending";
      if (current) item.setAttribute("aria-current", "step"); else item.removeAttribute("aria-current");
    }
    if (state) text("phase", phase === "applying" && stageText[stage] ? stageText[stage] : phaseText[phase] || "处理中");
    const fallback = phase === "paused" ? "已在步骤之间暂停。继续后再进行下一步。"
      : state?.pause_requested ? "当前步骤结束后暂停，不会继续下一步。"
      : working ? phase === "applying" ? "正在应用整份方案并核对结果。"
      : phase === "cancelled" ? "正在结束当前请求，完成后可以继续。" : "正在读取工程并生成方案，尚未修改工程。" : "";
    text("busy-detail", typeof progress.label === "string" && progress.label.trim() ? progress.label
      : typeof state?.detail === "string" && state.detail ? state.detail : fallback);
    $("commit-hint").hidden = phase !== "applying";
    $("task-progress").hidden = !working && !["ready", "error", "cancelled", "done", "paused"].includes(phase);
    $("task-progress").dataset.busy = String(working);
    $("task-progress").dataset.paused = String(phase === "paused");
  }
  function updateControls() {
    const working = busy(), connected = !!state?.control?.connected && online;
    for (const button of $("capability-list").querySelectorAll("button[data-available]")) button.disabled = working || !connected || button.dataset.available !== "true";
    $("submit").disabled = working || inFlight || !connected || !state?.provider?.configured || !$("prompt").value.trim();
    $("prompt").disabled = working;
    $("apply").disabled = working || inFlight || !connected || state?.phase !== "ready" || !state?.plan?.id || !readablePlan(state.plan);
    $("discard").disabled = working || inFlight || !online;
    $("undo").disabled = working || inFlight || !connected || !state?.can_undo;
    $("refresh").disabled = inFlight;
    $("settings-save").disabled = working || inFlight || !online || !providerReady(currentProviderEntry());
    $("scope").disabled = working;
    $("cancel-work").hidden = !["planning", "paused"].includes(state?.phase);
    $("cancel-work").disabled = inFlight || state?.phase === "applying" || !online;
    text("cancel-work", "停止");
    const canPause = state?.phase === "paused" || Object.prototype.hasOwnProperty.call(state || {}, "pause_requested");
    $("pause-work").hidden = !canPause || !["planning", "paused"].includes(state?.phase);
    $("pause-work").disabled = !canPause || inFlight || !online || !["planning", "paused"].includes(state?.phase)
      || (state?.phase === "planning" && state?.pause_requested === true);
    text("pause-work", state?.phase === "paused" ? "继续" : state?.pause_requested ? "等待暂停" : "暂停");
    $("shutdown").disabled = working || inFlight || !online;
    text("submit", state?.phase === "planning" ? "生成中…" : "发送");
    document.querySelectorAll("[data-prompt]").forEach((button) => { button.disabled = working; });
    renderProgress(working);
  }
  function renderSnapshot(snapshot) {
    text("project-title", `${snapshot.name || "未命名工程"}${snapshot.dirty ? " · 未保存" : ""}`);
    const bpm = snapshot.bpm ?? snapshot.tempo_bpm;
    text("tempo", typeof bpm === "number" ? `${Number(bpm.toFixed(3))} BPM` : "—");
    text("meter", snapshot.numerator && snapshot.denominator ? `${snapshot.numerator}/${snapshot.denominator}` : "—");
    text("revision", snapshot.revision ?? "—");
    const tracks = Array.isArray(snapshot.tracks) ? snapshot.tracks : [];
    const selectedTrack = tracks.find((track) => track.id === snapshot.selected_track_id);
    const selectedClip = tracks.flatMap((track) => track.clips || []).find((clip) => clip.id === snapshot.selected_clip_id);
    text("selection-text", selectedClip ? `${selectedTrack?.name || "片段"} / ${selectedClip.name || selectedClip.id}` : selectedTrack ? selectedTrack.name : "未选择轨道或片段");
    text("track-count", tracks.length);
    const signature = JSON.stringify([tracks.map((track) => [track.id, track.name, track.kind, track.clip_count ?? track.clips?.length ?? 0]), snapshot.selected_track_id]);
    if (signature !== trackSignature) {
      trackSignature = signature;
      const list = $("tracks"); list.replaceChildren();
      if (!tracks.length) list.append(element("li", "工程还是空的。可以让助手新建轨道，也可在 DAW 中导入素材。", "empty"));
      tracks.forEach((track) => {
        const row = element("li", null, track.id === snapshot.selected_track_id ? "selected" : "");
        row.append(element("div", track.name || "未命名轨道", "track-name"));
        const kind = {instrument: "MIDI", audio: "音频", bus: "总线"}[track.kind] || "轨道";
        row.append(element("div", `${kind} · ${track.clip_count ?? track.clips?.length ?? 0} 个片段`, "track-meta")); list.append(row);
      });
    }
    scopeContext();
  }
  function renderMessages(messages) {
    const items = Array.isArray(messages) ? messages : [], signature = JSON.stringify(items);
    if (signature === messageSignature) return;
    messageSignature = signature; $("conversation-empty").hidden = items.length > 0;
    const list = $("messages"); list.replaceChildren();
    items.forEach((message) => {
      const isUser = message.role === "user", article = element("article", null, `message ${isUser ? "user" : "assistant"}`);
      article.append(element("div", isUser ? "你" : "编曲助手", "message-label"));
      article.append(element("div", message.content || "", "message-body")); list.append(article);
    });
  }
  function render(next) {
    const scroll = $("transcript");
    const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 60;
    const oldMessages = messageSignature;
    state = next;
    const connected = !!state.control?.connected;
    text("connection", online ? connected ? "DAW 已连接" : "DAW 未连接" : "连接中断");
    $("connection").classList.toggle("connected", online && connected);
    renderSnapshot(state.snapshot || {}); renderMessages(state.messages);
    renderCapabilities(state.capability_groups);
    const plan = state.plan, visible = !!plan && ["ready", "applying"].includes(state.phase);
    $("plan").hidden = !visible;
    if (visible) {
      text("plan-summary", plan.summary || "请核对以下修改。");
      const frozenScope = plan.scope;
      const revision = plan.revision ?? plan.expected_revision ?? frozenScope?.project_revision;
      text("plan-revision", revision == null ? "" : `基于修订 ${revision}`);
      const scope = (frozenScope && typeof frozenScope === "object" ? frozenScope.mode : frozenScope) || submittedScope;
      text("plan-scope", scope === "project" ? "本次范围：整个工程" : scope === "selection" ? "本次范围：发送时的选择" : scope === "clip" ? "本次范围：整个片段" : "范围以提交时的选择为准");
      const steps = Array.isArray(plan.steps) ? plan.steps : [];
      const hasSteps = steps.length > 0 && steps.every((step) => typeof step?.label === "string" && step.label.trim());
      $("plan-sequence").hidden = !hasSteps;
      $("plan-steps").replaceChildren(...(hasSteps ? steps.map((step) => element("li", step.label)) : []));
      $("changes").replaceChildren(...(Array.isArray(plan.changes) ? plan.changes : []).map(changeItem));
    }
    renderNotePreviews(visible ? plan : null);
    renderAnalysisPreview(visible ? plan?.analysis : null);
    $("result").hidden = !state.last_result; text("result-text", state.last_result || "");
    const usage = state.usage || {}, format = (value) => Number(value || 0).toLocaleString("zh-CN");
    text("usage", `${format(usage.calls)} 次请求 · 输入 ${format(usage.prompt_tokens)} / 输出 ${format(usage.completion_tokens)} tokens`);
    renderProviders();
    notice(localNotice || state.error || (visible && !readablePlan(plan) ? "方案说明不完整，请放弃并重新生成。" : "")
      || (!state.provider?.configured ? "先展开顶部模型设置，配置所选服务的密钥。" : "")); updateControls();
    if (visible && plan.id !== shownPlanId) {
      shownPlanId = plan.id;
      requestAnimationFrame(() => $("plan").scrollIntoView({block: "start"}));
      followResponse = false;
    } else if (oldMessages !== messageSignature && (nearBottom || followResponse)) {
      requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
    }
  }
  function renderCapabilities(groups) {
    if (!Array.isArray(groups)) return;
    const signature = JSON.stringify(groups);
    if (signature === capabilitySignature) return;
    capabilitySignature = signature;
    const opened = new Set([...$("capability-list").querySelectorAll("details[open]")].map((row) => row.dataset.capability));
    const rows = groups.map((group) => {
      const row = element("details", null, "capability-row"); row.dataset.capability = group.id;
      row.open = opened.has(group.id);
      const heading = element("summary");
      heading.append(element("span", group.label), element("span", group.status_label, "capability-status"));
      const detail = element("p", group.detail);
      const example = element("button", group.example); example.type = "button";
      example.disabled = !group.enabled || busy();
      example.dataset.available = group.enabled ? "true" : "false";
      example.addEventListener("click", () => { $("prompt").value = group.example; $("prompt").focus(); updateControls(); });
      row.append(heading, detail, example); return row;
    });
    $("capability-list").replaceChildren(...rows);
  }
  function renderAnalysisPreview(candidate) {
    $("analysis-preview").hidden = !candidate;
    const signature = JSON.stringify(candidate);
    if (signature === analysisPreviewSignature) return;
    analysisPreviewSignature = signature;
    if (!candidate) return;
    const names = {separate: "分离候选", transcribe: "MIDI 候选", chords: "和弦候选"};
    text("analysis-preview-title", `${names[candidate.kind] || "分析候选"} · ${candidate.total} 项`);
    const model = candidate.model || {}, source = candidate.source || {};
    text("analysis-preview-info", `${model.id || model.model_id || "本机分析"} ${model.version || ""} · ${Number(source.duration_seconds || 0).toFixed(2)} 秒。尚未导入工程。`);
    const seconds = (value) => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(3)}s` : "—";
    const rows = (candidate.items || []).map((item) => {
      const label = candidate.kind === "separate" ? `${item.name} · ${seconds(item.duration_seconds)} · ${item.channels} 声道`
        : candidate.kind === "transcribe" ? `MIDI ${item.pitch} · ${seconds(item.start_seconds)} 起 · 长 ${seconds(item.duration_seconds)} · 力度 ${item.velocity}`
        : `${item.label} · ${seconds(item.start_seconds)}–${seconds(item.end_seconds)}${item.uncertain ? " · 待核对" : ""}`;
      return element("li", label);
    });
    $("analysis-preview-items").replaceChildren(...rows);
    text("analysis-preview-limit", candidate.total > rows.length ? `此处显示前 ${rows.length} 项，确认会导入完整的 ${candidate.total} 项；可在 DAW 分析面板继续检查。` : "试听与详细检查在 DAW 分析面板进行；确认后可一次撤销。");
  }
  async function refresh() {
    if (inFlight || stopped || !token || !nativeVisible) { armPoll(); return; }
    inFlight = true; updateControls();
    try { const data = await request("/api/state"); online = true; if (connectionError) localNotice = ""; connectionError = false; render(data); }
    catch (error) { online = false; connectionError = true; localNotice = error.message; notice(localNotice); text("connection", "连接中断"); $("connection").classList.remove("connected"); }
    finally { inFlight = false; updateControls(); armPoll(); }
  }
  async function mutate(path, body, onSuccess) {
    if (inFlight || stopped || !token) return;
    clearTimeout(timer); inFlight = true; mutating = true; localNotice = ""; updateControls();
    try { const data = await request(path, body); online = true; if (data.phase) render(data); if (onSuccess) onSuccess(data); }
    catch (error) { localNotice = error.message; notice(localNotice); if (path === "/api/shutdown") text("shutdown-feedback", error.message); if (path === "/api/settings") text("settings-feedback", error.message); }
    finally { inFlight = false; mutating = false; updateControls(); armPoll(); }
  }
  $("prompt").addEventListener("input", updateControls);
  $("prompt").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.isComposing && !$("submit").disabled) { event.preventDefault(); $("prompt-form").requestSubmit(); }
  });
  $("prompt-form").addEventListener("submit", (event) => {
    event.preventDefault(); const prompt = $("prompt").value.trim();
    if (prompt && !$("submit").disabled) {
      submittedScope = $("scope").value;
      followResponse = true;
      mutate("/api/plan", {prompt, scope: submittedScope}, () => { $("prompt").value = ""; });
    }
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { $("prompt").value = button.dataset.prompt; $("prompt").focus(); updateControls(); }));
  $("apply").addEventListener("click", () => { if (!$("apply").disabled) mutate("/api/apply", {plan_id: state.plan.id}); });
  $("discard").addEventListener("click", () => mutate("/api/cancel", {}));
  $("cancel-work").addEventListener("click", () => { if (!$("cancel-work").disabled) mutate("/api/cancel", {}); });
  $("pause-work").addEventListener("click", () => { if (!$("pause-work").disabled) mutate(state?.phase === "paused" ? "/api/resume" : "/api/pause", {}); });
  $("undo").addEventListener("click", () => { if (!$("undo").disabled) mutate("/api/undo", {}); });
  $("refresh").addEventListener("click", () => { clearTimeout(timer); refresh(); });
  function toggleSettings(open) {
    $("settings").hidden = !open;
    $("settings-toggle").setAttribute("aria-expanded", String(open));
    document.querySelector(".work-area").inert = open;
    $("standalone-footer").inert = open;
    if (open) { renderProviders(); $("provider").focus(); }
    else $("settings-toggle").focus();
  }
  $("settings-toggle").addEventListener("click", () => toggleSettings($("settings").hidden));
  $("scope").addEventListener("change", scopeContext);
  $("settings-form").addEventListener("input", () => { settingsDirty = true; });
  $("provider").addEventListener("change", () => {
    settingsDirty = true; $("api-key").value = ""; text("settings-feedback", "");
    populateProviderFields(currentProviderEntry()); updateControls();
  });
  $("settings-form").addEventListener("submit", (event) => {
    event.preventDefault(); if ($("settings-save").disabled) return;
    const payload = {provider: $("provider").value, model: $("model").value.trim()};
    if (payload.provider === "openai") payload.reasoning_effort = $("reasoning-effort").value;
    if ($("base-url").value.trim()) payload.base_url = $("base-url").value.trim();
    if ($("api-key").value.trim()) payload.api_key = $("api-key").value.trim();
    $("api-key").value = ""; text("settings-feedback", "");
    mutate("/api/settings", payload, () => { settingsDirty = false; formProviderId = null; renderProviders(); text("settings-feedback", "设置已保存，下次请求使用此模型。"); });
  });
  function collapseNative() {
    if (!embedded) return;
    const backend = window.__JUCE__?.backend;
    if (typeof backend?.emitEvent === "function") { reportNativeFocus(false); backend.emitEvent("agentClose", {}); }
    else { localNotice = "请使用 DAW 中的助手按钮收起侧栏。"; notice(localNotice); }
  }
  $("collapse").addEventListener("click", collapseNative);
  document.addEventListener("keydown", (event) => {
    if (!embedded) return;
    event.stopPropagation();
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "a" && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault(); collapseNative(); return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "4") event.preventDefault();
    if (event.key === "Escape" && !event.isComposing && event.keyCode !== 229 && !$("shutdown-dialog").open) {
      event.preventDefault();
      if (!$("settings").hidden) toggleSettings(false); else collapseNative();
    }
  });
  document.addEventListener("keyup", (event) => { if (embedded) event.stopPropagation(); });
  function reportNativeFocus(focused) {
    if (!embedded || typeof window.__JUCE__?.backend?.emitEvent !== "function") return;
    // The host needs only focus ownership. Never send input text, element IDs or keys.
    try { window.__JUCE__.backend.emitEvent("agentFocus", {focused: nativeVisible && focused === true}); }
    catch (_) { /* A closing native page has no focus to retain. */ }
  }
  if (embedded) {
    document.addEventListener("focusin", () => reportNativeFocus(true));
    document.addEventListener("focusout", (event) => reportNativeFocus(!!event.relatedTarget && document.contains(event.relatedTarget)));
    document.addEventListener("pointerdown", () => reportNativeFocus(true), true);
    window.addEventListener("focus", () => reportNativeFocus(true));
    window.addEventListener("blur", () => reportNativeFocus(false));
    window.addEventListener("pagehide", () => reportNativeFocus(false));
    document.addEventListener("visibilitychange", () => { if (document.hidden) reportNativeFocus(false); });
  }
  if (embedded && typeof window.__JUCE__?.backend?.addEventListener === "function") {
    window.__JUCE__.backend.addEventListener("agentVisibility", (event) => {
      nativeVisible = event?.visible !== false;
      if (nativeVisible) refresh();
      else {
        clearTimeout(timer); reportNativeFocus(false);
        // Retain the draft, but require a fresh click before recapturing native keys.
        document.activeElement?.blur?.();
      }
    });
  }
  $("shutdown").addEventListener("click", () => { if (!embedded) { text("shutdown-feedback", ""); $("shutdown-dialog").showModal(); } });
  $("shutdown-cancel").addEventListener("click", () => $("shutdown-dialog").close());
  $("shutdown-confirm").addEventListener("click", () => {
    if (embedded) return;
    $("shutdown-confirm").disabled = true;
    mutate("/api/shutdown", {confirm: true}, () => {
      stopped = true; online = false; state = null; clearTimeout(timer); $("shutdown-dialog").close();
      try { sessionStorage.removeItem(sessionTokenKey); } catch (_) { /* No persistent credential is stored. */ }
      text("connection", "助手已关闭"); $("connection").classList.remove("connected"); text("phase", "已关闭");
      notice("助手已关闭，可以关闭此网页。下次请从启动入口重新打开。"); $("plan").hidden = true;
    }).finally(() => { $("shutdown-confirm").disabled = false; });
  });
  if (!token) { stopped = true; text("connection", "未授权连接"); text("phase", "等待启动"); notice("请使用助手启动器打开的完整链接。这个页面没有连接令牌；重新启动助手后，需要使用新的启动链接。"); updateControls(); }
  else refresh();
})();
