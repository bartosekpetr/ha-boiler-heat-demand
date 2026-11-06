/*
 * Boiler Heat Demand card - served by the boiler_heat_demand integration.
 * Plain web component (shadow DOM), no build step, no dependencies.
 * Colours come only from Home Assistant theme CSS variables.
 */
const CARD_VERSION = "0.1.0";

// Sibling entities of the "Heat demand" binary sensor, found on the same
// device. The integration sets only `_attr_name`, so the entity_id ends with
// the slugified name and the friendly name ends with the English name. A
// per-entity config option always wins over this lookup.
const SIBLINGS = {
  auto_button: { domain: "button", slug: "resume_automatic_control", name: "Resume automatic control" },
  on_button: { domain: "button", slug: "boiler_on", name: "Boiler on" },
  off_button: { domain: "button", slug: "boiler_off", name: "Boiler off" },
  calling_entity: { domain: "sensor", slug: "rooms_calling_for_heat", name: "Rooms calling for heat" },
  pid_entity: { domain: "sensor", slug: "maximum_pid_demand", name: "Maximum PID demand" },
};

const OVERRIDE_KEYS = ["auto_button", "on_button", "off_button", "calling_entity", "pid_entity"];

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; box-sizing: border-box; overflow: hidden; }
  * { box-sizing: border-box; }
  .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
  .title { font-size: 1.2em; font-weight: 500; color: var(--primary-text-color); min-width: 0; overflow-wrap: anywhere; }
  .status { display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 16px;
    border: 1px solid var(--divider-color); color: var(--primary-text-color); font-weight: 500; }
  .status.on { background: var(--state-icon-active-color); border-color: var(--state-icon-active-color); color: var(--text-primary-color, var(--card-background-color)); }
  .status.warn { border: 2px dashed var(--warning-color); }
  .banner { margin-top: 12px; padding: 10px 12px; border-radius: 8px; overflow-wrap: anywhere; }
  .banner[hidden], .row[hidden], .seg button[hidden], .metrics[hidden], .override[hidden] { display: none; }
  .alerts { border: 2px solid var(--error-color); background: var(--card-background-color); color: var(--primary-text-color); }
  .alerts strong { color: var(--error-color); }
  .alerts ul { margin: 6px 0 0; padding-left: 20px; }
  .safety { border: 2px solid var(--warning-color); background: var(--card-background-color); color: var(--primary-text-color); }
  .safety strong { color: var(--warning-color); }
  .seg { display: flex; margin-top: 12px; border: 1px solid var(--divider-color); border-radius: 8px; overflow: hidden; }
  .seg button { flex: 1 1 0; min-width: 0; min-height: 44px; padding: 8px 4px; border: 0; border-left: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color); font: inherit; cursor: pointer; }
  .seg button:first-child { border-left: 0; }
  .seg button[aria-pressed="true"] { background: var(--state-icon-active-color); color: var(--text-primary-color, var(--card-background-color)); font-weight: 600; }
  .seg button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .seg button:disabled { opacity: 0.5; cursor: not-allowed; }
  .override { margin-top: 8px; color: var(--secondary-text-color); }
  .metrics { display: flex; flex-wrap: wrap; gap: 8px 24px; margin-top: 12px; }
  .metric { min-width: 0; }
  .metric .label { font-size: 0.85em; color: var(--secondary-text-color); }
  .metric .value { color: var(--primary-text-color); font-weight: 500; overflow-wrap: anywhere; }
  .hint { color: var(--secondary-text-color); }
`;

function humanize(key) {
  const text = String(key).replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

class BoilerHeatDemandCard extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = undefined;
    this._built = false;
    this._signature = "";
    this._timer = undefined;
    this._ids = {};
    this.attachShadow({ mode: "open" });
  }

  static getConfigElement() {
    return document.createElement("boiler-heat-demand-card-editor");
  }

  static getStubConfig(hass) {
    const states = (hass && hass.states) || {};
    const entity = Object.keys(states).find(
      (id) => id.startsWith("binary_sensor.") && states[id].attributes && "calling_rooms" in states[id].attributes
    );
    return { entity: entity || "" };
  }

  setConfig(config) {
    // Never throw: a bad config renders a hint instead of a broken card.
    this._config = { ...(config || {}) };
    this._signature = "";
    this._render();
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    this._stopTimer();
  }

  _stopTimer() {
    if (this._timer !== undefined) {
      clearInterval(this._timer);
      this._timer = undefined;
    }
  }

  // Entity ids on the same device as the heat demand sensor.
  _resolveIds() {
    const hass = this._hass;
    const cfg = this._config;
    const ids = {};
    const deviceId = hass && hass.entities && cfg.entity && hass.entities[cfg.entity]
      ? hass.entities[cfg.entity].device_id
      : undefined;
    for (const key of OVERRIDE_KEYS) {
      if (cfg[key]) {
        ids[key] = cfg[key];
        continue;
      }
      const want = SIBLINGS[key];
      if (!deviceId || !hass.entities) continue;
      const prefix = `${want.domain}.`;
      const wantName = want.name.toLowerCase();
      ids[key] = Object.keys(hass.entities).find((id) => {
        if (!id.startsWith(prefix) || hass.entities[id].device_id !== deviceId) return false;
        const slug = id.slice(prefix.length);
        if (slug === want.slug || slug.endsWith(`_${want.slug}`)) return true;
        const state = hass.states[id];
        const friendly = state && state.attributes && state.attributes.friendly_name;
        return typeof friendly === "string" && friendly.toLowerCase().endsWith(wantName);
      });
    }
    return ids;
  }

  _build() {
    const root = this.shadowRoot;
    const style = document.createElement("style");
    style.textContent = STYLE;
    const card = document.createElement("ha-card");
    this._card = card;

    const header = el("div", "header");
    this._title = el("div", "title");
    this._status = el("span", "status");
    header.append(this._title, this._status);

    this._hint = el("div", "hint");
    this._hint.hidden = true;

    this._alerts = el("div", "banner alerts");
    this._alerts.setAttribute("role", "alert");
    this._alerts.hidden = true;

    this._safety = el("div", "banner safety");
    this._safety.hidden = true;

    this._seg = el("div", "seg");
    this._seg.setAttribute("role", "group");
    this._seg.setAttribute("aria-label", "Boiler control mode");
    this._buttons = {};
    for (const [mode, key, label] of [
      ["auto", "auto_button", "Auto"],
      ["on", "on_button", "On"],
      ["off", "off_button", "Off"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => this._press(key));
      this._buttons[mode] = { key, button };
      this._seg.append(button);
    }

    this._override = el("div", "override");
    this._override.setAttribute("aria-live", "off");
    this._override.hidden = true;

    this._metrics = el("div", "metrics");
    this._metrics.hidden = true;

    card.append(header, this._hint, this._alerts, this._safety, this._seg, this._override, this._metrics);
    root.append(style, card);
    this._built = true;
  }

  _press(key) {
    const id = this._ids[key];
    if (!id || !this._hass) return;
    this._hass.callService("button", "press", { entity_id: id });
  }

  _render() {
    if (!this._built) this._build();
    const hass = this._hass;
    const cfg = this._config;
    if (!hass) return;

    if (!cfg.entity) {
      this._setHint("Choose the “Heat demand” binary sensor of Boiler Heat Demand in the card editor.");
      return;
    }
    const ids = this._resolveIds();
    this._ids = ids;
    const main = hass.states[cfg.entity];

    // Skip work unless something this card shows has changed (hass updates on every state change in HA).
    const used = [cfg.entity, ...OVERRIDE_KEYS.map((k) => ids[k])];
    const signature = used.map((id) => (id && hass.states[id] ? hass.states[id].last_updated + hass.states[id].state : "-")).join("|")
      + `|${cfg.name || ""}|${main ? "1" : "0"}`;
    if (signature === this._signature) return;
    this._signature = signature;

    if (!main) {
      this._setHint(`Entity ${cfg.entity} not found.`);
      return;
    }
    this._hint.hidden = true;
    this._paint(main, ids);
  }

  _setHint(text) {
    this._hint.textContent = text;
    this._hint.hidden = false;
    for (const node of [this._alerts, this._safety, this._seg, this._override, this._metrics]) node.hidden = true;
    this._title.textContent = this._config.name || "Boiler";
    this._status.textContent = "";
    this._stopTimer();
  }

  _paint(main, ids) {
    const hass = this._hass;
    const attrs = main.attributes || {};
    const valid = main.state !== "unavailable" && main.state !== "unknown";
    this._title.textContent = this._config.name || "Boiler";

    // Status pill: unavailable/unknown are shown as such, never as "off".
    this._status.className = "status";
    if (!valid) {
      this._status.classList.add("warn");
      this._status.textContent = main.state === "unavailable" ? "Unavailable" : "Unknown";
    } else if (main.state === "on") {
      this._status.classList.add("on");
      this._status.textContent = "Calling for heat";
    } else {
      this._status.textContent = "No heat demand";
    }

    // Alerts: prominent, role="alert".
    const alerts = Array.isArray(attrs.alerts) ? attrs.alerts : [];
    this._alerts.replaceChildren();
    if (alerts.length) {
      this._alerts.append(el("strong", "", alerts.length === 1 ? "Boiler alert" : "Boiler alerts"));
      const list = el("ul");
      for (const key of alerts) {
        const item = el("li", "", humanize(key));
        item.title = String(key);
        list.append(item);
      }
      this._alerts.append(list);
    }
    this._alerts.hidden = alerts.length === 0;

    // Safety override: a room is at or below its low-temperature safety limit.
    const override = valid ? attrs.manual_override : undefined;
    this._safety.replaceChildren();
    if (valid && attrs.safety_override === true) {
      this._safety.append(el("strong", "", "Low-temperature safety active"));
      this._safety.append(
        el("div", "", override === "off"
          ? " A room is at or below its safety temperature, so frost protection is overriding your manual OFF and the boiler is being kept heating."
          : " A room is at or below its safety temperature, so the boiler is being kept heating.")
      );
    }
    this._safety.hidden = this._safety.childElementCount === 0;

    // Three-way control. Modes whose button entity is missing are hidden.
    let anyButton = false;
    const activeMode = !valid ? undefined : override === "on" || override === "off" ? override : "auto";
    for (const [mode, { key, button }] of Object.entries(this._buttons)) {
      const id = ids[key];
      const buttonState = id ? hass.states[id] : undefined;
      button.hidden = !buttonState;
      if (buttonState) anyButton = true;
      button.disabled = !buttonState || buttonState.state === "unavailable";
      button.setAttribute("aria-pressed", String(activeMode === mode));
    }
    this._seg.hidden = !anyButton;

    // Optional metrics, each hidden if its source is missing.
    this._metrics.replaceChildren();
    const addMetric = (label, value) => {
      const metric = el("div", "metric");
      metric.append(el("div", "label", label), el("div", "value", value));
      this._metrics.append(metric);
    };
    if (valid) {
      const rooms = Array.isArray(attrs.calling_rooms) ? attrs.calling_rooms : [];
      addMetric("Calling rooms", rooms.length ? rooms.join(", ") : "None");
      if (typeof attrs.max_temperature_deficit === "number") {
        addMetric("Largest deficit", `${attrs.max_temperature_deficit.toFixed(1)} °C`);
      }
      const pid = ids.pid_entity ? hass.states[ids.pid_entity] : undefined;
      if (pid && pid.state !== "unavailable" && pid.state !== "unknown") {
        addMetric("Max PID demand", `${pid.state} ${(pid.attributes && pid.attributes.unit_of_measurement) || "%"}`);
      }
    }
    this._metrics.hidden = this._metrics.childElementCount === 0;

    this._main = main;
    this._tick();
    this._stopTimer();
    if (valid && (override === "on" || override === "off") && Number.isFinite(attrs.manual_override_seconds_left)) {
      this._timer = setInterval(() => this._tick(), 1000);
    }
  }

  // Manual override line. `manual_override` decides whether one is active;
  // `manual_override_seconds_left` is null both for "no override" and "never
  // expires", and is only refreshed when the controller publishes, so count
  // down from the state's last_updated instead of trusting the raw value.
  _tick() {
    const main = this._main;
    const attrs = (main && main.attributes) || {};
    const valid = main && main.state !== "unavailable" && main.state !== "unknown";
    const override = valid ? attrs.manual_override : undefined;
    if (override !== "on" && override !== "off") {
      this._override.hidden = true;
      return;
    }
    const mode = override === "on" ? "ON" : "OFF";
    let text = `Manual ${mode} — until you resume automatic control`;
    if (Number.isFinite(attrs.manual_override_seconds_left)) {
      const updated = Date.parse(main.last_updated);
      const elapsed = Number.isNaN(updated) ? 0 : (Date.now() - updated) / 1000;
      const left = Math.max(0, attrs.manual_override_seconds_left - Math.max(0, elapsed));
      text = `Manual ${mode} — resumes automatic in ${formatDuration(left)}`;
    }
    this._override.textContent = text;
    this._override.hidden = false;
  }
}

class BoilerHeatDemandCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...(config || {}) };
    this._draw();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _draw() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) => schema.label || schema.name;
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...ev.detail.value };
        for (const key of Object.keys(config)) if (config[key] === "" || config[key] === undefined) delete config[key];
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.append(this._form);
    }
    const pick = (name, label, domain) => ({
      name,
      label,
      selector: { entity: domain ? { domain } : { domain: "binary_sensor" } },
    });
    this._form.schema = [
      pick("entity", "Heat demand binary sensor (required)", "binary_sensor"),
      { name: "name", label: "Title", selector: { text: {} } },
      pick("auto_button", "Auto button override (optional)", "button"),
      pick("on_button", "On button override (optional)", "button"),
      pick("off_button", "Off button override (optional)", "button"),
      pick("calling_entity", "Rooms calling sensor override (optional)", "sensor"),
      pick("pid_entity", "PID demand sensor override (optional)", "sensor"),
    ];
    this._form.data = this._config;
    if (this._hass) this._form.hass = this._hass;
  }
}

if (!customElements.get("boiler-heat-demand-card")) {
  customElements.define("boiler-heat-demand-card", BoilerHeatDemandCard);
  customElements.define("boiler-heat-demand-card-editor", BoilerHeatDemandCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "boiler-heat-demand-card")) {
  window.customCards.push({
    type: "boiler-heat-demand-card",
    name: "Boiler Heat Demand",
    description: "Live heat demand, alerts and an Auto / On / Off control for Boiler Heat Demand.",
    preview: true,
  });
}

console.info(`%c BOILER-HEAT-DEMAND-CARD %c ${CARD_VERSION} `, "background:#555;color:#fff", "background:#999;color:#fff");
