"use strict";
(() => {
  const t = window.emusicianI18n.t;
  const $ = (id) => document.getElementById(id);
  const embedded = new URLSearchParams(window.location.search).get("embedded") === "1";
  document.body.classList.toggle("embedded", embedded);
  $("collapse").hidden = !embedded;
  $("standalone-footer").hidden = embedded;
  $("project-details").open = !embedded && window.innerWidth >= 920;
  if (embedded) text("scope-note", t("Uses the current DAW project. Closing the sidebar keeps your draft."));
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
  let capabilitySignature = "", analysisPreviewSignature = "", generationChoiceSignature = "";
  let providerSignature = "", providers = [], settingsDirty = false, formProviderId = null;
  let shownPlanId = null, followResponse = false, submittedScope = null;
  let notePreviewSignature = "", notePreviewPlanId = null, notePreviewNotes = [], notePreviewPage = 0;
  const notePreviewPageSize = 50;
  let nativeVisible = true;
  const busyPhases = new Set(["planning", "paused", "applying"]);
  function text(id, value) { $(id).textContent = value == null ? "" : String(value); }
  function element(tag, value, className) {
    const node = document.createElement(tag);
    if (value != null) node.textContent = String(value);
    if (className) node.className = className;
    return node;
  }
  function notice(value, detail = "") {
    text("notice-text", value || ""); $("notice").hidden = !value;
    text("notice-detail", detail); $("notice-details").hidden = !detail;
  }
  function stalePlan(plan) {
    const snapshot = state?.snapshot || {}, scope = plan?.scope;
    if (!plan) return false;
    const revision = plan.revision ?? plan.expected_revision ?? scope?.project_revision;
    if (plan.project_id && snapshot.project_id && plan.project_id !== snapshot.project_id) return true;
    if (Number.isInteger(revision) && Number.isInteger(snapshot.revision) && revision !== snapshot.revision) return true;
    return scope?.mode !== "project" && Number.isInteger(scope?.selection_revision)
      && Number.isInteger(snapshot.selection_context?.selection_revision)
      && scope.selection_revision !== snapshot.selection_context.selection_revision;
  }
  function plainError() {
    const messages = {
      insufficient_quota: "The model account has no API credits available. Check its billing, then send again.",
      rate_limit: "The model service declined the request. Check usage and limits before sending again.",
      rate_limit_exceeded: "Too many requests. Wait a moment before sending again.",
      authentication: "The model key or permissions are unavailable. Check Model settings.",
      missing_key: "No model key is configured. Open Model settings.",
      output_limit: "This task exceeded the model's response budget. Try a smaller request.",
      timeout: "The model timed out. Check the task status before sending again.",
      network: "The model connection was interrupted. Check the connection before sending again.",
    };
    return messages[state?.error_code] ? t(messages[state.error_code]) : state?.error;
  }
  function readablePlan(plan) {
    return Array.isArray(plan?.changes) && plan.changes.length > 0
      && plan.changes.every((change) => typeof change === "string" && change.trim());
  }
  function changeItem(change) {
    const row = element("li");
    if (typeof change !== "string") { row.textContent = t("This change has no description. Discard and generate a new plan."); return row; }
    // Highlight the action word without inferring which objects will be deleted.
    const pattern = /\u5220\u9664|\u79fb\u9664|\b(?:delete|remove)\b|#[0-9a-f]{6}\b|[+-]?(?:\d+\.?\d*|\.\d+)(?:\s*(?:BPM|dB|kHz|Hz|ms|beats?|%))?/gi;
    let offset = 0;
    for (const match of change.matchAll(pattern)) {
      const destructive = /^(?:\u5220\u9664|\u79fb\u9664|delete|remove)$/i.test(match[0]);
      const value = element(destructive ? "strong" : "span", match[0], destructive ? "change-action" : "change-value");
      if (/^#[0-9a-f]{6}$/i.test(match[0])) { value.classList.add("colour-value"); value.style.setProperty("--track-colour", match[0]); }
      row.append(document.createTextNode(change.slice(offset, match.index)), value);
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
      heading.append(element("span", t`Note ${item.index + 1}`), element("strong", t`MIDI pitch ${number(item.note.pitch)}`));
      const values = element("dl");
      for (const [key, label, unit] of [["start_beats", t("Start"), t(" beats")], ["length_beats", t("Length"), t(" beats")], ["velocity", t("Velocity"), ""], ["channel", t("Channel"), ""]]) {
        const field = element("div");
        field.append(element("dt", label), element("dd", number(item.note[key]) + unit)); values.append(field);
      }
      row.append(heading, values); list.append(row);
    }
    $("note-preview-rows").replaceChildren(content);
    $("note-preview-pager").hidden = notePreviewNotes.length <= notePreviewPageSize;
    text("note-preview-page", t`${start + 1}–${end} of ${notePreviewNotes.length}`);
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
      const label = typeof preview.label === "string" && preview.label.trim() ? preview.label : t("Clip with new notes");
      preview.notes.forEach((note, index) => notePreviewNotes.push({group, label, index, note: note || {}}));
    }
    notePreviewPage = 0;
    details.hidden = !notePreviewNotes.length;
    details.open = retainOpen && notePreviewNotes.length > 0;
    $("note-preview-rows").replaceChildren();
    $("note-preview-pager").hidden = true;
    text("note-preview-summary", t`New notes (${notePreviewNotes.length})`);
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
    text("key-state", entry.configured ? t("Configured locally") : t("Not configured"));
    text("provider-status", !providerReady(entry) ? t("This provider is not available yet.") : entry.configured ? t("API key saved locally. Use a request to check the model.") : t("Add a key under Connection and API key."));
    $("connection-settings").open = providerReady(entry) && !entry.configured;
  }
  function renderProviders() {
    providers = Array.isArray(state.providers) && state.providers.length ? state.providers : [{...state.provider, id: state.provider?.id || "kimi", label: state.provider?.label || state.provider?.id || "Kimi", adapter_ready: true}];
    const active = state.provider || {}, signature = JSON.stringify(providers);
    const selected = settingsDirty ? $("provider").value : active.id || providers[0]?.id;
    if (signature !== providerSignature) {
      providerSignature = signature;
      $("provider").replaceChildren(...providers.map((entry) => {
        const option = document.createElement("option"); option.value = entry.id;
        option.textContent = `${entry.label || entry.id}${!providerReady(entry) ? t(" · coming later") : !entry.configured ? t(" · not configured") : ""}`;
        option.disabled = !providerReady(entry); return option;
      }));
    }
    if (!settingsDirty) {
      $("provider").value = selected;
      if ($("settings").hidden || formProviderId !== selected) populateProviderFields({...currentProviderEntry(), ...(selected === active.id || !active.id ? active : {})});
    } else if (providers.some((entry) => entry.id === selected)) $("provider").value = selected;
    const label = active.label || providers.find((entry) => entry.id === active.id)?.label || active.id || "Kimi";
    text("current-model", active.model ? `${label} · ${active.model}` : t("Choose model"));
    $("current-model").title = `${$("current-model").textContent}${active.reasoning_effort ? ` · ${active.reasoning_effort}` : ""}${state.model_request?.timeout_seconds ? ` · ${state.model_request.timeout_seconds}s` : ""}`;
  }
  function scopeContext() {
    const snapshot = state?.snapshot || {}, context = snapshot.selection_context;
    const tracks = Array.isArray(snapshot.tracks) ? snapshot.tracks : [];
    const clips = tracks.flatMap((track) => track.clips || []);
    const pills = [];
    const add = (label) => { const pill = element("span", label, "context-pill"); pill.title = label; pills.push(pill); };
    if ($("scope").value === "project") {
      add(t`${tracks.length} tracks`);
      text("scope-hint", t("The whole project is in scope. Review changes before applying."));
    } else if (context?.notes_truncated) {
      const count = Number(context.note_count);
      add(Number.isSafeInteger(count) && count > 0 ? t`${count} notes · over the limit` : t("Too many selected notes"));
      text("scope-hint", t("Select up to 2,000 notes and try again."));
    } else if (!context?.available) {
      add(t("Selection unavailable"));
      text("scope-hint", t("The DAW has not supplied a full selection. Ask a question or choose Whole project."));
    } else {
      const trackIds = Array.isArray(context.track_ids) ? context.track_ids : [];
      const clipIds = Array.isArray(context.clip_ids) ? context.clip_ids : [];
      const notes = Array.isArray(context.note_ids) ? context.note_ids : [];
      if (trackIds.length) add(trackIds.length === 1 ? t`Track: ${tracks.find((t) => t.id === trackIds[0])?.name || trackIds[0]}` : t`${trackIds.length} tracks`);
      const focusedTrack = !trackIds.length && context.focus === "track" && context.active_track_id;
      if (focusedTrack) add(t`Track: ${tracks.find((t) => t.id === focusedTrack)?.name || focusedTrack}`);
      if (clipIds.length) add(clipIds.length === 1 ? t`Clip: ${clips.find((c) => c.id === clipIds[0])?.name || clipIds[0]}` : t`${clipIds.length} clips`);
      if (context.note_clip_id) add(notes.length ? t`${notes.length} notes` : t("No notes selected"));
      const range = context.time_range;
      const hasRange = range?.active && Number.isFinite(range.start_seconds) && Number.isFinite(range.end_seconds);
      if (hasRange) add(t`Range ${Number(range.start_seconds.toFixed(3))}–${Number(range.end_seconds.toFixed(3))} s`);
      const hasSelection = trackIds.length || focusedTrack || clipIds.length || notes.length || hasRange;
      if (!pills.length) add(t("Nothing selected"));
      text("scope-hint", hasSelection ? t("Uses the current selection. Changing it requires a new plan.") : t("Select objects to edit, or describe music to generate."));
    }
    $("context-pills").replaceChildren(...pills);
  }
  function armPoll() {
    clearTimeout(timer);
    const previewActive = ["preparing", "loading", "playing"].includes(state?.generation_preview?.status);
    if (!stopped && token && nativeVisible) timer = setTimeout(refresh, busyPhases.has(state?.phase) || previewActive ? 1000 : 2500);
  }
  async function request(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {method: body === undefined ? "GET" : "POST", headers: {"X-Agent-Token": token, "X-Agent-Language": window.emusicianI18n.locale, ...(body === undefined ? {} : {"Content-Type": "application/json"})}, body: body === undefined ? undefined : JSON.stringify(body), credentials: "omit", cache: "no-store", redirect: "error", signal: controller.signal});
      const data = await response.json();
      if (!response.ok || data.error && !data.phase) throw new Error(data.error || t`Request failed (HTTP ${response.status})`);
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error(t("Connection timed out. Refresh to check the result before retrying."));
      if (error instanceof TypeError) throw new Error(t("Cannot connect to the local assistant. Check that it is running, then refresh."));
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function busy() { return mutating || state?.busy === true || busyPhases.has(state?.phase); }
  function stopping(working = busy()) {
    return working && (state?.phase === "cancelled" || ["cancelled", "cancelling"].includes(state?.progress?.stage));
  }
  function renderProgress(working) {
    const phase = state?.phase, progress = state?.progress || {}, stage = progress.stage;
    const fallback = phase === "paused" ? t("Paused between steps. Resume when ready.")
      : state?.pause_requested ? t("Pausing after the current step.")
      : working ? phase === "applying" ? t("Applying the plan and checking the result.")
      : phase === "cancelled" ? t("Finishing the current request.") : t("Reading the project and preparing a plan.") : "";
    let detail = typeof progress.label === "string" && progress.label.trim() ? t(progress.label)
      : typeof state?.detail === "string" && state.detail ? t(state.detail) : fallback;
    if (state?.model_request?.waiting) detail += ` · ${state.model_request.elapsed_seconds}s / ${state.model_request.timeout_seconds}s`;
    if (stage === "generating") {
      const job = state?.generation_jobs?.at(-1), generationPhase = job?.phase || job?.status;
      const labels = {connecting: "Connecting to the generation service", reconnecting: "Reconnecting to the same generation job", queued: "Generation queued", loading: "Loading the generation model", running: "Generating audio", downloading: "Downloading and verifying audio", ready: "Audio downloaded and ready to preview"};
      detail = `${t(labels[generationPhase] || "Generating audio")} · ${t("Not added to the project")}`;
    }
    text("busy-detail", detail);
    let label = phase === "paused" ? "Paused" : phase === "applying" ? "Applying changes" : "Planning your request";
    let hint = phase === "paused" ? "Choose Resume to continue this task." : phase === "applying" ? "Updating your project and checking the result." : "You will review the result before anything is applied.";
    if (stage === "reading") label = "Reading your project";
    if (stage === "checking") label = "Preparing the selected result";
    if (phase === "applying" && stage === "preflight") label = "Checking the plan";
    if (phase === "applying" && stage === "verifying") label = "Checking results";
    if (["generating", "analyzing"].includes(stage)) {
      const jobs = stage === "generating" ? state.generation_jobs : state.analysis_jobs;
      const job = jobs?.at(-1), jobStage = job?.phase || job?.status;
      const labels = {connecting: "Connecting to the model", reconnecting: "Reconnecting to the task", queued: "Waiting for a compute slot", preparing: "Preparing audio", uploading: "Uploading the selected audio", loading: "Loading the model", downloading: "Receiving the result", validating: "Checking the result", postprocessing: "Finishing the result", cancelling: "Stopping the task", ready: "Result ready"};
      const kinds = {separate: "Separating stems", transcribe: "Transcribing MIDI", chords: "Detecting chords", beats: "Analyzing beats", score: "Analyzing music"};
      label = labels[jobStage] || (stage === "generating" ? "Generating music" : kinds[job?.kind] || "Analyzing audio");
      hint = "Your project stays unchanged until you apply the result.";
    }
    if (state?.pause_requested && phase !== "paused") hint = "Pausing after the current step.";
    if (stopping(working)) { label = "Stopping the task"; hint = "Waiting for the task to confirm it has stopped."; }
    text("phase", t(label)); text("progress-copy", t(hint));
    $("task-indicator").hidden = !working || phase === "paused";
    // Native progress currently describes only parts of a job. Without a
    // whole-task denominator, an indeterminate indicator is the honest state.
    $("task-indicator").removeAttribute("value");
    $("task-indicator").removeAttribute("aria-valuenow");
    $("task-indicator").setAttribute("aria-label", t(label));
    $("commit-hint").hidden = phase !== "applying";
    $("task-progress").hidden = !working && phase !== "paused";
    $("task-progress").dataset.busy = String(working);
    $("task-progress").dataset.paused = String(phase === "paused");
  }
  function updateControls() {
    const working = busy(), connected = !!state?.control?.connected && online;
    for (const button of $("capability-list").querySelectorAll("button[data-available]")) button.disabled = working || !connected || button.dataset.available !== "true";
    $("submit").disabled = working || inFlight || !connected || !state?.provider?.configured || !$("prompt").value.trim();
    $("prompt").disabled = working;
    $("apply").disabled = working || inFlight || !connected || state?.phase !== "ready" || !state?.plan?.id || !readablePlan(state.plan) || stalePlan(state.plan);
    $("generation-play").disabled = working || inFlight || !connected || ["preparing", "loading"].includes(state?.generation_preview?.status) || state?.phase !== "ready" || state?.plan?.execution_kind !== "generation_import";
    $("generation-stop").disabled = inFlight || !connected;
    $("generation-stop").hidden = !["preparing", "loading", "playing"].includes(state?.generation_preview?.status);
    $("discard").disabled = working || inFlight || !online;
    $("undo").disabled = working || inFlight || !connected || !state?.can_undo;
    $("refresh").disabled = inFlight;
    $("settings-save").disabled = working || inFlight || !online || !providerReady(currentProviderEntry());
    $("scope").disabled = working;
    $("cancel-work").hidden = !["planning", "paused"].includes(state?.phase);
    $("cancel-work").disabled = inFlight || state?.phase === "applying" || !online || stopping(working);
    text("cancel-work", t("Stop"));
    const canPause = state?.phase === "paused" || Object.prototype.hasOwnProperty.call(state || {}, "pause_requested");
    $("pause-work").hidden = !canPause || !["planning", "paused"].includes(state?.phase);
    $("pause-work").disabled = !canPause || inFlight || !online || stopping(working) || !["planning", "paused"].includes(state?.phase)
      || (state?.phase === "planning" && state?.pause_requested === true);
    text("pause-work", state?.phase === "paused" ? t("Resume") : state?.pause_requested ? t("Pausing") : t("Pause"));
    $("shutdown").disabled = working || inFlight || !online;
    text("submit", state?.phase === "planning" ? t("Working…") : t("Send"));
    $("submit").classList.toggle("primary", state?.phase !== "ready");
    document.querySelectorAll("[data-prompt]").forEach((button) => { button.disabled = working; });
    renderGenerationChoices();
    renderProgress(working);
  }
  function renderSnapshot(snapshot) {
    text("project-title", `${snapshot.name || t("Untitled project")}${snapshot.dirty ? t(" · unsaved") : ""}`);
    const bpm = snapshot.bpm ?? snapshot.tempo_bpm;
    text("tempo", typeof bpm === "number" ? `${Number(bpm.toFixed(3))} BPM` : "—");
    text("meter", snapshot.numerator && snapshot.denominator ? `${snapshot.numerator}/${snapshot.denominator}` : "—");
    text("revision", snapshot.revision ?? "—");
    const tracks = Array.isArray(snapshot.tracks) ? snapshot.tracks : [];
    const selectedTrack = tracks.find((track) => track.id === snapshot.selected_track_id);
    const selectedClip = tracks.flatMap((track) => track.clips || []).find((clip) => clip.id === snapshot.selected_clip_id);
    text("selection-text", selectedClip ? `${selectedTrack?.name || t("Clip")} / ${selectedClip.name || selectedClip.id}` : selectedTrack ? selectedTrack.name : t("No track or clip selected"));
    text("track-count", tracks.length);
    const signature = JSON.stringify([tracks.map((track) => [track.id, track.name, track.kind, track.colour, track.clip_count ?? track.clips?.length ?? 0]), snapshot.selected_track_id]);
    if (signature !== trackSignature) {
      trackSignature = signature;
      const list = $("tracks"); list.replaceChildren();
      if (!tracks.length) list.append(element("li", t("Create a track with the assistant or import audio in the DAW."), "empty"));
      tracks.forEach((track) => {
        const row = element("li", null, track.id === snapshot.selected_track_id ? "selected" : "");
        if (typeof track.colour === "string" && /^#[0-9a-f]{6}$/i.test(track.colour)) row.style.setProperty("--track-colour", track.colour);
        row.append(element("div", track.name || t("Untitled track"), "track-name"));
        const kind = {instrument: "MIDI", audio: t("Audio"), bus: t("Bus")}[track.kind] || t("Tracks");
        row.append(element("div", t`${kind} · ${track.clip_count ?? track.clips?.length ?? 0} clips`, "track-meta")); list.append(row);
      });
    }
    scopeContext();
  }
  function renderMessages(messages) {
    const items = Array.isArray(messages) ? messages : [], signature = JSON.stringify([items, state?.phase, state?.can_undo]);
    if (signature === messageSignature) return;
    messageSignature = signature; $("conversation-empty").hidden = items.length > 0;
    const list = $("messages"), history = $("history-messages"); list.replaceChildren(); history.replaceChildren();
    const lastUser = items.findLastIndex((message) => message.role === "user");
    const lastAnswer = items.findLastIndex((message) => message.role === "assistant" && message.origin !== "runtime");
    items.forEach((message, index) => {
      const isUser = message.role === "user", article = element("article", null, `message ${isUser ? "user" : "assistant"}`);
      article.append(element("div", isUser ? t("You") : t("Music assistant"), "message-label"));
      const content = message.content || "", body = element("div", content, "message-body");
      const current = index === lastUser || (index === lastAnswer && index > lastUser && state?.phase === "done" && !state?.can_undo);
      if (current && isUser && content.length > 190) {
        const details = element("details", null, "request-details");
        details.append(element("summary", content.slice(0, 155).trimEnd()+"…"), body); article.append(details);
      } else article.append(body);
      (current ? list : history).append(article);
    });
    $("conversation-history").hidden = !history.childElementCount;
  }
  function analysisChanges(candidate) {
    if (!candidate) return null;
    const total = Number(candidate.total), start = Number(candidate.source?.timeline_start || 0).toFixed(3);
    const tracks = Number(candidate.summary?.track_count ?? (candidate.kind === "transcribe" ? 1 : 0));
    const notes = Number(candidate.summary?.note_count ?? total);
    const title = candidate.kind === "separate" ? t`Create ${total} audio tracks.`
      : candidate.kind === "transcribe" ? t`Create ${tracks} MIDI tracks with ${notes} notes.`
      : candidate.kind === "chords" ? t`Add ${total} chords to the chord lane.`
      : candidate.kind === "score" ? t`Music analysis: ${tracks} MIDI tracks and ${Number(candidate.summary?.chord_count || 0)} chords.` : null;
    if (!title) return null;
    const rows = [title, t`Start at ${start} s. Keep the original audio.`];
    if (candidate.kind === "transcribe" || candidate.kind === "score") {
      if (candidate.summary?.controller_count) rows.push(t`Preserve ${Number(candidate.summary.controller_count)} controller events.`);
      rows.push(t("Choose an instrument for playback."));
    }
    if (candidate.kind === "score") rows.push(t("Keep beats and structure as analysis markers. Project tempo stays unchanged."));
    return rows;
  }
  function generationChanges(candidate) {
    if (!candidate) return null;
    const start = Number(candidate.source?.timeline_start || 0).toFixed(3);
    const duration = Number(candidate.audio?.duration_seconds || 0).toFixed(2);
    const rows = [t("Add generated music to a new audio track"), t`Start at ${start} s. Actual duration: ${duration} s.`, t("Keep existing music. Undo the import in one step.")];
    if (candidate.completion?.token_limit_reached || candidate.completion?.truncated === true || candidate.completion?.reason === "token_budget") rows.push(t("Generation reached its budget. The ending may be cut off; preview before adding."));
    return rows;
  }
  function renderGenerationChoices() {
    const choices = Array.isArray(state?.generation_choices) ? state.generation_choices : [];
    const currentPlan = state?.plan?.execution_kind === "generation_import" && ["ready", "applying"].includes(state?.phase) && !stalePlan(state.plan);
    const selected = (choice) => choice.selected === true && currentPlan;
    // Keep a sole completed candidate recoverable when the model failed before
    // proposing it, or when its former review became stale.
    $("generation-choices").hidden = !choices.length || (choices.length === 1 && selected(choices[0]));
    const locked = busy() || inFlight || !online || !state?.control?.connected;
    const signature = JSON.stringify([choices, locked, currentPlan, window.emusicianI18n.locale]);
    if (generationChoiceSignature === signature) return;
    generationChoiceSignature = signature;
    const modelNames = {"ace-step-1.5-xl-turbo": "ACE-Step", ace_step_1_5: "ACE-Step", "ace-step-1.5": "ACE-Step", ace_step: "ACE-Step", yue2: "YuE2"};
    $("generation-choice-list").replaceChildren(...choices.map((choice) => {
      const isSelected = selected(choice), row = element("li", null, isSelected ? "selected" : "");
      const description = element("div"), duration = Number(choice.duration_seconds);
      description.append(element("strong", modelNames[choice.model_id] || choice.model_id || t("Generated candidate")));
      const status = [Number.isFinite(duration) ? `${Number(duration.toFixed(2))} s` : "", choice.applied ? t("Added") : choice.available === false ? t("Unavailable") : choice.truncated ? t("Ending may be cut off") : ""].filter(Boolean).join(" · ");
      description.append(element("span", status, "muted"));
      const button = element("button", isSelected ? t("Selected") : t("Review")); button.type = "button";
      button.disabled = locked || choice.applied || choice.available === false || isSelected || !choice.result_id;
      button.setAttribute("aria-pressed", isSelected ? "true" : "false");
      button.addEventListener("click", () => { if (!button.disabled) mutate("/api/generation/select", {result_id: choice.result_id, scope: $("scope").value}); });
      row.append(description, button); return row;
    }));
  }
  function warpChanges(plan, snapshot) {
    if (!["audio_warp", "beat_apply"].includes(plan.execution_kind)) return null;
    const rows = [t("Prepare audio in the background, then apply in one undoable edit.")];
    if (plan.tempo_check?.numerator) rows.push(t`Entire project: ${Number(plan.tempo_check.bpm).toFixed(2)} BPM · ${plan.tempo_check.numerator}/${plan.tempo_check.denominator}`);
    else rows.push(t("Keep the current project tempo and meter."));
    for (const check of plan.warp_checks || []) {
      const track = (snapshot.tracks || []).find((item) => (item.clips || []).some((clip) => clip.id === check.clip_id));
      const name = track?.name || t("Audio clip");
      rows.push(t`${name} · Start ${check.timeline_start_seconds.toFixed(3)} s · Duration ${check.duration_seconds.toFixed(3)} s`);
      rows.push(check.enabled === false ? t("Disable Warp and restore the original speed.") : t`Playback ratio ${check.warp_speed_ratio.toFixed(4)} · ${check.follow_tempo ? t("Follow project tempo") : t("Fixed tempo")}`);
    }
    if (plan.analysis?.tempo?.variable_tempo) rows.push(t("Tempo varies; this edit uses a fixed ratio and does not straighten individual beats."));
    return rows;
  }
  function render(next) {
    const scroll = $("transcript");
    const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 60;
    const oldMessages = messageSignature;
    state = next;
    const connected = !!state.control?.connected;
    text("connection", online ? connected ? t("DAW connected") : t("DAW disconnected") : t("Disconnected"));
    $("connection").classList.toggle("connected", online && connected);
    renderSnapshot(state.snapshot || {}); renderMessages(state.messages);
    renderCapabilities(state.capability_groups);
    const plan = state.plan, visible = !!plan && ["ready", "applying"].includes(state.phase);
    $("plan").hidden = !visible;
    if (visible) {
      text("plan-summary", plan.summary || t("Review these changes."));
      const frozenScope = plan.scope;
      const revision = plan.revision ?? plan.expected_revision ?? frozenScope?.project_revision;
      text("plan-revision", revision == null ? "" : t`Revision ${revision}`);
      const scope = (frozenScope && typeof frozenScope === "object" ? frozenScope.mode : frozenScope) || submittedScope;
      text("plan-scope", scope === "project" ? t("Scope: whole project") : scope === "selection" ? t("Scope: selection when sent") : scope === "clip" ? t("Scope: whole clip") : t("Scope: selection when submitted"));
      const importedChanges = warpChanges(plan, state.snapshot || {}) || (plan.execution_kind === "analysis_import" ? analysisChanges(plan.analysis) : plan.execution_kind === "generation_import" ? generationChanges(plan.generation) : null);
      $("plan-summary").hidden = !!importedChanges;
      $("plan-stale").hidden = !stalePlan(plan);
      const steps = importedChanges ? [{label: t("Check the source and project version")}, {label: importedChanges[0]}] : Array.isArray(plan.steps) ? plan.steps : [];
      const hasSteps = steps.length > 0 && steps.every((step) => typeof step?.label === "string" && step.label.trim());
      $("plan-sequence").hidden = !hasSteps;
      $("plan-steps").replaceChildren(...(hasSteps ? steps.map((step) => element("li", step.label)) : []));
      const chord = plan.execution_kind === "chord_edit" && plan.chord_before && plan.chord_after;
      const changes = importedChanges || (chord ? [t`Chord ${plan.chord_before.label} → ${plan.chord_after.label}`,
        t`Time ${plan.chord_before.start_seconds}–${plan.chord_before.end_seconds} s → ${plan.chord_after.start_seconds}–${plan.chord_after.end_seconds} s`]
        : Array.isArray(plan.changes) ? plan.changes : []);
      $("changes").replaceChildren(...changes.map(changeItem));
    }
    renderNotePreviews(visible ? plan : null);
    renderAnalysisPreview(visible ? plan?.analysis : null);
    const generated = visible && plan?.execution_kind === "generation_import" && plan.generation;
    $("generation-preview").hidden = !generated;
    if (generated) text("generation-preview-info", `${Number(generated.audio?.duration_seconds || 0).toFixed(2)} s · ${Number(generated.audio?.sample_rate || 0)/1000} kHz · ${t("Generated candidate")}`);
    const audition = state.generation_preview || {}, previewLabels = {preparing: "Preparing preview…", loading: "Preparing preview…", playing: "Previewing", stopped: "Preview stopped", completed: "Preview ended", failed: "Preview failed", unavailable: "Preview unavailable"};
    text("generation-preview-status", audition.status ? `${t(previewLabels[audition.status] || "Preview status unknown")}${["failed", "unavailable"].includes(audition.status) && audition.detail ? ` · ${t(audition.detail)}` : ""}` : "");
    $("generation-play").disabled = !generated || state.busy || !connected || mutating;
    $("generation-stop").disabled = !connected || mutating;
    // A completed mutation response can arrive before the request's finally
    // block clears `mutating`; do not hide its result until the next poll.
    $("result").hidden = (!state.last_result && !state.can_undo) || visible || state.busy === true || busyPhases.has(state.phase);
    text("result-text", state.can_undo && !state.error ? t("Changes are in your project. You can undo this edit.") : t(state.last_result || ""));
    $("undo").hidden = !state.can_undo;
    const usage = state.usage || {}, format = (value) => Number(value || 0).toLocaleString(window.emusicianI18n.locale);
    text("usage", t`${format(usage.calls)} requests · ${format(usage.prompt_tokens)} input / ${format(usage.completion_tokens)} output tokens`);
    const candidate = plan?.generation || plan?.analysis;
    text("technical-stage", candidate ? t`Model: ${candidate.model_id || candidate.model?.id || "—"} · ${candidate.execution === "cloud" ? t("Cloud") : t("Local")}` : "");
    const jobs = [...(state.generation_jobs || []), ...(state.analysis_jobs || [])].slice(-8);
    $("technical-jobs").replaceChildren(...jobs.map((job) => element("li", [job.model_id || job.model?.id, job.phase || job.status, job.job_id || job.id].filter(Boolean).join(" · "))));
    renderProviders(); renderGenerationChoices();
    const presentation = state.presentation === true || state.provider?.presentation === true;
    document.body.classList.toggle("presentation-workspace", presentation);
    if (presentation) {
      text("apply", "Apply changes");
      if (generated) {
        const names = {yue2: "YuE2", "ace-step-1.5-xl-turbo": "ACE-Step"};
        const id = generated.model_id || generated.model?.id || "";
        text("generation-preview-info", `${names[id] || id} · ${Number(generated.audio?.duration_seconds || 0).toFixed(2)} s`);
      }
      $("settings").hidden = true;
      $("settings-toggle").setAttribute("aria-expanded", "false");
    }
    notice(localNotice || plainError() || (visible && !readablePlan(plan) ? t("The plan description is incomplete. Discard and generate again.") : "")
      || (!state.provider?.configured ? t("Open model settings above to add an API key.") : ""),
      state.error ? `${state.error}${state.error_code ? ` [${state.error_code}]` : ""}` : ""); updateControls();
    if (visible && plan.id !== shownPlanId) {
      shownPlanId = plan.id;
      $("plan-details").open = false;
      $("analysis-preview").open = false;
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
      heading.append(element("span", t(group.label)), element("span", t(group.status_label), "capability-status"));
      const simpleDetails = {separate: "Create separate audio tracks and keep the original.", transcribe: "Create a MIDI track to edit in the piano roll.", chords: "Create a chord lane on the timeline with editable labels.", beats: "Find beats and downbeats. Review before aligning audio or adopting its tempo.", warp: "Stretch without changing pitch, set source tempo and toggle tempo follow."};
      const detail = element("p", t(simpleDetails[group.id] || group.detail));
      const example = element("button", t(group.example)); example.type = "button";
      example.disabled = !group.enabled || busy();
      example.dataset.available = group.enabled ? "true" : "false";
      example.addEventListener("click", () => { $("prompt").value = t(group.example); $("prompt").focus(); updateControls(); });
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
    const names = {separate: t("Separated tracks"), transcribe: t("MIDI notes"), chords: t("Chords"), beats: t("Beat candidates"), score: t("Music analysis")};
    text("analysis-preview-title", t`${names[candidate.kind] || t("Analysis result")} · ${candidate.total} items`);
    const source = candidate.source || {};
    if (candidate.kind === "beats") {
      const bpm = Number.isFinite(candidate.tempo?.bpm) ? candidate.tempo.bpm.toFixed(2) : t("Set tempo");
      const meter = candidate.tempo?.meter_supported ? `${candidate.tempo.meter_numerator}/${candidate.tempo.meter_denominator}` : t("Review meter");
      text("analysis-preview-info", `${bpm} BPM · ${meter} · ${Number(source.duration_seconds || 0).toFixed(2)} s`);
    } else text("analysis-preview-info", `${Number(source.duration_seconds || 0).toFixed(2)} s · ${t("Undo is available after adding the result.")}`);
    const seconds = (value) => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(3)}s` : "—";
    const rows = (candidate.items || []).map((item) => {
      const label = candidate.kind === "separate" ? t`${item.name} · ${seconds(item.duration_seconds)} · ${item.channels} channels`
        : candidate.kind === "transcribe" || (candidate.kind === "score" && (!candidate.component || candidate.component === "notes")) ? t`MIDI ${item.pitch} · starts ${seconds(item.start_seconds)} · length ${seconds(item.duration_seconds)} · velocity ${item.velocity}`
        : candidate.kind === "beats" || (candidate.kind === "score" && candidate.component === "beats") ? `${item.is_downbeat ? t("Downbeat") : t("Beat")} · ${seconds(item.time_seconds)}`
        : `${item.label} · ${seconds(item.start_seconds)}–${seconds(item.end_seconds)}${item.uncertain ? t(" · review") : ""}`;
      return element("li", label);
    });
    $("analysis-preview-items").replaceChildren(...rows);
    text("analysis-preview-limit", candidate.kind === "beats" ? t("Beat markers are for review. Confirmation applies tempo and alignment without creating a track.") : candidate.total > rows.length ? t`Showing ${rows.length} of ${candidate.total}. Apply adds the complete result.` : t("Review in the DAW. Apply can be undone in one step."));
  }
  async function refresh() {
    if (inFlight || stopped || !token || !nativeVisible) { armPoll(); return; }
    inFlight = true; updateControls();
    try { const data = await request("/api/state"); online = true; if (connectionError) localNotice = ""; connectionError = false; render(data); }
    catch (error) { online = false; connectionError = true; localNotice = error.message; notice(localNotice); text("connection", t("Disconnected")); $("connection").classList.remove("connected"); }
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
  $("generation-play").addEventListener("click", () => { if (state?.plan?.id) mutate("/api/generation/preview", {plan_id: state.plan.id}); });
  $("generation-stop").addEventListener("click", () => mutate("/api/generation/preview", {stop: true}));
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
    mutate("/api/settings", payload, () => { settingsDirty = false; formProviderId = null; renderProviders(); text("settings-feedback", t("Settings saved. Your next request uses this model.")); });
  });
  function collapseNative() {
    if (!embedded) return;
    const backend = window.__JUCE__?.backend;
    if (typeof backend?.emitEvent === "function") { reportNativeFocus(false); backend.emitEvent("agentClose", {}); }
    else { localNotice = t("Use the DAW Agent button to close the sidebar."); notice(localNotice); }
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
      text("connection", t("Assistant closed")); $("connection").classList.remove("connected"); text("phase", t("Closed"));
      notice(t("The assistant is closed. You can close this page.")); $("plan").hidden = true;
    }).finally(() => { $("shutdown-confirm").disabled = false; });
  });
  window.emusicianSetLanguage = (language) => {
    window.emusicianI18n.setLanguage(language);
    messageSignature = trackSignature = capabilitySignature = providerSignature = analysisPreviewSignature = notePreviewSignature = "";
    // Re-render authored UI only. Drafts, project names, model answers and API
    // configuration fields remain unchanged; the worker is not restarted.
    if (state) render(state); else updateControls();
    if (embedded) text("scope-note", t("Uses the current DAW project. Closing the sidebar keeps your draft."));
  };
  if (!token) { stopped = true; text("connection", t("Connection not authorized")); text("phase", t("Waiting to start")); notice(t("Open the link supplied by the assistant launcher. This page has no session token.")); updateControls(); }
  else refresh();
})();
