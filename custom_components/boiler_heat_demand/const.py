"""Constants for Boiler Heat Demand."""

DOMAIN = "boiler_heat_demand"

CONF_RELAY = "relay_entity"
CONF_VALVES = "valve_entities"
CONF_MIN_VALVES = "min_valves"
CONF_MIN_ON = "min_on_minutes"
CONF_MIN_OFF = "min_off_minutes"
CONF_HYSTERESIS = "hysteresis"

DEFAULT_MIN_VALVES = 1
DEFAULT_MIN_ON = 5
DEFAULT_MIN_OFF = 5
DEFAULT_HYSTERESIS = 0.3

PLATFORMS = ["binary_sensor", "sensor"]
