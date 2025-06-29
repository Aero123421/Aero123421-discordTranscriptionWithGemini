import discord
import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path

from config import BotConfig
from config_manager import ConfigManager
from gemini_client import GeminiClient

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TranscriptionBot(discord.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.message_content = True
        super().__init__(intents=intents)

        self.config = BotConfig()
        self.config_manager = ConfigManager()
        self.gemini_client = GeminiClient(self.config.gemini_api_key, self.config.gemini_model_name)

        # 録音中のセッション管理
        self.recording_sessions: Dict[int, Dict] = {}

    async def on_ready(self):
        logger.info(f'{self.user} がログインしました')
        logger.info(f'使用中のGeminiモデル: {self.config.gemini_model_name}')

    async def on_voice_state_update(self, member, before, after):
        """ボイス状態変更時の処理"""
        if member.bot:
            return

        guild_id = member.guild.id
        config = self.config_manager.get_config(guild_id)

        if not config:
            return

        # カテゴリまたはチャンネル指定の録音開始/終了判定
        should_start_recording = False
        should_stop_recording = False

        if config.get('voice_category_id'):
            # カテゴリベースの録音
            category_id = config['voice_category_id']
            category = self.get_channel(category_id)

            if category and isinstance(category, discord.CategoryChannel):
                voice_channels = category.voice_channels

                # カテゴリ内のボイスチャンネルに誰かが参加した
                if after.channel and after.channel in voice_channels:
                    should_start_recording = True

                # カテゴリ内のボイスチャンネルが全て空になった
                if before.channel and before.channel in voice_channels:
                    all_empty = all(len(vc.members) == 0 or all(m.bot for m in vc.members) for vc in voice_channels)
                    if all_empty:
                        should_stop_recording = True

        if should_start_recording and guild_id not in self.recording_sessions:
            await self._start_recording(member.guild)
        elif should_stop_recording and guild_id in self.recording_sessions:
            await self._stop_recording(member.guild)

    async def _start_recording(self, guild):
        """録音開始"""
        guild_id = guild.id
        config = self.config_manager.get_config(guild_id)

        if not config or guild_id in self.recording_sessions:
            return

        try:
            # カテゴリ内の最初の非空ボイスチャンネルに接続
            category_id = config.get('voice_category_id')
            if category_id:
                category = self.get_channel(category_id)
                if category and isinstance(category, discord.CategoryChannel):
                    target_channel = None
                    for vc in category.voice_channels:
                        if len(vc.members) > 0 and not all(m.bot for m in vc.members):
                            target_channel = vc
                            break

                    if target_channel:
                        voice_client = await target_channel.connect()

                        # 録音セッション開始
                        session = {
                            'voice_client': voice_client,
                            'start_time': datetime.now(),
                            'channel': target_channel
                        }
                        self.recording_sessions[guild_id] = session

                        # 録音開始
                        voice_client.start_recording(
                            discord.sinks.MP3Sink(),
                            self._recording_finished_callback,
                            guild
                        )

                        logger.info(f'録音開始: {guild.name} - {target_channel.name}')

        except Exception as e:
            logger.error(f'録音開始エラー: {e}')

    async def _stop_recording(self, guild):
        """録音停止"""
        guild_id = guild.id
        session = self.recording_sessions.get(guild_id)

        if session and session['voice_client'].is_connected():
            try:
                session['voice_client'].stop_recording()
                logger.info(f'録音停止: {guild.name}')
            except Exception as e:
                logger.error(f'録音停止エラー: {e}')

    async def _recording_finished_callback(self, sink: discord.sinks.MP3Sink, guild: discord.Guild):
        """録音終了時のコールバック"""
        guild_id = guild.id
        session = self.recording_sessions.get(guild_id)

        if not session:
            return

        try:
            # ボイスクライアント切断
            if session['voice_client'].is_connected():
                await session['voice_client'].disconnect()

            # セッション削除
            del self.recording_sessions[guild_id]

            # 録音データが存在する場合のみ処理
            if sink.audio_data:
                await self._process_recording(sink, guild, session)

        except Exception as e:
            logger.error(f'録音処理エラー: {e}')

    async def _process_recording(self, sink: discord.sinks.MP3Sink, guild: discord.Guild, session: Dict):
        """録音データの処理と文字起こし"""
        try:
            config = self.config_manager.get_config(guild.id)
            text_channel_id = config.get('text_channel_id')

            if not text_channel_id:
                logger.warning(f'テキストチャンネルが設定されていません: {guild.name}')
                return

            text_channel = self.get_channel(text_channel_id)
            if not text_channel:
                logger.warning(f'テキストチャンネルが見つかりません: {text_channel_id}')
                return

            # 全ユーザーの音声を結合
            combined_audio_data = b''
            user_count = 0

            for user_id, audio in sink.audio_data.items():
                if audio.file:
                    audio.file.seek(0)
                    combined_audio_data += audio.file.read()
                    user_count += 1

            if not combined_audio_data:
                logger.info('録音データが空でした')
                return

            # 一時ファイルに保存
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                temp_file.write(combined_audio_data)
                temp_file_path = temp_file.name

            try:
                # Gemini APIで文字起こし
                logger.info('Gemini APIで文字起こし開始...')
                transcription = await self.gemini_client.transcribe_audio(temp_file_path)

                if transcription:
                    # 結果をテキストファイルとして保存・送信
                    timestamp = session['start_time'].strftime('%Y%m%d_%H%M%S')
                    filename = f'transcription_{timestamp}.txt'

                    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as txt_file:
                        content = f"録音開始時刻: {session['start_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
                        content += f"録音チャンネル: {session['channel'].name}\n"
                        content += f"参加者数: {user_count}人\n"
                        content += "="*50 + "\n\n"
                        content += transcription

                        txt_file.write(content)
                        txt_file_path = txt_file.name

                    # Discordに送信
                    with open(txt_file_path, 'rb') as f:
                        file = discord.File(f, filename)
                        await text_channel.send(
                            f"📝 **文字起こし完了** ({session['channel'].name})",
                            file=file
                        )

                    # 一時ファイル削除
                    os.unlink(txt_file_path)
                    logger.info(f'文字起こし完了: {guild.name}')
                else:
                    await text_channel.send("❌ 文字起こしに失敗しました。")

            finally:
                # 音声一時ファイル削除
                os.unlink(temp_file_path)

        except Exception as e:
            logger.error(f'録音処理エラー: {e}')
            config = self.config_manager.get_config(guild.id)
            if config and config.get('text_channel_id'):
                text_channel = self.get_channel(config['text_channel_id'])
                if text_channel:
                    await text_channel.send(f"❌ 録音処理中にエラーが発生しました: {str(e)}")

# スラッシュコマンド
bot = TranscriptionBot()

@bot.slash_command(description="録音対象のボイスカテゴリを設定します")
async def set_voice_category(
    ctx: discord.ApplicationContext,
    category: discord.Option(discord.CategoryChannel, "録音対象のカテゴリ", required=True)
):
    """ボイスカテゴリ設定"""
    if not isinstance(category, discord.CategoryChannel):
        await ctx.respond("❌ カテゴリを選択してください。", ephemeral=True)
        return

    # カテゴリにボイスチャンネルがあるか確認
    voice_channels = [ch for ch in category.channels if isinstance(ch, discord.VoiceChannel)]
    if not voice_channels:
        await ctx.respond("❌ 選択されたカテゴリにボイスチャンネルがありません。", ephemeral=True)
        return

    bot.config_manager.set_voice_category(ctx.guild.id, category.id)

    await ctx.respond(
        f"✅ 録音対象カテゴリを設定しました: **{category.name}**\n"
        f"📍 このカテゴリ内のボイスチャンネル ({len(voice_channels)}個) で自動録音が有効になります。",
        ephemeral=True
    )

@bot.slash_command(description="文字起こし結果を送信するテキストチャンネルを設定します")
async def set_text_channel(
    ctx: discord.ApplicationContext,
    channel: discord.Option(discord.TextChannel, "結果送信用チャンネル", required=True)
):
    """結果送信チャンネル設定"""
    bot.config_manager.set_text_channel(ctx.guild.id, channel.id)
    await ctx.respond(f"✅ 結果送信チャンネルを設定しました: {channel.mention}", ephemeral=True)

@bot.slash_command(description="現在の設定を表示します")
async def show_channels(ctx: discord.ApplicationContext):
    """設定表示"""
    config = bot.config_manager.get_config(ctx.guild.id)

    if not config:
        await ctx.respond("❌ まだ設定がありません。", ephemeral=True)
        return

    embed = discord.Embed(title="🔧 現在の設定", color=0x00ff00)

    # ボイスカテゴリ設定
    if config.get('voice_category_id'):
        category = bot.get_channel(config['voice_category_id'])
        if category:
            voice_channels = [ch for ch in category.channels if isinstance(ch, discord.VoiceChannel)]
            embed.add_field(
                name="📢 録音対象カテゴリ",
                value=f"{category.name} ({len(voice_channels)}個のボイスチャンネル)",
                inline=False
            )

    # テキストチャンネル設定
    if config.get('text_channel_id'):
        text_channel = bot.get_channel(config['text_channel_id'])
        if text_channel:
            embed.add_field(
                name="📝 結果送信チャンネル",
                value=text_channel.mention,
                inline=False
            )

    # 録音状態
    if ctx.guild.id in bot.recording_sessions:
        session = bot.recording_sessions[ctx.guild.id]
        embed.add_field(
            name="🔴 録音状態",
            value=f"録音中 ({session['channel'].name})",
            inline=False
        )
    else:
        embed.add_field(
            name="⭕ 録音状態",
            value="待機中",
            inline=False
        )

    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(description="設定をすべて削除します")
async def unset_channels(ctx: discord.ApplicationContext):
    """設定削除"""
    bot.config_manager.clear_config(ctx.guild.id)
    await ctx.respond("✅ すべての設定を削除しました。", ephemeral=True)

@bot.slash_command(description="現在の録音を手動で停止します（管理者限定）")
@discord.default_permissions(administrator=True)
async def stop(ctx: discord.ApplicationContext):
    """手動録音停止"""
    guild_id = ctx.guild.id
    session = bot.recording_sessions.get(guild_id)

    if not session:
        await ctx.respond("❌ 現在録音していません。", ephemeral=True)
        return

    try:
        await bot._stop_recording(ctx.guild)
        await ctx.respond("✅ 録音を手動停止しました。", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"❌ 録音停止エラー: {str(e)}", ephemeral=True)

if __name__ == "__main__":
    bot.run(bot.config.discord_token)
