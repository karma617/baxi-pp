const $ = (sel) => document.querySelector(sel);
const RUN_FORM_STORAGE_KEY = "paypal-web-run-form";
const PROXY_CONFIG_STORAGE_KEY = "paypal-web-proxy-config";
const state = {
  currentJobId: localStorage.getItem("paypal-web-current-job") || "",
  pollTimer: null,
  smsOptions: {
    herosms: { countries: [], services: [] },
    smsbower: { countries: [], services: [] },
  },
  smsOptionTimers: {},
};

function fmtTime(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString();
}

function fmtDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m ${s}s`;
}

function pretty(obj) {
  if (!obj) return "{}";
  return JSON.stringify(obj, null, 2);
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toast(message) {
  const el = $("#toast");
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hidden"), 2600);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

function setServer(ok) {
  const el = $("#serverStatus");
  if (!el) return;
  el.textContent = ok ? "已连接" : "连接失败";
  el.classList.toggle("ok", ok);
  el.classList.toggle("bad", !ok);
}

async function health() {
  try {
    await api("/api/health");
    setServer(true);
  } catch (err) {
    setServer(false);
  }
}

async function refreshJobs() {
  try {
    const data = await api("/api/jobs");
    renderJobs(data.jobs || []);
  } catch (err) {
    toast(err.message);
  }
}

function renderJobs(jobs) {
  const box = $("#jobsList");
  if (!jobs.length) {
    box.className = "jobs-list empty";
    box.textContent = "暂无任务";
    return;
  }
  box.className = "jobs-list";
  box.innerHTML = jobs.map(job => `
    <div class="job-item ${job.id === state.currentJobId ? "active" : ""}" data-job-id="${esc(job.id)}">
      <div class="job-top">
        <span class="job-id">#${esc(job.id)}</span>
        <span class="badge ${esc(job.status)}">${esc(job.status)}</span>
      </div>
      <div class="job-sub">${esc(job.stage || "")}</div>
      <div class="job-sub">${esc(job.ba_token || "")} · ${esc(fmtTime(job.created_at))} · ${job.proxy_enabled ? "代理开" : "代理关"}</div>
    </div>`).join("");
  box.querySelectorAll(".job-item").forEach(item => {
    item.addEventListener("click", () => selectJob(item.dataset.jobId));
  });
}

function selectJob(jobId) {
  state.currentJobId = jobId || "";
  if (jobId) localStorage.setItem("paypal-web-current-job", jobId);
  else localStorage.removeItem("paypal-web-current-job");
  refreshJobs();
  pollCurrent(true);
}

function renderLogs(logs) {
  const text = (logs || []).map(line => {
    const t = new Date((line.time || 0) * 1000).toLocaleTimeString();
    return `[${t}] ${line.level.padEnd(7)} ${line.message}`;
  }).join("\n");
  const box = $("#logsBox");
  box.textContent = text;
  if ($("#autoScroll").checked) box.scrollTop = box.scrollHeight;
}

function renderCurrent(job) {
  $("#currentEmpty").classList.add("hidden");
  $("#currentBody").classList.remove("hidden");
  $("#currentMeta").textContent = `#${job.id} · 创建于 ${fmtTime(job.created_at)} · ${job.proxy_label || "代理关闭"}`;
  $("#jobStatus").textContent = job.status;
  $("#jobStage").textContent = job.stage || "";
  $("#jobDuration").textContent = fmtDuration(job.duration);
  $("#generatedBox").textContent = pretty(job.generated);
  $("#resultBox").textContent = pretty(job.result || (job.error ? { error: job.error, traceback: job.traceback } : {}));
  $("#copyResult").disabled = !(job.result || job.error);

  const otpPanel = $("#otpPanel");
  otpPanel.classList.toggle("hidden", !job.awaiting_otp);
  $("#otpPrompt").textContent = job.awaiting_prompt || "请输入短信验证码或新手机号。";
  if (job.awaiting_otp) $("#otpValue").focus();

  renderLogs(job.logs || []);
}

async function pollCurrent(force = false) {
  if (!state.currentJobId) {
    $("#currentEmpty").classList.remove("hidden");
    $("#currentBody").classList.add("hidden");
    $("#currentMeta").textContent = "未选择任务";
    $("#copyResult").disabled = true;
    return;
  }
  try {
    const job = await api(`/api/jobs/${state.currentJobId}`);
    renderCurrent(job);
    if (force || ["completed", "failed", "awaiting_otp"].includes(job.status)) refreshJobs();
  } catch (err) {
    toast(err.message);
    state.currentJobId = "";
    localStorage.removeItem("paypal-web-current-job");
  }
}

function runFormPayload() {
  return {
    baToken: $("#baToken")?.value || "",
    phone: $("#phone")?.value || "",
    country: $("#country")?.value || "BR",
    maxCardAttempts: $("#maxCardAttempts")?.value || "5",
    maxPhoneChanges: $("#maxPhoneChanges")?.value || "5",
    debug: Boolean($("#debug")?.checked),
    smsProvider: $("#smsProvider")?.value || "manual",
    herosmsApiKey: $("#herosmsApiKey")?.value || "",
    herosmsBaseUrl: $("#herosmsBaseUrl")?.value || "",
    herosmsService: $("#herosmsService")?.value || "",
    herosmsCountry: $("#herosmsCountry")?.value || "",
    smsbowerApiKey: $("#smsbowerApiKey")?.value || "",
    smsbowerBaseUrl: $("#smsbowerBaseUrl")?.value || "",
    smsbowerService: $("#smsbowerService")?.value || "",
    smsbowerCountry: $("#smsbowerCountry")?.value || "",
    smsTimeoutSeconds: $("#smsTimeoutSeconds")?.value || "60",
    proxyEnabled: Boolean($("#proxyEnabled")?.checked),
    proxyMode: $("#proxyMode")?.value || "api",
    proxyPool: $("#proxyPool")?.value || "",
    proxyApiUrl: $("#proxyApiUrl")?.value || "",
  };
}

function saveRunForm() {
  const payload = runFormPayload();
  localStorage.setItem(RUN_FORM_STORAGE_KEY, JSON.stringify(payload));
  localStorage.setItem(PROXY_CONFIG_STORAGE_KEY, JSON.stringify({
    proxyEnabled: payload.proxyEnabled,
    proxyMode: payload.proxyMode,
    proxyPool: payload.proxyPool,
    proxyApiUrl: payload.proxyApiUrl,
  }));
}

function setInputValue(id, value) {
  const el = $(id);
  if (el) el.value = value || "";
}

function loadRunForm() {
  let payload = {};
  let proxyCfg = {};
  try {
    payload = JSON.parse(localStorage.getItem(RUN_FORM_STORAGE_KEY) || "{}") || {};
  } catch (err) {
    payload = {};
  }
  try {
    proxyCfg = JSON.parse(localStorage.getItem(PROXY_CONFIG_STORAGE_KEY) || "{}") || {};
  } catch (err) {
    proxyCfg = {};
  }

  if ($("#baToken")) $("#baToken").value = payload.baToken || "";
  if ($("#phone")) $("#phone").value = payload.phone || "";
  if ($("#country") && payload.country) $("#country").value = payload.country;
  if ($("#maxCardAttempts")) $("#maxCardAttempts").value = payload.maxCardAttempts || "5";
  if ($("#maxPhoneChanges")) $("#maxPhoneChanges").value = payload.maxPhoneChanges || "5";
  if ($("#debug")) $("#debug").checked = Boolean(payload.debug);
  if ($("#smsProvider")) $("#smsProvider").value = payload.smsProvider || "manual";
  if ($("#herosmsApiKey")) $("#herosmsApiKey").value = payload.herosmsApiKey || "";
  if ($("#herosmsBaseUrl")) $("#herosmsBaseUrl").value = payload.herosmsBaseUrl || "";
  setInputValue("#herosmsService", payload.herosmsService || "ot");
  setInputValue("#herosmsCountry", payload.herosmsCountry || "73");
  if ($("#smsbowerApiKey")) $("#smsbowerApiKey").value = payload.smsbowerApiKey || "";
  if ($("#smsbowerBaseUrl")) $("#smsbowerBaseUrl").value = payload.smsbowerBaseUrl || "";
  setInputValue("#smsbowerService", payload.smsbowerService || "ot");
  setInputValue("#smsbowerCountry", payload.smsbowerCountry || "73");
  if ($("#smsTimeoutSeconds")) $("#smsTimeoutSeconds").value = payload.smsTimeoutSeconds || "60";
  if ($("#proxyEnabled")) {
    $("#proxyEnabled").checked = Boolean(
      payload.proxyEnabled ?? proxyCfg.proxyEnabled
    );
  }
  if ($("#proxyMode")) {
    $("#proxyMode").value = payload.proxyMode || proxyCfg.proxyMode || "api";
  }
  if ($("#proxyPool")) {
    $("#proxyPool").value = payload.proxyPool || proxyCfg.proxyPool || "";
  }
  if ($("#proxyApiUrl")) {
    $("#proxyApiUrl").value = payload.proxyApiUrl || proxyCfg.proxyApiUrl || "";
  }
  syncSmsPanel();
  syncProxyPanel();
}

function saveProxyConfig() {
  saveRunForm();
  toast("代理配置已保存到浏览器");
}

function syncProxyPanel() {
  const panel = $("#proxyPanel");
  const enabled = $("#proxyEnabled");
  const mode = $("#proxyMode")?.value || "api";
  if (panel && enabled) panel.classList.toggle("hidden", !enabled.checked);
  const apiBox = $("#proxyApiBox");
  const poolBox = $("#proxyPoolBox");
  const apiSave = $("#proxyApiSaveRow");
  if (apiBox) apiBox.classList.toggle("hidden", mode !== "api");
  if (poolBox) poolBox.classList.toggle("hidden", mode !== "pool");
  if (apiSave) apiSave.classList.toggle("hidden", mode !== "api");
}

function syncSmsPanel() {
  const provider = $("#smsProvider")?.value || "manual";
  const phone = $("#phone");
  if (phone) {
    phone.required = provider === "manual";
    phone.placeholder = provider === "manual" ? "+5591980133818" : "自动模式可留空，平台会先取号";
  }
}

function openSettingsModal() {
  $("#settingsModal")?.classList.remove("hidden");
}

function closeSettingsModal() {
  saveRunForm();
  $("#settingsModal")?.classList.add("hidden");
}

function smsDomPrefix(provider) {
  return provider === "herosms" ? "herosms" : "smsbower";
}

function currentSmsProvider() {
  const provider = $("#smsProvider")?.value || "manual";
  return provider === "herosms" ? "herosms" : provider === "smsbower" ? "smsbower" : "manual";
}

function smsProviderPayload(provider) {
  const prefix = smsDomPrefix(provider);
  return {
    sms_provider: provider,
    [`${prefix}_api_key`]: $(`#${prefix}ApiKey`)?.value || "",
    [`${prefix}_base_url`]: $(`#${prefix}BaseUrl`)?.value || "",
    [`${prefix}_service`]: smsInputValue(provider, "services"),
    [`${prefix}_country`]: smsInputValue(provider, "countries"),
    country: smsInputValue(provider, "countries"),
  };
}

function optionText(option) {
  const code = option.code || "";
  const label = option.label || code;
  return code && label !== code ? `${label} (${code})` : label;
}

function smsOptionDisplay(provider, kind, option) {
  return option.label || option.code || "";
}

function findSmsOption(provider, kind, value) {
  const text = String(value || "").trim().toLowerCase();
  if (!text) return null;
  const rows = state.smsOptions[provider]?.[kind] || [];
  return rows.find(row => {
    return [
      row.code || "",
      row.label || "",
      optionText(row),
      smsOptionDisplay(provider, kind, row),
    ].some(candidate => String(candidate).trim().toLowerCase() === text);
  }) || null;
}

function smsInputValue(provider, kind) {
  const prefix = smsDomPrefix(provider);
  const suffix = kind === "countries" ? "Country" : "Service";
  const input = $(`#${prefix}${suffix}`);
  const value = input?.value.trim() || "";
  const row = findSmsOption(provider, kind, value);
  return row?.code || value;
}

function syncSmsInputDisplay(provider, kind) {
  const prefix = smsDomPrefix(provider);
  const suffix = kind === "countries" ? "Country" : "Service";
  const input = $(`#${prefix}${suffix}`);
  if (!input?.value.trim()) return;
  const row = findSmsOption(provider, kind, input.value);
  if (row) input.value = smsOptionDisplay(provider, kind, row);
}

function renderSmsSelect(provider, kind) {
  const prefix = smsDomPrefix(provider);
  const suffix = kind === "countries" ? "Country" : "Service";
  const input = $(`#${prefix}${suffix}`);
  const list = $(`#${prefix}${suffix}Options`);
  if (!input || !list) return;
  const current = input.value || "";
  const filter = current.trim().toLowerCase();
  const rows = state.smsOptions[provider]?.[kind] || [];
  const filtered = rows.filter(row => {
    const text = smsOptionDisplay(provider, kind, row).toLowerCase();
    return !filter || text.includes(filter);
  }).slice(0, 300);
  list.innerHTML = "";
  const source = filtered.length ? filtered : (current ? [{ code: current, label: current }] : []);
  source.forEach(row => {
    const opt = document.createElement("option");
    opt.value = smsOptionDisplay(provider, kind, row);
    list.appendChild(opt);
  });
}

function setSmsOptionsStatus(text, bad = false) {
  const el = $("#smsOptionsStatus");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("bad-text", Boolean(bad));
}

async function refreshSmsOptions(provider = currentSmsProvider(), silent = false) {
  if (provider === "manual") return;
  const prefix = smsDomPrefix(provider);
  const apiKey = $(`#${prefix}ApiKey`)?.value.trim() || "";
  if (!apiKey) {
    if (!silent) toast("请先填写接码平台 API Key");
    return;
  }
  try {
    setSmsOptionsStatus("正在拉取接码平台 service / country...");
    const data = await api("/api/sms/options", {
      method: "POST",
      body: JSON.stringify(smsProviderPayload(provider)),
    });
    state.smsOptions[provider] = {
      countries: data.countries || [],
      services: data.services || [],
    };
    syncSmsInputDisplay(provider, "countries");
    syncSmsInputDisplay(provider, "services");
    renderSmsSelect(provider, "countries");
    renderSmsSelect(provider, "services");
    setSmsOptionsStatus(`已加载 ${provider}：${state.smsOptions[provider].services.length} 个 service，${state.smsOptions[provider].countries.length} 个 country`);
    saveRunForm();
  } catch (err) {
    setSmsOptionsStatus(err.message || "接码选项加载失败", true);
    if (!silent) toast(err.message);
  }
}

async function refreshConfiguredSmsOptions(silent = false) {
  const providers = ["herosms", "smsbower"].filter(provider => {
    const prefix = smsDomPrefix(provider);
    return Boolean($(`#${prefix}ApiKey`)?.value.trim());
  });
  if (!providers.length) {
    if (!silent) toast("请先填写至少一个接码平台 API Key");
    return;
  }
  const current = currentSmsProvider();
  const ordered = providers.includes(current)
    ? [current, ...providers.filter(provider => provider !== current)]
    : providers;
  for (const provider of ordered) {
    await refreshSmsOptions(provider, true);
  }
  if (!silent) toast("接码选项已刷新");
}

function scheduleSmsOptionsRefresh(provider) {
  clearTimeout(state.smsOptionTimers[provider]);
  state.smsOptionTimers[provider] = setTimeout(() => {
    saveRunForm();
    refreshSmsOptions(provider, true);
  }, 800);
}

async function startJob(evt) {
  evt.preventDefault();
  saveRunForm();
  const btn = $("#startBtn");
  btn.disabled = true;
  btn.textContent = "启动中…";
  try {
    const data = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        ba_token: $("#baToken").value,
        phone: $("#phone").value,
        country: $("#country").value,
        max_card_attempts: Number($("#maxCardAttempts").value || 5),
        max_phone_changes: Number($("#maxPhoneChanges")?.value || 5),
        debug: $("#debug").checked,
        sms_provider: $("#smsProvider")?.value || "manual",
        herosms_api_key: $("#herosmsApiKey")?.value || "",
        herosms_base_url: $("#herosmsBaseUrl")?.value || "",
        herosms_service: smsInputValue("herosms", "services"),
        herosms_country: smsInputValue("herosms", "countries"),
        smsbower_api_key: $("#smsbowerApiKey")?.value || "",
        smsbower_base_url: $("#smsbowerBaseUrl")?.value || "",
        smsbower_service: smsInputValue("smsbower", "services"),
        smsbower_country: smsInputValue("smsbower", "countries"),
        sms_timeout_seconds: Number($("#smsTimeoutSeconds")?.value || 60),
        proxy_enabled: $("#proxyEnabled").checked,
        proxy_mode: $("#proxyMode")?.value || "api",
        proxy_pool_text: $("#proxyPool")?.value || "",
        proxy_api_url: $("#proxyApiUrl")?.value || "",
      }),
    });
    toast("任务已启动");
    selectJob(data.job.id);
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "开始执行";
  }
}

async function submitOtp(evt) {
  evt.preventDefault();
  if (!state.currentJobId) return;
  const value = $("#otpValue").value.trim();
  if (!value) return toast("请输入验证码或手机号");
  try {
    await api(`/api/jobs/${state.currentJobId}/otp`, {
      method: "POST",
      body: JSON.stringify({ value }),
    });
    $("#otpValue").value = "";
    toast("已提交");
    pollCurrent(true);
  } catch (err) {
    toast(err.message);
  }
}

async function copyResult() {
  if (!state.currentJobId) return;
  try {
    const job = await api(`/api/jobs/${state.currentJobId}`);
    await navigator.clipboard.writeText(pretty(job.result || { error: job.error, traceback: job.traceback }));
    toast("结果已复制");
  } catch (err) {
    toast(err.message);
  }
}

async function copyLogs() {
  const text = $("#logsBox")?.textContent || "";
  if (!text.trim()) return toast("暂无日志可复制");
  try {
    await navigator.clipboard.writeText(text);
    toast("日志已复制");
  } catch (err) {
    toast(err.message || "复制日志失败");
  }
}

function bind() {
  $("#runForm")?.addEventListener("submit", startJob);
  $("#otpForm")?.addEventListener("submit", submitOtp);
  $("#refreshJobs")?.addEventListener("click", refreshJobs);
  $("#copyResult")?.addEventListener("click", copyResult);
  $("#copyLogs")?.addEventListener("click", copyLogs);
  $("#clearCurrent")?.addEventListener("click", () => selectJob(""));
  $("#openSettings")?.addEventListener("click", openSettingsModal);
  $("#closeSettings")?.addEventListener("click", closeSettingsModal);
  $("#settingsModal")?.addEventListener("click", event => {
    if (event.target?.id === "settingsModal") closeSettingsModal();
  });
  $("#smsProvider")?.addEventListener("change", () => {
    syncSmsPanel();
    saveRunForm();
    refreshSmsOptions(currentSmsProvider(), true);
  });
  $("#refreshSmsOptions")?.addEventListener("click", () => refreshConfiguredSmsOptions(false));
  ["herosms", "smsbower"].forEach(provider => {
    const prefix = smsDomPrefix(provider);
    $(`#${prefix}ApiKey`)?.addEventListener("change", () => {
      saveRunForm();
      refreshSmsOptions(provider, true);
    });
    $(`#${prefix}ApiKey`)?.addEventListener("input", () => scheduleSmsOptionsRefresh(provider));
    $(`#${prefix}BaseUrl`)?.addEventListener("change", () => {
      saveRunForm();
      refreshSmsOptions(provider, true);
    });
    $(`#${prefix}Country`)?.addEventListener("input", () => {
      renderSmsSelect(provider, "countries");
      saveRunForm();
    });
    $(`#${prefix}Country`)?.addEventListener("change", () => {
      saveRunForm();
      refreshSmsOptions(provider, true);
    });
    $(`#${prefix}Service`)?.addEventListener("input", () => {
      renderSmsSelect(provider, "services");
      saveRunForm();
    });
    $(`#${prefix}Service`)?.addEventListener("change", saveRunForm);
  });
  $("#proxyEnabled")?.addEventListener("change", () => {
    syncProxyPanel();
    saveRunForm();
  });
  $("#proxyMode")?.addEventListener("change", () => {
    syncProxyPanel();
    saveRunForm();
  });
  $("#saveProxyConfig")?.addEventListener("click", saveProxyConfig);
  $("#saveProxyConfigApi")?.addEventListener("click", saveProxyConfig);
}

try {
  loadRunForm();
  bind();
  refreshConfiguredSmsOptions(true);
  health();
  refreshJobs().then(() => pollCurrent(true));
  setInterval(health, 8000);
  setInterval(refreshJobs, 5000);
  state.pollTimer = setInterval(() => pollCurrent(false), 1000);
} catch (err) {
  console.error(err);
  const el = $("#serverStatus");
  if (el) {
    el.textContent = "前端脚本异常";
    el.classList.add("bad");
  }
}
