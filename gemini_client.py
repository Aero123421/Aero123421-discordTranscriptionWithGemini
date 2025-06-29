import asyncio
import io
import logging
import os
import tempfile

from google import genai

logger = logging.getLogger(__name__)

class GeminiClient:
    """Google Gemini 2.5 Flash API クライアント"""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        thinking_budget: int = -1,
    ):
        """
        Args:
            api_key: Google Gemini API キー
            model_name: 使用モデル名
            thinking_budget: 思考予算（現在未使用）
        """
        # 環境変数を設定してからクライアント初期化
        os.environ["GEMINI_API_KEY"] = api_key
        self.client = genai.Client()  # 引数なしで初期化
        self.model_name = model_name

        logger.info(f"Initialized GeminiClient with model {model_name}")

    async def transcribe_audio(self, audio_file_path: str) -> str | None:
        """音声ファイルを文字起こし"""
        try:
            if not os.path.exists(audio_file_path):
                logger.error("音声ファイルが見つかりません: %s", audio_file_path)
                return None

            size = os.path.getsize(audio_file_path)
            if size > 20 * 1024 * 1024:
                msg = f"⚠️ ファイル大きすぎ ({size/1024/1024:.1f}MB)、20MB以下にしてください"
                logger.warning(msg)
                return msg

            logger.info("Processing audio: %s (%.1fKB)", audio_file_path, size/1024)

            # ファイルアップロード
            uploaded = self.client.files.upload(file=audio_file_path)

            # シンプルな音声文字起こしプロンプト
            prompt = """この音声ファイルを日本語で文字起こししてください。

【要求事項】
- 会話内容を正確に文字起こし
- 話者が複数いる場合は「話者A:」「話者B:」で区別
- 聞き取れない部分は[聞き取り不能]と記載
- 自然な日本語に整形
- 重要な内容は**太字**で強調"""

            # API呼び出し（新SDK方式）
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=[prompt, uploaded]
                )
            )

            # ファイル削除
            try:
                self.client.files.delete(name=uploaded.name)
            except Exception:
                pass

            # レスポンス処理
            if response and hasattr(response, 'text') and response.text:
                logger.info("Transcription succeeded")
                return response.text.strip()
            else:
                logger.warning("Empty or invalid transcription response")
                return "⚠️ 音声を認識できませんでした。"

        except Exception as e:
            logger.error("Transcription error: %s", e)
            error_msg = str(e).lower()
            if "quota" in error_msg or "resource_exhausted" in error_msg:
                return "❌ API使用量制限に達しました。しばらくして再試行してください。"
            elif "safety" in error_msg:
                return "⚠️ 安全性の理由で文字起こしをスキップしました。"
            elif "file_too_large" in error_msg:
                return "❌ ファイルサイズが大きすぎます。20MB以下にしてください。"
            else:
                return f"❌ 文字起こし中にエラーが発生しました: {e}"

    async def enhance_transcription(self, raw: str) -> str:
        """文字起こし後のテキストを整形"""
        try:
            prompt = f"""以下の文字起こしテキストを読みやすく整形してください：

【元テキスト】
{raw}

【整形要求】
- 話者を自然に段落分け
- 重要キーワードを**太字**で強調
- 会話の流れが分かりやすい構成
- 誤字脱字修正
- 不要な繰り返し除去"""
            
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
            )
            
            if response and hasattr(response, 'text') and response.text:
                return response.text.strip()
            else:
                return raw
                
        except Exception as e:
            logger.error("Enhancement error: %s", e)
            return raw

    def get_model_info(self) -> dict:
        """モデル情報取得"""
        return {
            "name": self.model_name,
            "description": "Gemini 2.5 Flash model via google-genai SDK",
            "status": "active"
        }

    async def test_connection(self) -> bool:
        """API 接続テスト（修正版）"""
        try:
            # シンプルなテストリクエスト
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents="Hello"
                )
            )
            
            # レスポンス確認
            if response and hasattr(response, 'text') and response.text:
                logger.info("Connection test succeeded: %s", response.text[:50])
                return True
            else:
                logger.warning("Connection test failed: no valid text response")
                logger.debug("Response object: %s", response)
                return False
                
        except Exception as e:
            logger.error("Connection test error: %s", e)
            return False

