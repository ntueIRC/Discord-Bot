import asyncio
import discord
from discord.ext import commands
import yt_dlp
import os
from dotenv import load_dotenv

# --- 環境變數與路徑設定 ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
FFMPEG_PATH = "ffmpeg.exe"

# --- 初始化檢查 ---
if not DISCORD_TOKEN:
    print("❌ 錯誤：找不到 DISCORD_TOKEN 環境變數。")
    exit()

if not os.path.exists(FFMPEG_PATH):
    print(f"⚠️ 警告：找不到 FFmpeg 於路徑：{FFMPEG_PATH}。播放指令可能失敗。")


intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True  

bot = commands.Bot(command_prefix='!', intents=intents)

# --- YTDL 設定 ---
yt_dlp.utils.BUG_REPORT_URL = None
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}
ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# --- YTDLSource 類別 ---


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()

        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream)
        )
        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)

        ffmpeg_opts = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }
        source = discord.FFmpegPCMAudio(
            filename, executable=FFMPEG_PATH, **ffmpeg_opts)

        return cls(source, data=data)


# --- Bot 事件與指令 ---
@bot.event
async def on_ready():
    print('-------------------------------------------')
    print(f'✅ 機器人已成功登入: {bot.user.name}')
    print('-------------------------------------------')


@bot.command()
async def play(ctx, *, url):

    if not os.path.exists(FFMPEG_PATH):
        await ctx.send(f"❌ **錯誤：** 找不到 FFmpeg 於 `{FFMPEG_PATH}`。無法播放。")
        return

    # 1. 檢查使用者是否在語音頻道
    if not ctx.author.voice:
        await ctx.send("你必須在語音頻道裡才能使用此指令!")
        return

    target_channel = ctx.author.voice.channel
    voice_client = ctx.voice_client

    # 2. 處理語音連線邏輯
    try:
        if voice_client is None:
            # 機器人未連線，連線到目標頻道
            await ctx.send(f"📞 正在連線到頻道: **{target_channel.name}**...")
            voice_client = await target_channel.connect(timeout=60.0)
        elif voice_client.channel != target_channel:
            # 在不同頻道，則移動過去
            await ctx.send(f"📶 正在移動到你的頻道: **{target_channel.name}**...")
            await voice_client.move_to(target_channel)

    except discord.errors.ClientException as e:
        # 如果機器人已經在頻道裡，但不是 target_channel，move_to 可能失敗
        await ctx.send(f"❌ 連線錯誤: {e}")
        return
    except asyncio.TimeoutError:
        await ctx.send("❌ 連線到語音頻道逾時。")
        return
    except Exception as e:
        # 捕捉 403 Forbidden (權限錯誤) 或其他連線錯誤
        await ctx.send(f"❌ 無法連線到語音頻道。請檢查 **連線(Connect)** 權限和 **防火牆** 設置。\n錯誤詳情: `{e}`")
        print(f"❌ 連線到語音頻道時發生錯誤: {e}")
        return

    # 3. 檢查是否正在播放 (如果連線成功)
    if voice_client.is_playing():
        await ctx.send("🔊 目前正在播放中，請等待歌曲結束或使用 `!stop` 停止。")
        return

    # 4. 取得音訊來源並播放
    try:
        await ctx.send(f"🔎 正在搜尋或載入: `{url}`...")

        # 這裡的 stream=True 是關鍵，讓 yt-dlp 串流播放，不需下載整個檔案
        player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)

        voice_client.play(player, after=lambda e: print(
            f'播放器錯誤: {e}') if e else None)

        await ctx.send(f'🎧 **開始播放**: **{player.title}**')

    except yt_dlp.DownloadError as e:
        await ctx.send(f"❌ **載入失敗：** 找不到該影片或 URL 無效。\n錯誤詳情：`{e}`")
        if voice_client:
            await voice_client.disconnect()
    except Exception as e:
        # 捕獲播放期間可能出現的 FFmpeg 或其他錯誤
        await ctx.send(f"❌ **播放時發生錯誤:** 請檢查 FFmpeg 是否正常工作。\n錯誤詳情: `{e}`")
        print(f"❌ 播放錯誤日誌: {e}")
        if voice_client:
            await voice_client.disconnect()

@bot.command(name='stop', aliases=['s'])
async def stop(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏹️ **播放已停止。**")
    elif ctx.voice_client:
        await ctx.send("沒有歌曲正在播放。")
    else:
        await ctx.send("我目前沒有連線到語音頻道。")

@bot.command(name='leave', aliases=['l', 'dc'])
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 **已斷開語音頻道。**")
    else:
        await ctx.send("我目前沒有連線到任何語音頻道。")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
