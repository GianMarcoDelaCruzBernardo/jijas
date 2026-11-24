# -*- coding: utf-8 -*-
"""Football AI Pro - reconstruido. 22 modelos independientes -> consenso -> Ollama.
Ejecutar:  python footballai_pro.py   (necesita ui.html en la misma carpeta)"""
import json, math, random, subprocess, sys, threading, time, traceback, uuid, webbrowser
import concurrent.futures, urllib.request, unicodedata, re
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
(BASE / "logs").mkdir(exist_ok=True)
(BASE / "predictions").mkdir(exist_ok=True)
OLLAMA = "http://localhost:11434"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOME_ADV = 1.08
N_HIST = 10


def log(msg):
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with open(BASE / "logs" / "system.log", "a", encoding="utf-8") as fp:
            fp.write(line + "\n")
    except Exception:
        pass


def g(d, *ks, default=None):
    """get anidado seguro: nunca revienta con None."""
    for k in ks:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, (list, tuple)) and isinstance(k, int) and -len(d) <= k < len(d):
            d = d[k]
        else:
            return default
        if d is None:
            return default
    return d


def num(x):
    if isinstance(x, dict):
        x = x.get("value", x.get("displayValue"))
    try:
        return float(x)
    except Exception:
        return 0.0


# ======================= OLLAMA =======================
def ollama_req(path, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(OLLAMA + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ensure_ollama(want):
    try:
        tags = ollama_req("/api/tags")
    except Exception:
        log("Iniciando Ollama...")
        subprocess.Popen(["ollama", "serve"], creationflags=NOWIN)
        tags = None
        for _ in range(20):
            time.sleep(1)
            try:
                tags = ollama_req("/api/tags")
                break
            except Exception:
                pass
        if tags is None:
            raise RuntimeError("Ollama no arranco. Abrelo manualmente.")
    names = [m["name"] for m in tags.get("models", [])]
    for n in names:
        if n == want:
            return n
    for n in names:
        if n.split(":")[0] == want.split(":")[0]:
            return n
    raise RuntimeError(f"Modelo '{want}' no instalado. Ejecuta: ollama pull {want}")


# ======================= ESPN: PARTIDOS =======================
LEAGUES = [("per.1", "Liga 1 Peru", "🇵🇪"), ("fifa.worldq.conmebol", "Eliminatorias CONMEBOL", "🌎"),
           ("conmebol.libertadores", "Libertadores", "🏆"), ("conmebol.sudamericana", "Sudamericana", "🏆"),
           ("uefa.champions", "Champions League", "🇪🇺"), ("uefa.europa", "Europa League", "🇪🇺"),
           ("eng.1", "Premier League", "🏴"), ("esp.1", "LaLiga", "🇪🇸"), ("ita.1", "Serie A", "🇮🇹"),
           ("ger.1", "Bundesliga", "🇩🇪"), ("fra.1", "Ligue 1", "🇫🇷"), ("eng.2", "Championship", "🏴"),
           ("esp.2", "LaLiga 2", "🇪🇸"), ("ned.1", "Eredivisie", "🇳🇱"), ("por.1", "Primeira Liga", "🇵🇹"),
           ("arg.1", "Argentina", "🇦🇷"), ("bra.1", "Brasileirao", "🇧🇷"), ("col.1", "Colombia", "🇨🇴"),
           ("chi.1", "Chile", "🇨🇱"), ("uru.1", "Uruguay", "🇺🇾"), ("ecu.1", "Ecuador", "🇪🇨"),
           ("bol.1", "Bolivia", "🇧🇴"), ("par.1", "Paraguay", "🇵🇾"), ("ven.1", "Venezuela", "🇻🇪"),
           ("mex.1", "Liga MX", "🇲🇽"), ("usa.1", "MLS", "🇺🇸")]


def espn_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def american_to_dec(x):
    try:
        x = float(str(x).replace("+", ""))
    except Exception:
        return None
    if x == 0:
        return None
    return round(1 + (x / 100 if x > 0 else 100 / abs(x)), 2)


def parse_odds(comp):
    o = g(comp, "odds", 0, default={}) or {}
    h = american_to_dec(g(o, "homeTeamOdds", "moneyLine")) or american_to_dec(g(o, "moneyline", "home", "close", "odds"))
    d = american_to_dec(g(o, "drawOdds", "moneyLine")) or american_to_dec(g(o, "moneyline", "draw", "close", "odds"))
    a = american_to_dec(g(o, "awayTeamOdds", "moneyLine")) or american_to_dec(g(o, "moneyline", "away", "close", "odds"))
    return {"dec_home": h, "dec_draw": d, "dec_away": a, "ou_line": o.get("overUnder")}


def parse_event(ev, slug, name, flag):
    comp = g(ev, "competitions", 0, default={}) or {}
    cs = {c.get("homeAway"): c for c in (comp.get("competitors") or []) if isinstance(c, dict)}
    if "home" not in cs or "away" not in cs:
        return None
    st = g(ev, "status", "type", default={}) or {}
    state = st.get("state", "pre")
    try:
        dt = datetime.fromisoformat(str(ev.get("date", "")).replace("Z", "+00:00")).astimezone()
    except Exception:
        dt = datetime.now().astimezone()
    ht, at = cs["home"].get("team") or {}, cs["away"].get("team") or {}
    o = g(comp, "odds", 0, default={}) or {}
    return {"id": str(ev.get("id", "")), "slug": slug, "liga": name, "flag": flag, "leagueFlag": flag, "state": state,
            "clock": str(g(ev, "status", "displayClock", default="")) if state == "in" else "",
            "period": str(st.get("shortDetail") or st.get("detail") or ""), "iso": dt.isoformat(),
            "home": ht.get("displayName", "Local"), "away": at.get("displayName", "Visitante"),
            "homeId": str(ht.get("id", "")), "awayId": str(at.get("id", "")),
            "hs": str(cs["home"].get("score", "")), "as": str(cs["away"].get("score", "")),
            "homeLogo": ht.get("logo", ""), "awayLogo": at.get("logo", ""),
            "bookLine": str(o.get("details", "")), "bookOU": o.get("overUnder", ""), "odds": parse_odds(comp)}


_warned = set()


def fetch_today():
    day = datetime.now().strftime("%Y%m%d")
    fails = []

    def one(l):
        slug, name, flag = l
        try:
            d = espn_get(f"{ESPN}/{slug}/scoreboard?dates={day}")
        except Exception:
            fails.append(slug)
            return []
        out = []
        for ev in (d.get("events") or []):
            try:
                m = parse_event(ev, slug, name, flag)
                if m:
                    out.append(m)
            except Exception:
                if slug not in _warned:
                    _warned.add(slug)
                    log(f"AVISO evento no legible en {slug}: {traceback.format_exc(limit=2)}")
        return out

    with concurrent.futures.ThreadPoolExecutor(10) as ex:
        res = list(ex.map(one, LEAGUES))
    seen, ms = set(), []
    for lst in res:
        for m in lst:
            if m["id"] not in seen:
                seen.add(m["id"])
                ms.append(m)
    order = {"in": 0, "pre": 1, "post": 2}
    ms.sort(key=lambda m: (order.get(m["state"], 1), m["iso"]))
    log(f"Partidos de hoy: {len(ms)} ({len(fails)} ligas sin respuesta)")
    return ms


# ======================= ESPN: HISTORIAL =======================
_sum_cache = {}
STATMAP = {"corners": "wonCorners", "fouls": "foulsCommitted", "yellow": "yellowCards", "red": "redCards",
           "shots": "totalShots", "sot": "shotsOnTarget"}


def fetch_summary(slug, eid):
    k = (slug, str(eid))
    if k in _sum_cache:
        return _sum_cache[k]
    try:
        d = espn_get(f"{ESPN}/{slug}/summary?event={eid}")
    except Exception as e:
        log(f"AVISO summary {eid}: {e!r}")
        d = {}
    _sum_cache[k] = d
    return d


def team_stats_from(d):
    res = {}
    for t in (g(d, "boxscore", "teams", default=[]) or []):
        tid = str(g(t, "team", "id", default=""))
        raw = {}
        for s in (t.get("statistics") or []):
            if isinstance(s, dict) and s.get("name"):
                raw[s["name"]] = num(s.get("displayValue", s.get("value")))
        st = {k: raw[nm] for k, nm in STATMAP.items() if nm in raw}
        if "yellow" in st:
            st["cards"] = st["yellow"] + st.get("red", 0.0)
        res[tid] = st
    return res


def get_team_history(slug, tid, limit=N_HIST):
    games = {}
    y = datetime.now().year
    for year in (y, y - 1, y - 2):
        try:
            d = espn_get(f"{ESPN}/{slug}/teams/{tid}/schedule?season={year}")
        except Exception:
            continue
        for ev in (d.get("events") or []):
            comp = g(ev, "competitions", 0, default={}) or {}
            if not g(comp, "status", "type", "completed", default=False):
                continue
            cs = comp.get("competitors") or []
            me = next((c for c in cs if str(g(c, "team", "id", default="")) == str(tid)), None)
            op = next((c for c in cs if c is not me), None)
            if me and op:
                gf, ga = num(me.get("score")), num(op.get("score"))
                games[str(ev.get("id"))] = {"id": str(ev.get("id")), "gf": gf, "ga": ga,
                                            "opp": str(g(op, "team", "id", default="")),
                                            "oppName": g(op, "team", "displayName", default="?"),
                                            "date": str(ev.get("date", ""))[:10]}
        if len(games) >= limit:
            break
    return sorted(games.values(), key=lambda x: x["date"], reverse=True)[:limit]


def build_history(m, n=N_HIST):
    H = {}
    for side in ("home", "away"):
        tid = m[side + "Id"]
        games = get_team_history(m["slug"], tid, n)
        with concurrent.futures.ThreadPoolExecutor(6) as ex:
            sums = list(ex.map(lambda x: fetch_summary(m["slug"], x["id"]), games))
        for x, d in zip(games, sums):
            st = team_stats_from(d)
            x["own"] = st.get(str(tid), {})
            x["opp_st"] = st.get(x["opp"], {})
        H[side] = games
    return H


# ======================= DATOS POR FAMILIA =======================
FAMS = ["goals", "corners", "cards", "fouls", "shots", "sot"]
PRIOR = {"goals": 1.3, "corners": 4.8, "cards": 2.0, "fouls": 11.5, "shots": 12.0, "sot": 4.0}
NOUN = {"goals": "goles", "corners": "córners", "cards": "tarjetas", "fouls": "faltas", "shots": "remates", "sot": "remates al arco"}
TITLE = {"goals": "Goles totales", "corners": "Córners totales", "cards": "Tarjetas totales", "fouls": "Faltas totales",
         "shots": "Remates totales", "sot": "Remates al arco totales", "btts": "Ambos marcan"}


class Fam:
    def __init__(s):
        s.hf, s.ha, s.af, s.aa, s.th, s.ta = [], [], [], [], [], []

    def ok(s):
        return len(s.hf) >= 3 and len(s.af) >= 3


def build_data(H):
    D = {f: Fam() for f in FAMS}
    for side, (f, a, t) in {"home": ("hf", "ha", "th"), "away": ("af", "aa", "ta")}.items():
        for x in H[side]:
            G = D["goals"]
            getattr(G, f).append(x["gf"]); getattr(G, a).append(x["ga"]); getattr(G, t).append(x["gf"] + x["ga"])
            o, p = x.get("own") or {}, x.get("opp_st") or {}
            for fam in FAMS[1:]:
                if fam in o and fam in p:
                    F = D[fam]
                    getattr(F, f).append(o[fam]); getattr(F, a).append(p[fam]); getattr(F, t).append(o[fam] + p[fam])
    D["present"] = [f for f in FAMS if D[f].ok()]
    D["games"] = {s: [(x["gf"], x["ga"]) for x in H[s]] for s in ("home", "away")}

    def ppg(gs):
        gs = gs[:5]
        return sum(3 if a > b else 1 if a == b else 0 for a, b in gs) / len(gs) if gs else 1.0
    D["ppg"] = {s: ppg(D["games"][s]) for s in ("home", "away")}
    return D


def pick_lines(D):
    lines = {"goals": [0.5, 1.5, 2.5, 3.5, 4.5]}
    for fam in D["present"]:
        if fam == "goals":
            continue
        F = D[fam]
        allt = F.th + F.ta
        c = math.floor(sum(allt) / len(allt)) + 0.5
        lines[fam] = [x for x in (c - 2, c - 1, c, c + 1, c + 2) if x > 0]
    return lines


# ======================= DISTRIBUCIONES =======================
def pmf(mean, dist="pois", K=12):
    mean = max(mean, 1e-6)
    K = max(K, int(mean * 4 + 15)) if K > 12 else K

    def pois(lam):
        return [math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1)) for k in range(K + 1)]
    if dist == "nb":
        r = 6.0
        p = r / (r + mean)
        out = [math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p))
               for k in range(K + 1)]
    elif dist == "zip":
        pi = 0.06
        out = [(1 - pi) * v for v in pois(mean / (1 - pi))]
        out[0] += pi
    else:
        out = pois(mean)
    s = sum(out)
    return [x / s for x in out]


def goal_matrix(lh, la, dist, rho=0.0, K=10):
    ph, pa = pmf(lh, dist, K), pmf(la, dist, K)
    M = [[ph[i] * pa[j] for j in range(K + 1)] for i in range(K + 1)]
    if rho:
        M[0][0] *= max(0.0, 1 - lh * la * rho); M[0][1] *= max(0.0, 1 + lh * rho)
        M[1][0] *= max(0.0, 1 + la * rho); M[1][1] *= max(0.0, 1 - rho)
    s = sum(sum(r) for r in M)
    return [[x / s for x in r] for r in M]


def matrix_outputs(M, lines_goals):
    K = len(M)
    out = {}
    for L in lines_goals:
        out[f"goals_{L}"] = sum(M[i][j] for i in range(K) for j in range(K) if i + j > L) * 100
    out["btts"] = sum(M[i][j] for i in range(1, K) for j in range(1, K)) * 100
    out["home_win"] = sum(M[i][j] for i in range(K) for j in range(K) if i > j) * 100
    out["draw"] = sum(M[i][i] for i in range(K)) * 100
    out["away_win"] = 100 - out["home_win"] - out["draw"]
    return out


def p_over(pm_, line):
    return max(0.0, min(1.0, 1 - sum(pm_[:int(math.floor(line)) + 1]))) * 100


# ======================= ESTIMADORES (lista reciente-primero) =======================
def e_mean(v, p): return sum(v) / len(v) if v else p
def e_median(v, p):
    if not v: return p
    s = sorted(v); n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
def _wmean(v, w): return sum(a * b for a, b in zip(v, w)) / sum(w)
def e_decay(v, p): return _wmean(v, [0.85 ** i for i in range(len(v))]) if v else p
def e_ewma(v, p): return _wmean(v, [0.5 ** (i / 3.0) for i in range(len(v))]) if v else p
def e_weibull(v, p): return _wmean(v, [math.exp(-((i + 0.5) / 4.0) ** 1.4) for i in range(len(v))]) if v else p
def e_trim(v, p):
    s = sorted(v)
    if len(s) >= 5: s = s[1:-1]
    return sum(s) / len(s) if s else p
def e_wins(v, p):
    if not v: return p
    m = sum(v) / len(v); sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
    return sum(min(max(x, m - 1.5 * sd), m + 1.5 * sd) for x in v) / len(v)
def e_bayes(v, p): return (p * 4 + sum(v)) / (4 + len(v))
def e_shrink(v, p): return (len(v) * e_mean(v, p) + 5 * p) / (len(v) + 5) if v else p
def e_trend(v, p):
    n = len(v)
    if n < 4: return e_mean(v, p)
    xs = list(range(n))[::-1]  # el mas viejo = 0
    mx, my = sum(xs) / n, sum(v) / n
    den = sum((x - mx) ** 2 for x in xs) or 1
    b = sum((x - mx) * (y - my) for x, y in zip(xs, v)) / den
    return max(0.3 * my, my + b * (n - mx))
def e_ens_med(v, p): return e_median([e_mean(v, p), e_decay(v, p), e_ewma(v, p), e_trim(v, p)], p)
def e_ens_bd(v, p): return (e_bayes(v, p) + e_decay(v, p)) / 2


def combo_means(F, est, prior, combo):
    hf, ha, af, aa = est(F.hf, prior), est(F.ha, prior), est(F.af, prior), est(F.aa, prior)
    if combo == "lv":
        return 0.6 * hf + 0.4 * aa, 0.6 * af + 0.4 * ha
    if combo == "vl":
        return 0.4 * hf + 0.6 * aa, 0.4 * af + 0.6 * ha
    if combo == "mult":
        lg = max((hf + aa + af + ha) / 4, 1e-6)
        return lg * (hf / lg) * (aa / lg), lg * (af / lg) * (ha / lg)
    return (hf + aa) / 2, (af + ha) / 2


# ======================= LOS 22 MODELOS (cada uno independiente) =======================
def spec(est, dist="pois", combo="avg", rho=0.0, form=False):
    def run(D, lines, rnd):
        out = {}
        for fam in D["present"]:
            F = D[fam]
            lh, la = combo_means(F, est, PRIOR[fam], combo)
            if fam == "goals":
                lh, la = lh * HOME_ADV, la / HOME_ADV
                if form:
                    d = (D["ppg"]["home"] - D["ppg"]["away"]) / 3
                    lh, la = lh * (1 + 0.25 * d), la * (1 - 0.25 * d)
                out.update(matrix_outputs(goal_matrix(lh, la, dist, rho), lines["goals"]))
            else:
                pm_ = pmf(lh + la, dist, 25)
                for L in lines[fam]:
                    out[f"{fam}_{L}"] = p_over(pm_, L)
        return out
    return run


def _poisson_draw(rnd, lam):
    if lam > 30:
        return max(0, int(round(rnd.gauss(lam, lam ** 0.5))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rnd.random()
        if p <= L:
            return k
        k += 1


def model_montecarlo(D, lines, rnd, N=3000):
    out = {}
    for fam in D["present"]:
        F = D[fam]
        lh, la = combo_means(F, e_mean, PRIOR[fam], "avg")
        if fam == "goals":
            lh, la = lh * HOME_ADV, la / HOME_ADV
        hs, as_ = [], []
        for _ in range(N):
            hs.append(_poisson_draw(rnd, max(0.05, rnd.gauss(lh, 0.35 * lh))))
            as_.append(_poisson_draw(rnd, max(0.05, rnd.gauss(la, 0.35 * la))))
        tot = [a + b for a, b in zip(hs, as_)]
        for L in lines[fam]:
            out[f"{fam}_{L}"] = sum(1 for t in tot if t > L) / N * 100
        if fam == "goals":
            out["btts"] = sum(1 for a, b in zip(hs, as_) if a > 0 and b > 0) / N * 100
            out["home_win"] = sum(1 for a, b in zip(hs, as_) if a > b) / N * 100
            out["draw"] = sum(1 for a, b in zip(hs, as_) if a == b) / N * 100
            out["away_win"] = 100 - out["home_win"] - out["draw"]
    return out


def model_empirical(D, lines, rnd):
    out = {}
    for fam in D["present"]:
        F = D[fam]
        for L in lines[fam]:
            r = [(sum(1 for x in lst if x > L) + 1) / (len(lst) + 2) for lst in (F.th, F.ta) if lst]
            out[f"{fam}_{L}"] = sum(r) / len(r) * 100
    gh, ga = D["games"]["home"], D["games"]["away"]
    if gh and ga:
        n1, n2 = len(gh), len(ga)
        out["btts"] = (sum(1 for a, b in gh if a > 0 and b > 0) / n1 + sum(1 for a, b in ga if a > 0 and b > 0) / n2) / 2 * 100
        out["home_win"] = (sum(1 for a, b in gh if a > b) / n1 + sum(1 for a, b in ga if a < b) / n2) / 2 * 100
        out["draw"] = (sum(1 for a, b in gh if a == b) / n1 + sum(1 for a, b in ga if a == b) / n2) / 2 * 100
        out["away_win"] = max(0.0, 100 - out["home_win"] - out["draw"])
    return out


def model_normal(D, lines, rnd):
    out = spec(e_mean, "pois")(D, lines, rnd)
    for fam in D["present"]:
        F = D[fam]
        lh, la = combo_means(F, e_mean, PRIOR[fam], "avg")
        mean = lh + la
        allt = F.th + F.ta
        mu = sum(allt) / len(allt)
        sd = max(0.5, (sum((x - mu) ** 2 for x in allt) / len(allt)) ** 0.5)
        for L in lines[fam]:
            out[f"{fam}_{L}"] = (1 - 0.5 * (1 + math.erf((L - mean) / (sd * 2 ** 0.5)))) * 100
    return out


MODELS = [
    ("Poisson media", spec(e_mean)),
    ("Poisson decaimiento", spec(e_decay)),
    ("Poisson local-visit", spec(e_mean, combo="lv")),
    ("Poisson visit-local", spec(e_mean, combo="vl")),
    ("Gamma-Poisson bayes", spec(e_bayes)),
    ("Binomial negativa", spec(e_mean, dist="nb")),
    ("Prior-shrink liga", spec(e_shrink)),
    ("EWMA forma", spec(e_ewma)),
    ("Zero-inflated", spec(e_mean, dist="zip")),
    ("Winsorizada", spec(e_wins)),
    ("Weibull recencia", spec(e_weibull)),
    ("Dixon-Coles", spec(e_mean, rho=-0.10)),
    ("Rating multiplicativo", spec(e_mean, combo="mult")),
    ("ELO forma simple", spec(e_decay, form=True)),
    ("Monte Carlo totales", model_montecarlo),
    ("Ensemble mediana", spec(e_ens_med)),
    ("Ensemble bayes-decay", spec(e_ens_bd)),
    ("Frecuencia empirica", model_empirical),
    ("Poisson mediana", spec(e_median)),
    ("Tendencia lineal", spec(e_trend)),
    ("NB decaimiento", spec(e_decay, dist="nb")),
    ("Normal promedio bruto", model_normal),
]

# --- Punto de extension: aqui se enchufan los repos de GitHub (penaltyblog, matchbrain...) ---
# Cada adaptador debe devolver el mismo dict {"goals_2.5": %, "btts": %, "home_win": %, ...}
# y se agrega con:  MODELS.append(("penaltyblog", mi_funcion))


# ======================= CONSENSO =======================
def _r1(x): return round(x, 1)


def consensus(results, lines, D):
    """results: lista de dicts, uno por modelo exitoso."""
    n = len(results)
    fams = []

    def make_row(label, line, over_ps):
        mean = sum(over_ps) / n
        over = mean >= 50
        ps = over_ps if over else [100 - p for p in over_ps]
        med = sorted(ps)[n // 2]
        out_idx = [i for i, p in enumerate(ps) if abs(p - med) > 20]
        clean = [p for i, p in enumerate(ps) if i not in out_idx] or ps
        cm = sum(clean) / len(clean)
        m_ = sum(ps) / n
        sd = (sum((p - m_) ** 2 for p in ps) / n) ** 0.5
        agree = sum(1 for p in ps if p >= 50)
        return {"line": line, "label": label(over), "probs": [_r1(p) for p in ps], "mean": _r1(m_), "sd": _r1(sd),
                "agree": agree, "n": n, "conf": _r1(cm * agree / n), "clean_mean": _r1(cm), "outliers": out_idx}

    for fam in D["present"]:
        rows = []
        for L in lines[fam]:
            key = f"{fam}_{L}"
            if all(key in r for r in results):
                rows.append(make_row(lambda o, L=L, fam=fam: f"{'Más' if o else 'Menos'} {L:g} {NOUN[fam]}", L, [r[key] for r in results]))
        if rows:
            fams.append({"fam": fam, "title": TITLE[fam], "rows": rows})
    if "goals" in D["present"] and all("btts" in r for r in results):
        fams.append({"fam": "btts", "title": TITLE["btts"], "rows": [
            make_row(lambda o: "Ambos marcan: Sí" if o else "Ambos marcan: No", 0.5, [r["btts"] for r in results])]})
    r1x2 = {}
    for k in ("home_win", "draw", "away_win"):
        ps = [r[k] for r in results if k in r]
        if ps:
            med = sorted(ps)[len(ps) // 2]
            cl = [p for p in ps if abs(p - med) <= 20] or ps
            r1x2[k] = sum(cl) / len(cl)
    return fams, r1x2


def value_bets(r1x2, odds):
    names = {"home_win": ("Gana local", "dec_home"), "draw": ("Empate", "dec_draw"), "away_win": ("Gana visitante", "dec_away")}
    decs = {k: odds.get(v[1]) for k, v in names.items()}
    raws = {k: 1 / d for k, d in decs.items() if d}
    tot = sum(raws.values()) if len(raws) == 3 else None
    out = []
    for k, (label, _) in names.items():
        if k in r1x2 and decs.get(k):
            impl = raws[k] / tot * 100 if tot else raws[k] * 100
            edge = r1x2[k] - impl
            if edge >= 5:
                out.append({"mkt": label, "p": _r1(r1x2[k]), "cuota": decs[k], "impl": _r1(impl), "edge": _r1(edge)})
    return sorted(out, key=lambda x: -x["edge"])


def averages(D):
    av = {}
    for fam in D["present"]:
        F = D[fam]
        av[fam] = {"h_for": _r1(e_mean(F.hf, 0)), "h_ag": _r1(e_mean(F.ha, 0)), "a_for": _r1(e_mean(F.af, 0)),
                   "a_ag": _r1(e_mean(F.aa, 0)), "n": len(F.hf)}
    return av


def history_view(H):
    out = {}
    for side in ("home", "away"):
        out[side] = [{"r": "G" if x["gf"] > x["ga"] else "E" if x["gf"] == x["ga"] else "P",
                      "s": f"{int(x['gf'])}-{int(x['ga'])}", "opp": x.get("oppName", "?")} for x in H[side]]
    return out


# ======================= TELEGRAM (solo lectura del JSON generado por el scraper) =======================
def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\b(fc|cf|sc|ac|club|deportivo)\b", "", s).strip()


def telegram_picks(home, away):
    p = BASE / "social_sentiment.json"
    if not p.exists():
        return ""
    try:
        posts = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    toks = {t for t in (_norm(home) + " " + _norm(away)).split() if len(t) > 3}
    hit = [x for x in posts if any(t in " ".join(x.get("equipos_norm", [])) for t in toks)]
    return "\n".join(f"  - {x.get('canal_name', x.get('channel'))}: {x.get('mercado_texto')} (cuota {x.get('cuota')}, tipo {x.get('mercado_tipo')})" for x in hit)


# ======================= ANALISIS =======================
def analyze(m, H, log_step=lambda *a: None):
    D = build_data(H)
    if "goals" not in D["present"]:
        raise RuntimeError("Historial insuficiente (menos de 3 partidos por equipo)")
    lines = pick_lines(D)
    log_step("Historial listo", "done", f"{len(H['home'])}/{len(H['away'])} partidos | mercados: {', '.join(D['present'])}")
    log_step(f"Calculando {len(MODELS)} modelos x cada mercado")
    results, names, failed = [], [], []
    for name, fn in MODELS:
        try:
            r = fn(D, lines, random.Random(f"{m['id']}|{name}"))
            if not r:
                raise ValueError("sin salida")
            results.append(r); names.append(name)
        except Exception as e:
            failed.append(name)
            log(f"MODELO FALLO {name}: {e!r}")
    log_step("Modelos listos", "done", f"{len(results)} ok" + (f", fallaron: {', '.join(failed)}" if failed else ""))
    if len(results) < 3:
        raise RuntimeError("Fallaron casi todos los modelos, revisa la consola")
    log_step("Consenso + value vs Bet365")
    fams, r1x2 = consensus(results, lines, D)
    odds = m.get("odds") or {}
    value = value_bets(r1x2, odds)
    log_step("Consenso listo", "done", f"{sum(len(f['rows']) for f in fams)} mercados, {len(value)} value bets")
    return {"fams": fams, "value": value, "averages": averages(D), "history": history_view(H), "odds": odds,
            "model_names": names, "failed_models": failed, "r1x2": r1x2}


def build_prompt(m, res, H):
    live = f"PARTIDO EN VIVO: marcador {m['hs']}-{m['as']}, minuto {m['clock']}." if m["state"] == "in" else ""
    odds = res["odds"]

    def form(side):
        return ", ".join(f"{x['r']} {x['s']} vs {x['opp']}" for x in res["history"][side][:5])
    avt = "\n".join(f"  {NOUN.get(f, f)}: {m['home']} {a['h_for']} a favor/{a['h_ag']} en contra; {m['away']} {a['a_for']} a favor/{a['a_ag']} en contra"
                    for f, a in res["averages"].items())
    lines = []
    for f in res["fams"]:
        for r in f["rows"]:
            outn = [res["model_names"][i] for i in r["outliers"]]
            lines.append(f"  {r['label']}: {r['clean_mean']}% (acuerdo {r['agree']}/{r['n']}, dispersion {r['sd']}" + (f", outliers descartados: {', '.join(outn)}" if outn else "") + ")")
    vtxt = "\n".join(f"  {v['mkt']}: modelo {v['p']}% vs implicita {v['impl']}% (cuota {v['cuota']}, edge {v['edge']}%)" for v in res["value"]) or "  (sin value bets o sin cuotas)"
    tg = telegram_picks(m["home"], m["away"])
    tgtxt = f"\nPICKS DE TIPSTERS EN TELEGRAM (hoy, via OCR):\n{tg}\nSi coinciden con el consenso sube la confianza; si van en contra, marcalo como divergencia.\n" if tg else ""
    r = res["r1x2"]
    x2 = f"1X2 consenso: local {_r1(r.get('home_win', 0))}% / empate {_r1(r.get('draw', 0))}% / visitante {_r1(r.get('away_win', 0))}%"
    return f"""Eres un analista de élite. NO inventes datos: usa SOLO lo de abajo. Partido: {m['home']} vs {m['away']} ({m['liga']}). {live}
Cuota Bet365 1X2: local {odds.get('dec_home', 'N/A')} / empate {odds.get('dec_draw', 'N/A')} / visitante {odds.get('dec_away', 'N/A')}. Total OU línea {odds.get('ou_line')}.
{x2}
Últimos {m['home']}: {form('home')}
Últimos {m['away']}: {form('away')}
Promedios reales por partido:
{avt}

TABLA DE CONSENSO ({len(res['model_names'])} modelos por mercado, ya con outliers filtrados):
{chr(10).join(lines)}

VALUE BETS detectados (edge modelo-implícita):
{vtxt}
{tgtxt}
TAREA en español, markdown, estilo informe de analista:
## RESUMEN (2-3 líneas)
## PICKS RECOMENDADAS
Lista con formato: **Mercado** → línea recomendada, probabilidad, cuota Bet365 si existe, y EDGE. Elige la línea intermedia más sólida cuando los modelos discrepan entre líneas altas y bajas. Máximo 8 picks, ordenadas por confianza.
## VALUE BETS
Solo los de edge>=5%, con cuota. Si no hay, di "sin ventaja clara contra Bet365".
## CONSENSO Y DIVERGENCIA
Por mercado clave (goles, btts, córners, tarjetas): di si los modelos coinciden o si hay guerra, y qué outliers descartaste.
## RIESGOS
Pocos datos, alineaciones no publicadas, partido en vivo, desviación alta.
## CONFIANZA
Alta/Media/Baja por mercado principal.
Cierra con: "Recuerda, ninguna apuesta está garantizada y todas implican riesgo."
Máximo 400 palabras."""


JOBS = {}
_LOCK = threading.Lock()


def run_job(jid, body):
    job = JOBS[jid]
    m = body["match"]

    def step(n, st="running", d=""):
        job["steps"].append({"name": n, "status": st, "detail": d})
        log(f"[{jid}] {n}: {st} {d}")
    try:
        step(f"Historial real ESPN ({N_HIST} partidos/equipo)")
        H = build_history(m)
        res = analyze(m, H, step)
        job.update({k: res[k] for k in ("fams", "value", "averages", "history", "odds", "model_names", "failed_models")})
        step(f"Ollama comparando modelo por modelo (1-3 min)")
        model = ensure_ollama(body.get("model") or "qwen2.5:7b")
        r = ollama_req("/api/chat", {"model": model, "stream": False, "options": {"temperature": 0.1, "num_ctx": 8192},
                                     "messages": [{"role": "user", "content": build_prompt(m, res, H)}]}, timeout=900)
        job["ollama_text"] = g(r, "message", "content", default="")
        job["ollama_model"] = model
        step("Ollama listo", "done")
        job["status"] = "done"
        safe = "".join(c for c in f"{m['home']}_vs_{m['away']}" if c.isalnum() or c in "_-")
        (BASE / "predictions" / f"{safe}_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        log("EXCEPCION:\n" + traceback.format_exc())
        job["error"] = str(e)
        job["status"] = "error"
        step("Error", "error", str(e))


def start_job(body):
    m = body["match"]
    with _LOCK:
        for jid, j in JOBS.items():
            if g(j, "match", "id") == m["id"] and (j["status"] == "running" or (j["status"] == "done" and not body.get("force"))):
                return jid
        jid = uuid.uuid4().hex[:8]
        JOBS[jid] = {"id": jid, "status": "running", "steps": [], "match": m}
        for old in list(JOBS)[:-30]:
            JOBS.pop(old, None)
    threading.Thread(target=run_job, args=(jid, body), daemon=True).start()
    return jid


# ======================= SERVIDOR =======================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def sj(self, d, c=200):
        b = json.dumps(d, ensure_ascii=False).encode("utf-8")
        self.send_response(c)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p == "/":
                ui = BASE / "ui.html"
                b = ui.read_bytes() if ui.exists() else "<h1>Falta ui.html junto a footballai_pro.py</h1>".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            elif p == "/api/matches":
                self.sj(fetch_today())
            elif p == "/api/models":
                self.sj([x["name"] for x in ollama_req("/api/tags").get("models", []) if "embed" not in x["name"]])
            elif p.startswith("/api/job/"):
                j = JOBS.get(p.split("/")[-1])
                self.sj(j if j else {"error": "no encontrado"}, 200 if j else 404)
            else:
                self.sj({"error": "404"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log("EXC GET:\n" + traceback.format_exc())
            try:
                self.sj({"error": "server"}, 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/analyze":
                self.sj({"job": start_job(body)})
            else:
                self.sj({"error": "404"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log("EXC POST:\n" + traceback.format_exc())
            try:
                self.sj({"error": "server"}, 500)
            except Exception:
                pass


def main(port=8888):
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        log(f"Puerto {port} en uso. Cierra el servidor viejo primero.")
        input("Enter para salir...")
        return
    log(f"Football AI Pro en http://127.0.0.1:{port} | {len(MODELS)} modelos | cierra esta ventana para detener")
    if not (BASE / "ui.html").exists():
        log("AVISO: no existe ui.html en esta carpeta")
    webbrowser.open(f"http://127.0.0.1:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("Detenido.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        input("Error fatal. Enter para cerrar...")
