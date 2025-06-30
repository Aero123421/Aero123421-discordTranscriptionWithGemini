import asyncio
import io
import logging
import os
import tempfile
from typing import Dict

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
    """MP3録音用カスタムシンク"""
    def __init__(self):
        super().__init__()

class SilenceAudioSource(discord.AudioSource):
    """音声接続維持用のサイレンス音声"""
    def read(self) -> bytes:
        return b'\x00' * 3840

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("------")
    logger.info("Starting Gemini API connection test...")
    try:
        if await gemini_client.test_connection():
            logger.info("✅ Gemini API connection test passed")
        else:
            logger.warning("⚠️ Gemini API connection test failed - continuing anyway")
    except Exception as e:
        logger.warning(f"⚠️ Connection test exception: {e} - continuing anyway")
    logger.info("🤖 Discord Transcription Bot is ready!")

@bot.slash_command(name="set_voice_category", description="録音対象のボイスチャンネルカテゴリを設定")
async def set_voice_category(ctx: discord.ApplicationContext, category: discord.CategoryChannel):
    try:
        config_manager.set_voice_category(ctx.guild.id, category.id)
        await ctx.respond(f"✅ 録音対象カテゴリを **{category.name}** に設定しました。", ephemeral=True)
        logger.info(f"Voice category set: {category.id} in guild {ctx.guild.id}")
    except Exception as e:
        await ctx.respond(f"❌ 設定に失敗: {e}", ephemeral=True)
        logger.error(e)

@bot.slash_command(name="set_text_channel", description="文字起こし結果を送信するテキストチャンネルを設定")
async def set_text_channel(ctx: discord.ApplicationContext, channel: discord.TextChannel):
    try:
        config_manager.set_text_channel(ctx.guild.id, channel.id)
        await ctx.respond(f"✅ 結果送信チャンネルを {channel.mention} に設定しました。", ephemeral=True)
        logger.info(f"Text channel set: {channel.id} in guild {ctx.guild.id}")
    except Exception as e:
        await ctx.respond(f"❌ 設定に失敗: {e}", ephemeral=True)
        logger.error(e)

@bot.slash_command(name="show_channels", description="現在の設定を表示")
async def show_channels(ctx: discord.ApplicationContext):
    try:
        await ctx.defer()
        settings = config_manager.get_channels(ctx.guild.id)
        embed = discord.Embed(title="📋 現在の設定", color=0x00ff00)
        
        # ボイスカテゴリ
        voice_id = settings.get('voice_category_id')
        embed.add_field(
            name="🎤 録音対象カテゴリ",
            value=f"<#{voice_id}>" if voice_id else "未設定",
            inline=False
        )
        
        # テキストチャンネル
        text_id = settings.get('text_channel_id')
        embed.add_field(
            name="📝 結果送信チャンネル",
            value=f"<#{text_id}>" if text_id else "未設定",
            inline=False
        )
        
        await ctx.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        if not ctx.response.is_done():
            await ctx.respond(f"❌ 取得失敗: {e}", ephemeral=True)
        logger.error(e)

@bot.slash_command(name="unset_channels", description="すべての設定を解除")
async def unset_channels(ctx: discord.ApplicationContext):
    try:
        await ctx.defer()
        config_manager.unset_channels(ctx.guild.id)
        await ctx.followup.send("✅ すべての設定を解除しました。", ephemeral=True)
        logger.info(f"Cleared settings for guild {ctx.guild.id}")
    except Exception as e:
        if not ctx.response.is_done():
            await ctx.respond(f"❌ 解除失敗: {e}", ephemeral=True)
        logger.error(e)

@bot.slash_command(name="stop", description="現在の録音を手動で停止（管理者のみ）")
@discord.default_permissions(administrator=True)
async def stop_recording_command(ctx: discord.ApplicationContext):
    try:
        await ctx.defer()
        guild_id = ctx.guild.id
        info = recording_states.get(guild_id)
        if not info:
            await ctx.followup.send("❌ 現在録音中ではありません。", ephemeral=True)
            return
        
        vc = info['voice_client']
        if vc and vc.recording:
            try:
                vc.stop_recording()
                await ctx.followup.send("✅ 録音を停止しました。", ephemeral=True)
                logger.info(f"Manual stop recording in guild {guild_id}")
            except Exception as e:
                await ctx.followup.send(f"❌ 停止に失敗: {e}", ephemeral=True)
                logger.error(f"Error manually stopping recording: {e}")
        else:
            await ctx.followup.send("❌ 録音中ではありません。", ephemeral=True)
    except Exception as e:
        if not ctx.response.is_done():
            await ctx.respond(f"❌ コマンドエラー: {e}", ephemeral=True)
        logger.error(e)

@bot.slash_command(name="test", description="接続テスト用コマンド")
async def test_command(ctx: discord.ApplicationContext):
    await ctx.respond("✅ Bot is working correctly!", ephemeral=True)
    logger.info(f"Test command by {ctx.user}")

@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    if member.bot:
        return
    
    guild_id = member.guild.id
    cat_id = config_manager.get_channels(guild_id).get('voice_category_id')
    
    if not cat_id:
        return
    
    def is_target(ch): 
        return ch and ch.category_id == cat_id
    
    # 録音開始（重複チェック強化）
    if not before.channel and after.channel and is_target(after.channel):
        if guild_id not in recording_states and not member.guild.voice_client:
            await start_recording(member.guild, after.channel)
        else:
            logger.debug(f"Recording already active or voice client exists for guild {guild_id}")
    
    # 録音停止
    elif before.channel and is_target(before.channel):
        cat = bot.get_channel(cat_id)
        if cat and all(len([m for m in vc.members if not m.bot]) == 0 for vc in cat.voice_channels):
            await stop_recording_cleanup(member.guild)

async def start_recording(guild: discord.Guild, channel: discord.VoiceChannel):
    guild_id = guild.id
    
    # 既存接続の詳細チェック
    if guild_id in recording_states:
        logger.warning(f"Recording already in progress for guild {guild_id}")
        return
    
    # 音声クライアント接続チェック
    if guild.voice_client:
        logger.warning(f"Already connected to voice in guild {guild_id}")
        return
    
    try:
        logger.info(f"Attempting to connect to voice channel: {channel.name}")
        vc = await channel.connect()
        
        # 🔧 Pycord固有の修正：サイレンス音声で接続維持
        silence_source = SilenceAudioSource()
        vc.play(silence_source)
        
        sink = MP3Sink()
        vc.start_recording(sink, finished_callback, channel)
        recording_states[guild_id] = {
            'voice_client': vc, 
            'sink': sink,
            'silence_source': silence_source
        }
        logger.info(f"Recording started in {channel.name} (Guild: {guild_id})")
        
    except discord.errors.ClientException as e:
        logger.error(f"ClientException in start_recording: {e}")
        # 既存の録音状態をクリーンアップ
        recording_states.pop(guild_id, None)
    except Exception as e:
        logger.error(f"Unexpected error in start_recording: {e}")
        recording_states.pop(guild_id, None)

async def stop_recording_cleanup(guild: discord.Guild):
    guild_id = guild.id
    info = recording_states.pop(guild_id, None)
    
    if info:
        vc = info['voice_client']
        if vc and vc.recording:
            try:
                vc.stop_recording()
                logger.info(f"Recording stopped for guild {guild_id}")
            except Exception as e:
                logger.error(f"Error stopping recording: {e}")
        
        # サイレンス音声停止
        if vc and vc.is_playing():
            try:
                vc.stop()
            except Exception as e:
                logger.error(f"Error stopping silence audio: {e}")

# ✅ 修正: 非同期コルーチンに変更（Pycord対応）
async def finished_callback(sink: MP3Sink, channel: discord.VoiceChannel, *args):
    """録音完了時のコールバック（非同期版）"""
    logger.info(f"Recording finished for {channel.name}")
    try:
        await process_recording(sink, channel)
    except Exception as e:
        logger.error(f"Error in finished_callback: {e}")

async def process_recording(sink: MP3Sink, channel: discord.VoiceChannel):
    guild = channel.guild
    guild_id = guild.id
    
    # 録音状態をクリーンアップ
    info = recording_states.pop(guild_id, None)
    
    # 音声クライアント切断
    if info and info['voice_client']:
        vc = info['voice_client']
        try:
            # サイレンス音声停止
            if vc.is_playing():
                vc.stop()
            
            # 音声クライアント切断
            await vc.disconnect()
            logger.info(f"Disconnected from voice channel in {guild.name}")
        except Exception as e:
            logger.error(f"Error disconnecting from voice: {e}")
    
    # 音声データ結合
    combined_audio = b"".join(buf.getvalue() for buf in sink.audio_data.values())
    if not combined_audio:
        logger.warning(f"No audio data recorded for {channel.name}")
        return
    
    logger.info(f"Processing {len(combined_audio)} bytes of audio data")
    
    # 一時ファイル作成
    tmp_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    try:
        tmp_file.write(combined_audio)
        tmp_file.close()
        
        # 文字起こし→整形
        logger.info(f"Starting transcription for {channel.name}")
        text = await gemini_client.transcribe_audio(tmp_file.name)
        
        if text:
            logger.info("Transcription completed, enhancing...")
            summary = await gemini_client.enhance_transcription(text)
        else:
            logger.warning("No text transcribed from audio")
            summary = "音声を文字起こしできませんでした。"
        
        # チャンネルへ送信
        text_id = config_manager.get_channels(guild_id).get('text_channel_id')
        if text_id:
            ch = bot.get_channel(text_id)
            if ch:
                fp = io.StringIO(summary)
                file = discord.File(fp, filename=f"transcript_{channel.name}_{guild_id}.txt")
                await ch.send(f"🎤 **{channel.name}** での録音結果:", file=file)
                logger.info(f"Transcript sent to channel {text_id}")
            else:
                logger.error(f"Text channel {text_id} not found")
        else:
            logger.warning(f"No text channel configured for guild {guild_id}")
            
    except Exception as e:
        logger.error(f"Error processing recording: {e}")
    finally:
        # 一時ファイル削除
        try:
            os.unlink(tmp_file.name)
            logger.debug(f"Deleted temporary file: {tmp_file.name}")
        except Exception as e:
            logger.error(f"Error deleting temp file: {e}")

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Error in event {event}", exc_info=True)

@bot.event
async def on_application_command_error(ctx: discord.ApplicationContext, error):
    try:
        if not ctx.response.is_done():
            await ctx.respond(f"❌ コマンドエラー: {error}", ephemeral=True)
        else:
            await ctx.followup.send(f"❌ コマンドエラー: {error}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error sending error message: {e}")
    logger.error(f"Command error: {error}", exc_info=True)

if __name__ == "__main__":
    try:
        bot.run(config.DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
