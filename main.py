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
        
        await ctx.respond(embed=embed, ephemeral=True)
    except Exception as e:
        await ctx.respond(f"❌ 取得失敗: {e}", ephemeral=True)
        logger.error(e)

@bot.slash_command(name="unset_channels", description="すべての設定を解除")
async def unset_channels(ctx: discord.ApplicationContext):
    try:
        config_manager.unset_channels(ctx.guild.id)
        await ctx.respond("✅ すべての設定を解除しました。", ephemeral=True)
        logger.info(f"Cleared settings for guild {ctx.guild.id}")
    except Exception as e:
        await ctx.respond(f"❌ 解除失敗: {e}", ephemeral=True)
        logger.error(e)

@bot.slash_command(name="stop", description="現在の録音を手動で停止（管理者のみ）")
@discord.default_permissions(administrator=True)
async def stop_recording(ctx: discord.ApplicationContext):
    guild_id = ctx.guild.id
    info = recording_states.get(guild_id)
    if not info:
        await ctx.respond("❌ 現在録音中ではありません。", ephemeral=True)
        return
    
    vc = info['voice_client']
    if vc and vc.recording:
        vc.stop_recording()
        await ctx.respond("✅ 録音を停止しました。", ephemeral=True)
        logger.info(f"Stopped recording in guild {guild_id}")
    else:
        await ctx.respond("❌ 録音中ではありません。", ephemeral=True)

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
    
    def is_target(ch): return ch and ch.category_id == cat_id
    
    # 録音開始
    if not before.channel and after.channel and is_target(after.channel):
        await start_recording(member.guild, after.channel)
    
    # 録音停止
    elif before.channel and is_target(before.channel):
        cat = bot.get_channel(cat_id)
        if cat and all(len([m for m in vc.members if not m.bot]) == 0 for vc in cat.voice_channels):
            await stop_recording_cleanup(member.guild)

async def start_recording(guild: discord.Guild, channel: discord.VoiceChannel):
    guild_id = guild.id
    if guild_id in recording_states:
        return
    
    vc = await channel.connect()
    sink = MP3Sink()
    vc.start_recording(sink, finished_callback, channel)
    recording_states[guild_id] = {'voice_client': vc, 'sink': sink}
    logger.info(f"Recording started in {channel.name}")

async def stop_recording_cleanup(guild: discord.Guild):
    info = recording_states.pop(guild.id, None)
    if info:
        vc = info['voice_client']
        if vc and vc.recording:
            vc.stop_recording()

def finished_callback(sink: MP3Sink, channel: discord.VoiceChannel, *args):
    logger.info(f"Recording finished for {channel.name}")
    loop = bot.loop
    if loop and not loop.is_closed():
        asyncio.run_coroutine_threadsafe(process_recording(sink, channel), loop)

async def process_recording(sink: MP3Sink, channel: discord.VoiceChannel):
    guild = channel.guild
    info = recording_states.pop(guild.id, None)
    if info and info['voice_client']:
        try:
            await info['voice_client'].disconnect()
        except:
            pass
    
    # 音声データ結合
    combined = b"".join(buf.getvalue() for buf in sink.audio_data.values())
    if not combined:
        return
    
    # 一時保存
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(combined)
    tmp.close()
    
    # 文字起こし→整形→送信
    text = await gemini_client.transcribe_audio(tmp.name)
    summary = await gemini_client.enhance_transcription(text or "")
    os.unlink(tmp.name)
    
    # チャンネルへ送信
    text_id = config_manager.get_channels(guild.id).get('text_channel_id')
    if text_id:
        ch = bot.get_channel(text_id)
        if ch:
            fp = io.StringIO(summary)
            await ch.send(file=discord.File(fp, filename="transcript.txt"))

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Error in {event}", exc_info=True)

@bot.event
async def on_application_command_error(ctx: discord.ApplicationContext, error):
    if not ctx.response.is_done():
        await ctx.respond(f"❌ コマンドエラー: {error}", ephemeral=True)
    logger.error(error, exc_info=True)

if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)
