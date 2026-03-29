"""Config flow for Climaton integration."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN

from .const import DOMAIN, DEFAULT_PORT
from .protocol import ClimatonConnection


class ClimatonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climaton."""

    VERSION = 1

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
                conn = ClimatonConnection(host, port, token)
                ok = await self.hass.async_add_executor_job(conn.connect)
                conn.disconnect()

                if ok:
                    await self.async_set_unique_id(token_hex)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Climaton ({host})",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_TOKEN: token_hex,
                        },
                    )
                else:
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
