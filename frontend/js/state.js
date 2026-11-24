/**
 * Centralized reactive store for OmniPilot Hub UI.
 * Prevents prop-drilling and ensures predictable state updates.
 */

const initialState = {
  token: sessionStorage.getItem("omnipilot_token") || localStorage.getItem("omnipilot_token") || "",
  labMode: Boolean(sessionStorage.getItem("omnipilot_token") && !localStorage.getItem("omnipilot_token")),
  connected: false,
  activeTab: "overview",
  telemetry: null,
  phonePresence: null,
  modules: null,
  todaySchedule: { date: "-", events: [] },
  activeAlarms: [],
  approvals: [],
  documents: [],
  messages: [],
  autoScreen: false,
  interactiveControl: true,
};

class Store {
  constructor(seed) {
    this._state = { ...seed };
    this._listeners = new Set();
  }

  getState() {
    return this._state;
  }

  setState(patch) {
    this._state = { ...this._state, ...patch };
    for (const listener of this._listeners) {
      listener(this._state);
    }
  }

  subscribe(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }
}

export const store = new Store(initialState);
