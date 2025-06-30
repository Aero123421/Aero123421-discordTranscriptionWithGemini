# main.py
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

# ------------------------------------------------------------
# ログ設定
# ------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# 設定読み込み
# ------------------------------------------------------------
config = BotConfig()

# ------------------------------------------------------------
# Discord Bot 初期化
# ------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------------------------------------------
# Gemini クライアント
# ------------------------------------------------------------
gemini_client = GeminiClient(
    api_key=config.GEMINI_API_KEY,
    model_name=config.GEMINI_MODEL_NAME,
    thinking_budget=config.GEMINI_THINKING_BUDGET,
)

# ------------------------------------------------------------
# 設定管理
# ------------------------------------------------------------
config_manager = ConfigManager()

# ------------------------------------------------------------
# 録音状態管理
# ------------------------------------------------------------
recording_states: Dict[int, Dict] = {}

# ------------------------------------------------------------
# Sink & Silence Source
# ------------------------------------------------------------
class MP3Sink(discord.sinks.MP3Sink):
    """Pycord MP3 Sink"""
    def __init__(self):
        super().__init__()

class SilenceAudioSource(discord.AudioSource):
    """接続維持用の無音ストリーム"""
    def read(self) -> bytes:  # 20 ms = 3840byte (48kHz * 2ch * 2byte * 0.02)
        return b"\x00" * 3840

# ------------------------------------------------------------
# Bot イベント
# ------------------------------------------------------------
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("------")
    logger.info("Starting Gemini API connection test...")
    if await gemini_client.test_connection():
        logger.info("✅ Gemini API connection test passed")
    else:
        logger.warning("⚠️ Gemini API connection test failed - continuing anyway")
    logger.info("🤖 Discord Transcription Bot is ready!")

# ------------------------------------------------------------
# スラッシュコマンド
# ------------------------------------------------------------
@bot.slash_command(name="set_voice_category", description="録音対象のボイスカテゴリを設定")
async def set_voice_category(ctx: discord.ApplicationContext, category: discord.CategoryChannel):
    config_manager.set_voice_category(ctx.guild.id, category.id)
    await ctx.respond(f"✅ 録音対象カテゴリを **{category.name}** に設定しました。", ephemeral=True)

@bot.slash_command(name="set_text_channel", description="文字起こし送信チャンネルを設定")
async def set_text_channel(ctx: discord.ApplicationContext, channel: discord.TextChannel):
    config_manager.set_text_channel(ctx.guild.id, channel.id)
    await ctx.respond(f"✅ 結果送信チャンネルを {channel.mention} に設定しました。", ephemeral=True)

@bot.slash_command(name="show_channels", description="現在の設定を表示")
async def show_channels(ctx: discord.ApplicationContext):
    s = config_manager.get_channels(ctx.guild.id)
    embed = discord.Embed(title="📋 現在の設定", color=0x00ff00)
    embed.add_field(name="🎤 録音対象カテゴリ",
                    value=f"<#{s.get('voice_category_id')}>" if s.get('voice_category_id') else "未設定",
                    inline=False)
    embed.add_field(name="📝 結果送信チャンネル",
                    value=f"<#{s.get('text_channel_id')}>" if s.get('text_channel_id') else "未設定",
                    inline=False)
    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name="unset_channels", description="設定をすべて解除")
async def unset_channels(ctx: discord.ApplicationContext):
    config_manager.unset_channels(ctx.guild.id)
    await ctx.respond("✅ すべての設定を解除しました。", ephemeral=True)

@bot.slash_command(name="stop", description="現在の録音を停止（管理者のみ）")
@discord.default_permissions(administrator=True)
async def stop_recording_cmd(ctx: discord.ApplicationContext):
    info = recording_states.get(ctx.guild.id)
    if not info:
        await ctx.respond("❌ 現在録音中ではありません。", ephemeral=True)
        return
    vc: discord.VoiceClient = info["voice_client"]
    if vc and vc.recording:
        vc.stop_recording()
        await ctx.respond("✅ 録音を停止しました。", ephemeral=True)

# ------------------------------------------------------------
# Voice State 監視
# ------------------------------------------------------------
@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    if member.bot:
        return

    guild_id = member.guild.id
    cat_id = config_manager.get_channels(guild_id).get("voice_category_id")
    if not cat_id:
        return

    def is_target(ch): return ch and ch.category_id == cat_id

    # ── 参加：録音開始 ──────────────────────────────
    if not before.channel and after.channel and is_target(after.channel):
        if guild_id not in recording_states and not member.guild.voice_client:
            await start_recording(member.guild, after.channel)

    # ── 退出：録音停止（カテゴリ内に誰も居なくなった） ─────────
    elif before.channel and is_target(before.channel):
        cat = bot.get_channel(cat_id)
        if cat and all(len([m for m in vc.members if not m.bot]) == 0
                       for vc in cat.voice_channels):
            await stop_recording_cleanup(member.guild)

# ------------------------------------------------------------
# 録音開始
# ------------------------------------------------------------
async def start_recording(guild: discord.Guild, channel: discord.VoiceChannel):
    if guild.voice_client or guild.id in recording_states:
        return

    logger.info(f"Attempting to connect to voice channel: {channel.name}")
    vc = await channel.connect()

    # 接続維持用に無音を再生
    silence = SilenceAudioSource()
    vc.play(silence)

    sink = MP3Sink()
    vc.start_recording(sink, finished_callback, channel)

    recording_states[guild.id] = {
        "voice_client": vc,
        "sink": sink,
        "silence": silence,
    }
    logger.info(f"Recording started in {channel.name} (Guild: {guild.id})")

# ------------------------------------------------------------
# 録音停止＆切断
# ------------------------------------------------------------
async def stop_recording_cleanup(guild: discord.Guild):
    info = recording_states.pop(guild.id, None)
    if not info:
        return

    vc: discord.VoiceClient = info["voice_client"]
    if vc and vc.recording:
        vc.stop_recording()

    # 念のため強制切断
    if vc and vc.is_connected():
        await vc.disconnect(force=True)
        logger.info(f"Disconnected from voice in guild {guild.id}")

# ------------------------------------------------------------
# 録音完了コールバック
# ------------------------------------------------------------
async def finished_callback(sink: MP3Sink, channel: discord.VoiceChannel, *args):
    logger.info(f"Recording finished for {channel.name}")
    await process_recording(sink, channel)

# ------------------------------------------------------------
# 音声 → 文字起こし → 送信
# ------------------------------------------------------------
async def process_recording(sink: MP3Sink, channel: discord.VoiceChannel):
    # 音声データを結合
    blobs = []
    for audio in sink.audio_data.values():
        audio.file.seek(0)
        blobs.append(audio.file.read())

    if not blobs:
        logger.warning(f"No audio data recorded for {channel.name}")
        return

    combined = b"".join(blobs)
    logger.info(f"Processing {len(combined)} bytes of audio data")

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(combined)
    tmp.close()

    try:
        text = await gemini_client.transcribe_audio(tmp.name)
        summary = await gemini_client.enhance_transcription(text or "")
    finally:
        os.unlink(tmp.name)

    # テキストチャンネルへ送信
    text_id = config_manager.get_channels(channel.guild.id).get("text_channel_id")
    if text_id:
        ch = bot.get_channel(text_id)
        if ch:
            f = io.StringIO(summary)
            await ch.send(file=discord.File(f, filename="transcript.txt"))

# ------------------------------------------------------------
# エラーハンドラ
# ------------------------------------------------------------
@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Error in {event}", exc_info=True)

@bot.event
async def on_application_command_error(ctx, error):
    if not ctx.response.is_done():
        await ctx.respond(f"❌ コマンドエラー: {error}", ephemeral=True)
    logger.error("Application command error", exc_info=True)

# ------------------------------------------------------------
# 起動
# ------------------------------------------------------------
if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)
