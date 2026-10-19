import re
import time
import logging
import discord
from discord.ext import tasks

from config import (
    RECOVERY_CHECK_INTERVAL_MIN,
    RECOVERY_MAX_ATTEMPTS,
    CART_EVENTS_CHANNEL_ID,
)
from db import add_pending_cart, get_carts_to_nudge, register_nudge, order_already_processed, mark_order_processed

log = logging.getLogger("cart_recovery")


def build_cart_nudge_embed(total, items, url, attempt):
    openers = [
        "👋 Oi! Passando pra lembrar que teu carrinho tá aqui esperando.",
        "😊 Ei, não esqueci de você! Teu carrinho ainda tá reservado.",
        "⏳ Última passadinha: teu carrinho tá te esperando.",
    ]
    
    embed = discord.Embed(
        title="🛒 Carrinho Abandonado",
        description=openers[min(attempt, len(openers)-1)],
        color=0x2b2d31
    )
    
    embed.add_field(name="📦 Itens", value=f"`{items}`", inline=True)
    embed.add_field(name="💸 Total", value=f"`{total}`", inline=True)
    
    embed.add_field(name="⚡ Entrega", value="Automática — recebe na hora.", inline=True)
    embed.add_field(name="🛟 Staff", value="Online 24h pra te ajudar.", inline=True)
    
    embed.add_field(name="\u200b", value=f"**[🔗 Finalizar meu pedido agora]({url})**", inline=False)
    
    embed.set_footer(text="Se já finalizou, ignora essa mensagem. Se o ticket fechou, abra outro no #atendimento.")
    
    return embed


def deep_extract(node, found):
    if not node:
        return

    raw = getattr(node, "to_dict", lambda: {})() or {}

    content = raw.get("content") or getattr(node, "content", None)
    if isinstance(content, str):
        if ("total" in content.lower() or "subtotal" in content.lower()) and not found.get("total"):
            m = re.search(r"R\$\s*[\d.,]+", content)
            if m:
                found["total"] = m.group(0)
        if not found.get("item"):
            m_item = re.search(r"\*\*([^*]+)\*\*", content)
            if m_item and "carrinho" not in m_item.group(1).lower():
                found["item"] = m_item.group(1).strip()

    url = raw.get("url") or getattr(node, "url", None)
    if url and not found.get("url"):
        found["url"] = url

    custom_id = raw.get("custom_id") or getattr(node, "custom_id", None)
    if custom_id == "lp_place_order" and not found.get("url_channel"):
        found["url_channel"] = True

    children = getattr(node, "children", None)
    if children:
        for child in children:
            deep_extract(child, found)
    if isinstance(node, list):
        for item in node:
            deep_extract(item, found)


def parse_cart_message(message: discord.Message):
    if not message.mentions:
        return None

    user = message.mentions[0]
    found = {"total": None, "url": None, "item": None, "url_channel": False}

    for comp in message.components:
        deep_extract(comp, found)

    if not found.get("url") and found.get("url_channel"):
        found["url"] = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}"

    if not (found["total"] and found["url"]):
        return {
            "user_id": user.id,
            "total": found["total"] or "R$ —",
            "item": found["item"] or "seu pedido",
            "url": found["url"] or "—",
            "_incomplete": True,
        }

    return {
        "user_id": user.id,
        "total": found["total"],
        "item": found["item"] or "seu pedido",
        "url": found["url"],
    }


class CartRecovery:
    def __init__(self, bot):
        self.bot = bot

    async def register_cart(self, user, order_id, total, items, url):
        await add_pending_cart(user.id, order_id, total, items, url, int(time.time()))

    async def send_now(self, user, total, items, url, attempt=0):
        try:
            embed = build_cart_nudge_embed(total, items, url, attempt)
            await user.send(embed=embed)
            return True
        except discord.Forbidden:
            log.warning("DM bloqueada user=%s", user.id)
            return False
        except discord.HTTPException as e:
            log.exception("Erro DM user=%s: %s", user.id, e)
            return False

    async def handle_cart_message(self, message):
        if message.channel.category_id != CART_EVENTS_CHANNEL_ID:
            return

        order_id = f"cart-{message.id}"
        if await order_already_processed(order_id):
            return

        data = parse_cart_message(message)
        if not data:
            return

        if data.get("_incomplete"):
            log.warning("Carrinho incompleto: user=%s total=%s", data["user_id"], data["total"])
            return

        user = self.bot.get_user(data["user_id"])
        if user is None:
            try:
                user = await self.bot.fetch_user(data["user_id"])
            except discord.NotFound:
                return

        await self.register_cart(user, order_id, data["total"], data["item"], data["url"])
        
        if await self.send_now(user, data["total"], data["item"], data["url"], attempt=0):
            await register_nudge(user.id, int(time.time()))
            await mark_order_processed(order_id, int(time.time()))
            log.info("Carrinho auto-registrado e DM enviada: user=%s", user.id)

    @tasks.loop(minutes=RECOVERY_CHECK_INTERVAL_MIN)
    async def nudge_loop(self):
        now = int(time.time())
        interval = RECOVERY_CHECK_INTERVAL_MIN * 60
        rows = await get_carts_to_nudge(now, interval, RECOVERY_MAX_ATTEMPTS)

        for user_id, order_id, total, items, url, attempts, _, _ in rows:
            user = self.bot.get_user(user_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(user_id)
                except discord.NotFound:
                    continue
            if await self.send_now(user, total, items, url, attempts):
                await register_nudge(user_id, now)

    async def start(self):
        self.nudge_loop.start()

    async def stop(self):
        self.nudge_loop.cancel()