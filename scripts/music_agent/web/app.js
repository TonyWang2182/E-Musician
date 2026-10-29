"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
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
  const busyPhases = new Set(["planning", "applying"]);
  const phaseText = {idle: "准备就绪", planning: "正在生成方案", ready: "等待你确认", applying: "正在应用并检查", done: "已完成", error: "需要处理", cancelled: "已停止"};
  function text(id, value) { $(id).textContent = value == null ? "" : String(value); }
  function element(tag, value, className) {
    const node = document.createElement(tag);
    if (value != null) node.textContent = String(value);
    if (className) node.className = className;
    return node;
  }
  function notice(value) { text("notice", value || ""); $("notice").hidden = !value; }
  function armPoll() {
    clearTimeout(timer);
    if (!stopped && token) timer = setTimeout(refresh, busyPhases.has(state?.phase) ? 1000 : 2500);
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
  function updateControls() {
    const working = busy(), connected = !!state?.control?.connected && online;
    $("submit").disabled = working || inFlight || !connected || !state?.provider?.configured || !$("prompt").value.trim();
    $("prompt").disabled = working;
    $("apply").disabled = working || inFlight || !connected || state?.phase !== "ready" || !state?.plan?.id;
    $("discard").disabled = working || inFlight || !online;
    $("undo").disabled = working || inFlight || !connected || !state?.can_undo;
    $("refresh").disabled = inFlight;
    $("settings-save").disabled = working || inFlight || !online;
    $("cancel-work").hidden = !busyPhases.has(state?.phase);
    $("cancel-work").disabled = inFlight || state?.phase === "applying" || !online;
    text("cancel-work", state?.phase === "applying" ? "正在提交修改" : "停止生成");
    $("shutdown").disabled = working || inFlight || !online;
    text("submit", state?.phase === "planning" ? "生成中…" : "生成方案");
    document.querySelectorAll("[data-prompt]").forEach((button) => { button.disabled = working; });
    text("busy-detail", working ? state?.phase === "applying" ? "提交到 DAW 后，正在回读工程检查结果。" : state?.phase === "cancelled" ? "正在结束当前请求，完成后可以继续。" : "正在读取工程并请求模型，尚未修改工程。" : "");
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
    state = next;
    const connected = !!state.control?.connected;
    text("connection", online ? connected ? "DAW 已连接" : "DAW 未连接" : "连接中断");
    $("connection").classList.toggle("connected", online && connected);
    text("phase", phaseText[state.phase] || state.phase || "准备就绪");
    renderSnapshot(state.snapshot || {}); renderMessages(state.messages);
    const plan = state.plan, visible = !!plan && ["ready", "applying"].includes(state.phase);
    $("plan").hidden = !visible;
    if (visible) {
      text("plan-summary", plan.summary || "请核对以下修改。");
      const revision = plan.expected_revision ?? plan.revision;
      text("plan-revision", revision == null ? "" : `基于修订 ${revision}`);
      $("changes").replaceChildren(...(Array.isArray(plan.changes) ? plan.changes : []).map((change) => element("li", typeof change === "string" ? change : JSON.stringify(change))));
    }
    $("result").hidden = !state.last_result; text("result-text", state.last_result || "");
    const usage = state.usage || {}, format = (value) => Number(value || 0).toLocaleString("zh-CN");
    text("usage", `本次会话 · ${format(usage.calls)} 次模型请求 · 输入 ${format(usage.prompt_tokens)} / 输出 ${format(usage.completion_tokens)} tokens`);
    text("key-state", state.provider?.configured ? "本机已配置" : "尚未配置");
    if ($("settings").hidden) {
      $("model").value = state.provider?.model || "kimi-k2.6";
      $("base-url").value = state.provider?.base_url || "https://api.moonshot.cn/v1";
    }
    notice(localNotice || state.error || (!state.provider?.configured ? "先展开“模型设置”配置 Kimi 密钥，再开始对话。" : "")); updateControls();
  }
  async function refresh() {
    if (inFlight || stopped || !token) { armPoll(); return; }
    inFlight = true; updateControls();
    try { const data = await request("/api/state"); online = true; if (connectionError) localNotice = ""; connectionError = false; render(data); }
    catch (error) { online = false; connectionError = true; localNotice = error.message; notice(localNotice); text("connection", "连接中断"); $("connection").classList.remove("connected"); }
    finally { inFlight = false; updateControls(); armPoll(); }
  }
  async function mutate(path, body, onSuccess) {
    if (inFlight || stopped || !token) return;
    clearTimeout(timer); inFlight = true; mutating = true; localNotice = ""; updateControls();
    try { const data = await request(path, body); online = true; if (data.phase) render(data); if (onSuccess) onSuccess(data); }
    catch (error) { localNotice = error.message; notice(localNotice); if (path === "/api/shutdown") text("shutdown-feedback", error.message); }
    finally { inFlight = false; mutating = false; updateControls(); armPoll(); }
  }
  $("prompt").addEventListener("input", updateControls);
  $("prompt").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.isComposing && !$("submit").disabled) { event.preventDefault(); $("prompt-form").requestSubmit(); }
  });
  $("prompt-form").addEventListener("submit", (event) => {
    event.preventDefault(); const prompt = $("prompt").value.trim();
    if (prompt && !$("submit").disabled) mutate("/api/plan", {prompt}, () => { $("prompt").value = ""; });
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { $("prompt").value = button.dataset.prompt; $("prompt").focus(); updateControls(); }));
  $("apply").addEventListener("click", () => { if (!$("apply").disabled) mutate("/api/apply", {plan_id: state.plan.id}); });
  $("discard").addEventListener("click", () => mutate("/api/cancel", {}));
  $("cancel-work").addEventListener("click", () => { if (!$("cancel-work").disabled) mutate("/api/cancel", {}); });
  $("undo").addEventListener("click", () => { if (!$("undo").disabled) mutate("/api/undo", {}); });
  $("refresh").addEventListener("click", () => { clearTimeout(timer); refresh(); });
  $("settings-toggle").addEventListener("click", () => { const open = $("settings").hidden; $("settings").hidden = !open; $("settings-toggle").setAttribute("aria-expanded", String(open)); if (open) $(state?.provider?.configured ? "model" : "api-key").focus(); });
  $("settings-form").addEventListener("submit", (event) => {
    event.preventDefault(); if ($("settings-save").disabled) return;
    const payload = {model: $("model").value.trim(), base_url: $("base-url").value};
    if ($("api-key").value.trim()) payload.api_key = $("api-key").value.trim();
    $("api-key").value = ""; text("settings-feedback", "");
    mutate("/api/settings", payload, () => { text("settings-feedback", "设置已保存。下次生成方案将使用这些设置。"); });
  });
  $("shutdown").addEventListener("click", () => { text("shutdown-feedback", ""); $("shutdown-dialog").showModal(); });
  $("shutdown-cancel").addEventListener("click", () => $("shutdown-dialog").close());
  $("shutdown-confirm").addEventListener("click", () => {
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
