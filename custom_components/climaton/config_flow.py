"""Config flow for Climaton integration."""

import ipaddress
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.helpers.device_registry import format_mac

from .const import CONF_MAC, DOMAIN, DEFAULT_PORT
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


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class ClimatonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climaton."""

    VERSION = 1

    def __init__(self):
        self._discovered_host = None
        self._discovered_port = DEFAULT_PORT
        self._discovered_mac = None

    async def _async_can_connect(self, host, port, token):
        conn = ClimatonConnection(host, port, token)
        try:
            return await self.hass.async_add_executor_job(conn.connect)
        except (OSError, OverflowError):
            # Unresolvable host, no route, or a bad port.
            return False
        finally:
            conn.disconnect()

    async def _async_create_or_update(
        self, host, port, token, raise_on_progress, mac=None
    ):
        token_hex = token.hex()
        entry = await self.async_set_unique_id(
            token_hex, raise_on_progress=raise_on_progress
        )
        self._async_abort_discoveries_for(host)
        data = {CONF_HOST: host, CONF_PORT: port}
        if mac:
            data[CONF_MAC] = mac
        # Same device (token) at a new address: update the
        # existing entry instead of aborting without a change.
        if entry is not None:
            return self.async_update_reload_and_abort(
                entry,
                title=f"Climaton ({host})",
                data_updates=data,
                reason="already_configured",
            )
        return self.async_create_entry(
            title=f"Climaton ({host})",
            data={**data, CONF_TOKEN: token_hex},
        )

    def _async_abort_discoveries_for(self, host):
        """Close other open discovery cards for the device just added."""
        for flow in self._async_in_progress(include_uninitialized=True):
            if (
                flow["flow_id"] != self.flow_id
                and flow["context"].get("title_placeholders", {}).get("host") == host
            ):
                self.hass.config_entries.flow.async_abort(flow["flow_id"])

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
        # The manifest matcher already filters on this. Protocol 2 and 3
        # devices need an ECDH key exchange, which this integration lacks.
        if discovery_info.properties.get("protocol") != "1":
            return self.async_abort(reason="not_supported")

        host = str(discovery_info.ip_address)
        port = discovery_info.port or DEFAULT_PORT
        mac = format_mac(discovery_info.properties.get("macaddr") or "") or None
        entries = self._async_current_entries(include_ignore=False)

        # Known device: follow it to its new address. Entries set up with
        # a hostname instead of an IP are left alone.
        if mac:
            for entry in entries:
                if entry.data.get(CONF_MAC) != mac:
                    continue
                if not _is_ip(entry.data[CONF_HOST]) or (
                    entry.data[CONF_HOST] == host and entry.data[CONF_PORT] == port
                ):
                    return self.async_abort(reason="already_configured")
                return self._async_move_entry(entry, host, port, mac)

        # An entry at this address that has no MAC yet: learn it, but only
        # if the device there is the entry's own. A loaded entry has just
        # reached it; otherwise check its token at its own address.
        for entry in entries:
            if entry.data[CONF_HOST] == host and entry.data[CONF_PORT] == port:
                if mac and CONF_MAC not in entry.data and (
                    entry.state is config_entries.ConfigEntryState.LOADED
                    or await self._async_can_connect(
                        host, port, bytes.fromhex(entry.data[CONF_TOKEN])
                    )
                ):
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_MAC: mac}
                    )
                return self.async_abort(reason="already_configured")

        # Repeat announcements and the "Ignore" button refer to this id.
        # An open card for this device at an older address is replaced.
        unique_id = mac or f"zeroconf-{discovery_info.name}"
        for flow in self._async_in_progress(include_uninitialized=True):
            if (
                flow["flow_id"] != self.flow_id
                and flow["context"].get("unique_id") == unique_id
                and flow["context"].get("title_placeholders", {}).get("host") != host
            ):
                self.hass.config_entries.flow.async_abort(flow["flow_id"])
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Entries created before discovery have no MAC. Only for those that
        # could not be set up, try their token on the new address.
        # Working and disabled entries keep their token to themselves.
        for entry in entries:
            if (
                CONF_MAC in entry.data
                or entry.disabled_by
                or entry.state is config_entries.ConfigEntryState.LOADED
                or not _is_ip(entry.data[CONF_HOST])
            ):
                continue
            token = bytes.fromhex(entry.data[CONF_TOKEN])
            if await self._async_can_connect(host, port, token):
                return self._async_move_entry(entry, host, port, mac)

        self._discovered_host = host
        self._discovered_port = port
        self._discovered_mac = mac
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_zeroconf_confirm()

    def _async_move_entry(self, entry, host, port, mac):
        _LOGGER.warning(
            "Climaton device moved from %s:%s to %s:%s, updating entry",
            entry.data[CONF_HOST], entry.data[CONF_PORT], host, port,
        )
        data_updates = {CONF_HOST: host, CONF_PORT: port}
        if mac:
            data_updates[CONF_MAC] = mac
        return self.async_update_reload_and_abort(
            entry,
            title=f"Climaton ({host})",
            data_updates=data_updates,
            reason="already_configured",
        )

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
                    host, port, token, raise_on_progress=False,
                    mac=self._discovered_mac,
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
