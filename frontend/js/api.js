/**
 * API & WebSocket transport layer for OmniPilot Hub.
 */
import { store } from "./state.js";

export class ApiClient {
  get token() {
    return store.getState().token;
  }

  async request(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const response = await fetch(path, { ...options, headers });
    if (response.status === 401) {
      throw new Error("UNAUTHORIZED");
    }
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const err = await response.json();
        detail = err.detail || detail;
      } catch {
        // ignore JSON parse failure
      }
      throw new Error(detail);
    }
    return response.json();
  }

  getStatus() {
    return this.request("/api/status");
  }

  getChatHistory() {
    return this.request("/api/chat/history");
  }

  sendChat(prompt) {
    return this.request("/api/chat", {
      method: "POST",
      body: JSON.stringify({ prompt, channel: "web" }),
    });
  }

  createSchedule(data) {
    return this.request("/api/schedules", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  deleteSchedule(id) {
    return this.request(`/api/schedules/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  armAlarm(data) {
    return this.request("/api/alarms/arm", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  ackAlarm(id) {
    return this.request(`/api/alarms/${encodeURIComponent(id)}/ack`, {
      method: "POST",
    });
  }

  ackAllAlarms() {
    return this.request("/api/alarms/ack-all", { method: "POST" });
  }

  sendPhoneHeartbeat(eventType = "pwa_checkin") {
    return this.request("/api/phone/heartbeat", {
      method: "POST",
      body: JSON.stringify({ event_type: eventType, device_name: "pwa", auto_ack_alarms: true }),
    });
  }

  getApprovals() {
    return this.request("/api/approvals");
  }

  approveAction(id) {
    return this.request(`/api/approvals/${encodeURIComponent(id)}/approve`, { method: "POST" });
  }

  rejectAction(id) {
    return this.request(`/api/approvals/${encodeURIComponent(id)}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: "Ditolak oleh Boss dari PWA" }),
    });
  }

  launchApp(appName) {
    return this.request("/api/pc/launch", {
      method: "POST",
      body: JSON.stringify({ app_name: appName }),
    });
  }

  runShell(command) {
    return this.request("/api/pc/command", {
      method: "POST",
      body: JSON.stringify({ command }),
    });
  }

  sendMouseAction(action, x_ratio = 0.5, y_ratio = 0.5, delta = 0) {
    return this.request("/api/pc/mouse", {
      method: "POST",
      body: JSON.stringify({ action, x_ratio, y_ratio, delta }),
    });
  }

  sendKeyboardAction({ text = null, hotkey = null }) {
    return this.request("/api/pc/keyboard", {
      method: "POST",
      body: JSON.stringify({ text, hotkey }),
    });
  }

  lockPC() {
    return this.request("/api/pc/lock", { method: "POST" });
  }

  getDocuments() {
    return this.request("/api/documents");
  }

  createDocument(data) {
    return this.request("/api/documents", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  screenshotUrl() {
    const q = new URLSearchParams({ token: this.token, t: String(Date.now()) });
    return `/api/pc/screenshot?${q.toString()}`;
  }

  downloadDocUrl(filename) {
    const q = new URLSearchParams({ token: this.token });
    return `/api/documents/download/${encodeURIComponent(filename)}?${q.toString()}`;
  }

  connectWebSocket(onEvent) {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${proto}://${window.location.host}/ws?token=${encodeURIComponent(this.token)}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => store.setState({ connected: true });
    ws.onclose = () => {
      store.setState({ connected: false });
      setTimeout(() => {
        if (store.getState().token) {
          this.connectWebSocket(onEvent);
        }
      }, 4000);
    };
    ws.onmessage = (evt) => {
      try {
        onEvent(JSON.parse(evt.data));
      } catch {
        // ignore malformed event
      }
    };
    return ws;
  }
}

export const api = new ApiClient();
