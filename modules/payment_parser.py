import re
import time
import logging
import discord
from db import order_already_processed, mark_order_processed
from modules.card_generator import generate_receipt_image

log = logging.getLogger("payment_parser")

RE_APPROVED = re.compile(r"Pagamento aprovado", re.IGNORECASE)
RE_ORDER_ID = re.compile(r"Pedido\s*:\s*\**\s*#?(\w+)", re.IGNORECASE)
RE_CLIENT   = re.compile(r"Cliente\s*:\s*\**\s*(<@!?(\d+)>|@?([^\n*]+))", re.IGNORECASE)
RE_EMAIL    = re.compile(r"Email\s*:\s*\**\s*([^\s\n]+@[^\s\n*]+)", re.IGNORECASE)
RE_CHANNEL  = re.compile(r"Canal do checkout\s*:\s*\**\s*([^\n*]+)", re.IGNORECASE)
RE_ITEMS    = re.compile(r"Itens\s*:\s*\**\s*(\d+)", re.IGNORECASE)
RE_TOTAL    = re.compile(r"Total\s*:\s*\**\s*(R\$[\d.,]+)", re.IGNORECASE)
RE_DATE     = re.compile(r"Data\s*:\s*\**\s*([^\n*]+)", re.IGNORECASE)

# Mapa de preços para nomes de produtos (ADICIONE OS SEUS AQUI)
PRODUCT_MAP = {
    "3.90": "CONTAS GUEST - VINCULADA",
    "8.99": "GERADOR DE SENSI",
    "5.90": "PACK DE SENSI",
    "12.90": "PAINEL ANDROID EXTERNAL",
    "4.90": "PROXY ANDROID",
}

def extract_text_from_components(node) -> str:
    texts = []
    if not node:
        return ""
    raw = getattr(node, "to_dict", lambda: {})() or {}
    content = raw.get("content") or getattr(node, "content", None)
    if isinstance(content, str):
        texts.append(content)
    children = getattr(node, "children", None)
    if children:
        for child in children:
            texts.append(extract_text_from_components(child))
    if isinstance(node, list):
        for item in node:
            texts.append(extract_text_from_components(item))
    return "\n".join(t for t in texts if t)


def parse_payment_message(content: str, embeds: list, components: list) -> dict | None:
    full_text = content or ""

    for e in embeds:
        if e.title: full_text += "\n" + e.title
        if e.description: full_text += "\n" + e.description
        for f in e.fields: full_text += f"\n{f.name}: {f.value}"
        if e.footer and e.footer.text: full_text += "\n" + e.footer.text

    for comp in components:
        full_text += "\n" + extract_text_from_components(comp)

    if not RE_APPROVED.search(full_text):
        return None

    order_match = RE_ORDER_ID.search(full_text)
    if not order_match:
        return None

    def grab(regex, default="—"):
        m = regex.search(full_text)
        if not m: return default
        return m.group(1).replace("*", "").strip()

    def grab_client():
        m = RE_CLIENT.search(full_text)
        if not m: return "—"
        if m.group(2):
            return f"<@{m.group(2)}>"
        return m.group(3).replace("*", "").strip()

    total_str = grab(RE_TOTAL)
    item_name = "PRODUTO ADQUIRIDO"
    
    # Tenta adivinhar o nome do produto pelo preço
    if total_str:
        price_clean = total_str.replace("R$", "").strip()
        if price_clean in PRODUCT_MAP:
            item_name = PRODUCT_MAP[price_clean]
            
    # Se o embed tiver um título de produto, usa ele
    if embeds:
        for e in embeds:
            if e.title and "Pagamento aprovado" not in e.title:
                item_name = e.title
                break

    return {
        "order_id": order_match.group(1).strip(),
        "client":   grab_client(),
        "email":    grab(RE_EMAIL),
        "checkout": grab(RE_CHANNEL),
        "items":    grab(RE_ITEMS),
        "total":    total_str,
        "date":     grab(RE_DATE),
        "item":     item_name,
    }


class PaymentParser:
    def __init__(self, bot, source_channel_id, target_channel_id):
        self.bot = bot
        self.source_channel_id = source_channel_id
        self.target_channel_id = target_channel_id

    async def handle_message(self, message: discord.Message):
        if message.channel.id != self.source_channel_id:
            return

        data = parse_payment_message(message.content, message.embeds, message.components)
        if not data:
            return

        if await order_already_processed(data["order_id"]):
            return

        target = self.bot.get_channel(self.target_channel_id)
        if target is None:
            return

        try:
            client_id = None
            m = re.search(r"<@!?(\d+)>", data["client"])
            if m:
                client_id = int(m.group(1))
            
            user = self.bot.get_user(client_id) if client_id else None
            avatar_url = user.display_avatar.url if user else None
            client_name = user.name if user else data["client"].replace("<@", "").replace(">", "")

            img_buffer = await generate_receipt_image(
                client_name=client_name,
                client_avatar_url=avatar_url,
                date=data["date"],
                total=data["total"],
                product_name=data["item"],
                product_img_url=None
            )

            await target.send(file=discord.File(fp=img_buffer, filename="recibo.png"))
            await mark_order_processed(data["order_id"], int(time.time()))
            log.info("Pedido %s repostado.", data["order_id"])
        except Exception as e:
            log.exception("Falha ao gerar card: %s", e)