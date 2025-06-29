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
        
        # ディレクトリが存在する場合は削除
        self._cleanup_directories()
        
        self.fernet = self._load_or_create_key()
        self.data = self._load_config()
    
    def _cleanup_directories(self):
        """ディレクトリが誤って作成されている場合の修正"""
        for file_path in [self.config_file, self.key_file]:
            if file_path.exists() and file_path.is_dir():
                logger.warning(f"ディレクトリが見つかりました。削除します: {file_path}")
                try:
                    import shutil
                    shutil.rmtree(file_path)
                except Exception as e:
                    logger.error(f"ディレクトリ削除エラー: {e}")
    
    def _load_or_create_key(self) -> Fernet:
        """暗号化キーの読み込みまたは生成"""
        try:
            if self.key_file.exists() and self.key_file.is_file():
                with open(self.key_file, 'rb') as f:
                    key_data = f.read()
                if key_data:  # ファイルが空でない場合
                    key = key_data
                    logger.info("既存の暗号化キーを読み込みました")
                else:
                    # 空ファイルの場合は新しいキーを生成
                    key = Fernet.generate_key()
                    with open(self.key_file, 'wb') as f:
                        f.write(key)
                    logger.info("空ファイルに新しい暗号化キーを生成しました")
            else:
                key = Fernet.generate_key()
                with open(self.key_file, 'wb') as f:
                    f.write(key)
                os.chmod(self.key_file, 0o600)
                logger.info("新しい暗号化キーを生成しました")
            
            return Fernet(key)
        except Exception as e:
            logger.error(f"暗号化キーの処理エラー: {e}")
            # フォールバック：新しいキーを生成
            key = Fernet.generate_key()
            try:
                with open(self.key_file, 'wb') as f:
                    f.write(key)
                logger.info("フォールバックで新しいキーを生成しました")
                return Fernet(key)
            except Exception as fallback_error:
                logger.error(f"フォールバックキー生成も失敗: {fallback_error}")
                raise
    
    def _load_config(self) -> Dict[int, Dict[str, Any]]:
        """設定ファイルの読み込み"""
        try:
            if not self.config_file.exists() or self.config_file.is_dir():
                return {}
            
            with open(self.config_file, 'rb') as f:
                encrypted_data = f.read()
            
            if not encrypted_data:
                return {}
            
            decrypted_data = self.fernet.decrypt(encrypted_data)
            data = json.loads(decrypted_data.decode('utf-8'))
            
            return {int(k): v for k, v in data.items()}
            
        except Exception as e:
            logger.error(f"設定ファイル読み込みエラー: {e}")
            return {}
    
    def _save_config(self):
        """設定ファイルの保存"""
        try:
            json_data = {str(k): v for k, v in self.data.items()}
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            encrypted_data = self.fernet.encrypt(json_str.encode('utf-8'))
            
            with open(self.config_file, 'wb') as f:
                f.write(encrypted_data)
            
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
