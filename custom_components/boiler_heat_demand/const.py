"""Constants for Boiler Heat Demand."""

DOMAIN = "boiler_heat_demand"

CONF_RELAY = "relay_entity"
CONF_VALVES = "valve_entities"
CONF_MIN_VALVES = "min_valves"
CONF_MIN_ON = "min_on_minutes"
CONF_MIN_OFF = "min_off_minutes"
CONF_HYSTERESIS = "hysteresis"
CONF_VALVE_TIMEOUT = "valve_timeout_minutes"
CONF_DEMAND_MODE = "demand_mode"
CONF_START_DEFICIT = "start_deficit"
CONF_STOP_DEFICIT = "stop_deficit"
CONF_SAFETY_MIN_TEMP = "safety_min_temp"
CONF_VALVE_FAILSAFE = "valve_failsafe"
CONF_RELAY_TIMEOUT = "relay_timeout_minutes"
CONF_NOTIFY = "notify_service"
CONF_LEARNING = "learning_enabled"
CONF_ROOMS = "rooms"
CONF_ROOM_NAME = "name"
CONF_ROOM_VALVES = "valves"
CONF_ROOM_SENSOR = "temp_sensor"
CONF_ADD_ANOTHER = "add_another"
CONF_EDIT_ROOMS = "edit_rooms"
CONF_OUTDOOR = "outdoor_temp_entity"
CONF_PID_ATTRIBUTE = "pid_demand_attribute"
CONF_PID_START = "pid_start_percent"
CONF_PID_STOP = "pid_stop_percent"

DEFAULT_LEARNING = True
STORAGE_VERSION = 1
SAVE_DELAY_S = 300

DEFAULT_DEMAND_MODE = "valve_count"
DEFAULT_START_DEFICIT = 0.5
DEFAULT_STOP_DEFICIT = 0.1
DEFAULT_PID_START = 20.0
DEFAULT_PID_STOP = 5.0
DEFAULT_SAFETY_MIN_TEMP = 8.0
DEFAULT_VALVE_FAILSAFE = "ignore"
DEFAULT_RELAY_TIMEOUT = 5
RELAY_VERIFY_SECONDS = 60

DEFAULT_MIN_VALVES = 1
DEFAULT_MIN_ON = 5
DEFAULT_MIN_OFF = 5
DEFAULT_HYSTERESIS = 0.3
DEFAULT_VALVE_TIMEOUT = 30

PLATFORMS = ["binary_sensor", "sensor", "button"]
