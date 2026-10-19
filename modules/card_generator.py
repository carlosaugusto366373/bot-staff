import io
import re
import datetime
import aiohttp
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "arialbd.ttf"
FONT_REG = "arial.ttf"

async def fetch_image(url: str) -> Image.Image:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.read()
            return Image.open(io.BytesIO(data)).convert("RGBA")

def draw_rounded_rect(draw, xy, radius, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)

def clean_date(date_str):
    m = re.search(r"<t:(\d+):[fFdDtT]>", date_str)
    if m:
        ts = int(m.group(1))
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%d/%m/%Y às %H:%M")
    return date_str

async def generate_receipt_image(client_name, client_avatar_url, date, total, product_name, product_img_url=None):
    # 1. Cria um degradê escuro elegante de fundo
    bg = Image.new("RGBA", (1000, 1000), (15, 15, 20, 255))
    draw = ImageDraw.Draw(bg)
    
    # Desenha o gradiente no fundo
    for y in range(1000):
        r = int(15 + (y / 1000) * 10)
        g = int(15 + (y / 1000) * 12)
        b = int(25 + (y / 1000) * 20)
        draw.line([(0, y), (1000, y)], fill=(r, g, b, 255))

    try:
        font_large = ImageFont.truetype(FONT_BOLD, 60)
        font_med = ImageFont.truetype(FONT_BOLD, 40)
        font_small = ImageFont.truetype(FONT_REG, 30)
        font_huge = ImageFont.truetype(FONT_BOLD, 90)
        font_price = ImageFont.truetype(FONT_BOLD, 100)
    except:
        font_large = font_med = font_small = font_huge = font_price = ImageFont.load_default()

    date_clean = clean_date(date)

    # RECIBO e Borda
    draw.text((80, 80), "R E C I B O", font=font_small, fill=(150, 150, 150, 255))
    
    # Avatar
    if client_avatar_url:
        try:
            avatar = await fetch_image(client_avatar_url)
            avatar = avatar.resize((100, 100))
            mask = Image.new("L", (100, 100), 0)
            d_mask = ImageDraw.Draw(mask)
            d_mask.ellipse((0, 0, 100, 100), fill=255)
            bg.paste(avatar, (80, 150), mask)
        except:
            pass

    # Nome e Data
    draw.text((200, 150), client_name, font=font_large, fill=(255, 255, 255, 255))
    draw.text((200, 210), f"@{client_name.lower()}", font=font_small, fill=(150, 150, 150, 255))
    draw.text((700, 170), date_clean, font=font_small, fill=(200, 200, 200, 255))

    # Compra Realizada
    draw.text((80, 300), "Compra Realizada", font=font_huge, fill=(255, 255, 255, 255))

    # Linha pontilhada
    for x in range(80, 920, 20):
        draw.rectangle((x, 420, x+10, 425), fill=(80, 80, 80, 255))

    # CARRINHO (Nome do Produto)
    draw.text((80, 470), "C A R R I N H O", font=font_small, fill=(150, 150, 150, 255))
    safe_product = product_name[:35] + "..." if len(product_name) > 35 else product_name
    draw.text((80, 520), f"1x {safe_product.upper()}", font=font_med, fill=(255, 255, 255, 255))
    draw.text((800, 520), total, font=font_med, fill=(255, 255, 255, 255))

    # SUBTOTAL
    draw.text((80, 620), "S U B T O T A L", font=font_small, fill=(150, 150, 150, 255))
    draw.text((800, 620), total, font=font_med, fill=(255, 255, 255, 255))

    # Valor Pago (Caixa semi-transparente)
    draw_rounded_rect(draw, (80, 700, 920, 880), radius=20, fill=(25, 30, 45, 255))
    draw.text((120, 780), "V A L O R  P A G O", font=font_small, fill=(150, 150, 150, 255))
    draw.text((600, 750), total, font=font_price, fill=(80, 150, 255, 255))

    # Footer com linha
    draw.text((80, 930), "QZZ COMMUNITY • PAGAMENTO APROVADO", font=font_small, fill=(100, 100, 100, 255))

    img_byte_arr = io.BytesIO()
    bg.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr