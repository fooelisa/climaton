"""Sensor platform for Climaton."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ClimatonCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    token = entry.data["token"]
    device_info = {
        "identifiers": {(DOMAIN, token)},
        "name": "Climaton Water Heater",
        "manufacturer": "Electrolux",
        "model": "EWH50SI SmartInverter",
    }

    async_add_entities([
        ClimatonCurrentTempSensor(coordinator, token, device_info),
        ClimatonTankSensor(coordinator, token, device_info),
        ClimatonRssiSensor(coordinator, token, device_info),
    ])


class ClimatonCurrentTempSensor(CoordinatorEntity[ClimatonCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Current temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, token, device_info):
        super().__init__(coordinator)
        self._attr_unique_id = f"{token}_current_temp"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return self.coordinator.connection.state.current_temperature


class ClimatonTankSensor(CoordinatorEntity[ClimatonCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Tank level"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator, token, device_info):
        super().__init__(coordinator)
        self._attr_unique_id = f"{token}_tank_level"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return self.coordinator.connection.state.tank_level


class ClimatonRssiSensor(CoordinatorEntity[ClimatonCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "WiFi signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, token, device_info):
        super().__init__(coordinator)
        self._attr_unique_id = f"{token}_rssi"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return self.coordinator.connection.state.rssi
