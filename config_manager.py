import json
import os
from pathlib import Path
from typing import Dict, Optional, Any
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger(__name__)

class ConfigManager:
    """暗号化された設定管理クラス"""

    def __init__(self, config_file: str = "channels.json", key_file: str = "config.key"):
        self.config_file = Path(config_file)
        self.key_file = Path(key_file)
        self.fernet = self._load_or_create_key()
        self._config_cache: Dict[int, Dict[str, Any]] = {}
        self._load_config()

    def _load_or_create_key(self) -> Fernet:
        """暗号化キーの読み込みまたは作成"""
        try:
            if self.key_file.exists():
                with open(self.key_file, 'rb') as f:
                    key = f.read()
                logger.info("既存の暗号化キーを読み込みました")
            else:
                key = Fernet.generate_key()
                with open(self.key_file, 'wb') as f:
                    f.write(key)
                # キーファイルの権限を制限
                os.chmod(self.key_file, 0o600)
                logger.info("新しい暗号化キーを生成しました")

            return Fernet(key)

        except Exception as e:
            logger.error(f"暗号化キーの処理エラー: {e}")
            raise

    def _load_config(self):
        """設定ファイルの読み込み"""
        try:
            if not self.config_file.exists():
                logger.info("設定ファイルが存在しません。新規作成します。")
                self._config_cache = {}
                return

            with open(self.config_file, 'rb') as f:
                encrypted_data = f.read()

            if encrypted_data:
                decrypted_data = self.fernet.decrypt(encrypted_data)
                self._config_cache = json.loads(decrypted_data.decode('utf-8'))
                logger.info(f"設定ファイルを読み込みました ({len(self._config_cache)} サーバー)")
            else:
                self._config_cache = {}

        except Exception as e:
            logger.error(f"設定ファイル読み込みエラー: {e}")
            self._config_cache = {}

    def _save_config(self):
        """設定ファイルの保存"""
        try:
            # 数値キーを文字列に変換（JSON仕様のため）
            config_to_save = {str(k): v for k, v in self._config_cache.items()}

            json_data = json.dumps(config_to_save, indent=2, ensure_ascii=False)
            encrypted_data = self.fernet.encrypt(json_data.encode('utf-8'))

            with open(self.config_file, 'wb') as f:
                f.write(encrypted_data)

            # 設定ファイルの権限を制限
            os.chmod(self.config_file, 0o600)
            logger.info("設定ファイルを保存しました")

        except Exception as e:
            logger.error(f"設定ファイル保存エラー: {e}")
            raise

    def get_config(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """サーバー設定の取得"""
        return self._config_cache.get(guild_id)

    def set_voice_category(self, guild_id: int, category_id: int):
        """ボイスカテゴリの設定"""
        if guild_id not in self._config_cache:
            self._config_cache[guild_id] = {}

        self._config_cache[guild_id]['voice_category_id'] = category_id
        # 個別チャンネル設定をクリア（カテゴリ優先）
        self._config_cache[guild_id].pop('voice_channel_ids', None)

        self._save_config()
        logger.info(f"ボイスカテゴリを設定: Guild {guild_id}, Category {category_id}")

    def set_voice_channels(self, guild_id: int, channel_ids: list):
        """個別ボイスチャンネルの設定"""
        if guild_id not in self._config_cache:
            self._config_cache[guild_id] = {}

        self._config_cache[guild_id]['voice_channel_ids'] = channel_ids
        # カテゴリ設定をクリア（個別チャンネル優先）
        self._config_cache[guild_id].pop('voice_category_id', None)

        self._save_config()
        logger.info(f"ボイスチャンネルを設定: Guild {guild_id}, Channels {channel_ids}")

    def set_text_channel(self, guild_id: int, channel_id: int):
        """テキストチャンネルの設定"""
        if guild_id not in self._config_cache:
            self._config_cache[guild_id] = {}

        self._config_cache[guild_id]['text_channel_id'] = channel_id
        self._save_config()
        logger.info(f"テキストチャンネルを設定: Guild {guild_id}, Channel {channel_id}")

    def clear_config(self, guild_id: int):
        """サーバー設定の削除"""
        if guild_id in self._config_cache:
            del self._config_cache[guild_id]
            self._save_config()
            logger.info(f"設定を削除: Guild {guild_id}")

    def get_all_configs(self) -> Dict[int, Dict[str, Any]]:
        """全設定の取得（デバッグ用）"""
        return self._config_cache.copy()

    def backup_config(self, backup_file: str = None):
        """設定のバックアップ"""
        if backup_file is None:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = f"channels_backup_{timestamp}.json"

        try:
            with open(backup_file, 'w', encoding='utf-8') as f:
                config_to_backup = {str(k): v for k, v in self._config_cache.items()}
                json.dump(config_to_backup, f, indent=2, ensure_ascii=False)

            logger.info(f"設定をバックアップしました: {backup_file}")
            return backup_file

        except Exception as e:
            logger.error(f"バックアップエラー: {e}")
            raise

    def restore_config(self, backup_file: str):
        """設定の復元"""
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                restored_config = json.load(f)

            # 文字列キーを数値に変換
            self._config_cache = {int(k): v for k, v in restored_config.items()}
            self._save_config()
            logger.info(f"設定を復元しました: {backup_file}")

        except Exception as e:
            logger.error(f"復元エラー: {e}")
            raise
