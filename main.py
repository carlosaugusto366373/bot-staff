import os
import logging
import time
import re
import asyncio
import discord
from discord.ext import commands
from aiohttp import web

import config
from db import init_db, order_already_processed, mark_order_processed
from modules.payment_parser import PaymentParser, parse_payment_message
from modules.card_generator import generate_receipt_image
from modules.cart_recovery import CartRecovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
parser = PaymentParser(bot, config.LOG_ORDERS_CHANNEL_ID, config.DELIVERED_CHANNEL_ID)
recovery = CartRecovery(bot)


@bot.event
async def on_ready():
    log.info("Logado como %s (id=%s)", bot.user, bot.user.id)
    await init_db()
    await recovery.start()
    log.info("Módulos iniciados.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.id == bot.user.id:
        return
    await parser.handle_message(message)
    await recovery.handle_cart_message(message)
    await bot.process_commands(message)


# --- COMANDOS ---
@bot.command(name="carrinho", aliases=["nudge", "lembrar"])
@commands.has_permissions(manage_guild=True)
async def registrar_carrinho(ctx, member: discord.Member, total: str, url: str, *, itens: str = "seu pedido"):
    order_id = f"manual-{ctx.message.id}"
    ok = await recovery.send_now(member, total, itens, url, attempt=0)
    if ok:
        await recovery.register_cart(member, order_id, total, itens, url)
        await ctx.reply(f"✅ DM enviada pra {member.mention}.")
    else:
        await ctx.reply(f"⚠️ Não consegui mandar DM pra {member.mention}.")


@bot.command(name="reprocessar")
@commands.has_permissions(manage_guild=True)
async def reprocessar_logs(ctx, limite: int = 100):
    source = bot.get_channel(config.LOG_ORDERS_CHANNEL_ID)
    target = bot.get_channel(config.DELIVERED_CHANNEL_ID)
    
    if not source or not target:
        await ctx.reply("❌ Canais não encontrados. Confere os IDs.")
        return

    msg = await ctx.reply(f"⏳ Lendo as últimas {limite} mensagens...")
    count_ok = 0
    count_skip = 0
    count_fail = 0

    async for m in source.history(limit=limite):
        data = parse_payment_message(m.content, m.embeds, m.components)
        if not data:
            continue
        if await order_already_processed(data["order_id"]):
            count_skip += 1
            continue

        try:
            client_id = None
            match_cid = re.search(r"<@!?(\d+)>", data["client"])
            if match_cid:
                client_id = int(match_cid.group(1))
            
            user = bot.get_user(client_id) if client_id else None
            avatar_url = user.display_avatar.url if user else None
            client_name = user.name if user else data["client"].replace("<@", "").replace(">", "")

            img_buffer = await generate_receipt_image(
                client_name=client_name,
                client_avatar_url=avatar_url,
                date=data["date"],
                total=data["total"],
                product_name=data["item"].upper(),
                product_img_url=None
            )

            await target.send(file=discord.File(fp=img_buffer, filename="recibo.png"))
            await mark_order_processed(data["order_id"], int(time.time()))
            count_ok += 1
        except Exception as e:
            log.error("Erro: %s", e)
            count_fail += 1

    await msg.edit(content=f"✅ Varredura concluída.\n\n**Enviados:** {count_ok}\n**Já processados:** {count_skip}\n**Falhas:** {count_fail}")


@bot.command(name="status")
@commands.has_permissions(manage_guild=True)
async def status(ctx):
    await ctx.reply("bot ativo.")


# --- SERVIDOR WEB FAKE PARA O RENDER ---
async def handle_ping(request):
    return web.Response(text="Bot QZZ STAFF Online e rodando!")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Servidor web escutando na porta {port}")

# --- MAIN ---
async def main():
    await start_webserver() # Sobe o servidor web pro Render
    await bot.start(config.TOKEN) # Sobe o bot

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass