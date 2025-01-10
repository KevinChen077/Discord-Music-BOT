import os
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import time
import requests
import asyncio
import concurrent.futures  # 引入 concurrent.futures

OWNER_ID = 576330163558678542

# 設定音樂暫存目錄並確保存在
CACHE_DIR = r"/home/ubuntu/servertempaudio"                                                                 #音樂暫存位置
os.makedirs(CACHE_DIR, exist_ok=True)

intents = discord.Intents.default()
intents.messages = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree  # 使用預設的指令樹

guild_data = {}

youtube_info_cache = {}
# 擴大專用的執行緒池，用於 YouTube 資訊提取
youtube_executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)

def get_guild_data(guild_id):
    if guild_id not in guild_data:
        guild = bot.get_guild(guild_id)
        guild_name = guild.name if guild else "未知伺服器"
        guild_data[guild_id] = {
            "music_queue": [],
            "played_history": [],
            "current_song": None
        }
        now = time.localtime()
        timeformate = time.strftime("%Y-%m-%d %H:%M:%S", now)
        with open("/home/ubuntu/MusicBOTLog/MusicBotLog.txt", "a+", encoding='UTF-8') as f:                 #伺服器加入logC:/Users/kevin/Downloads/MusicBOTLog/
            f.write(f'伺服器名稱: {guild_name}\t伺服器ID: {guild_id}\t{timeformate}\n\n')
    return guild_data[guild_id]

async def get_youtube_info(url, ydl_opts):
    """
    使用專用的執行緒池非同步取得 Youtube 影片資訊，並使用緩存機制避免重複下載
    """
    if url in youtube_info_cache:
        return youtube_info_cache[url]
    try:
        def download_info():
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    info = info['entries'][0]
                return info

        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(youtube_executor, download_info)
        if info:
            youtube_info_cache[url] = info
        return info
    except Exception as e:
        print(f"Error extracting info: {e}")
        return None

class HistorySelect(discord.ui.Select):
    def __init__(self, guild_id):
        gd = get_guild_data(guild_id)
        options = []
        self.mapping = {}
        recent_history = gd["played_history"][-25:]
        for idx, song in enumerate(recent_history):
            title = song[1].get('title', '無標題')
            value = str(idx)
            options.append(discord.SelectOption(label=title, value=value))
            self.mapping[value] = song
        super().__init__(placeholder="選擇要重播的歌曲", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        song = self.mapping.get(value)
        if not song:
            await interaction.response.send_message("無法找到選擇的歌曲。", ephemeral=True)
            return
        guild_id = self.view.guild_id
        gd = get_guild_data(guild_id)
        gd["music_queue"].insert(0, (interaction, song[0], song[1]))
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        await interaction.response.send_message(f"已將 **{song[1].get('title', '無標題')}** 加入佇列頂端，即將重播。", ephemeral=True)

class HistorySelectView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        select = HistorySelect(guild_id)
        if select.options:
            self.add_item(select)

class MusicControlView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="上一首", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        gd = get_guild_data(self.guild_id)
        if not gd["played_history"]:
            await interaction.response.send_message("沒有上一首歌曲。", ephemeral=True)
            return
        prev_song = gd["played_history"].pop()
        gd["music_queue"].insert(0, (interaction, prev_song[0], prev_song[1]))
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
        await interaction.response.send_message(f"正在切換至上一首：**{prev_song[1].get('title','無標題')}**", ephemeral=True)

    @discord.ui.button(label="播放/暫停", style=discord.ButtonStyle.primary)
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("機器人未連接語音頻道。", ephemeral=True)
            return
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("已暫停播放。", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("已繼續播放。", ephemeral=True)
        else:
            await interaction.response.send_message("目前沒有正在播放的音樂。", ephemeral=True)

    @discord.ui.button(label="下一首", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("已跳至下一首。", ephemeral=True)
        else:
            await interaction.response.send_message("目前沒有正在播放的音樂。", ephemeral=True)

    @discord.ui.button(label="佇列", style=discord.ButtonStyle.secondary)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        gd = get_guild_data(self.guild_id)
        music_queue = gd["music_queue"]
        if not music_queue:
            await interaction.response.send_message("目前佇列沒有音樂。", ephemeral=True)
            return
        queue_list = "\n".join([f"{i + 1}. {song[2].get('title', '無標題')}" for i, song in enumerate(music_queue)])
        await interaction.response.send_message(f"目前佇列中的音樂：\n{queue_list}", ephemeral=True)

    @discord.ui.button(label="播放歷史", style=discord.ButtonStyle.secondary)
    async def history(self, interaction: discord.Interaction, button: discord.ui.Button):
        gd = get_guild_data(self.guild_id)
        played_history = gd["played_history"][-25:]
        if not played_history:
            await interaction.response.send_message("目前沒有播放歷史。", ephemeral=True)
        else:
            history_text = "\n".join([f"{idx + 1}. {song[1].get('title', '無標題')}" for idx, song in enumerate(played_history)])
            view = HistorySelectView(self.guild_id)
            await interaction.response.send_message(
                f"最近播放過的歌曲：\n{history_text}\n\n請選擇要重播的歌曲：",
                view=view,
                ephemeral=True
            )

@bot.event
async def on_ready():
    print(f'機器人已登入：{bot.user}')
    try:
        synced = await tree.sync()
        print(f"已同步 {len(synced)} 個指令")
    except Exception as e:
        print(f"指令同步失敗：{e}")

@tree.command(name="play", description="播放指定的音樂")
@app_commands.describe(url="YouTube 網址")
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    if interaction.user.voice is None:
        await interaction.followup.send("你必須先進入語音頻道才能播放音樂！", ephemeral=True)
        return

    voice_channel = interaction.user.voice.channel

    if interaction.guild.voice_client is None:
        await voice_channel.connect()
        print(f'已連接 {voice_channel}')
    elif interaction.guild.voice_client.channel != voice_channel:
        await interaction.guild.voice_client.move_to(voice_channel)
        print(f'移動至 {voice_channel}')

    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'ignoreerrors': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        # 這裡暫不設定 outtmpl，以供資訊提取
    }

    try:
        info = await get_youtube_info(url, ydl_opts)  # 使用非同步取得影片資訊
        if not info:
            await interaction.followup.send("無法取得音樂資訊，請確認連結是否正確。")
            return

        # 設定下載後的檔案路徑，以影片 ID 命名 mp3 檔案
        file_path = os.path.join(CACHE_DIR, f"{info['id']}.mp3")

        # 如果檔案不存在則下載並儲存至本機
        if not os.path.isfile(file_path):
            # 更新下載選項，設定輸出路徑模板
            ydl_opts['outtmpl'] = os.path.join(CACHE_DIR, '%(id)s.%(ext)s')
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        gd = get_guild_data(interaction.guild.id)
        music_queue = gd["music_queue"]
        # 將本機檔案路徑與資訊加入播放佇列
        music_queue.append((interaction, file_path, info))

        if not interaction.guild.voice_client.is_playing():
            await play_next(interaction)

        await interaction.followup.send(f"已加入佇列：**{info.get('title', '無標題')}**")
    except Exception as e:
        print(f"[ERROR] 無法播放音樂：{e}")
        await interaction.followup.send("播放音樂時發生錯誤，請稍後再試或更換連結。")

async def play_next(interaction: discord.Interaction):
    gd = get_guild_data(interaction.guild.id)
    music_queue = gd["music_queue"]

    if len(music_queue) > 0:
        next_song = music_queue.pop(0)
        audio_source_path = next_song[1]  # 使用本機檔案路徑
        info = next_song[2]

        # 移除 before_options，只保留適用於本地檔案的選項
        ffmpeg_options = {
            'options': '-vn -threads 0'
        }

        # 使用本地檔案建立 FFmpegPCMAudio 物件
        source = await asyncio.to_thread(discord.FFmpegPCMAudio, audio_source_path, **ffmpeg_options)
        gd["current_song"] = (audio_source_path, info)

        def after_playing(err):
            if err:
                print(f"[ERROR] 播放錯誤：{err}")
            else:
                if gd["current_song"]:
                    gd["played_history"].append(gd["current_song"])
                    now = time.localtime()
                    timeformate = time.strftime("%Y-%m-%d %H:%M:%S", now)
                    guild = interaction.guild
                    guild_name = guild.name if guild else "未知伺服器"
                    server_log_path = f"/home/ubuntu/MusicBOTLog/Server_{guild.id}_PlayLog.txt"             #加入伺服器紀錄
                    with open(server_log_path, "a+", encoding='UTF-8') as f:
                        f.write(f"[{timeformate}] 播放結束 - {info.get('title', '無標題')} "
                                f"({info.get('webpage_url','')}) 在伺服器：{guild_name}\n")
                bot.loop.create_task(play_next(interaction))

        interaction.guild.voice_client.play(source, after=after_playing)

        embed = discord.Embed(title=info.get('title', '無標題'),
                              url=info.get('webpage_url'),
                              description="播放控制面板")
        thumbnail_url = info.get('thumbnail')
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        view = MusicControlView(interaction.guild.id)
        await interaction.followup.send(embed=embed, view=view)
    else:
        gd["current_song"] = None
        await interaction.followup.send("佇列已經沒有音樂了。")

@tree.command(name="skip", description="跳過當前音樂")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client is not None and interaction.guild.voice_client.is_playing():
        gd = get_guild_data(interaction.guild.id)
        if gd["current_song"]:
            gd["played_history"].append(gd["current_song"])
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("已跳過當前音樂，播放下一首。")
    else:
        await interaction.response.send_message("目前沒有正在播放的音樂。")

@tree.command(name="move", description="將機器人移動到你所在的語音頻道")
async def move(interaction: discord.Interaction):
    if interaction.user.voice is None:
        await interaction.response.send_message("你必須先進入語音頻道！", ephemeral=True)
        return
    voice_channel = interaction.user.voice.channel
    if interaction.guild.voice_client and interaction.guild.voice_client.channel != voice_channel:
        await interaction.guild.voice_client.move_to(voice_channel)
        print(f'移動至 {voice_channel}')
        await interaction.response.send_message(f"已移動至 {voice_channel}")
    else:
        await interaction.response.send_message("機器人已在你的語音頻道或尚未連線。")

@tree.command(name="stop", description="停止播放並離開語音頻道")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc is not None:
        if vc.is_playing():
            vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("機器人已斷開語音頻道。")
    else:
        await interaction.response.send_message("機器人目前沒有連接到任何語音頻道。")

@tree.command(name="queue", description="查看佇列中的音樂")
async def queue(interaction: discord.Interaction):
    gd = get_guild_data(interaction.guild.id)
    music_queue = gd["music_queue"]
    if not music_queue:
        await interaction.response.send_message("目前佇列沒有音樂。")
    else:
        queue_list = "\n".join([f"{i + 1}. {song[2].get('title', '無標題')}" for i, song in enumerate(music_queue)])
        await interaction.response.send_message(f"目前佇列中的音樂：\n{queue_list}")

@tree.command(name="next", description="查看下一首歌曲名稱")
async def next_song(interaction: discord.Interaction):
    gd = get_guild_data(interaction.guild.id)
    music_queue = gd["music_queue"]
    if music_queue:
        next_song = music_queue[0]
        await interaction.response.send_message(f"下一首歌曲：**{next_song[2].get('title', '無標題')}**")
    else:
        await interaction.response.send_message("目前沒有下一首歌曲。")

@tree.command(name="reset", description="清除佇列中的所有音樂")
async def reset(interaction: discord.Interaction):
    gd = get_guild_data(interaction.guild.id)
    gd["music_queue"].clear()
    await interaction.response.send_message("佇列已清除。")

@tree.command(name="history", description="查看播放歷史")
async def history(interaction: discord.Interaction):
    gd = get_guild_data(interaction.guild.id)
    played_history = gd["played_history"]
    if not played_history:
        await interaction.response.send_message("目前沒有播放歷史。")
    else:
        history_list = "\n".join([f"{i + 1}. {song[1].get('title', '無標題')}" for i, song in enumerate(played_history)])
        await interaction.response.send_message(f"音樂播放歷史：\n{history_list}")

@tree.command(name="now", description="查看目前正在播放的音樂")
async def now(interaction: discord.Interaction):
    gd = get_guild_data(interaction.guild.id)
    current_song = gd["current_song"]
    if current_song:
        await interaction.response.send_message(f"目前正在播放：**{current_song[1].get('title', '無標題')}**")
    else:
        await interaction.response.send_message("目前沒有正在播放的音樂。")

@tree.command(name="servers", description="Only Developer can use it")
async def servers(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("你沒有權限執行此指令。", ephemeral=True)
        return
    if interaction.guild is not None:
        await interaction.response.send_message("這個指令只能在私人訊息中使用。", ephemeral=True)
        return

    guilds = bot.guilds
    guild_count = len(guilds)
    guild_names = "\n".join(guild.name for guild in guilds)
    response = f"目前在 {guild_count} 個伺服器中使用，名稱：\n{guild_names}"
    await interaction.response.send_message(response)

@tree.command(name="broadcast", description="Only Developer can use it")
@app_commands.describe(message="Only Developer can use it")
async def broadcast(interaction: discord.Interaction, message: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("你沒有權限執行此指令。", ephemeral=True)
        return
    if interaction.guild is not None:
        await interaction.response.send_message("此指令只能在私人訊息中使用。", ephemeral=True)
        return

    count = 0
    for guild in bot.guilds:
        channel = discord.utils.find(
            lambda c: c.name.lower() == '音樂機器人指令更新' and c.permissions_for(guild.me).send_messages,
            guild.text_channels
        )
        if channel:
            try:
                await channel.send(message)
                count += 1
            except Exception as e:
                print(f"發送至 {guild.name} 失敗：{e}")
                continue
    await interaction.response.send_message(f"消息已成功發送至 {count} 個伺服器的 音樂機器人指令更新 頻道。")

@tree.command(name="invite", description="傳送邀請連結至你的私人訊息")
async def invite(interaction: discord.Interaction):
    try:
        invitelink = "https://reurl.cc/mRp0W9"
        await interaction.user.send(f"這是機器人的邀請連結：{invitelink}")
        await interaction.response.send_message("邀請連結已傳送至您的私人訊息！", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message("無法發送私人訊息，請檢查您的隱私設定。", ephemeral=True)

@tree.command(name="coffee", description="贊助我!")
async def coffee(interaction: discord.Interaction):
    message = "My brain and server ISN'T FREE so please buy me a coffee!\nLINK:https://paypal.me/Shark077?country.x=TW&locale.x=en_US"
    await interaction.response.send_message(message)
    print("已傳送COFFEE")

@tree.command(name="dog", description="新年快樂")
async def dog(interaction: discord.Interaction):
    message = "你在狗叫什麼"
    await interaction.response.send_message(message)
    print("Dog Bark!")

@tree.command(name="sex", description="我愛你")
async def sex(interaction: discord.Interaction):
    message = f"{interaction.user.display_name}在發情"
    await interaction.response.send_message(message)
    print("Smol Dog Horny")

@tree.command(name="support", description="中文版 Help")
async def support(interaction: discord.Interaction):
    message = """```
中文版請輸入 /supporten
/play <YT網址>   播放音樂
/control        開啟音樂控制介面
/stop           暫停並離開
/skip           跳過當前音樂
/queue          查看佇列中的音樂
/reset          清空所有佇列音樂
/now            查看當前正在播放的音樂
/next           查看下一首歌的名稱
/history        查看播放歷史
/move           將機器人移動到發送訊息者的位置
/invite         傳送邀請連結（私訊）
/ping           顯示機器人與Discord伺服器之間的延遲
/coffee         贊助我（PayPal）
```"""
    await interaction.response.send_message(message)
    print("中文版Help")

@tree.command(name="supporten", description="英文版 Help")
async def supporten(interaction: discord.Interaction):
    message = """```
中文版請輸入 /support
/play <URL>     Play music
/control        Music contro panel
/stop           Pause and leave
/skip           Skip the current song
/queue          View songs in queue
/reset          Clear all queued songs
/now            Show currently playing song
/next           Show the name of the next song
/history        View playback history
/move           Move the bot to the sender's voice channel
/invite         Send an invite link (private message)
/ping           Show latency bewteen BOT and Discord Server
/coffee         Buy Me A Coffee (PayPal)
```"""
    await interaction.response.send_message(message)
    print("英文版Help")

@tree.command(name="ping", description="顯示機器人與Discord伺服器之間的延遲")
async def ping(interaction: discord.Interaction):
    api = requests.get("https://discord.com/api/v10/gateway").elapsed.total_seconds()
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"機器人與伺服器延遲: {latency}ms\nDiscord API回應時間: {round(api*1000,3)}ms")

@tree.command(name="control", description="顯示音樂控制面板")
async def control(interaction: discord.Interaction):
    gd = get_guild_data(interaction.guild.id)
    current_song = gd["current_song"]
    if not current_song:
        await interaction.response.send_message("目前沒有正在播放的音樂。", ephemeral=True)
        return

    info = current_song[1]
    embed = discord.Embed(title=info.get('title', '無標題'),
                          url=info.get('webpage_url'),
                          description="播放控制面板")
    thumbnail_url = info.get('thumbnail')
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    view = MusicControlView(interaction.guild.id)
    await interaction.response.send_message(embed=embed, view=view)

bot.run("MTMyNjg1OTM2OTI1Nzc2MjgyNg.GKCJNx.1INW0uOD8082j0YWuGSQ8iieARTRmudI0T0FPs")
