import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, config_file="channels.json"):
        self.cf = Path(config_file)
        self._cleanup()
        self.data = self._load_config()

    def _cleanup(self):
        if self.cf.exists() and self.cf.is_dir():
            import shutil; shutil.rmtree(self.cf)

    def _load_config(self):
        if not self.cf.exists() or self.cf.is_dir() or self.cf.stat().st_size == 0:
            return {}
        try:
            with self.cf.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(f"Could not decode {self.cf}, starting with a new config.")
            return {}

    def _save(self):
        with self.cf.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    def set_voice_category(self, guild_id, cat_id):
        self.data.setdefault(str(guild_id), {})["voice_category_id"] = cat_id
        self._save()

    def set_text_channel(self, guild_id, ch_id):
        self.data.setdefault(str(guild_id), {})["text_channel_id"] = ch_id
        self._save()

    def get_channels(self, guild_id):
        return self.data.get(str(guild_id), {})

    def unset_channels(self, guild_id):
        self.data.pop(str(guild_id), None)
        self._save()