import os
from pathlib import Path
from dotenv import load_dotenv

# Forzar la ruta absoluta al archivo .env
env_path = Path(r"C:\FootballAI\Pro\.env")
print(f"🔍 Buscando .env en: {env_path}")
print(f"📁 ¿Existe el archivo?: {env_path.exists()}")

load_dotenv(dotenv_path=env_path)

api_id = os.getenv('TELEGRAM_API_ID')
api_hash = os.getenv('TELEGRAM_API_HASH')

print(f"📖 API_ID leído: '{api_id}'")
print(f"📖 API_HASH leído: '{api_hash}'")

if api_id and api_hash:
    print("✅ ¡Credenciales cargadas correctamente!")
else:
    print("❌ Fallo al cargar las credenciales.")