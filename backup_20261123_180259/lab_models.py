"""lab_models.py - Laboratorio de modelos independientes (FootballAI)

train    : entrena 8 algoritmos por liga con los CSV de football-data y MIDE su acierto en partidos pasados
predict  : da la prediccion de un partido (cada modelo por separado + conjunto ponderado por acierto real)
informe  : muestra la tabla de acierto de todos los modelos
"""
import argparse, csv, difflib, json, math, os, sys, time, unicodedata, warnings
from datetime import datetime
from pathlib import Path
warnings.filterwarnings("ignore")
import numpy as np
import joblib
from sklearn.ensemble import (ExtraTreesClassifier, ExtraTreesRegressor, HistGradientBoostingClassifier,
                              HistGradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor)
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
try:
    from xgboost import XGBClassifier, XGBRegressor
except Exception:
    XGBClassifier = XGBRegressor = None
try:
    from lightgbm import LGBMClassifier, LGBMRegressor
except Exception:
    LGBMClassifier = LGBMRegressor = None

ROOT = Path(os.environ.get("FOOTBALLAI_PRO", r"C:\FootballAI\Pro"))
DATA, LAB = ROOT / "data", ROOT / "lab"
LAB.mkdir(parents=True, exist_ok=True)
EURO = ["E0", "E1", "SP1", "I1", "D1", "F1", "N1", "P1", "T1"]
NEW = ["ARG", "AUT", "BRA", "CHN", "DNK", "FIN", "IRL", "JPN", "MEX", "NOR", "POL", "ROU", "RUS", "SWE", "SWZ", "USA"]
SLUG = {"eng.1": "E0", "eng.2": "E1", "esp.1": "SP1", "ita.1": "I1", "ger.1": "D1", "fra.1": "F1", "ned.1": "N1",
        "por.1": "P1", "bra.1": "BRA", "arg.1": "ARG", "mex.1": "MEX", "usa.1": "USA"}
ODDS = [("AvgH", "AvgD", "AvgA"), ("PSH", "PSD", "PSA"), ("PH", "PD", "PA"), ("B365H", "B365D", "B365A"),
        ("MaxH", "MaxD", "MaxA"),
        ("AvgCH", "AvgCD", "AvgCA"), ("PSCH", "PSCD", "PSCA"), ("B365CH", "B365CD", "B365CA"), ("MaxCH", "MaxCD", "MaxCA")]
STATS = {"corners": ("HC", "AC"), "cards": ("HY", "AY"), "fouls": ("HF", "AF"), "shots": ("HS", "AS"),
         "sot": ("HST", "AST")}
STAT_LABEL = {"corners": "córners", "cards": "tarjetas", "fouls": "faltas", "shots": "remates", "sot": "tiros al arco"}
GOAL_T = {"o15": ("Goles", 1.5), "o25": ("Goles", 2.5), "o35": ("Goles", 3.5), "btts": ("Ambos marcan", None)}
N_HIST, MIN_HIST = 8, 3
FAST = False


# ------------------------------------------------------------------ datos
def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None


def pdate(s):
    for f in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime((s or "").strip(), f)
        except Exception:
            pass
    return None


def first(r, *keys):
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return None


def league_files(code):
    if code in NEW:
        return [DATA / f"fd_new_{code}.csv"]
    return sorted(set(DATA.glob(f"fd_{code}.csv")) | set(DATA.glob(f"fd_{code}_*.csv")))


def load_league(code):
    rows = []
    for f in league_files(code):
        if not f.exists():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8-sig", errors="replace")):
            h, a = first(r, "HomeTeam", "Home"), first(r, "AwayTeam", "Away")
            hg, ag = fnum(first(r, "FTHG", "HG")), fnum(first(r, "FTAG", "AG"))
            d = pdate(first(r, "Date") or "")
            if not (h and a and d and hg is not None and ag is not None):
                continue
            odds = None
            for ks in ODDS:
                v = [fnum(r.get(k)) for k in ks]
                if all(x and x > 1 for x in v):
                    odds = v
                    break
            st = {}
            for k, (ca, cb) in STATS.items():
                x, y = fnum(r.get(ca)), fnum(r.get(cb))
                if x is not None and y is not None:
                    st[k] = (x, y)
            rows.append({"d": d, "h": h.strip(), "a": a.strip(), "hg": hg, "ag": ag, "odds": odds, "st": st})
    rows.sort(key=lambda r: r["d"])
    return rows


# ------------------------------------------------------------------ features
def mean(v):
    return sum(v) / len(v) if v else 0.0


def new_team():
    return {"elo": 1500.0, "hist": []}


def side_feats(t):
    h = t["hist"][-N_HIST:]
    return [t["elo"], mean([x["gf"] for x in h]), mean([x["ga"] for x in h]), mean([x["pts"] for x in h]),
            mean([1.0 if x["gf"] + x["ga"] > 2.5 else 0.0 for x in h]),
            mean([1.0 if x["gf"] > 0 and x["ga"] > 0 else 0.0 for x in h])]


def goal_vec(th, ta, lg):
    fh, fa = side_feats(th), side_feats(ta)
    lg = max(lg, 0.3)
    return fh + fa + [fh[0] - fa[0], lg, fh[1] * fa[2] / lg, fa[1] * fh[2] / lg]


def stat_vec(th, ta, k, lgm):
    def mf(t, i):
        v = [x["st"][k][i] for x in t["hist"][-N_HIST:] if k in x["st"]]
        return mean(v), len(v)
    (hf, n1), (ha, n2), (af, n3), (aa, n4) = mf(th, 0), mf(th, 1), mf(ta, 0), mf(ta, 1)
    if min(n1, n2, n3, n4) < MIN_HIST:
        return None
    return [hf, ha, af, aa, (hf + aa) / 2, (af + ha) / 2, lgm, th["elo"] - ta["elo"]]


def elo_update(th, ta, hg, ag):
    exp_h = 1 / (1 + 10 ** (-(th["elo"] + 60 - ta["elo"]) / 400))
    res = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
    d = 20 * (1 + math.log(abs(hg - ag) + 1)) * (res - exp_h)
    th["elo"] += d
    ta["elo"] -= d


def build(rows):
    teams, G, C = {}, [], {k: [] for k in STATS}
    lg_n, lg_s = 0, 0.0
    lgst = {k: [0, 0.0] for k in STATS}
    for r in rows:
        th, ta = teams.setdefault(r["h"], new_team()), teams.setdefault(r["a"], new_team())
        lg = lg_s / lg_n if lg_n > 20 else 2.6
        if len(th["hist"]) >= MIN_HIST and len(ta["hist"]) >= MIN_HIST:
            G.append({"x": goal_vec(th, ta, lg), "hg": r["hg"], "ag": r["ag"], "odds": r["odds"]})
        for k in STATS:
            if k in r["st"] and lgst[k][0] > 20:
                v = stat_vec(th, ta, k, lgst[k][1] / lgst[k][0])
                if v:
                    C[k].append({"x": v, "y": sum(r["st"][k])})
        hp = 3 if r["hg"] > r["ag"] else 1 if r["hg"] == r["ag"] else 0
        ap = 3 if r["ag"] > r["hg"] else 1 if r["hg"] == r["ag"] else 0
        elo_update(th, ta, r["hg"], r["ag"])
        sh = {k: v for k, v in r["st"].items()}
        th["hist"].append({"gf": r["hg"], "ga": r["ag"], "pts": hp, "st": sh})
        ta["hist"].append({"gf": r["ag"], "ga": r["hg"], "pts": ap, "st": {k: (v[1], v[0]) for k, v in sh.items()}})
        th["hist"], ta["hist"] = th["hist"][-N_HIST:], ta["hist"][-N_HIST:]
        lg_n += 1
        lg_s += r["hg"] + r["ag"]
        for k in r["st"]:
            lgst[k][0] += 1
            lgst[k][1] += sum(r["st"][k])
    state = {"teams": teams, "lg": lg_s / lg_n if lg_n else 2.6,
             "lgm": {k: (v[1] / v[0] if v[0] else None) for k, v in lgst.items()}}
    return G, C, state


# ------------------------------------------------------------------ modelos
def cls_models():
    n = 60 if FAST else 150
    m = {"Regresion_Logistica": make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500)),
         "Random_Forest": RandomForestClassifier(n, max_depth=7, min_samples_leaf=15, n_jobs=-1, random_state=7),
         "Extra_Trees": ExtraTreesClassifier(n, max_depth=8, min_samples_leaf=15, n_jobs=-1, random_state=7),
         "Gradient_Boosting": HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=n, random_state=7)}
    if XGBClassifier:
        m["XGBoost"] = XGBClassifier(n_estimators=n, max_depth=3, learning_rate=0.05, subsample=0.8,
                                     colsample_bytree=0.8, n_jobs=2, verbosity=0)
    if LGBMClassifier:
        m["LightGBM"] = LGBMClassifier(n_estimators=n, num_leaves=8, learning_rate=0.05, min_child_samples=20,
                                       subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, n_jobs=2)
    if not FAST:
        m["KNN"] = make_pipeline(StandardScaler(), KNeighborsClassifier(40, weights="distance"))
        m["Red_Neuronal_MLP"] = make_pipeline(StandardScaler(), MLPClassifier((32, 16), alpha=0.01, max_iter=300,
                                                                             early_stopping=True, random_state=7))
    return m


def reg_models():
    n = 60 if FAST else 150
    m = {"Ridge": make_pipeline(StandardScaler(), Ridge(alpha=5.0)),
         "Random_Forest": RandomForestRegressor(n, max_depth=6, min_samples_leaf=15, n_jobs=-1, random_state=7),
         "Extra_Trees": ExtraTreesRegressor(n, max_depth=7, min_samples_leaf=15, n_jobs=-1, random_state=7),
         "Gradient_Boosting": HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=n, random_state=7)}
    if XGBRegressor:
        m["XGBoost"] = XGBRegressor(n_estimators=n, max_depth=3, learning_rate=0.05, subsample=0.8,
                                    colsample_bytree=0.8, n_jobs=2, verbosity=0)
    if LGBMRegressor:
        m["LightGBM"] = LGBMRegressor(n_estimators=n, num_leaves=8, learning_rate=0.05, min_child_samples=20,
                                      subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, n_jobs=2)
    return m


def proba(m, X):
    return np.clip(m.predict_proba(X)[:, 1], 0.02, 0.98)


def norm_weights(skills):
    w = {k: max(v, 0.0) for k, v in skills.items()}
    s = sum(w.values())
    return {k: v / s for k, v in w.items()} if s > 0 else {k: 0.0 for k in w}


def train_cls(X, y, odds_p=None):
    """devuelve (modelos_finales, pesos, filas_informe, base, skill_conjunto)"""
    k = int(len(X) * 0.8)
    Xtr, Xte, ytr, yte = X[:k], X[k:], y[:k], y[k:]
    base = float(ytr.mean())
    b0 = float(np.mean((base - yte) ** 2))
    rows, skills, tp = [], {}, {}
    for name, m in cls_models().items():
        try:
            m.fit(Xtr, ytr)
            p = proba(m, Xte)
        except Exception as e:
            print(f"      ! {name}: {e!r}")
            continue
        br = float(np.mean((p - yte) ** 2))
        skills[name] = 1 - br / b0
        tp[name] = p
        rows.append({"modelo": name, "n_test": len(yte), "brier": round(br, 4), "base": round(b0, 4),
                     "skill": round(skills[name], 4), "acierto": round(float(np.mean((p > 0.5) == yte)), 4)})
    if odds_p is not None:
        op = odds_p[k:]
        ok = ~np.isnan(op)
        if ok.sum() > 50:
            br = float(np.mean((op[ok] - yte[ok]) ** 2))
            b0o = float(np.mean((base - yte[ok]) ** 2))
            rows.append({"modelo": "MERCADO(cuotas)", "n_test": int(ok.sum()), "brier": round(br, 4),
                         "base": round(b0o, 4), "skill": round(1 - br / b0o, 4),
                         "acierto": round(float(np.mean((op[ok] > 0.5) == yte[ok])), 4)})
    w = norm_weights(skills)
    ens_skill = 0.0
    if sum(w.values()) > 0:
        pe = sum(w[n] * tp[n] for n in w)
        ens_skill = 1 - float(np.mean((pe - yte) ** 2)) / b0
    rows.append({"modelo": "CONJUNTO", "n_test": len(yte), "brier": "", "base": round(b0, 4),
                 "skill": round(ens_skill, 4), "acierto": ""})
    final = {}
    for name, m in cls_models().items():
        if name in skills:
            m.fit(X, y)
            final[name] = m
    return final, w, rows, base, ens_skill


def train_reg(X, y):
    k = int(len(X) * 0.8)
    Xtr, Xte, ytr, yte = X[:k], X[k:], y[:k], y[k:]
    mae0 = float(np.mean(np.abs(ytr.mean() - yte)))
    rows, skills, tp = [], {}, {}
    for name, m in reg_models().items():
        try:
            m.fit(Xtr, ytr)
            p = m.predict(Xte)
        except Exception as e:
            print(f"      ! {name}: {e!r}")
            continue
        mae = float(np.mean(np.abs(p - yte)))
        skills[name] = 1 - mae / mae0
        tp[name] = p
        rows.append({"modelo": name, "n_test": len(yte), "brier": round(mae, 3), "base": round(mae0, 3),
                     "skill": round(skills[name], 4), "acierto": ""})
    w = norm_weights(skills)
    mu_te = sum(w[n] * tp[n] for n in w) if sum(w.values()) > 0 else np.full(len(yte), ytr.mean())
    var_res = float(np.var(yte - mu_te))
    ens_skill = 1 - float(np.mean(np.abs(yte - mu_te))) / mae0
    rows.append({"modelo": "CONJUNTO", "n_test": len(yte), "brier": round(float(np.mean(np.abs(yte - mu_te))), 3),
                 "base": round(mae0, 3), "skill": round(ens_skill, 4), "acierto": ""})
    final = {}
    for name, m in reg_models().items():
        if name in skills:
            m.fit(X, y)
            final[name] = m
    return final, w, rows, float(y.mean()), var_res, ens_skill


def train_league(code):
    t0 = time.time()
    rows = load_league(code)
    if len(rows) < 300:
        print(f"[{code}] solo {len(rows)} partidos, se omite")
        return []
    G, C, state = build(rows)
    if len(G) < 250:
        print(f"[{code}] historial insuficiente, se omite")
        return []
    print(f"[{code}] {len(rows)} partidos, {len(G)} usables para entrenar")
    X = np.array([g["x"] for g in G], dtype=float)
    hg = np.array([g["hg"] for g in G])
    ag = np.array([g["ag"] for g in G])
    tg = {"o15": (hg + ag > 1.5), "o25": (hg + ag > 2.5), "o35": (hg + ag > 3.5), "btts": (hg > 0) & (ag > 0),
          "H": hg > ag, "D": hg == ag, "A": hg < ag}
    om = np.full((len(G), 3), np.nan)
    for i, g in enumerate(G):
        if g["odds"]:
            inv = [1 / o for o in g["odds"]]
            om[i] = [v / sum(inv) for v in inv]
    bundle = {"code": code, "state": state, "cls": {}, "reg": {}, "trained": datetime.now().isoformat(timespec="minutes"),
              "n": len(G)}
    report = []
    for tname, y in tg.items():
        y = y.astype(int)
        if y.min() == y.max():
            continue
        op = om[:, {"H": 0, "D": 1, "A": 2}[tname]] if tname in ("H", "D", "A") else None
        models, w, rep, base, es = train_cls(X, y, op)
        bundle["cls"][tname] = {"models": models, "w": w, "base": base, "skill": es}
        for r in rep:
            report.append({"liga": code, "mercado": tname, **r})
        best = max([r for r in rep if r["modelo"] not in ("CONJUNTO", "MERCADO(cuotas)")], key=lambda r: r["skill"])
        print(f"   {tname:5} mejor modelo: {best['modelo']:<20} skill {best['skill']:+.3f} | conjunto {es:+.3f}")
    for k, lst in C.items():
        if len(lst) < 300:
            continue
        Xs = np.array([c["x"] for c in lst], dtype=float)
        ys = np.array([c["y"] for c in lst], dtype=float)
        models, w, rep, base, var_res, es = train_reg(Xs, ys)
        bundle["reg"][k] = {"models": models, "w": w, "base": base, "var": var_res, "skill": es}
        for r in rep:
            report.append({"liga": code, "mercado": k, **r})
        print(f"   {k:7} conjunto skill {es:+.3f} (media {base:.1f}, n={len(lst)})")
    joblib.dump(bundle, LAB / f"{code}.joblib", compress=3)
    with open(LAB / f"informe_{code}.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["liga", "mercado", "modelo", "n_test", "brier", "base", "skill", "acierto"])
        wr.writeheader()
        wr.writerows(report)
    print(f"[{code}] listo en {time.time() - t0:.0f}s")
    return report


# ------------------------------------------------------------------ prediccion
def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    for w in (" fc", " cf", " sc", " fk", " club", " de ", " cd", " ac"):
        s = s.replace(w, " ")
    return " ".join(s.replace(".", " ").replace("-", " ").split())


def resolve(names, query):
    nq = norm(query)
    idx = {norm(n): n for n in names}
    if nq in idx:
        return idx[nq]
    for k, v in idx.items():
        if nq in k or k in nq:
            return v
    m = difflib.get_close_matches(nq, list(idx), 1, 0.55)
    if m:
        return idx[m[0]]
    raise ValueError(f"No encuentro '{query}'. Equipos parecidos: {difflib.get_close_matches(nq, list(idx), 5, 0.3)}")


def p_over(mu, var, line):
    k, mu = int(math.floor(line)), max(mu, 0.05)
    if var > mu * 1.02:
        r = min(max(mu * mu / (var - mu), 2.0), 200.0)
        p = r / (r + mu)
        cdf = sum(math.exp(math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1)) * p ** r * (1 - p) ** i
                  for i in range(k + 1))
    else:
        cdf = sum(math.exp(-mu) * mu ** i / math.factorial(i) for i in range(k + 1))
    return min(max(1 - cdf, 0.001), 0.999)


def market(group, line, unit, probs, w, base, skill, yes_no=False):
    pe = sum(w.get(n, 0) * p for n, p in probs.items()) if sum(w.values()) > 0 else base
    over = pe >= 0.5
    agree = sum(1 for p in probs.values() if (p >= 0.5) == over)
    pick_p = pe if over else 1 - pe
    q = min(1.0, 0.3 + 6 * max(skill, 0))
    conf = round(100 * (0.5 * abs(pe - 0.5) * 2 + 0.5 * agree / max(len(probs), 1)) * q)
    pick = ("Si" if over else "No") if yes_no else ("Mas" if over else "Menos")
    label = f"Ambos marcan: {pick}" if yes_no else f"{pick} {line} {unit}"
    return {"group": group, "line": line, "label": label, "pick": pick, "pick_p": round(pick_p, 3),
            "p_over": round(pe, 3), "agree": f"{agree}/{len(probs)}", "conf": conf, "skill": round(skill, 3),
            "models": {n: round(float(p), 3) for n, p in probs.items()}}


def predict(code, home, away):
    f = LAB / f"{code}.joblib"
    if not f.exists():
        raise FileNotFoundError(f"No hay modelos entrenados para {code}. Ejecuta: python lab_models.py train --ligas {code}")
    b = joblib.load(f)
    teams = b["state"]["teams"]
    h, a = resolve(list(teams), home), resolve(list(teams), away)
    th, ta = teams[h], teams[a]
    out = {"liga": code, "home": h, "away": a, "entrenado": b["trained"], "markets": [], "players": []}
    xg = np.array([goal_vec(th, ta, b["state"]["lg"])], dtype=float)
    for t, (grp, line) in GOAL_T.items():
        c = b["cls"].get(t)
        if not c:
            continue
        probs = {n: float(proba(m, xg)[0]) for n, m in c["models"].items()}
        out["markets"].append(market(grp, line, "goles", probs, c["w"], c["base"], c["skill"], yes_no=(t == "btts")))
    for k, c in b["reg"].items():
        lgm = b["state"]["lgm"].get(k)
        v = stat_vec(th, ta, k, lgm) if lgm else None
        if not v:
            continue
        xs = np.array([v], dtype=float)
        mus = {n: float(m.predict(xs)[0]) for n, m in c["models"].items()}
        mu = sum(c["w"][n] * mus[n] for n in mus) if sum(c["w"].values()) > 0 else c["base"]
        out.setdefault("esperado", {})[k] = round(mu, 2)
        base_line = math.floor(mu) + 0.5
        for line in [base_line + d for d in (-2, -1, 0, 1, 2)]:
            if line < 0.5:
                continue
            probs = {n: p_over(m_, c["var"], line) for n, m_ in mus.items()}
            out["markets"].append(market(STAT_LABEL[k].capitalize(), line, STAT_LABEL[k], probs,
                                         c["w"], p_over(mu, c["var"], line), c["skill"]))
    out["top"] = sorted([m for m in out["markets"] if m["pick_p"] >= 0.6], key=lambda m: -m["conf"])[:10]
    return out


def show(r):
    print(f"\n{r['home']}  vs  {r['away']}   [{r['liga']}]   modelos entrenados: {r['entrenado']}")
    if r.get("esperado"):
        print("Esperado:", ", ".join(f"{STAT_LABEL[k]} {v}" for k, v in r["esperado"].items()))
    print("\nMEJORES PRONOSTICOS (prob >= 60%, ordenados por confianza):")
    for m in r["top"] or []:
        print(f"  {m['label']:<28} {m['pick_p']*100:5.1f}%  acuerdo {m['agree']:>5}  confianza {m['conf']:>3}%  (acierto medido: {m['skill']:+.3f})")
    if not r["top"]:
        print("  (ningun mercado supera 60%)")
    print("\nTODOS LOS MERCADOS:")
    for m in r["markets"]:
        print(f"  {m['label']:<28} {m['pick_p']*100:5.1f}%  {m['agree']:>5}  conf {m['conf']:>3}%")


def informe():
    rows = []
    for f in sorted(LAB.glob("informe_*.csv")):
        rows += list(csv.DictReader(open(f, encoding="utf-8")))
    if not rows:
        print("Aun no hay informes. Ejecuta train.")
        return
    print(f"{'liga':5} {'mercado':8} {'mejor modelo':<20} {'skill':>7} {'conjunto':>9} {'mercado(cuotas)':>16}")
    for lg in sorted({r["liga"] for r in rows}):
        for mk in dict.fromkeys(r["mercado"] for r in rows if r["liga"] == lg):
            sel = [r for r in rows if r["liga"] == lg and r["mercado"] == mk]
            ind = [r for r in sel if r["modelo"] not in ("CONJUNTO", "MERCADO(cuotas)")]
            if not ind:
                continue
            best = max(ind, key=lambda r: float(r["skill"]))
            ens = next((r["skill"] for r in sel if r["modelo"] == "CONJUNTO"), "")
            mkt = next((r["skill"] for r in sel if r["modelo"] == "MERCADO(cuotas)"), "")
            print(f"{lg:5} {mk:8} {best['modelo']:<20} {float(best['skill']):+7.3f} {float(ens):+9.3f} {mkt:>16}")
    print("\nskill > 0 = mejor que adivinar con la frecuencia historica. Cerca de 0 = sin ventaja real.")


def main():
    global FAST
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "predict", "informe", "ligas"])
    ap.add_argument("--ligas", default="")
    ap.add_argument("--rapido", action="store_true")
    ap.add_argument("--liga", default="")
    ap.add_argument("--slug", default="")
    ap.add_argument("--home", default="")
    ap.add_argument("--away", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    FAST = a.rapido
    if a.cmd == "ligas":
        for c in EURO + NEW:
            print(c, "OK" if (LAB / f"{c}.joblib").exists() else "-", len(league_files(c)), "archivo(s)")
    elif a.cmd == "train":
        codes = [c.strip().upper() for c in a.ligas.split(",") if c.strip()] or EURO + NEW
        t0 = time.time()
        for c in codes:
            try:
                train_league(c)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[{c}] ERROR: {e!r}")
        print(f"\nEntrenamiento terminado en {(time.time() - t0) / 60:.1f} min. Ver tabla: python lab_models.py informe")
    elif a.cmd == "predict":
        code = a.liga.upper() or SLUG.get(a.slug, "")
        r = predict(code, a.home, a.away)
        print(json.dumps(r, ensure_ascii=False, indent=2)) if a.json else show(r)
    else:
        informe()


if __name__ == "__main__":
    main()
