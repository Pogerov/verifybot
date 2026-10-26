import discord
from discord.ext import commands
from datetime import datetime, timezone
from aiohttp import web
import os
import asyncio

# ==================== НАСТРОЙКИ ====================
TOKEN = os.environ.get("TOKEN", "YOUR_BOT_TOKEN")

# ID твоего сервера (ОБЯЗАТЕЛЬНО!)
GUILD_ID = int(os.environ.get("GUILD_ID", "0"))

VERIFY_CHANNEL_ID = int(os.environ.get("VERIFY_CHANNEL_ID", "0"))
VERIFY_ROLE_ID    = int(os.environ.get("VERIFY_ROLE_ID", "0"))
LOG_CHANNEL_ID    = int(os.environ.get("LOG_CHANNEL_ID", "0"))

VERIFY_EMOJI = "✅"
VERIFY_TEXT = (
    "**Для прохода на сервер, пожалуйста пройдите верификацию.**\n"
    "Нажмите на смайлик снизу!"
)

REMOVE_ROLE_ON_UNREACT = False
# ===================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
verify_message_id: int | None = None


async def send_verify_message(channel):
    embed = discord.Embed(description=VERIFY_TEXT, color=discord.Color.green())
    embed.set_footer(text="Нажмите ✅, чтобы получить доступ")
    msg = await channel.send(embed=embed)
    await msg.add_reaction(VERIFY_EMOJI)
    return msg


async def setup_channel_permissions(guild):
    channel = guild.get_channel(VERIFY_CHANNEL_ID)
    role = guild.get_role(VERIFY_ROLE_ID)
    if channel is None or role is None:
        print(f"[{guild.name}] ОШИБКА: Канал или роль не найдены! Проверь ID.")
        return
    try:
        # @everyone видит канал, но не может писать
        await channel.set_permissions(
            guild.default_role, view_channel=True, send_messages=False, add_reactions=False
        )
        # Верифицированные не видят канал
        await channel.set_permissions(role, view_channel=False)
        print(f"[{guild.name}] Права канала настроены")
    except discord.Forbidden:
        print(f"[{guild.name}] Нет прав Manage Channels")


async def setup_verify_message(guild):
    global verify_message_id
    await setup_channel_permissions(guild)
    
    channel = guild.get_channel(VERIFY_CHANNEL_ID)
    if channel is None:
        print(f"[{guild.name}] ОШИБКА: Канал верификации не найден (проверь VERIFY_CHANNEL_ID)")
        return

    # Ищем старое сообщение
    try:
        async for msg in channel.history(limit=50):
            if msg.author.id == bot.user.id and msg.embeds:
                for r in msg.reactions:
                    if str(r.emoji) == VERIFY_EMOJI:
                        verify_message_id = msg.id
                        print(f"[{guild.name}] Найдено старое сообщение: {msg.id}")
                        try:
                            await msg.add_reaction(VERIFY_EMOJI)
                        except discord.HTTPException:
                            pass
                        return
    except discord.Forbidden:
        print(f"[{guild.name}] Нет прав читать историю канала")

    # Если не нашли — создаём новое
    try:
        msg = await send_verify_message(channel)
        verify_message_id = msg.id
        print(f"[{guild.name}] СОЗДАНО НОВОЕ СООБЩЕНИЕ: {msg.id}")
    except discord.Forbidden:
        print(f"[{guild.name}] ОШИБКА: Нет прав писать в канал верификации!")


async def grant_role(member, role):
    try:
        await member.add_roles(role, reason="Верификация ✅")
        print(f"[{member.guild.name}] Роль выдана: {member}")
    except discord.Forbidden:
        print(f"ОШИБКА: Нет прав выдать роль {role.name} (подними роль бота выше!)")


async def remove_role(member, role):
    try:
        await member.remove_roles(role, reason="Снята реакция")
    except (discord.Forbidden, discord.HTTPException):
        pass


async def send_log(guild, member, action):
    if LOG_CHANNEL_ID == 0:
        return
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        return
    passed = action == "grant"
    embed = discord.Embed(
        title="✅ Верификация пройдена" if passed else "❌ Верификация отменена",
        color=discord.Color.green() if passed else discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
    embed.add_field(name="Пользователь", value=f"{member.mention} (`{member.id}`)", inline=False)
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass


@bot.event
async def on_ready():
    print("=" * 40)
    print(f"Бот запущен как {bot.user}")
    print(f"Серверов: {len(bot.guilds)}")
    
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        print(f"ОШИБКА: Бот не нашел сервер с ID {GUILD_ID}!")
        print("Проверь GUILD_ID в Render Environment Variables")
        return
        
    print(f"Работаю на сервере: {guild.name} (ID: {guild.id})")
    await setup_verify_message(guild)
    print("=" * 40)


@bot.event
async def on_raw_reaction_add(payload):
    global verify_message_id
    if payload.guild_id != GUILD_ID:
        return  # Игнорируем другие сервера
    if verify_message_id is not None and payload.message_id != verify_message_id:
        return
    if str(payload.emoji) != VERIFY_EMOJI:
        return
    if payload.user_id == bot.user.id:
        return
    
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return
    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return
        
    role = guild.get_role(VERIFY_ROLE_ID)
    if role is None:
        return
        
    if role in member.roles:
        try:
            channel = guild.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(VERIFY_EMOJI, member)
        except (discord.NotFound, discord.Forbidden):
            pass
        return
        
    await grant_role(member, role)
    await send_log(guild, member, "grant")


@bot.event
async def on_raw_reaction_remove(payload):
    if not REMOVE_ROLE_ON_UNREACT:
        return
    if payload.guild_id != GUILD_ID:
        return
    if verify_message_id is not None and payload.message_id != verify_message_id:
        return
    if str(payload.emoji) != VERIFY_EMOJI:
        return
        
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return
    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return
        
    role = guild.get_role(VERIFY_ROLE_ID)
    if role and role in member.roles:
        await remove_role(member, role)
        await send_log(guild, member, "remove")


@bot.command()
@commands.has_permissions(administrator=True)
async def repost(ctx):
    global verify_message_id
    if ctx.guild.id != GUILD_ID:
        return
    channel = ctx.guild.get_channel(VERIFY_CHANNEL_ID)
    if channel is None:
        return
    msg = await send_verify_message(channel)
    verify_message_id = msg.id
    await ctx.send(f"✅ Пересоздано: {msg.jump_url}", delete_after=10)


# ---------- ВЕБ-СЕРВЕР ДЛЯ UPTIMEROBOT ----------
async def health(request):
    return web.Response(text="OK", status=200)


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")


async def main():
    await start_web_server()
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
