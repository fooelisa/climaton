"""Config flow for Climaton integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN

from .const import DOMAIN, DEFAULT_PORT
from .protocol import ClimatonConnection

_LOGGER = logging.getLogger(__name__)

PORT_SCHEMA = vol.All(int, vol.Range(min=1, max=65535))


def _parse_token(token_hex):
    """Return the 16-byte token, or None if the input is not valid."""
    try:
        token = bytes.fromhex(token_hex)
    except ValueError:
        return None
    return token if len(token) == 16 else None


class ClimatonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climaton."""

    VERSION = 1

    def __init__(self):
        self._discovered_host = None
        self._discovered_port = DEFAULT_PORT

    async def _async_can_connect(self, host, port, token):
        conn = ClimatonConnection(host, port, token)
        try:
            return await self.hass.async_add_executor_job(conn.connect)
        except (OSError, OverflowError):
            # Unresolvable host, no route, or a bad port.
            return False
        finally:
            conn.disconnect()

    async def _async_create_or_update(self, host, port, token, raise_on_progress):
        token_hex = token.hex()
        entry = await self.async_set_unique_id(
            token_hex, raise_on_progress=raise_on_progress
        )
        # Same device (token) at a new address: update the
        # existing entry instead of aborting without a change.
        if entry is not None:
            return self.async_update_reload_and_abort(
                entry,
                title=f"Climaton ({host})",
                data_updates={CONF_HOST: host, CONF_PORT: port},
                reason="already_configured",
            )
        return self.async_create_entry(
            title=f"Climaton ({host})",
            data={
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_TOKEN: token_hex,
            },
        )

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            token = _parse_token(user_input[CONF_TOKEN])

            if token is None:
                errors["base"] = "invalid_token"
            elif await self._async_can_connect(host, port, token):
                return await self._async_create_or_update(
                    host, port, token, raise_on_progress=True
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): PORT_SCHEMA,
                vol.Required(CONF_TOKEN): str,
            }),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info):
        """Handle a device announced over mDNS (_syncleo._udp)."""
        if discovery_info.ip_address.version != 4:
            return self.async_abort(reason="not_ipv4_address")

        host = str(discovery_info.ip_address)
        port = discovery_info.port or DEFAULT_PORT
        entries = self._async_current_entries(include_ignore=False)

        # Announcements repeat. Stop early if an entry already uses this address.
        for entry in entries:
            if entry.data[CONF_HOST] == host and entry.data[CONF_PORT] == port:
                return self.async_abort(reason="already_configured")

        # The device can get a new IP from DHCP. Find the entry whose token
        # the device at the announced address accepts, and move it there.
        for entry in entries:
            token = bytes.fromhex(entry.data[CONF_TOKEN])
            if await self._async_can_connect(host, port, token):
                _LOGGER.info(
                    "Climaton device moved from %s:%s to %s:%s, updating entry",
                    entry.data[CONF_HOST], entry.data[CONF_PORT], host, port,
                )
                return self.async_update_reload_and_abort(
                    entry,
                    title=f"Climaton ({host})",
                    data_updates={CONF_HOST: host, CONF_PORT: port},
                    reason="already_configured",
                )

        # A device that no entry knows. The flow's unique id is the device
        # name until the token is known, so repeat announcements and the
        # "Ignore" button refer to this device.
        await self.async_set_unique_id(f"zeroconf-{discovery_info.name}")
        self._abort_if_unique_id_configured()

        self._discovered_host = host
        self._discovered_port = port
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input=None):
        """Ask for the pairing token of a discovered device."""
        host = self._discovered_host
        port = self._discovered_port
        errors = {}

        if user_input is not None:
            token = _parse_token(user_input[CONF_TOKEN])
            if token is None:
                errors["base"] = "invalid_token"
            elif await self._async_can_connect(host, port, token):
                return await self._async_create_or_update(
                    host, port, token, raise_on_progress=False
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            description_placeholders={"host": host},
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Change the host or port of an existing entry, keeping its token."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            token = bytes.fromhex(entry.data[CONF_TOKEN])

            if await self._async_can_connect(host, port, token):
                return self.async_update_reload_and_abort(
                    entry,
                    title=f"Climaton ({host})",
                    data_updates={CONF_HOST: host, CONF_PORT: port},
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                vol.Optional(
                    CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                ): PORT_SCHEMA,
            }),
            errors=errors,
        )
