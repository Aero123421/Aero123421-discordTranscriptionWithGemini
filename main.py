import asyncio
import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

import discord
from discord.ext import commands

from config import BotConfig
from config_manager import ConfigManager
from gemini_client import GeminiClient

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 設定読み込み
config = BotConfig()

# Discord Bot設定
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

# Bot初期化（修正版）
bot = commands.Bot(command_prefix="!", intents=intents)

# Gemini クライアント初期化
gemini_client = GeminiClient(
    api_key=config.GEMINI_API_KEY,
    model_name=config.GEMINI_MODEL_NAME,
    thinking_budget=config.GEMINI_THINKING_BUDGET
)

# 設定管理
config_manager = ConfigManager()

# 録音状態管理
recording_states: Dict[int, Dict] = {}


class MP3Sink(discord.sinks.MP3Sink):
    """MP3録音用のカスタムシンク"""
    
    def __init__(self):
        super().__init__()


@bot.event
async def on_ready():
    """Bot起動時の処理"""
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("------")
    
    # Gemini API接続テスト
    if await gemini_client.test_connection():
        logger.info("Gemini API connection test passed")
    else:
        logger.error("Gemini API connection test failed")


# スラッシュコマンド定義（修正版：@bot.slash_command を使用）
@bot.slash_command(name="set_voice_category", description="録音対象のボイスチャンネルカテゴリを設定")
async def set_voice_category(ctx: discord.ApplicationContext, category: discord.CategoryChannel):
    """ボイスカテゴリ設定"""
    try:
        config_manager.set_voice_category(ctx.guild.id, category.id)
        await ctx.respond(
            f"✅ 録音対象カテゴリを **{category.name}** に設定しました。\n"
            f"このカテゴリ内のボイスチャンネルに参加すると録音が開始されます。",
            ephemeral=True
        )
        logger.info(f"Voice category set: {category.name} (ID: {category.id}) in guild {ctx.guild.id}")
    except Exception as e:
        await ctx.respond(f"❌ 設定に失敗しました: {e}", ephemeral=True)
        logger.error(f"Failed to set voice category: {e}")


@bot.slash_command(name="set_text_channel", description="文字起こし結果を送信するテキストチャンネルを設定")
async def set_text_channel(ctx: discord.ApplicationContext, channel: discord.TextChannel):
    """テキストチャンネル設定"""
    try:
        config_manager.set_text_channel(ctx.guild.id, channel.id)
        await ctx.respond(
            f"✅ 文字起こし結果送信チャンネルを {channel.mention} に設定しました。",
            ephemeral=True
        )
        logger.info(f"Text channel set: {channel.name} (ID: {channel.id}) in guild {ctx.guild.id}")
    except Exception as e:
        await ctx.respond(f"❌ 設定に失敗しました: {e}", ephemeral=True)
        logger.error(f"Failed to set text channel: {e}")


@bot.slash_command(name="show_channels", description="現在の設定を表示")
async def show_channels(ctx: discord.ApplicationContext):
    """設定表示"""
    try:
        settings = config_manager.get_channels(ctx.guild.id)
        
        embed = discord.Embed(title="📋 現在の設定", color=0x00ff00)
        
        # ボイスカテゴリ設定
        if settings.get('voice_category_id'):
            category = bot.get_channel(settings['voice_category_id'])
            if category:
                embed.add_field(
                    name="🎤 録音対象カテゴリ",
                    value=f"**{category.name}**\n(ID: {category.id})",
                    inline=False
                )
            else:
                embed.add_field(
                    name="🎤 録音対象カテゴリ",
                    value=f"⚠️ カテゴリが見つかりません (ID: {settings['voice_category_id']})",
                    inline=False
                )
        else:
            embed.add_field(
                name="🎤 録音対象カテゴリ",
                value="未設定",
                inline=False
            )
        
        # テキストチャンネル設定
        if settings.get('text_channel_id'):
            channel = bot.get_channel(settings['text_channel_id'])
            if channel:
                embed.add_field(
                    name="📝 結果送信チャンネル",
                    value=f"{channel.mention}\n(ID: {channel.id})",
                    inline=False
                )
            else:
                embed.add_field(
                    name="📝 結果送信チャンネル",
                    value=f"⚠️ チャンネルが見つかりません (ID: {settings['text_channel_id']})",
                    inline=False
                )
        else:
            embed.add_field(
                name="📝 結果送信チャンネル",
                value="未設定",
                inline=False
            )
        
        await ctx.respond(embed=embed, ephemeral=True)
        
    except Exception as e:
        await ctx.respond(f"❌ 設定の取得に失敗しました: {e}", ephemeral=True)
        logger.error(f"Failed to show channels: {e}")


@bot.slash_command(name="unset_channels", description="すべての設定を解除")
async def unset_channels(ctx: discord.ApplicationContext):
    """設定解除"""
    try:
        config_manager.unset_channels(ctx.guild.id)
        await ctx.respond("✅ すべての設定を解除しました。", ephemeral=True)
        logger.info(f"All settings cleared for guild {ctx.guild.id}")
    except Exception as e:
        await ctx.respond(f"❌ 設定の解除に失敗しました: {e}", ephemeral=True)
        logger.error(f"Failed to unset channels: {e}")


@bot.slash_command(name="stop", description="現在の録音を手動で停止（管理者のみ）")
@discord.default_permissions(administrator=True)
async def stop_recording_command(ctx: discord.ApplicationContext):
    """録音手動停止"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in recording_states:
            await ctx.respond("❌ 現在録音中ではありません。", ephemeral=True)
            return
        
        recording_info = recording_states[guild_id]
        vc = recording_info.get('voice_client')
        
        if vc and vc.recording:
            vc.stop_recording()
            await ctx.respond("✅ 録音を手動で停止しました。文字起こし処理を開始します。", ephemeral=True)
            logger.info(f"Recording manually stopped in guild {guild_id}")
        else:
            await ctx.respond("❌ 録音が見つかりません。", ephemeral=True)
            
    except Exception as e:
        await ctx.respond(f"❌ 録音停止に失敗しました: {e}", ephemeral=True)
        logger.error(f"Failed to stop recording: {e}")


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """ボイス状態変更時の処理"""
    if member.bot:  # Bot は無視
        return
    
    guild_id = member.guild.id
    settings = config_manager.get_channels(guild_id)
    voice_category_id = settings.get('voice_category_id')
    
    if not voice_category_id:
        return  # カテゴリが設定されていない
    
    # カテゴリ内のチャンネルかチェック
    def is_target_channel(channel):
        return channel and channel.category_id == voice_category_id
    
    # 録音開始判定
    if not before.channel and after.channel and is_target_channel(after.channel):
        await start_recording(member.guild, after.channel)
    
    # 録音停止判定（カテゴリ内のすべてのチャンネルが空になった場合）
    elif before.channel and is_target_channel(before.channel):
        category = bot.get_channel(voice_category_id)
        if category:
            # カテゴリ内のボイスチャンネルをチェック
            has_members = False
            for channel in category.voice_channels:
                if len([m for m in channel.members if not m.bot]) > 0:
                    has_members = True
                    break
            
            if not has_members:
                await stop_recording(member.guild)


async def start_recording(guild: discord.Guild, voice_channel: discord.VoiceChannel):
    """録音開始"""
    try:
        guild_id = guild.id
        
        # 既に録音中の場合はスキップ
        if guild_id in recording_states:
            return
        
        # ボイスチャンネルに接続
        vc = await voice_channel.connect()
        
        # 録音開始
        sink = MP3Sink()
        vc.start_recording(sink, finished_callback, voice_channel)
        
        # 録音状態を保存
        recording_states[guild_id] = {
            'voice_client': vc,
            'voice_channel': voice_channel,
            'sink': sink,
            'start_time': asyncio.get_event_loop().time()
        }
        
        logger.info(f"Recording started in {voice_channel.name} (Guild: {guild.name})")
        
    except Exception as e:
        logger.error(f"Failed to start recording: {e}")
        # 接続に失敗した場合はクリーンアップ
        if guild_id in recording_states:
            del recording_states[guild_id]


async def stop_recording(guild: discord.Guild):
    """録音停止"""
    try:
        guild_id = guild.id
        
        if guild_id not in recording_states:
            return
        
        recording_info = recording_states[guild_id]
        vc = recording_info['voice_client']
        
        if vc and vc.recording:
            vc.stop_recording()
        
        logger.info(f"Recording stopped in guild {guild.name}")
        
    except Exception as e:
        logger.error(f"Failed to stop recording: {e}")


def finished_callback(sink: MP3Sink, voice_channel: discord.VoiceChannel, *args):
    """録音完了時のコールバック"""
    asyncio.create_task(process_recording(sink, voice_channel))


async def process_recording(sink: MP3Sink, voice_channel: discord.VoiceChannel):
    """録音データの処理"""
    try:
        guild_id = voice_channel.guild.id
        
        # 録音状態をクリーンアップ
        if guild_id in recording_states:
            recording_info = recording_states.pop(guild_id)
            vc = recording_info['voice_client']
            if vc:
                await vc.disconnect()
        
        # 音声データが空の場合はスキップ
        if not sink.audio_data:
            logger.info("No audio data recorded, skipping transcription")
            return
        
        # 音声データを結合
        combined_audio = b""
        for user_id, audio_data in sink.audio_data.items():
            combined_audio += audio_data.getvalue()
        
        if not combined_audio:
            logger.info("Combined audio is empty, skipping transcription")
            return
        
        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
            tmp_file.write(combined_audio)
            tmp_file_path = tmp_file.name
        
        try:
            logger.info(f"Processing audio file: {tmp_file_path}")
            
            # 文字起こし実行
            transcription = await gemini_client.transcribe_audio(tmp_file_path)
            
            if not transcription:
                logger.warning("Transcription failed or empty")
                return
            
            # テキスト整形
            enhanced_text = await gemini_client.enhance_transcription(transcription)
            
            # 結果をテキストチャンネルに送信
            await send_transcription_result(voice_channel.guild, enhanced_text, voice_channel.name)
            
        finally:
            # 一時ファイルを削除
            try:
                os.unlink(tmp_file_path)
            except Exception as e:
                logger.error(f"Failed to delete temp file: {e}")
        
    except Exception as e:
        logger.error(f"Failed to process recording: {e}")


async def send_transcription_result(guild: discord.Guild, text: str, voice_channel_name: str):
    """文字起こし結果の送信"""
    try:
        settings = config_manager.get_channels(guild.id)
        text_channel_id = settings.get('text_channel_id')
        
        if not text_channel_id:
            logger.warning(f"Text channel not configured for guild {guild.id}")
            return
        
        text_channel = bot.get_channel(text_channel_id)
        if not text_channel:
            logger.error(f"Text channel not found: {text_channel_id}")
            return
        
        # ファイルとして送信
        file_content = f"ボイスチャンネル: {voice_channel_name}\n" \
                      f"サーバー: {guild.name}\n" \
                      f"日時: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n" \
                      f"--- 文字起こし結果 ---\n\n{text}"
        
        file_obj = io.StringIO(file_content)
        discord_file = discord.File(file_obj, filename=f"transcript_{voice_channel_name}_{discord.utils.utcnow().strftime('%Y%m%d_%H%M%S')}.txt")
        
        embed = discord.Embed(
            title="🎤 音声文字起こし完了",
            description=f"**ボイスチャンネル:** {voice_channel_name}",
            color=0x00ff00,
            timestamp=discord.utils.utcnow()
        )
        
        await text_channel.send(embed=embed, file=discord_file)
        logger.info(f"Transcription result sent to {text_channel.name}")
        
    except Exception as e:
        logger.error(f"Failed to send transcription result: {e}")


@bot.event
async def on_error(event, *args, **kwargs):
    """エラーハンドリング"""
    logger.error(f"An error occurred in event {event}", exc_info=True)


if __name__ == "__main__":
    try:
        bot.run(config.DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

