# Football AI Pro

Servidor web local que analiza los partidos de futbol de hoy: 22 modelos matematicos independientes, consenso con filtro de outliers, picks guardados y analisis final con Ollama. Modos: antes del partido, en vivo (lo que resta; 2.o tiempo en el descanso) y finalizado (cada pick con acierto/fallo). Datos de ESPN.

## Instalacion
1. Python 3.10 o superior y [Ollama](https://ollama.com). Luego: `ollama pull qwen2.5:7b`
2. Clonar el repo y, dentro de la carpeta: `python footballai_pro.py`
3. Abrir http://127.0.0.1:8888

No necesita paquetes (`requirements.txt` esta vacio a proposito). En Windows tambien sirve `iniciar.ps1`, que asume la ruta `C:\FootballAI\Pro`.

## Telegram (opcional)
Crear un venv aparte e instalar `requirements-telegram.txt`. Copiar `.env.example` a `.env` y poner TELEGRAM_API_ID y TELEGRAM_API_HASH (se obtienen en my.telegram.org). Nunca subir `.env` ni `*.session`.

## Aviso
Es una herramienta de analisis estadistico, no garantiza resultados. Que varios modelos coincidan no los vuelve independientes: comparten los mismos datos.