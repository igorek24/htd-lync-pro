"""Config flow for HTD Lync."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .client import HtdLyncClient
from .const import (
    CONF_ANNOUNCE_PLAYER,
    CONF_ANNOUNCE_TTS,
    CONF_DOORBELL_RESTORE,
    CONF_MAX_ON_VOLUME,
    CONF_POLL_INTERVAL,
    CONF_QUIET_CAP,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SERIAL_PATH,
    CONF_TONE_ENCODING,
    DEFAULT_DOORBELL_RESTORE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
)
from .protocol import ToneEncoding

TCP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
    }
)

SERIAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL_PATH, default="/dev/ttyUSB0"): str,
    }
)


async def _validate(client: HtdLyncClient) -> str:
    """Try to connect and identify the unit; returns the model name."""
    try:
        await client.async_connect()
        await client.async_wait_ready(timeout=8)
        return client.model or "Lync"
    finally:
        await client.async_disconnect()


class HtdLyncConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["tcp", "serial"])

    async def async_step_tcp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
            )
            self._abort_if_unique_id_configured()
            client = HtdLyncClient(
                host=user_input[CONF_HOST], port=user_input[CONF_PORT]
            )
            try:
                model = await _validate(client)
            except (asyncio.TimeoutError, OSError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"HTD {model}", data=user_input
                )
        return self.async_show_form(
            step_id="tcp", data_schema=TCP_SCHEMA, errors=errors
        )

    async def async_step_serial(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_SERIAL_PATH])
            self._abort_if_unique_id_configured()
            client = HtdLyncClient(serial_path=user_input[CONF_SERIAL_PATH])
            try:
                model = await _validate(client)
            except (asyncio.TimeoutError, OSError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"HTD {model}", data=user_input
                )
        return self.async_show_form(
            step_id="serial", data_schema=SERIAL_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the gateway IP/port (or serial path) of an existing entry."""
        entry = self._get_reconfigure_entry()
        is_serial = CONF_SERIAL_PATH in entry.data
        errors: dict[str, str] = {}

        if user_input is not None:
            if is_serial:
                client = HtdLyncClient(serial_path=user_input[CONF_SERIAL_PATH])
            else:
                client = HtdLyncClient(
                    host=user_input[CONF_HOST], port=user_input[CONF_PORT]
                )
            try:
                await _validate(client)
            except (asyncio.TimeoutError, OSError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        if is_serial:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_SERIAL_PATH,
                        default=entry.data.get(CONF_SERIAL_PATH),
                    ): str,
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST)): str,
                    vol.Required(
                        CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                    ): int,
                }
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HtdLyncOptionsFlow:
        return HtdLyncOptionsFlow()


class HtdLyncOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
                    vol.Required(
                        CONF_DOORBELL_RESTORE,
                        default=self.config_entry.options.get(
                            CONF_DOORBELL_RESTORE, DEFAULT_DOORBELL_RESTORE
                        ),
                    ): bool,
                    vol.Required(
                        CONF_MAX_ON_VOLUME,
                        default=self.config_entry.options.get(CONF_MAX_ON_VOLUME, 0),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                    vol.Required(
                        CONF_QUIET_CAP,
                        default=self.config_entry.options.get(CONF_QUIET_CAP, 0),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                    vol.Required(
                        CONF_QUIET_START,
                        default=self.config_entry.options.get(CONF_QUIET_START, "22:00"),
                    ): str,
                    vol.Required(
                        CONF_QUIET_END,
                        default=self.config_entry.options.get(CONF_QUIET_END, "07:00"),
                    ): str,
                    vol.Optional(
                        CONF_ANNOUNCE_PLAYER,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_ANNOUNCE_PLAYER
                            )
                        },
                    ): str,
                    vol.Optional(
                        CONF_ANNOUNCE_TTS,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_ANNOUNCE_TTS
                            )
                        },
                    ): str,
                    vol.Required(
                        CONF_TONE_ENCODING,
                        default=self.config_entry.options.get(
                            CONF_TONE_ENCODING, ToneEncoding.SIGNED.value
                        ),
                    ): vol.In([e.value for e in ToneEncoding]),
                }
            ),
        )
