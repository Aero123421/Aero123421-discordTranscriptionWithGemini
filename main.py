# main.py ― 修正版
#   ・finished_callback を非同期化
#   ・AudioData を .file で取得（Pycord 方式）
#   ・無音ストリームで接続維持 & force=True で確実に切断
#   ・重複接続／録音同時実行をブロック
#   ・GeminiClient（client.files.upload 対応版）と連携

import asyncio
import io
import logging
import os
import tempfile
from typing import Dict

import discord
from discord.ext import commands
from discord.utils import MISSING

from config import BotConfig
from config_manager import ConfigManager
from gemini_client import GeminiClient

# ─────────────────────────────────────────
# ログ設定
# ─────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 設定読み込み
# ─────────────────────────────────────────
cfg = BotConfig()

# ─────────────────────────────────────────
# Discord Bot 初期化
# ─────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────
# Gemini クライアント
# ─────────────────────────────────────────
gemini = GeminiClient(
    api_key=cfg.GEMINI_API_KEY,
    model_name=cfg.GEMINI_MODEL_NAME,
    concurrency=cfg.GEMINI_API_CONCURRENCY,
)

# ─────────────────────────────────────────
# 設定マネージャ & 録音状態
# ─────────────────────────────────────────
manager = ConfigManager()
recording_states: Dict[int, Dict] = {}


# ─────────────────────────────────────────
# 録音系ユーティリティ
# ─────────────────────────────────────────
class MP3Sink(discord.sinks.MP3Sink):
    """Pycord 標準 MP3Sink をそのまま利用"""
    pass


class Silence(discord.AudioSource):
    """接続維持用の無音 20 ms フレーム (48 kHz / 2 ch / 16 bit = 3840 B)"""
    def read(self) -> bytes:
        return b"\x00" * 3840


# ─────────────────────────────────────────
# Bot イベント
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("------")
    logger.info("Starting Gemini API connection test…")
    if await gemini.test_connection():
        logger.info("✅ Gemini API connection test passed")
    else:
        logger.warning("⚠️ Gemini API connection test failed – continuing anyway")
    logger.info("🤖 Discord Transcription Bot is ready!")


# ─────────────────────────────────────────
# スラッシュコマンド
# ─────────────────────────────────────────
@bot.slash_command(name="set_voice_category", description="録音対象カテゴリを設定")
async def set_voice_category(
    ctx: discord.ApplicationContext, category: discord.CategoryChannel
):
    manager.set_voice_category(ctx.guild.id, category.id)
    await ctx.respond(
        f"✅ 録音対象カテゴリを **{category.name}** に設定しました。", ephemeral=True
    )


@bot.slash_command(name="set_text_channel", description="結果送信チャンネルを設定")
async def set_text_channel(ctx: discord.ApplicationContext, channel: discord.TextChannel):
    manager.set_text_channel(ctx.guild.id, channel.id)
    await ctx.respond(f"✅ 結果送信チャンネルを {channel.mention} に設定しました。", ephemeral=True)


@bot.slash_command(name="show_channels", description="現在の設定を表示")
async def show_channels(ctx: discord.ApplicationContext):
    s = manager.get_channels(ctx.guild.id)
    embed = discord.Embed(title="📋 現在の設定", color=0x00FF00)
    embed.add_field(
        name="🎤 録音対象カテゴリ",
        value=f"<#{s.get('voice_category_id')}>" if s.get("voice_category_id") else "未設定",
        inline=False,
    )
    embed.add_field(
        name="📝 結果送信チャンネル",
        value=f"<#{s.get('text_channel_id')}>" if s.get("text_channel_id") else "未設定",
        inline=False,
    )
    await ctx.respond(embed=embed, ephemeral=True)


@bot.slash_command(name="unset_channels", description="設定を解除")
async def unset_channels(ctx: discord.ApplicationContext):
    manager.unset_channels(ctx.guild.id)
    await ctx.respond("✅ すべての設定を解除しました。", ephemeral=True)


@bot.slash_command(name="stop", description="録音を手動停止（管理者）")
@discord.default_permissions(administrator=True)
async def stop_cmd(ctx: discord.ApplicationContext):
    info = recording_states.get(ctx.guild.id)
    if not info:
        await ctx.respond("❌ 現在録音中ではありません。", ephemeral=True)
        return
    vc: discord.VoiceClient = info["voice_client"]
    if vc and vc.recording:
        vc.stop_recording()
        await ctx.respond("✅ 録音を停止しました。", ephemeral=True)
    else:
        await ctx.respond("❌ 録音中ではありません。", ephemeral=True)


@bot.slash_command(name="test", description="Bot が応答するかテスト")
async def test_command(ctx: discord.ApplicationContext):
    await ctx.respond("✅ Bot is working correctly!", ephemeral=True)


# ─────────────────────────────────────────
# 安全切断ユーティリティ
# ─────────────────────────────────────────
async def safe_disconnect(vc: discord.VoiceClient):
    """_MissingSentinel で壊れた VC を安全に破棄"""
    try:
        if getattr(vc, "ws", None) in (None, MISSING):
            # 内部ソケットが壊れている → 直接 close して握手を打ち切る
            vc.cleanup()
        elif vc.is_connected():
            await vc.disconnect(force=True)
    except Exception as e:
        logger.error(f"Force-disconnect failed: {e}")


# ─────────────────────────────────────────
# VoiceState 監視
# ─────────────────────────────────────────
@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    try:
        if member.bot:
            return

        guild_id = member.guild.id
        cat_id = manager.get_channels(guild_id).get("voice_category_id")
        if not cat_id:
            return

        def in_target(ch):
            return ch and ch.category_id == cat_id

        # ── 参加：録音開始 ────────────────────────────
        if not before.channel and after.channel and in_target(after.channel):
            if guild_id not in recording_states and not member.guild.voice_client:
                await start_recording(member.guild, after.channel)

        # ── 退出：カテゴリが空なら録音停止 ────────────────
        elif before.channel and in_target(before.channel):
            cat = bot.get_channel(cat_id)
            if cat and all(
                len([m for m in vc.members if not m.bot]) == 0 for vc in cat.voice_channels
            ):
                await stop_recording_cleanup(member.guild)
    except Exception as e:
        logger.error("Error in on_voice_state_update", exc_info=e)


# ─────────────────────────────────────────
# 録音開始
# ─────────────────────────────────────────
async def start_recording(guild: discord.Guild, channel: discord.VoiceChannel):
    if guild.id in recording_states:
        return
    if guild.voice_client:  # 既存 VC がある
        await safe_disconnect(guild.voice_client)
        if guild.voice_client.is_connected():  # まだ繋がっていれば戻る
            logger.warning("VoiceClient still alive; aborting new connect")
            return

    logger.info(f"Attempting to connect to voice channel: {channel.name}")
    # 発言権限がないチャンネルでも切断されないよう自分をミュートして接続
    vc = await channel.connect(self_mute=True)

    # ハンドシェイク直後に録音を開始すると稀に復号エラーが発生するため少し待つ
    await asyncio.sleep(0.2)

    sink = MP3Sink()
    vc.start_recording(sink, finished_callback, channel)

    recording_states[guild.id] = {
        "voice_client": vc,
        "sink": sink,
    }
    logger.info(f"Recording started in {channel.name} (Guild: {guild.id})")


# ─────────────────────────────────────────
# 録音停止 & 切断
# ─────────────────────────────────────────
async def stop_recording_cleanup(guild: discord.Guild):
    info = recording_states.pop(guild.id, None)
    if not info:
        return

    vc: discord.VoiceClient = info["voice_client"]
    if vc and vc.is_playing():
        vc.stop()
    if vc and vc.recording:
        vc.stop_recording()
    if vc and vc.is_connected():
        await vc.disconnect(force=True)
        logger.info(f"Disconnected from voice in guild {guild.id}")


# ─────────────────────────────────────────
# 録音完了コールバック（非同期）
# ─────────────────────────────────────────
async def finished_callback(sink: MP3Sink, channel: discord.VoiceChannel, *_):
    logger.info(f"Recording finished for {channel.name}")
    await process_recording(sink, channel)


# ─────────────────────────────────────────
# 録音後処理 → Gemini → Discord
# ─────────────────────────────────────────
async def process_recording(sink: MP3Sink, channel: discord.VoiceChannel):
    # 1) 音声データを結合
    chunks = []
    for audio in sink.audio_data.values():
        try:
            audio.file.seek(0)
            chunks.append(audio.file.read())
        except Exception as e:
            logger.error(f"Read error: {e}")
    if not chunks:
        logger.warning("No audio captured.")
        return

    combined = b"".join(chunks)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(combined)
    tmp.close()

    try:
        # 2) Gemini で文字起こし + 整形
        raw = await gemini.transcribe_audio(tmp.name)
        summary = await gemini.enhance_transcription(raw or "")

        # 3) 指定テキストチャンネルへ送信
        ch_id = manager.get_channels(channel.guild.id).get("text_channel_id")
        if ch_id and (dest := bot.get_channel(ch_id)):
            fp = io.StringIO(summary)
            await dest.send(
                f"🎤 **{channel.name}** での録音結果：", file=discord.File(fp, "transcript.txt")
            )
    except Exception as e:
        logger.error("Error in process_recording", exc_info=e)
    finally:
        os.unlink(tmp.name)


# ─────────────────────────────────────────
# エラーハンドラ
# ─────────────────────────────────────────
@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Error in event {event}", exc_info=True)


@bot.event
async def on_application_command_error(ctx, error):
    if not ctx.response.is_done():
        await ctx.respond(f"❌ コマンドエラー: {error}", ephemeral=True)
    logger.error("Application command error", exc_info=True)


# ─────────────────────────────────────────
# エントリポイント
# ─────────────────────────────────────────
if __name__ == "__main__":
    bot.run(cfg.DISCORD_TOKEN)

