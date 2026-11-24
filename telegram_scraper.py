import asyncio, json, re, base64, urllib.request, unicodedata, os
from datetime import datetime, timedelta
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(r"C:\FootballAI\Pro\.env"))
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
if not API_ID or not API_HASH: 
    print("❌ Error: API_ID o API_HASH no configurados en .env"); raise SystemExit(1)

BASE = Path(r"C:\FootballAI\Pro")
OUT = BASE / "social_sentiment.json"
CACHE_F = BASE / "ocr_cache.json"
TEMP = BASE / "temp_images"; TEMP.mkdir(exist_ok=True)
OLLAMA = "http://localhost:11434"

client = TelegramClient(str(BASE / "footballai_session"), API_ID, API_HASH)

# Cache para no reprocesar
cache = {}
if CACHE_F.exists():
    try: cache = json.loads(CACHE_F.read_text(encoding="utf-8"))
    except Exception: cache = {}
def save_cache(): CACHE_F.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

# OCR Principal
_reader = None
def ocr(path):
    global _reader
    if _reader is None:
        import easyocr; _reader = easyocr.Reader(["es", "en"], gpu=False, verbose=False)
    try: return " | ".join(_reader.readtext(str(path), detail=0))
    except Exception: return ""

# Fallback Visión
def vision(path):
    try:
        b64 = base64.b64encode(Path(path).read_bytes()).decode()
        pl = {"model": "qwen2.5-vl:3b", "stream": False, 
              "prompt": "Transcribe TODO el texto visible en esta imagen de apuestas. Una línea por fragmento.", "images": [b64]}
        rq = urllib.request.Request(OLLAMA + "/api/generate", data=json.dumps(pl).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(rq, timeout=120) as r: return json.loads(r.read()).get("response", "")
    except Exception: return ""

# LLM Extractor (maneja CUALQUIER plantilla)
EXTRACT_PROMPT = """Analiza este texto OCR de una imagen de un canal de pronósticos.
Devuelve SOLO JSON válido (sin markdown, sin explicación):
{"es_pick_real":true/false, "deporte":"futbol|tenis|basket|otro",
 "equipos":["Equipo A","Equipo B"], "liga":"texto o null",
 "mercado_tipo":"gol|corner|tarjeta|falta|remate|tiro_arco|offside|primer_tiempo|jugador|ganador|btts|otro",
 "mercado_texto":"ej: Más de 2.5 goles | Equipo con más córners | Jugador remata | null",
 "linea":2.5, "cuota":1.67, "jugador":"nombre o null", "fecha_partido":"23/11/2026 o null"}
REGLAS:
- es_pick_real=false si es SOLO publicidad (stake gratis, premium, VIP, regalo, suscríbete, contacto).
- Si hay varios picks, devuelve SOLO el PRIMERO.
- No inventes; campo ausente = null o [].
TEXTO OCR:
"""
def extract(text):
    if not text or len(text) < 10: return None
    try:
        pl = {"model": "qwen2.5", "stream": False, "options": {"temperature": 0.0, "num_ctx": 4096},
              "messages": [{"role": "user", "content": EXTRACT_PROMPT + text}]}
        rq = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(pl).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(rq, timeout=120) as r: raw = json.loads(r.read())["message"]["content"]
        m = re.search(r"\{.*\}", raw, re.S)
        if not m: return None
        d = json.loads(m.group(0))
        if d.get("es_pick_real") and d.get("deporte") == "futbol" and d.get("mercado_tipo") not in (None, "otro"):
            return d
    except Exception: return None
    return None

def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\b(fc|cf|sc|ac|club|deportivo)\b", "", s).strip()

async def main():
    print("🚀 Telegram Scraper v5 — Auto-canales, SOLO HOY, indexado por equipos")
    print("=" * 60)
    await client.connect()
    if not await client.is_user_authorized():
        ph = input("📱 Ingresa tu número de teléfono (ej: +51999999999): ")
        await client.send_code_request(ph)
        try: await client.sign_in(ph, input("🔑 Ingresa el código que llegó a Telegram: "))
        except SessionPasswordNeededError: await client.sign_in(password=input("🔒 Contraseña 2FA: "))
        print("✅ Sesión iniciada correctamente")

    # Detectar canales suscritos
    dialogs = await client.get_dialogs()
    chans = []
    kw = ["stake", "picks", "pronostic", "bet", "tip", "apost", "freebet", "tipster", "futbol", "soccer", "cuota", "predic", "ganador", "parlay", "combo"]
    for d in dialogs:
        ent = d.entity
        if isinstance(ent, Channel) and not getattr(ent, "megagroup", False):
            nm = (d.name or "").lower()
            if any(k in nm for k in kw) and getattr(ent, "username", None):
                chans.append((ent.username, d.name))
    
    print(f"📡 {len(chans)} canales de pronósticos detectados en tus suscripciones.")
    if not chans:
        print("⚠️ Ningún canal coincide. Asegúrate de estar unido a canales públicos de pronósticos.")
        await client.disconnect(); return

    posts = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    seen = {p.get("msg_id") for p in posts}
    today = datetime.now().astimezone().date()
    nuevos = 0

    for uname, cname in chans:
        print(f"\n🔍 @{uname} ({cname})...")
        try:
            async for msg in client.iter_messages(uname, limit=200):
                if not msg.date: continue
                if msg.date.astimezone().date() != today: break  # SOLO HOY
                mid = f"{uname}_{msg.id}"
                if mid in seen: continue
                
                is_img = bool(msg.photo) or (msg.document and (msg.document.mime_type or "").startswith("image/"))
                d = None
                if is_img:
                    if mid in cache:
                        d = cache[mid]
                    else:
                        p = TEMP / f"m{msg.id}.jpg"
                        await msg.download_media(p)
                        text = ocr(p)
                        if len(text) < 15: text = vision(p)
                        d = extract(text)
                        cache[mid] = d if d else {"skip": True}; save_cache()
                        if p.exists(): p.unlink()
                elif msg.text and len(msg.text) > 25:
                    d = extract(msg.text)
                
                if d and not d.get("skip"):
                    d.update({"channel": uname, "canal_name": cname, "msg_id": mid,
                              "date": msg.date.astimezone().strftime("%Y-%4m-%d %H:%M"),
                              "source": "imagen_ocr" if is_img else "texto",
                              "equipos_norm": [norm(e) for e in d.get("equipos", [])]})
                    posts.append(d); nuevos += 1
                    print(f"   ⚽ {d.get('mercado_tipo')} | {d.get('mercado_texto')} | Cuota: {d.get('cuota')} | {d.get('equipos')}")
        except Exception as e:
            print(f"   ⚠️ Error: {type(e).__name__}")
        print(f"   ✅ Acumulado: {len(posts)} picks")

    OUT.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ {nuevos} nuevos · Total: {len(posts)} picks guardados en {OUT}")
    await client.disconnect()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\n⚠️ Cancelado por el usuario (cache guardado)")
    except Exception as e:
        import traceback; print(f"\n❌ Error fatal: {e}"); traceback.print_exc()