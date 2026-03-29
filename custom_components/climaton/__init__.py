"""Climaton Water Heater integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ClimatonCoordinator
from .protocol import ClimatonConnection

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.WATER_HEATER, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    token = bytes.fromhex(entry.data[CONF_TOKEN])

    connection = ClimatonConnection(host, port, token)
    ok = await hass.async_add_executor_job(connection.connect)
    if not ok:
        _LOGGER.error("Failed to connect to Climaton device at %s:%s", host, port)
        return False

    coordinator = ClimatonCoordinator(hass, connection)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.connection.disconnect()
    return unload_ok
