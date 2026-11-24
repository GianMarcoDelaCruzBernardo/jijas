import urllib.request
import json
import re
from bs4 import BeautifulSoup
from pathlib import Path

def get_reddit_sentiment(team1, team2):
    """Busca menciones del partido en Reddit sin necesitar API Keys (usa endpoint público JSON)."""
    query = f"{team1} {team2}".replace(" ", "+")
    url = f"https://www.reddit.com/r/soccer/search.json?q={query}&restrict_sr=on&sort=new&t=week"
    # Fallback a solo el equipo local si no hay resultados del partido
    url_fallback = f"https://www.reddit.com/r/soccer/search.json?q={team1.replace(' ', '+')}&restrict_sr=on&sort=new&t=week"
    
    headers = {'User-Agent': 'FootballAI/1.0 (by /u/FootballAI_Bot)'}
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            posts = data['data']['children']
            if not posts: # Intentar fallback
                req = urllib.request.Request(url_fallback, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read())
                    posts = data['data']['children']
            
            results = []
            for post in posts[:3]: # Tomar los 3 más recientes
                title = post['data']['title']
                score = post['data']['score']
                results.append(f"- [{score} upvotes] {title}")
            return "\n".join(results) if results else "No se encontraron discusiones recientes en r/soccer."
    except Exception as e:
        return f"Error buscando en Reddit: {e}"

def scrape_team_form(team_name):
    """Scraping básico de forma reciente (simulado con estructura lista para URLs reales)."""
    # Nota: Sitios como FBref o Flashscore tienen anti-scraping. 
    # Esta función está preparada para que pegues una URL específica de un sitio que permita scraping.
    # Por ahora, devuelve una estructura lista para ser llenada o usa una búsqueda simple.
    return f"Análisis web en proceso para {team_name}. (Integración lista para URLs específicas de FBref/Understat)."

def get_external_intelligence(home, away):
    """Orquestador principal de inteligencia externa."""
    print(f"   🌐 Buscando inteligencia externa para: {home} vs {away}...")
    
    reddit_data = get_reddit_sentiment(home, away)
    web_data = scrape_team_form(home) # Se puede expandir a 'away' también
    
    return f"""
REDDIT COMMUNITY SENTIMENT (r/soccer):
{reddit_data}

WEB SCRAPING DATA:
{web_data}
"""