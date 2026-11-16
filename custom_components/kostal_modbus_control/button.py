"""Button that shows the Predbat apps.yaml settings for this inverter."""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BUTTON_PREDBAT_CONFIG, DOMAIN
from .predbat_config import build_predbat_apps_yaml


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kostal Modbus buttons."""
    async_add_entities([KostalPredbatConfigButton(hass.data[DOMAIN][entry.entry_id], entry)])


class KostalPredbatConfigButton(ButtonEntity):
    """Shows the apps.yaml settings Predbat needs, as a notification to copy from."""

    _attr_has_entity_name = True
    _attr_name = "Show Predbat Configuration"
    _attr_icon = "mdi:file-code-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data, entry: ConfigEntry) -> None:
        self._data = data
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{BUTTON_PREDBAT_CONFIG}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.entry_id)})

    async def async_press(self) -> None:
        yaml_text = build_predbat_apps_yaml(self.hass, self._entry, self._data)
        persistent_notification.async_create(
            self.hass,
            "Copy these settings into Predbat's `apps.yaml`. Lines starting with `#` "
            "show what was not found.\n\n```yaml\n" + yaml_text + "\n```",
            title="Predbat configuration",
            notification_id=f"{DOMAIN}_{self._entry.entry_id}_predbat_config",
        )
        # The notification only shows under Notifications, so say where to find it
        self.hass.bus.async_fire(
            "logbook_entry",
            {
                "name": str(self.name),
                "message": "Predbat configuration is ready under Notifications",
                "domain": DOMAIN,
                "entity_id": self.entity_id,
            },
        )
