import json
import logging
import os
from pathlib import Path
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, config_file="channels.json", key_file="encryption.key"):
        self.cf = Path(config_file)
        self.kf = Path(key_file)
        self._cleanup()
        self.fernet = self._load_or_create_key()
        self.data = self._load_config()

    def _cleanup(self):
        for p in (self.cf, self.kf):
            if p.exists() and p.is_dir():
                import shutil; shutil.rmtree(p)

    def _load_or_create_key(self):
        if self.kf.exists() and self.kf.is_file():
            key = self.kf.read_bytes() or Fernet.generate_key()
        else:
            key = Fernet.generate_key()
            self.kf.write_bytes(key)
            os.chmod(self.kf, 0o600)
        logger.info("Encryption key loaded")
        return Fernet(key)

    def _load_config(self):
        if not self.cf.exists() or self.cf.is_dir():
            return {}
        raw = self.cf.read_bytes()
        if not raw:
            return {}
        dec = self.fernet.decrypt(raw)
        return json.loads(dec)

    def _save(self):
        enc = self.fernet.encrypt(json.dumps(self.data).encode())
        self.cf.write_bytes(enc)
        os.chmod(self.cf, 0o600)

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
