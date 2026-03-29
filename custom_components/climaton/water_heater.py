"""Water heater platform for Climaton."""

import logging
from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ClimatonCoordinator
from .protocol import DeviceState

_LOGGER = logging.getLogger(__name__)

OPERATION_MODES = ["off", "low", "mid", "turbo"]
MODE_TO_INT = {"off": 0, "low": 1, "mid": 2, "turbo": 3}

MIN_TEMP = 30
MAX_TEMP = 75


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ClimatonWaterHeater(coordinator, entry)])


class ClimatonWaterHeater(CoordinatorEntity[ClimatonCoordinator], WaterHeaterEntity):
    """Climaton water heater entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_operation_list = OPERATION_MODES
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(self, coordinator: ClimatonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data['token']}_water_heater"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["token"])},
            "name": "Climaton Water Heater",
            "manufacturer": "Electrolux",
            "model": "EWH50SI SmartInverter",
        }

    @property
    def current_temperature(self) -> float:
        return self.coordinator.connection.state.current_temperature

    @property
    def target_temperature(self) -> float:
        return self.coordinator.connection.state.target_temperature

    @property
    def current_operation(self) -> str:
        return self.coordinator.connection.state.mode_name

    @property
    def is_away_mode_on(self) -> bool:
        return False

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.hass.async_add_executor_job(
                self.coordinator.connection.set_temperature, temp
            )
            self.async_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        mode_int = MODE_TO_INT.get(operation_mode)
        if mode_int is not None:
            await self.hass.async_add_executor_job(
                self.coordinator.connection.set_mode, mode_int
            )
            self.async_write_ha_state()
