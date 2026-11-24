# CONTEXTO DEL PROYECTO - FootballAI Pro
Lee este archivo COMPLETO antes de tocar nada. No adivines: si algo no esta aqui, lee el archivo real o pregunta.

## Que es
Servidor web local que analiza partidos de futbol de hoy. Combina 22 modelos matematicos independientes, un consenso con filtro de outliers y un analisis final de Ollama. Interfaz en http://127.0.0.1:8888 (puerto UNICO). Solo libreria estandar de Python (sin numpy/pandas).

## Como se ejecuta (UNICA forma valida)
- Normal (ventana visible): C:\FootballAI\Pro\iniciar.ps1  o doble clic en iniciar.bat
- Segundo plano (agente): powershell -NoProfile -File C:\FootballAI\Pro\iniciar.ps1 -Background
- Logs en segundo plano: Pro\logs\server_out.log y server_err.log. Log del sistema: Pro\logs\system.log
- Verificar: GET http://127.0.0.1:8888/api/matches debe devolver JSON. El log dice "Football AI Pro en http://127.0.0.1:8888 | 22 modelos".
- Si el log dice puerto 8766 o "8 modelos simulados": es la version VIEJA. Detenla y usa iniciar.ps1.

## Estructura (C:\FootballAI)
Pro\                      <- PROYECTO ACTIVO (unica carpeta que se edita)
  footballai_pro.py       servidor + 22 modelos + consenso + picks + modo en vivo + informe final + memoria
  ui.html                 interfaz (recuperada; NO editar salvo peticion explicita)
  iniciar.ps1 / .bat      lanzador (mata versiones viejas y arranca la nueva)
  predictions_log.json    MEMORIA: picks guardados antes del partido y su resultado (no borrar)
  predictions\            JSON de cada analisis
  backups\                copias de seguridad de footballai_pro.py
  logs\                   registros
  data\                   CSV historicos (football-data.co.uk, ClubElo) - aun no usados por los modelos
  catalog\                catalogo de repos de GitHub encontrados
  telegram_scraper.py, external_intel.py, venv_telegram\   scraper de Telegram (aislado, aun sin login)
  .env, footballai_session*   SECRETOS: nunca mostrarlos, imprimirlos ni copiarlos
venv\                     entorno Python general (NO instalar paquetes aqui: ya hubo conflictos de numpy)
github_models\            repos clonados de GitHub. NO estan conectados al sistema todavia
recovery\                 respaldos de la recuperacion del codigo. No borrar
_archivo_viejo\           versiones antiguas archivadas (8 modelos simulados). NUNCA ejecutar

## Flujo de un analisis
1. ESPN scoreboard (26 ligas) -> lista de partidos de hoy (/api/matches).
2. Al analizar: se refresca el estado del partido (summary de ESPN) y se baja el historial de 10 partidos por equipo, EXCLUYENDO el partido actual.
3. 22 modelos corren por separado (cada uno en try/except; si uno falla se omite y queda en el log "MODELO FALLO").
4. Consenso por mercado: descarta modelos a mas de 20 puntos de la mediana; conf = media limpia x acuerdo/22.
5. Picks del sistema (max 6, max 2 por mercado). Se guardan en predictions_log.json.
6. Ollama (qwen2.5:7b, localhost:11434) redacta el informe.
Tres modos segun el estado del partido:
- pre: pronostico completo + picks guardados en la memoria.
- in (en vivo): recalcula lo que RESTA (marcador, minuto, estadisticas acumuladas); en el descanso analiza el 2.o tiempo.
- post: informe automatico SIN IA con cada pick marcado acierto/fallo y estadisticas reales.
Cada 10 min un hilo califica los picks pendientes de partidos terminados.
Endpoints: / , /api/matches , /api/models , POST /api/analyze , /api/job/<id> , /api/record

## Los 22 modelos (todos formulas propias, no codigo de GitHub)
Poisson media, Poisson decaimiento, Poisson local-visit, Poisson visit-local, Gamma-Poisson bayes, Binomial negativa, Prior-shrink liga, EWMA forma, Zero-inflated, Winsorizada, Weibull recencia, Dixon-Coles, Rating multiplicativo, ELO forma simple, Monte Carlo totales, Ensemble mediana, Ensemble bayes-decay, Frecuencia empirica, Poisson mediana, Tendencia lineal, NB decaimiento, Normal promedio bruto.
Estan en la lista MODELS de footballai_pro.py. Para agregar uno: MODELS.append(("nombre", funcion)); la funcion recibe (D, lines, rnd) y devuelve un dict {"goals_2.5": %, "btts": %, "home_win": %, ..., "mu_corners": media}.
Mercados: goles, ambos marcan, 1X2, corners, tarjetas, faltas, remates, remates al arco.

## REGLAS DE SEGURIDAD (obligatorias)
1. Antes de modificar footballai_pro.py: copiarlo a Pro\backups\footballai_pro_AAAAMMDD_HHMMSS.py. Despues de modificar: python -m py_compile; si falla, restaurar el backup.
2. NUNCA borrar archivos ni carpetas. Para quitar algo, MOVER a C:\FootballAI\_archivo_viejo\.
3. NUNCA reescribir footballai_pro.py entero pegandolo en un here-string, ni parchearlo con regex sobre lineas sueltas. Ya se perdio una version asi. Usar reemplazos exactos de un bloque, uno por uno, verificando que el texto original aparezca UNA sola vez.
4. NO ejecutar nada de _archivo_viejo\ ni scripts que abran otro servidor.
5. NO instalar paquetes en C:\FootballAI\venv. El scraper de Telegram usa Pro\venv_telegram.
6. NO leer, mostrar ni subir .env ni footballai_session*.
7. NO inventar rutas ni nombres: si dudas, lista la carpeta o pregunta.
8. Un solo servidor, puerto 8888. Para reiniciar siempre usar iniciar.ps1.

## Pendiente / limites conocidos
- Los repos de github_models no estan conectados (cada uno necesita un adaptador).
- Telegram: login bloqueado por demasiados intentos; codigo de login = 5 numeros.
- Los modelos usan los mismos datos: que 21/22 coincidan no equivale a 21 opiniones independientes. La memoria de aciertos necesita decenas de partidos para ser fiable.
- ESPN a veces no trae estadisticas en vivo; entonces solo se analizan goles.