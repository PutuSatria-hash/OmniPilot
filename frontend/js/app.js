/**
 * Presentational controller for OmniPilot Hub Glassmorphism PWA.
 */
import { alarmAudio } from "./alarmAudio.js";
import { api } from "./api.js";
import { store } from "./state.js";

const $ = (id) => document.getElementById(id);

let screenTimer = null;
let activeWs = null;

function showToast(text) {
  const container = $("toast-container");
  const node = document.createElement("div");
  node.className = "toast";
  node.textContent = text;
  container.appendChild(node);
  setTimeout(() => node.remove(), 3600);
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function formatRemaining(deadlineIso) {
  const diffSec = Math.floor((new Date(deadlineIso).getTime() - Date.now()) / 1000);
  if (diffSec <= 0) return "WAKTU HABIS";
  const m = Math.floor(diffSec / 60);
  const s = diffSec % 60;
  return `${m}m ${String(s).padStart(2, "0")}d`;
}

// ------------------------------------------------------------------
// Renderers
// ------------------------------------------------------------------
function render(state) {
  // Connection status
  const dot = $("conn-dot");
  dot.className = `dot ${state.connected ? "dot-online" : "dot-offline"}`;
  $("conn-label").textContent = state.connected ? "Terhubung Real-Time" : "Mode Sinkronisasi";

  // AI Mode Pill
  if (state.modules) {
    const count = (state.modules.ai_providers || []).length;
    const last = state.modules.last_ai_model ? ` (${state.modules.last_ai_model})` : "";
    $("ai-mode-pill").textContent = count > 0 ? `AI Waterfall: ${count} Provider${last}` : "Mode Command Lokal";
  }

  // Telemetry
  if (state.telemetry) {
    const t = state.telemetry;
    $("pc-hostname").textContent = `${t.hostname} (${t.os})`;
    $("metric-cpu").textContent = `${t.cpu_percent}%`;
    $("metric-ram").textContent = `${t.ram_percent}%`;
    $("metric-battery").textContent =
      t.battery_percent !== null ? `${t.battery_percent}%` : "AC Power";
    $("metric-tailscale").textContent = t.tailscale_ip || "Belum aktif";
    $("metric-local-ip").textContent = t.local_ip || "-";
    const pubNode = $("metric-public-url");
    if (pubNode) {
      pubNode.textContent = t.campus_tunnel_url || "Jalankan 3_START_CAMPUS_TUNNEL.bat";
    }
    $("remote-rustdesk-id").textContent = t.rustdesk_id || "Isi RUSTDESK_PC_ID di .env";
    $("remote-sunshine-ip").textContent = t.sunshine_host || t.local_ip || "-";
  }

  // Phone Presence
  if (state.phonePresence) {
    const p = state.phonePresence;
    $("metric-phone").textContent = p.seen ? `${p.inactive_minutes} mnt lalu` : "Belum ada";
  }

  // Critical Alarm Banner
  const critical = state.activeAlarms.find((a) => a.status === "CRITICAL");
  const banner = $("critical-alarm-banner");
  if (critical) {
    banner.classList.remove("hidden");
    $("critical-alarm-title").textContent = `${critical.title} — ${critical.message}`;
    alarmAudio.start();
  } else {
    banner.classList.add("hidden");
    alarmAudio.stop();
  }

  // Approvals Badge
  const pendingCount = state.approvals.filter((a) => a.status === "PENDING").length;
  const badge = $("approval-badge");
  badge.textContent = String(pendingCount);
  badge.classList.toggle("hidden", pendingCount === 0);

  renderAlarms(state.activeAlarms);
  renderSchedules(state.todaySchedule);
  renderApprovals(state.approvals);
  renderDocuments(state.documents);
  renderChat(state.messages);
}

function renderAlarms(alarms) {
  const html = alarms.length
    ? alarms
        .map(
          (a) => `
          <div class="item-card status-${escapeHtml(a.status)}">
            <div>
              <strong>${escapeHtml(a.title)}</strong>
              <p class="muted-sm">${escapeHtml(a.status)} | Sisa: ${formatRemaining(a.deadline_at)}</p>
            </div>
            <button class="btn btn-sm btn-ghost-cyan" data-ack-alarm="${escapeHtml(a.id)}">Saya Sudah Cek</button>
          </div>`
        )
        .join("")
    : `<p class="muted-sm">Tidak ada alarm aktif. Semua aman, Boss.</p>`;

  $("overview-alarms").innerHTML = html;
  $("full-alarms-list").innerHTML = html;
}

function renderSchedules(scheduleData) {
  $("today-date-label").textContent = scheduleData.date || "-";
  const events = scheduleData.events || [];
  const html = events.length
    ? events
        .map(
          (ev) => `
          <div class="item-card">
            <div>
              <strong>${escapeHtml(ev.start_time)} — ${escapeHtml(ev.title)}</strong>
              <p class="muted-sm">${escapeHtml(ev.description || ev.category || "Agenda")}</p>
            </div>
            ${
              ev.source === "local"
                ? `<button class="btn btn-sm btn-danger" data-del-schedule="${escapeHtml(ev.id)}">Hapus</button>`
                : `<span class="badge-pill">Google Calendar</span>`
            }
          </div>`
        )
        .join("")
    : `<p class="muted-sm">Belum ada agenda untuk hari ini.</p>`;

  $("overview-schedules").innerHTML = html;
  $("full-schedules-list").innerHTML = html;
}

function renderApprovals(approvals) {
  const list = $("approvals-list");
  if (!approvals.length) {
    list.innerHTML = `<p class="muted-sm">Belum ada permintaan persetujuan.</p>`;
    return;
  }
  list.innerHTML = approvals
    .map(
      (item) => `
      <div class="item-card">
        <div>
          <strong>[${escapeHtml(item.status)}] ${escapeHtml(item.title)}</strong>
          <p class="muted-sm" style="white-space: pre-wrap; margin-top: 4px;">${escapeHtml(item.summary)}</p>
          ${item.result_text ? `<p class="muted-sm">Hasil: ${escapeHtml(item.result_text)}</p>` : ""}
        </div>
        ${
          item.status === "PENDING"
            ? `<div class="row-gap">
                <button class="btn btn-sm btn-success" data-approve="${escapeHtml(item.id)}">Approve</button>
                <button class="btn btn-sm btn-danger" data-reject="${escapeHtml(item.id)}">Tolak</button>
              </div>`
            : ""
        }
      </div>`
    )
    .join("");
}

function renderDocuments(docs) {
  const container = $("docs-list");
  if (!docs.length) {
    container.innerHTML = `<p class="muted-sm">Belum ada dokumen tersimpan.</p>`;
    return;
  }
  container.innerHTML = docs
    .map(
      (doc) => `
      <div class="item-card">
        <div>
          <strong>${escapeHtml(doc.filename)}</strong>
          <p class="muted-sm">${(doc.size_bytes / 1024).toFixed(1)} KB</p>
        </div>
        <a class="btn btn-sm btn-ghost-cyan" href="${api.downloadDocUrl(doc.filename)}" target="_blank">Unduh</a>
      </div>`
    )
    .join("");
}

function renderChat(messages) {
  const feed = $("chat-feed");
  if (!messages.length) {
    feed.innerHTML = `<div class="bubble bubble-assistant">Siap, Boss. Kirim perintah atau pilih salah satu tombol cepat di atas.</div>`;
    return;
  }
  feed.innerHTML = messages
    .map(
      (m) =>
        `<div class="bubble ${m.role === "user" ? "bubble-user" : "bubble-assistant"}">${escapeHtml(m.content)}</div>`
    )
    .join("");
  feed.scrollTop = feed.scrollHeight;
}

// ------------------------------------------------------------------
// Data Synchronization
// ------------------------------------------------------------------
async function refreshAll() {
  try {
    const [status, history, approvalsRes, docsRes] = await Promise.all([
      api.getStatus(),
      api.getChatHistory(),
      api.getApprovals(),
      api.getDocuments(),
    ]);

    store.setState({
      telemetry: status.telemetry,
      phonePresence: status.phone_presence,
      todaySchedule: status.today_schedule,
      activeAlarms: status.active_alarms,
      modules: status.modules,
      messages: history.messages,
      approvals: approvalsRes.approvals,
      documents: docsRes.documents,
    });
    $("auth-modal").classList.add("hidden");
  } catch (err) {
    if (err.message === "UNAUTHORIZED") {
      $("auth-modal").classList.remove("hidden");
      $("auth-error").textContent = "Token tidak valid atau belum dimasukkan.";
      $("auth-error").classList.remove("hidden");
    } else {
      showToast(`Gagal sinkronisasi: ${err.message}`);
    }
  }
}

function refreshScreen() {
  const img = $("live-screen-img");
  const placeholder = $("screen-placeholder");
  img.onload = () => {
    img.classList.add("loaded");
    placeholder.classList.add("hidden");
  };
  img.onerror = () => showToast("Gagal mengambil tangkapan layar PC.");
  img.src = api.screenshotUrl();
}

// ------------------------------------------------------------------
// Event Wiring
// ------------------------------------------------------------------
function bindEvents() {
  // Navigation tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${target}`));
      store.setState({ activeTab: target });
    });
  });

  // Auth modal & Zero-Trace Logout (PC Lab Kampus safe)
  $("btn-open-auth").addEventListener("click", () => {
    $("auth-token-input").value = store.getState().token;
    $("auth-lab-mode").checked = store.getState().labMode;
    $("auth-error").classList.add("hidden");
    $("auth-modal").classList.remove("hidden");
  });

  $("btn-logout").addEventListener("click", () => {
    localStorage.removeItem("omnipilot_token");
    sessionStorage.removeItem("omnipilot_token");
    if (screenTimer) clearInterval(screenTimer);
    if (activeWs) {
      try { activeWs.close(); } catch {}
      activeWs = null;
    }
    alarmAudio.stop();
    store.setState({ token: "", connected: false, autoScreen: false });
    $("auth-token-input").value = "";
    $("auth-modal").classList.remove("hidden");
    showToast("Sesi & token dihapus dari browser. Aman meninggalkan PC Lab.");
  });

  $("auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const token = $("auth-token-input").value.trim();
    const labMode = $("auth-lab-mode").checked;
    if (labMode) {
      localStorage.removeItem("omnipilot_token");
      sessionStorage.setItem("omnipilot_token", token);
    } else {
      sessionStorage.removeItem("omnipilot_token");
      localStorage.setItem("omnipilot_token", token);
    }
    store.setState({ token, labMode });
    await refreshAll();
    if ($("auth-modal").classList.contains("hidden")) {
      activeWs = api.connectWebSocket(handleWsEvent);
      showToast(labMode ? "Masuk dalam Mode PC Lab (sesi sementara)." : "Terhubung ke OmniPilot Hub, Boss.");
    }
  });

  // Phone Check-In
  $("btn-phone-checkin").addEventListener("click", async () => {
    try {
      await api.sendPhoneHeartbeat("manual_pwa_checkin");
      showToast("Status cek HP tercatat. Timer alarm diperbarui.");
      await refreshAll();
    } catch (err) {
      showToast(err.message);
    }
  });

  // Chat submit & Quick chips
  const submitPrompt = async (promptText) => {
    const trimmed = promptText.trim();
    if (!trimmed) return;
    if (trimmed.toLowerCase() === "/screen") {
      document.querySelector('.tab-btn[data-tab="remote"]')?.click();
      refreshScreen();
      showToast("Memuat tampilan layar laptop Boss...");
      return;
    }
    const prev = store.getState().messages;
    store.setState({ messages: [...prev, { role: "user", content: trimmed }] });
    try {
      const res = await api.sendChat(trimmed);
      const curr = store.getState().messages;
      store.setState({ messages: [...curr, { role: "assistant", content: res.reply }] });
      await refreshAll();
    } catch (err) {
      showToast(`Error chat: ${err.message}`);
    }
  };

  $("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("chat-input");
    const val = input.value;
    input.value = "";
    await submitPrompt(val);
  });

  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => submitPrompt(chip.dataset.prompt));
  });

  // Quick 5m alarm button
  $("btn-quick-arm").addEventListener("click", async () => {
    await api.armAlarm({
      title: "Timer Cek HP Cepat (5 Menit)",
      message: "Konfirmasi cek HP sebelum alarm darurat berbunyi.",
      timeout_minutes: 5,
    });
    showToast("Smart Alarm 5 menit diaktifkan, Boss.");
    await refreshAll();
  });

  // Schedule creation
  $("schedule-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api.createSchedule({
        title: $("sched-title").value.trim(),
        event_date: $("sched-date").value,
        start_time: $("sched-time").value,
        alarm_timeout_minutes: Number($("sched-timeout").value) || 5,
        category: $("sched-category").value,
        description: $("sched-desc").value.trim(),
        alarm_enabled: true,
      });
      $("sched-title").value = "";
      $("sched-desc").value = "";
      showToast("Jadwal hari ini tersimpan, Boss.");
      await refreshAll();
    } catch (err) {
      showToast(err.message);
    }
  });

  // Custom Alarm form
  $("alarm-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api.armAlarm({
        title: $("alarm-title").value.trim(),
        timeout_minutes: Number($("alarm-timeout").value) || 5,
        message: $("alarm-message").value.trim(),
      });
      $("alarm-title").value = "";
      showToast("Smart Escalation Alarm diaktifkan, Boss.");
      await refreshAll();
    } catch (err) {
      showToast(err.message);
    }
  });

  // Global ACK buttons
  const ackAllHandler = async () => {
    await api.ackAllAlarms();
    alarmAudio.stop();
    showToast("Semua alarm aktif dimatikan, Boss.");
    await refreshAll();
  };
  $("btn-ack-all-banner").addEventListener("click", ackAllHandler);
  $("btn-ack-all-tab").addEventListener("click", ackAllHandler);

  // Delegated click handlers for dynamic cards
  document.body.addEventListener("click", async (e) => {
    const ackId = e.target.dataset?.ackAlarm;
    if (ackId) {
      await api.ackAlarm(ackId);
      showToast("Alarm dikonfirmasi & dimatikan.");
      await refreshAll();
      return;
    }
    const delId = e.target.dataset?.delSchedule;
    if (delId) {
      await api.deleteSchedule(delId);
      showToast("Jadwal dihapus.");
      await refreshAll();
      return;
    }
    const aprId = e.target.dataset?.approve;
    if (aprId) {
      const res = await api.approveAction(aprId);
      showToast(`Disetujui: ${res.status}`);
      await refreshAll();
      return;
    }
    const rejId = e.target.dataset?.reject;
    if (rejId) {
      await api.rejectAction(rejId);
      showToast("Permintaan dibatalkan.");
      await refreshAll();
    }
  });

  // Remote Screen, Interactive Mouse & Keyboard Control (PC Lab / HP)
  $("btn-refresh-screen").addEventListener("click", refreshScreen);
  $("btn-toggle-autoscreen").addEventListener("click", () => {
    const next = !store.getState().autoScreen;
    store.setState({ autoScreen: next });
    $("btn-toggle-autoscreen").textContent = `Auto: ${next ? "ON (2s)" : "OFF"}`;
    if (screenTimer) clearInterval(screenTimer);
    if (next) {
      refreshScreen();
      screenTimer = setInterval(refreshScreen, 2000);
    }
  });

  $("btn-toggle-control").addEventListener("click", () => {
    const next = !store.getState().interactiveControl;
    store.setState({ interactiveControl: next });
    $("btn-toggle-control").textContent = `Klik Layar: ${next ? "ON" : "OFF"}`;
    $("screen-frame").classList.toggle("interactive", next);
  });

  $("live-screen-img").addEventListener("click", async (e) => {
    if (!store.getState().interactiveControl) return;
    const img = $("live-screen-img");
    const rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    const xRatio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const yRatio = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    const mode = $("mouse-click-mode").value;

    const frameRect = $("screen-frame").getBoundingClientRect();
    const ripple = $("click-ripple");
    ripple.style.left = `${e.clientX - frameRect.left}px`;
    ripple.style.top = `${e.clientY - frameRect.top}px`;
    ripple.classList.remove("hidden");
    ripple.style.animation = "none";
    void ripple.offsetWidth;
    ripple.style.animation = "";

    try {
      await api.sendMouseAction(mode, xRatio, yRatio);
      setTimeout(refreshScreen, 350);
    } catch (err) {
      showToast(`Kontrol mouse gagal: ${err.message}`);
    }
  });

  document.querySelectorAll(".btn-scroll").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api.sendMouseAction("scroll", 0.5, 0.5, Number(btn.dataset.delta));
        setTimeout(refreshScreen, 300);
      } catch (err) {
        showToast(err.message);
      }
    });
  });

  $("btn-lock-pc").addEventListener("click", async () => {
    try {
      await api.lockPC();
      showToast("Layar laptop rumah berhasil dikunci, Boss.");
    } catch (err) {
      showToast(err.message);
    }
  });

  $("remote-type-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("remote-type-input");
    const text = input.value;
    if (!text) return;
    input.value = "";
    try {
      await api.sendKeyboardAction({ text });
      setTimeout(refreshScreen, 350);
    } catch (err) {
      showToast(`Ketik gagal: ${err.message}`);
    }
  });

  document.querySelectorAll(".btn-hotkey").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api.sendKeyboardAction({ hotkey: btn.dataset.hotkey });
        setTimeout(refreshScreen, 350);
      } catch (err) {
        showToast(`Shortcut gagal: ${err.message}`);
      }
    });
  });

  document.querySelectorAll(".action-launch").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api.launchApp(btn.dataset.app);
        showToast(`Membuka ${btn.dataset.app} di laptop Boss...`);
      } catch (err) {
        showToast(err.message);
      }
    });
  });

  $("shell-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const cmd = $("shell-input").value.trim();
    if (!cmd) return;
    const out = $("shell-output");
    out.classList.remove("hidden");
    out.textContent = "Menjalankan perintah di laptop...";
    try {
      const res = await api.runShell(cmd);
      out.textContent =
        res.status === "pending_approval"
          ? `${res.message} (ID: ${res.approval_id})`
          : res.stdout || res.stderr || `(selesai, exit code ${res.exit_code})`;
      await refreshAll();
    } catch (err) {
      out.textContent = `Error: ${err.message}`;
    }
  });

  // Document generator
  $("doc-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await api.createDocument({
        title: $("doc-title").value.trim(),
        subtitle: $("doc-subtitle").value.trim(),
        fmt: $("doc-format").value,
        sections: [
          {
            heading: $("doc-heading").value.trim(),
            content: $("doc-content").value.trim(),
            bullets: [],
          },
        ],
      });
      $("doc-title").value = "";
      $("doc-content").value = "";
      showToast(`Dokumen dibuat: ${res.filename}`);
      await refreshAll();
    } catch (err) {
      showToast(err.message);
    }
  });

  $("btn-refresh-approvals").addEventListener("click", refreshAll);
  $("btn-refresh-docs").addEventListener("click", refreshAll);
}

function handleWsEvent(evt) {
  if (evt.type === "alarm_critical") {
    showToast(`ALARM DARURAT: ${evt.payload.title}`);
  } else if (evt.type === "approval_requested") {
    showToast(`Butuh persetujuan Boss: ${evt.payload.title}`);
  }
  refreshAll();
}

// ------------------------------------------------------------------
// Bootstrap
// ------------------------------------------------------------------
async function init() {
  $("sched-date").value = new Date().toISOString().slice(0, 10);
  store.subscribe(render);
  bindEvents();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  // Update countdown labels smoothly every second
  setInterval(() => {
    const alarms = store.getState().activeAlarms;
    if (alarms.length) renderAlarms(alarms);
  }, 1000);

  // Support deep link ?token=... from Laptop QR code!
  const urlParams = new URLSearchParams(window.location.search);
  const queryToken = urlParams.get("token");
  if (queryToken) {
    localStorage.setItem("omnipilot_token", queryToken);
    store.setState({ token: queryToken });
    window.history.replaceState({}, document.title, "/");
  }

  if (!store.getState().token) {
    $("auth-modal").classList.remove("hidden");
    return;
  }

  await refreshAll();
  activeWs = api.connectWebSocket(handleWsEvent);
  setInterval(refreshAll, 25000);
}

init();
