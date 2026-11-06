/*
 * Prints the dashboard config the shipped strategy generates, as JSON, so a
 * Python test can render its markdown through Home Assistant's own template
 * engine. Driving the real module through a stub DOM (rather than copying the
 * template into the test) is what stops the two drifting apart.
 *
 * Usage: node tests/js/dashboard_config.mjs <heat-demand-entity-id>
 */
const entity = process.argv[2] || "binary_sensor.automated_boiler_heat_demand";

const registry = new Map();
globalThis.HTMLElement = class {};
globalThis.customElements = {
  get: (name) => registry.get(name),
  define: (name, cls) => registry.set(name, cls),
};
globalThis.window = globalThis;
globalThis.document = { createElement: () => ({ append() {}, addEventListener() {} }) };
// The module logs its version banner on import; keep stdout pure JSON.
console.info = () => {};

const CARD = "../../custom_components/boiler_heat_demand/frontend/boiler-heat-demand-card.js";
await import(new URL(CARD, import.meta.url).href);

const Strategy = registry.get("ll-strategy-dashboard-boiler-heat-demand");
if (!Strategy) throw new Error("dashboard strategy was not registered");

const deviceId = "dev1";
const reset = "button.automated_boiler_reset_learning";
const hass = {
  devices: { [deviceId]: { name: "Automated Boiler" } },
  entities: {
    [entity]: { device_id: deviceId, platform: "boiler_heat_demand" },
    [reset]: { device_id: deviceId, platform: "boiler_heat_demand" },
  },
  states: {
    [entity]: { state: "on", attributes: { friendly_name: "Automated Boiler Heat demand" } },
    [reset]: { state: "unknown", attributes: { friendly_name: "Automated Boiler Reset learning" } },
  },
};

process.stdout.write(JSON.stringify(await Strategy.generate({}, hass), null, 2));
