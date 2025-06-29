import asyncio
import io
import logging
import os
import tempfile

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

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
            model_name: 使用モデル名（例: gemini-2.5-flash）
            thinking_budget: 思考予算（0=思考オフ, -1=動的思考, 正の整数=固定トークン数）
        """
        # API クライアント初期化
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.thinking_budget = thinking_budget

        # 安全設定（高レベルのみブロック）
        self.safety_settings = {
            types.HarmCategory.HARM_CATEGORY_HARASSMENT: types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        }

        # システム指示
        self.system_instruction = """
あなたはDiscordのボイスチャット音声を文字起こしする専門AIです。

【タスク】
1. 提供された音声ファイルを正確に日本語で文字起こししてください
2. 話者が複数いる場合は「話者A:」「話者B:」のように区別してください
3. 自然な会話の流れになるよう整形してください
4. 聞き取れない部分は[聞き取り不能]と記載してください

【出力形式】
- 読みやすい日本語で出力
- 話者切替は改行で区切る
- 重要な発言は**太字**で強調
- 時系列順に整理
"""

        logger.info(f"Initialized GeminiClient with model {model_name}")

    async def transcribe_audio(self, audio_file_path: str) -> str | None:
        """
        音声ファイルを文字起こし

        Returns:
            文字起こしテキスト (失敗時は None or エラーメッセージ)
        """
        try:
            if not os.path.exists(audio_file_path):
                logger.error("音声ファイルが見つかりません: %s", audio_file_path)
                return None

            size = os.path.getsize(audio_file_path)
            if size > 20 * 1024 * 1024:
                msg = f"⚠️ ファイル大きすぎ ({size/1024/1024:.1f}MB)、20MB以下にしてください"
                logger.warning(msg)
                return msg

            logger.info("Uploading audio: %s (%.1fKB)", audio_file_path, size/1024)

            # ファイルアップロード
            uploaded = self.client.files.upload(file=audio_file_path)

            # 生成設定
            gen_cfg = types.GenerationConfig(
                temperature=0.1,
                top_p=0.8,
                top_k=20,
                max_output_tokens=8192,
                candidate_count=1,
            )

            # 思考設定
            thinking_cfg = None
            if self.thinking_budget != 0:
                thinking_cfg = types.ThinkingConfig(
                    thinking_budget=(self.thinking_budget if self.thinking_budget > 0 else None)
                )

            # 非同期呼び出し
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=[self.system_instruction, uploaded],
                    generation_config=gen_cfg,
                    thinking_config=thinking_cfg,
                    safety_settings=self.safety_settings,
                )
            )

            # アップロードファイル削除
            try:
                genai.delete_file(uploaded.name)
            except Exception:
                pass

            if response.text:
                logger.info("Transcription succeeded")
                return response.text.strip()
            else:
                logger.warning("Empty transcription result")
                return "⚠️ 音声を認識できませんでした。"

        except Exception as e:
            logger.error("Transcription error: %s", e)
            msg = str(e).lower()
            if "quota" in msg:
                return "❌ API使用量制限に達しました。しばらくして再試行してください。"
            if "safety" in msg:
                return "⚠️ 安全性の理由で文字起こしをスキップしました。"
            if "file_too_large" in msg:
                return "❌ ファイルサイズが大きすぎます。20MB以下にしてください。"
            return f"❌ 文字起こし中にエラーが発生しました: {e}"

    async def enhance_transcription(self, raw: str) -> str:
        """
        文字起こし後のテキストを整形
        """
        try:
            prompt = f"""
以下の文字起こしテキストをより読みやすく整形してください：

【元テキスト】
{raw}

【整形要求】
- 話者を自然に段落分け
- 重要キーワードを**太字**で強調
- 会話の流れが分かりやすい構成
- 誤字脱字修正
- 不要な繰り返し除去
"""
            gen_cfg = types.GenerationConfig(temperature=0.3, max_output_tokens=4096)
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    generation_config=gen_cfg,
                    safety_settings=self.safety_settings,
                )
            )
            return response.text.strip() if response.text else raw
        except Exception as e:
            logger.error("Enhance error: %s", e)
            return raw

    def get_model_info(self) -> dict:
        """
        モデル情報取得
        """
        try:
            info = self.client.get_model(self.model_name)
            return {
                "name": info.name,
                "description": info.description,
                "input_token_limit": info.input_token_limit,
                "output_token_limit": info.output_token_limit,
                "supported_methods": info.supported_generation_methods,
            }
        except Exception as e:
            logger.error("Model info error: %s", e)
            return {"error": str(e)}

    async def test_connection(self) -> bool:
        """
        API 接続テスト
        """
        try:
            gen_cfg = types.GenerationConfig(max_output_tokens=10)
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents="こんにちは",
                    generation_config=gen_cfg,
                )
            )
            ok = bool(response.text)
            logger.info("Connection test %s", "succeeded" if ok else "failed")
            return ok
        except Exception as e:
            logger.error("Connection test error: %s", e)
            return False
