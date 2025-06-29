import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

class ConfigManager:
    """チャンネル設定の暗号化管理"""
    
    def __init__(self, config_file: str = "channels.json", key_file: str = "encryption.key"):
        self.config_file = Path(config_file)
        self.key_file = Path(key_file)
        self.fernet = self._load_or_create_key()
        self.data = self._load_config()
    
    def _load_or_create_key(self) -> Fernet:
        """暗号化キーの読み込みまたは生成"""
        try:
            if self.key_file.exists():
                with open(self.key_file, 'rb') as f:
                    key = f.read()
                logger.info("既存の暗号化キーを読み込みました")
            else:
                key = Fernet.generate_key()
                with open(self.key_file, 'wb') as f:
                    f.write(key)
                # ファイル権限を制限
                os.chmod(self.key_file, 0o600)
                logger.info("新しい暗号化キーを生成しました")
            
            return Fernet(key)
        except Exception as e:
            logger.error(f"暗号化キーの処理エラー: {e}")
            raise
    
    def _load_config(self) -> Dict[int, Dict[str, Any]]:
        """設定ファイルの読み込み"""
        try:
            if not self.config_file.exists():
                return {}
            
            # ファイルがディレクトリの場合はエラー
            if self.config_file.is_dir():
                logger.error(f"設定ファイルがディレクトリです: {self.config_file}")
                return {}
            
            with open(self.config_file, 'rb') as f:
                encrypted_data = f.read()
            
            if not encrypted_data:
                return {}
            
            decrypted_data = self.fernet.decrypt(encrypted_data)
            data = json.loads(decrypted_data.decode('utf-8'))
            
            # guild_id を int に変換
            return {int(k): v for k, v in data.items()}
            
        except Exception as e:
            logger.error(f"設定ファイル読み込みエラー: {e}")
            return {}
    
    def _save_config(self):
        """設定ファイルの保存"""
        try:
            # guild_id を str に変換してJSON化
            json_data = {str(k): v for k, v in self.data.items()}
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            encrypted_data = self.fernet.encrypt(json_str.encode('utf-8'))
            
            with open(self.config_file, 'wb') as f:
                f.write(encrypted_data)
            
            # ファイル権限を制限
            os.chmod(self.config_file, 0o600)
            
        except Exception as e:
            logger.error(f"設定ファイル保存エラー: {e}")
            raise
    
    def set_voice_category(self, guild_id: int, category_id: int):
        """ボイスカテゴリ設定"""
        if guild_id not in self.data:
            self.data[guild_id] = {}
        
        self.data[guild_id]['voice_category_id'] = category_id
        self._save_config()
        logger.info(f"Voice category set for guild {guild_id}: {category_id}")
    
    def set_text_channel(self, guild_id: int, channel_id: int):
        """テキストチャンネル設定"""
        if guild_id not in self.data:
            self.data[guild_id] = {}
        
        self.data[guild_id]['text_channel_id'] = channel_id
        self._save_config()
        logger.info(f"Text channel set for guild {guild_id}: {channel_id}")
    
    def get_channels(self, guild_id: int) -> Dict[str, Any]:
        """チャンネル設定取得"""
        return self.data.get(guild_id, {})
    
    def unset_channels(self, guild_id: int):
        """チャンネル設定解除"""
        if guild_id in self.data:
            del self.data[guild_id]
            self._save_config()
            logger.info(f"All settings cleared for guild {guild_id}")

