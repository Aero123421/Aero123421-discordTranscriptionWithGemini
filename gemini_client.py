import asyncio
import logging
from pathlib import Path
from typing import Optional
import tempfile
import os

try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
except ImportError:
    raise ImportError("google-generativeai が必要です。pip install google-generativeai でインストールしてください。")

logger = logging.getLogger(__name__)

class GeminiClient:
    """Google Gemini 2.5 Flash APIクライアント"""

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", thinking_budget: int = -1):
        """
        Gemini APIクライアントの初期化

        Args:
            api_key: Google AI APIキー
            model_name: 使用するモデル名 (gemini-2.5-flash)
            thinking_budget: 思考予算 (0=思考オフ, -1=動的思考, 正の整数=トークン数)
        """
        self.api_key = api_key
        self.model_name = model_name
        self.thinking_budget = thinking_budget

        # Gemini API初期化
        genai.configure(api_key=api_key)

        # 安全設定（音声転写用に緩和）
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        }

        # モデル初期化
        self.model = genai.GenerativeModel(
            model_name=model_name,
            safety_settings=self.safety_settings,
            system_instruction=self._get_system_instruction()
        )

        logger.info(f"Gemini APIクライアント初期化完了: {model_name}")

    def _get_system_instruction(self) -> str:
        """システム指示の取得"""
        return """
あなたはDiscordのボイスチャット音声を文字起こしする専門AIです。

【タスク】
1. 提供された音声ファイルの内容を正確に日本語で文字起こししてください
2. 話者が複数いる場合は可能な限り区別してください
3. 会話の流れが自然になるよう整形してください
4. 聞き取れない部分は[聞き取り不能]と記載してください

【出力形式】
- 読みやすい日本語で出力
- 話者の切り替わりは改行で区切る
- 重要な発言やキーワードは**太字**で強調
- 時系列順に整理

【注意事項】
- 個人情報や機密情報が含まれる場合は適切に配慮
- 不適切な内容は[内容を適切に修正]として処理
- 音声品質が悪い場合はその旨を記載

正確で読みやすい文字起こしを心がけてください。
"""

    async def transcribe_audio(self, audio_file_path: str) -> Optional[str]:
        """
        音声ファイルの文字起こし

        Args:
            audio_file_path: 音声ファイルのパス

        Returns:
            文字起こし結果のテキスト（失敗時はNone）
        """
        try:
            if not os.path.exists(audio_file_path):
                logger.error(f"音声ファイルが見つかりません: {audio_file_path}")
                return None

            # ファイルサイズチェック（20MB制限）
            file_size = os.path.getsize(audio_file_path)
            if file_size > 20 * 1024 * 1024:
                logger.warning(f"ファイルサイズが大きすぎます: {file_size / 1024 / 1024:.1f}MB")
                return "⚠️ 音声ファイルが大きすぎるため、文字起こしできませんでした（制限: 20MB）"

            logger.info(f"音声文字起こし開始: {audio_file_path} ({file_size / 1024:.1f}KB)")

            # 音声ファイルをアップロード
            audio_file = genai.upload_file(audio_file_path)

            # Gemini 2.5 Flash用の生成設定
            generation_config = genai.types.GenerationConfig(
                temperature=0.1,  # 一貫性重視
                top_p=0.8,
                top_k=20,
                max_output_tokens=8192,
                candidate_count=1
            )

            # 思考機能設定（2.5 Flash用）
            thinking_config = None
            if self.thinking_budget != 0:  # 思考機能を使用
                thinking_config = genai.types.ThinkingConfig(
                    thinking_budget=self.thinking_budget if self.thinking_budget > 0 else None
                )

            # プロンプト作成
            prompt = """
この音声ファイルを日本語で文字起こししてください。

【要求事項】
1. 会話の内容を正確に文字起こし
2. 話者が複数いる場合は「話者A:」「話者B:」のように区別
3. 聞き取れない部分は[聞き取り不能]と記載
4. 自然な日本語に整形
5. 重要な内容は太字で強調

音声ファイル:
"""

            # 文字起こし実行
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.model.generate_content(
                    [prompt, audio_file],
                    generation_config=generation_config,
                    safety_settings=self.safety_settings
                )
            )

            # アップロードしたファイルを削除
            genai.delete_file(audio_file.name)

            if response.text:
                logger.info("文字起こし成功")
                return response.text.strip()
            else:
                logger.warning("文字起こし結果が空でした")
                return "⚠️ 音声を認識できませんでした。音声が小さすぎるか、ノイズが多い可能性があります。"

        except Exception as e:
            logger.error(f"文字起こしエラー: {e}")

            # エラーの種類に応じたメッセージ
            error_msg = str(e).lower()
            if "quota" in error_msg:
                return "❌ API使用量制限に達しました。しばらく時間をおいてからお試しください。"
            elif "safety" in error_msg:
                return "⚠️ 安全性の理由により文字起こしをスキップしました。"
            elif "file_too_large" in error_msg:
                return "❌ ファイルサイズが大きすぎます。20MB以下のファイルを使用してください。"
            else:
                return f"❌ 文字起こし中にエラーが発生しました: {str(e)}"

    async def enhance_transcription(self, raw_transcription: str) -> str:
        """
        文字起こし結果の改善・整形

        Args:
            raw_transcription: 生の文字起こしテキスト

        Returns:
            改善された文字起こしテキスト
        """
        try:
            prompt = f"""
以下の文字起こしテキストをより読みやすく整形してください：

【元テキスト】
{raw_transcription}

【整形要求】
1. 話者の発言を自然な段落に分ける
2. 重要なキーワードを**太字**で強調
3. 会話の流れが理解しやすいよう構成
4. 誤字脱字があれば修正
5. 不自然な繰り返しや「えー」「あの」等の整理

読みやすく整形されたテキストを出力してください。
"""

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,
                        max_output_tokens=4096
                    )
                )
            )

            if response.text:
                return response.text.strip()
            else:
                return raw_transcription

        except Exception as e:
            logger.error(f"文字起こし改善エラー: {e}")
            return raw_transcription

    def get_model_info(self) -> dict:
        """モデル情報の取得"""
        try:
            model_info = genai.get_model(self.model_name)
            return {
                'name': model_info.name,
                'display_name': model_info.display_name,
                'description': model_info.description,
                'input_token_limit': model_info.input_token_limit,
                'output_token_limit': model_info.output_token_limit,
                'supported_generation_methods': model_info.supported_generation_methods,
                'temperature': getattr(model_info, 'temperature', 'N/A'),
                'top_p': getattr(model_info, 'top_p', 'N/A'),
                'top_k': getattr(model_info, 'top_k', 'N/A')
            }
        except Exception as e:
            logger.error(f"モデル情報取得エラー: {e}")
            return {'error': str(e)}

    async def test_connection(self) -> bool:
        """API接続テスト"""
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.model.generate_content(
                    "こんにちは",
                    generation_config=genai.types.GenerationConfig(max_output_tokens=10)
                )
            )

            if response.text:
                logger.info("Gemini API接続テスト成功")
                return True
            else:
                logger.warning("Gemini API接続テスト失敗: レスポンスが空")
                return False

        except Exception as e:
            logger.error(f"Gemini API接続テスト失敗: {e}")
            return False
