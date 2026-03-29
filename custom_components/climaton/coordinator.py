"""DataUpdateCoordinator for Climaton."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL_SECONDS
from .protocol import ClimatonConnection, DeviceState

_LOGGER = logging.getLogger(__name__)


class ClimatonCoordinator(DataUpdateCoordinator[DeviceState]):
    """Coordinator to poll the Climaton device."""

    def __init__(self, hass: HomeAssistant, connection: ClimatonConnection) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.connection = connection

    async def _async_update_data(self) -> DeviceState:
        try:
            ok = await self.hass.async_add_executor_job(self.connection.poll)
        except Exception as err:
            raise UpdateFailed(f"Error polling device: {err}") from err
        if not ok:
            raise UpdateFailed("Failed to poll device")
        return self.connection.state
