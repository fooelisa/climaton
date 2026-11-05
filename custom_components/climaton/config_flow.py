"""Config flow for Climaton integration."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN

from .const import DOMAIN, DEFAULT_PORT
from .protocol import ClimatonConnection


class ClimatonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climaton."""

    VERSION = 1

    async def _async_can_connect(self, host, port, token):
        conn = ClimatonConnection(host, port, token)
        try:
            return await self.hass.async_add_executor_job(conn.connect)
        finally:
            conn.disconnect()

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            token_hex = user_input[CONF_TOKEN]

            try:
                token = bytes.fromhex(token_hex)
                if len(token) != 16:
                    errors["base"] = "invalid_token"
            except ValueError:
                errors["base"] = "invalid_token"

            if not errors:
                if await self._async_can_connect(host, port, token):
                    await self.async_set_unique_id(token_hex)
                    # Same device (token) at a new address: update the
                    # existing entry instead of aborting without a change.
                    self._abort_if_unique_id_configured(
                        updates={CONF_HOST: host, CONF_PORT: port}
                    )
                    return self.async_create_entry(
                        title=f"Climaton ({host})",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_TOKEN: token_hex,
                        },
                    )
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_TOKEN): str,
            }),
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
                ): int,
            }),
            errors=errors,
        )
