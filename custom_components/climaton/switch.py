"""Switch platform for Climaton."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
        ClimatonToggleSwitch(coordinator, token, device_info,
                             "keep_warm", "Keep warm", "mdi:fire",
                             coordinator.connection.set_keep_warm),
        ClimatonToggleSwitch(coordinator, token, device_info,
                             "smart_mode", "Smart mode", "mdi:brain",
                             coordinator.connection.set_smart_mode),
        ClimatonToggleSwitch(coordinator, token, device_info,
                             "bss", "Anti-legionella (BSS)", "mdi:shield-bug",
                             coordinator.connection.set_bss),
    ])


class ClimatonToggleSwitch(CoordinatorEntity[ClimatonCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, token, device_info, field, name, icon, setter):
        super().__init__(coordinator)
        self._field = field
        self._setter = setter
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{token}_{field}"
        self._attr_device_info = device_info

    @property
    def is_on(self):
        return getattr(self.coordinator.connection.state, self._field)

    async def async_turn_on(self, **kwargs):
        await self.hass.async_add_executor_job(self._setter, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.hass.async_add_executor_job(self._setter, False)
        self.async_write_ha_state()
