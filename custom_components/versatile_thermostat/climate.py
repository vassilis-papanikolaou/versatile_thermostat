import math

from homeassistant.core import HomeAssistant, callback, CoreState
from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
    async_call_later,
)

import logging

_LOGGER = logging.getLogger(__name__)

from homeassistant.components.climate.const import (
    ATTR_PRESET_MODE,
    ATTR_FAN_MODE,
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    PRESET_ACTIVITY,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_HOME,
    PRESET_NONE,
    PRESET_SLEEP,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
)

from homeassistant.const import (
    UnitOfTemperature,
    ATTR_TEMPERATURE,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
    CONF_NAME,
    CONF_UNIQUE_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    STATE_OFF,
    STATE_ON,
    EVENT_HOMEASSISTANT_START,
)

from .const import (
    DOMAIN,
    CONF_HEATER,
    CONF_POWER_SENSOR,
    CONF_TEMP_SENSOR,
    CONF_MAX_POWER_SENSOR,
    CONF_MOTION_SENSOR,
    CONF_WINDOW_SENSOR,
    CONF_DEVICE_POWER,
    CONF_PRESETS,
    SUPPORT_FLAGS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the VersatileThermostat thermostat with config flow."""
    _LOGGER.debug(
        "Calling async_setup_entry entry=%s, data=%s", entry.entry_id, entry.data
    )

    unique_id = entry.entry_id
    name = entry.data.get(CONF_NAME)
    heater_entity_id = entry.data.get(CONF_HEATER)
    temp_sensor_entity_id = entry.data.get(CONF_TEMP_SENSOR)
    power_sensor_entity_id = entry.data.get(CONF_POWER_SENSOR)
    max_power_sensor_entity_id = entry.data.get(CONF_MAX_POWER_SENSOR)
    window_sensor_entity_id = entry.data.get(CONF_WINDOW_SENSOR)
    motion_sensor_entity_id = entry.data.get(CONF_MOTION_SENSOR)
    device_power = entry.data.get(CONF_DEVICE_POWER)

    presets = {}
    for (key, value) in CONF_PRESETS.items():
        _LOGGER.debug("looking for key=%s, value=%s", key, value)
        if value in entry.data:
            presets[key] = entry.data.get(value)
        else:
            _LOGGER.debug("value %s not found in Entry", value)

    async_add_entities(
        [
            VersatileThermostat(
                unique_id,
                name,
                heater_entity_id,
                temp_sensor_entity_id,
                power_sensor_entity_id,
                max_power_sensor_entity_id,
                window_sensor_entity_id,
                motion_sensor_entity_id,
                presets,
                device_power,
            )
        ],
        True,
    )


class VersatileThermostat(ClimateEntity, RestoreEntity):
    """Representation of a Versatile Thermostat device."""

    _name: str
    _heater_entity_id: str

    def __init__(
        self,
        unique_id,
        name,
        heater_entity_id,
        temp_sensor_entity_id,
        power_sensor_entity_id,
        max_power_sensor_entity_id,
        window_sensor_entity_id,
        motion_sensor_entity_id,
        presets,
        device_power,
    ) -> None:
        """Initialize the thermostat."""

        super().__init__()

        self._unique_id = unique_id
        self._name = name
        self._heater_entity_id = heater_entity_id
        self._temp_sensor_entity_id = temp_sensor_entity_id
        self._power_sensor_entity_id = power_sensor_entity_id
        self._max_power_sensor_entity_id = max_power_sensor_entity_id
        self._window_sensor_entity_id = window_sensor_entity_id
        self._motion_sensor_entity_id = motion_sensor_entity_id

        # if self.ac_mode:
        #    self.hvac_list = [HVAC_MODE_COOL, HVAC_MODE_OFF]
        # else:
        self._hvac_list = [HVAC_MODE_HEAT, HVAC_MODE_OFF]
        self._unit = TEMP_CELSIUS
        # Will be restored if possible
        self._hvac_mode = None  # HVAC_MODE_OFF
        self._saved_hvac_mode = self._hvac_mode

        self._support_flags = SUPPORT_FLAGS
        if len(presets):
            self._support_flags = SUPPORT_FLAGS | SUPPORT_PRESET_MODE
            self._attr_preset_modes = [PRESET_NONE] + list(presets.keys())
            _LOGGER.debug("Set preset_modes to %s", self._attr_preset_modes)
        else:
            _LOGGER.debug("No preset_modes")
            self._attr_preset_modes = [PRESET_NONE]
        self._presets = presets
        _LOGGER.debug("%s - presets are set to: %s", self, self._presets)
        # Will be restored if possible
        self._attr_preset_mode = None  # PRESET_NONE

        # Power management
        self._device_power = device_power
        if (
            self._max_power_sensor_entity_id
            and self._power_sensor_entity_id
            and self._device_power
        ):
            self._pmax_on = True
            self._current_power = -1
            self._current_power_max = -1
        else:
            self._pmax_on = False

        # will be restored if possible
        self._target_temp = None
        self._saved_target_temp = self._target_temp
        self._humidity = None
        self._ac_mode = False
        self._fan_mode = None
        self._swing_mode = None
        self._cur_temp = None

        _LOGGER.debug(
            "%s - Creation of a new VersatileThermostat entity: unique_id=%s heater_entity_id=%s",
            self,
            self.unique_id,
            heater_entity_id,
        )

    def __str__(self):
        return f"VersatileThermostat-{self.name}"

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def should_poll(self):
        return False

    @property
    def name(self):
        return self._name

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        if self._hvac_mode == HVAC_MODE_OFF:
            return CURRENT_HVAC_OFF
        if not self._is_device_active:
            return CURRENT_HVAC_IDLE
        if self._ac_mode:
            return CURRENT_HVAC_COOL
        return CURRENT_HVAC_HEAT

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        if not self.hass.states.get(self._heater_entity_id):
            return None

        return self.hass.states.is_state(self._heater_entity_id, STATE_ON)

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.info("%s - Set hvac mode: %s", self, hvac_mode)
        if hvac_mode == HVAC_MODE_HEAT:
            self._hvac_mode = HVAC_MODE_HEAT
            # TODO await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_COOL:
            self._hvac_mode = HVAC_MODE_COOL
            # TODO await self._async_control_heating(force=True)
        elif hvac_mode == HVAC_MODE_OFF:
            self._hvac_mode = HVAC_MODE_OFF
            # TODO self.prop_current_phase = PROP_PHASE_NONE
            # if self._is_device_active:
            #    await self._async_heater_turn_off()
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode):
        """Set new preset mode."""
        _LOGGER.info("%s - Set preset_mode: %s", self, preset_mode)
        if preset_mode not in (self._attr_preset_modes or []):
            raise ValueError(
                f"Got unsupported preset_mode {preset_mode}. Must be one of {self._attr_preset_modes}"
            )
        if preset_mode == self._attr_preset_mode:
            # I don't think we need to call async_write_ha_state if we didn't change the state
            return
        if preset_mode == PRESET_NONE:
            self._attr_preset_mode = PRESET_NONE
            self._target_temp = self._saved_target_temp
            # TODO await self._async_control_heating(force=True)
        elif preset_mode == PRESET_ACTIVITY:
            self._attr_preset_mode = PRESET_ACTIVITY
            # TODO self._target_temp = self._presets[self.no_motion_mode]
            # await self._async_control_heating(force=True)
        else:
            if self._attr_preset_mode == PRESET_NONE:
                self._saved_target_temp = self._target_temp
            self._attr_preset_mode = preset_mode
            self._target_temp = self._presets[preset_mode]
            # TODO await self._async_control_heating(force=True)

        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        _LOGGER.info("%s - Set fan mode: %s", self, fan_mode)
        if fan_mode is None:
            return
        self._fan_mode = fan_mode
        self.async_write_ha_state()

    async def async_set_humidity(self, humidity: int):
        """Set new target humidity."""
        _LOGGER.info("%s - Set fan mode: %s", self, humidity)
        if humidity is None:
            return
        self._humidity = humidity

    async def async_set_swing_mode(self, swing_mode):
        """Set new target swing operation."""
        _LOGGER.info("%s - Set fan mode: %s", self, swing_mode)
        if swing_mode is None:
            return
        self._swing_mode = swing_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        _LOGGER.info("%s - Set target temp: %s", self, temperature)
        if temperature is None:
            return
        self._target_temp = temperature
        self._attr_preset_mode = PRESET_NONE
        # TODO await self._async_control_heating(force=True)
        self.async_write_ha_state()

    @callback
    async def entry_update_listener(
        self, hass: HomeAssistant, config_entry: ConfigEntry
    ) -> None:
        """Called when the entry have changed in ConfigFlow"""
        _LOGGER.info("%s - Change entry with the values: %s", self, config_entry.data)

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        _LOGGER.debug("Calling async_added_to_hass")

        await super().async_added_to_hass()

        # Add listener
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._heater_entity_id], self._async_switch_changed
            )
        )

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._temp_sensor_entity_id],
                self._async_temperature_changed,
            )
        )
        if self._window_sensor_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._window_sensor_entity_id],
                    self._async_windows_changed,
                )
            )
        if self._motion_sensor_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._motion_sensor_entity_id],
                    self._async_motion_changed,
                )
            )
        # if self._keep_alive:
        #    self.async_on_remove(
        #        async_track_time_interval(
        #            self.hass, self._async_control_heating, self._keep_alive
        #        )
        #    )
        if self._power_sensor_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._power_sensor_entity_id],
                    self._async_power_changed,
                )
            )

        if self._max_power_sensor_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._max_power_sensor_entity_id],
                    self._async_max_power_changed,
                )
            )

        await self.async_startup()

    async def async_startup(self):
        """Triggered on startup, used to get old state and set internal states accordingly"""
        _LOGGER.debug("%s - Calling async_startup", self)

        @callback
        def _async_startup_internal(*_):
            _LOGGER.debug("%s - Calling async_startup_internal", self)
            need_write_state = False
            temperature_state = self.hass.states.get(self._temp_sensor_entity_id)
            if temperature_state and temperature_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                _LOGGER.debug(
                    "%s - temperature sensor have been retrieved: %f",
                    self,
                    float(temperature_state.state),
                )
                # TODO self._async_update_temp(temperature_state)
                need_write_state = True

            switch_state = self.hass.states.get(self._heater_entity_id)
            if switch_state and switch_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self.hass.create_task(self._check_switch_initial_state())

            if self._pmax_on:
                # try to acquire current power and power max
                current_power_state = self.hass.states.get(self._power_sensor_entity_id)
                if current_power_state and current_power_state.state not in (
                    STATE_UNAVAILABLE,
                    STATE_UNKNOWN,
                ):
                    self._current_power = float(current_power_state.state)
                    _LOGGER.debug(
                        "%s - Current power have been retrieved: %f",
                        self,
                        self._current_power,
                    )
                    need_write_state = True

                # Try to acquire power max
                current_power_max_state = self.hass.states.get(
                    self._max_power_sensor_entity_id
                )
                if current_power_max_state and current_power_max_state.state not in (
                    STATE_UNAVAILABLE,
                    STATE_UNKNOWN,
                ):
                    self._current_power_max = float(current_power_max_state.state)
                    _LOGGER.debug(
                        "%s - Current power max have been retrieved: %f",
                        self,
                        self._current_power_max,
                    )
                    need_write_state = True

            if need_write_state:
                self.async_write_ha_state()
            # TODO self.hass.create_task(self._async_control_heating())

        if self.hass.state == CoreState.running:
            _async_startup_internal()
        else:
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_START, _async_startup_internal
            )

        await self.get_my_previous_state()

    async def get_my_previous_state(self):
        """Try to get my previou state"""
        # Check If we have an old state
        old_state = await self.async_get_last_state()
        _LOGGER.debug(
            "%s - Calling get_my_previous_state old_state is %s", self, old_state
        )
        if old_state is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    if self._ac_mode:
                        self._target_temp = self.max_temp
                    else:
                        self._target_temp = self.min_temp
                    _LOGGER.warning(
                        "%s - Undefined target temperature, falling back to %s",
                        self,
                        self._target_temp,
                    )
                else:
                    self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])

            if old_state.attributes.get(ATTR_PRESET_MODE) in self._attr_preset_modes:
                self._attr_preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)

            if not self._hvac_mode and old_state.state:
                self._hvac_mode = old_state.state

        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                if self._ac_mode:
                    self._target_temp = self.max_temp
                else:
                    self._target_temp = self.min_temp
            _LOGGER.warning(
                "No previously saved temperature, setting to %s", self._target_temp
            )

        # Set default state to off
        if not self._hvac_mode:
            self._hvac_mode = HVAC_MODE_OFF

        _LOGGER.info(
            "%s - restored state is target_temp=%f, preset_mode=%s, hvac_mode=%s",
            self,
            self._target_temp,
            self._attr_preset_mode,
            self._hvac_mode,
        )

    @callback
    async def _async_temperature_changed(self, event):
        """Handle temperature changes."""
        new_state = event.data.get("new_state")
        _LOGGER.info(
            "%s - Temperature changed. Event.new_state is %s",
            self,
            new_state,
        )
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._async_update_temp(new_state)
        # TODO await self._async_control_heating()
        self.async_write_ha_state()

    @callback
    async def _async_windows_changed(self, event):
        """Handle window changes."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        _LOGGER.info(
            "%s - Window changed. Event.new_state is %s, _hvac_mode=%s, _saved_hvac_mode=%s",
            self,
            new_state,
            self._hvac_mode,
            self._saved_hvac_mode,
        )
        if new_state is None or old_state is None or new_state.state == old_state.state:
            return
        if not self._saved_hvac_mode:
            self._saved_hvac_mode = self._hvac_mode
        if new_state.state == STATE_OFF:
            await self.async_set_hvac_mode(self._saved_hvac_mode)
        elif new_state.state == STATE_ON:
            self._saved_hvac_mode = self._hvac_mode
            await self.async_set_hvac_mode(HVAC_MODE_OFF)
        else:
            return

    @callback
    async def _async_motion_changed(self, event):
        """Handle motion changes."""
        new_state = event.data.get("new_state")
        _LOGGER.info(
            "%s - Motion changed. Event.new_state is %s, _attr_preset_mode=%s, activity=%s",
            self,
            new_state,
            self._attr_preset_mode,
            PRESET_ACTIVITY,
        )
        if self._attr_preset_mode != PRESET_ACTIVITY:
            return
        if new_state is None or new_state.state not in (STATE_OFF, STATE_ON):
            return

        # if self.motion_delay:
        #    if new_state.state == STATE_ON:
        #        self._target_temp = self._presets[self.motion_mode]
        #        await self._async_control_heating()
        #        self.async_write_ha_state()
        #    else:
        #        async def try_no_motion_condition(_):
        #            if self._attr_preset_mode != PRESET_ACTIVITY:
        #                return
        #            try:
        #                long_enough = condition.state(
        #                    self.hass,
        #                    self.motion_entity_id,
        #                    STATE_OFF,
        #                    self.motion_delay,
        #                )
        #            except ConditionError:
        #                long_enough = False
        #            if long_enough:
        #                self._target_temp = self._presets[self.no_motion_mode]
        #                await self._async_control_heating()
        #                self.async_write_ha_state()
        #
        #        async_call_later(self.hass, self.motion_delay, try_no_motion_condition)

    @callback
    async def _check_switch_initial_state(self):
        """Prevent the device from keep running if HVAC_MODE_OFF."""
        _LOGGER.debug("%s - Calling _check_switch_initial_state", self)
        if self._hvac_mode == HVAC_MODE_OFF and self._is_device_active:
            _LOGGER.warning(
                "The climate mode is OFF, but the switch device is ON. Turning off device %s",
                self._heater_entity_id,
            )
            # TODO await self._async_heater_turn_off()

    @callback
    def _async_switch_changed(self, event):
        """Handle heater switch state changes."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return
        if old_state is None:
            self.hass.create_task(self._check_switch_initial_state())
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            cur_temp = float(state.state)
            if math.isnan(cur_temp) or math.isinf(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")
            self._cur_temp = cur_temp
        except ValueError as ex:
            _LOGGER.error("Unable to update temperature from sensor: %s", ex)

    @callback
    async def _async_power_changed(self, event):
        """Handle power changes."""
        _LOGGER.debug("Thermostat %s - Receive new Power event", self.name)
        _LOGGER.debug(event)
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None or new_state.state == old_state.state:
            return

        try:
            current_power = float(new_state.state)
            if math.isnan(current_power) or math.isinf(current_power):
                raise ValueError(f"Sensor has illegal state {new_state.state}")
            self._current_power = current_power

        except ValueError as ex:
            _LOGGER.error("Unable to update current_power from sensor: %s", ex)

    @callback
    async def _async_max_power_changed(self, event):
        """Handle power max changes."""
        _LOGGER.debug("Thermostat %s - Receive new Power Max event", self.name)
        _LOGGER.debug(event)
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None or new_state.state == old_state.state:
            return

        try:
            current_power_max = float(new_state.state)
            if math.isnan(current_power_max) or math.isinf(current_power_max):
                raise ValueError(f"Sensor has illegal state {new_state.state}")
            self._current_power_max = current_power_max

        except ValueError as ex:
            _LOGGER.error("Unable to update current_power from sensor: %s", ex)