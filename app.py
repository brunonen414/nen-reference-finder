#!/usr/bin/env python3
"""Nen — Reference Finder (deployable). Flask app, password-protected.
Self-contained: reads ./data (JSON) and ./frames (pre-exported JPEGs). No AI deps.
Local:  python app.py   |   Prod: gunicorn app:app   (set APP_PASSWORD env var)
"""
import glob, io, json, os, re
from functools import wraps
from flask import Flask, request, jsonify, send_file, send_from_directory, Response
try:
    from PIL import Image
except Exception:
    Image = None

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); DBV = os.path.join(DATA, "videos"); NOV = os.path.join(DATA, "novella")
FRAMES = os.path.join(HERE, "frames"); IMGS = os.path.join(HERE, "imgs")
PASSWORD = os.environ.get("APP_PASSWORD", "nen")   # set this in the host dashboard

P = json.load(open(os.path.join(DATA, "profiles.json"), encoding="utf-8"))
VIDS = P["videos"]; BYID = {v["id"]: v for v in VIDS}
VIBE_VOCAB = sorted({x.lower() for v in VIDS for x in v.get("vibe", [])})
BRAND_STOP = {"please","context","town","humble","metal","variant","reflex","highlight",
              "console","lotus","profound","operand","conversion","paradigm","rox","pylon",
              "cora","edra","matic","coris","aleph","otim","rogo","tilde"}
URL_MAP = {}
for mp in glob.glob(os.path.join(DBV, "*", "meta.json")):
    m = json.load(open(mp, encoding="utf-8")); s = m.get("sheet", {})
    URL_MAP[m.get("video_id")] = s.get("url") or s.get("x_url") or s.get("linkedin_url") or ""
URL_MAP["novella"] = "https://x.com/maxekane/status/2054909691210178968"
EXCLUDE = {"paraform"}  # videos NOT produced by Nen — never show as references/hooks

GOAL_ARCH = {"awareness": ["Cinematic Narrative","Kinetic / Motion-Graphics","Skit-Hybrid"],
             "leads": ["UI-Walkthrough Demo","Testimonial / Customer-Proof"],
             "thought": ["Founder / Talking-Head Explainer","Cinematic Narrative"]}
ANNOUNCE_HAS = {"funding": "funding", "product": "demo", "feature": "demo"}

def parse_brief(text):
    t = text or ""; tl = t.lower()
    vibe = [w for w in VIBE_VOCAB if re.search(r"\b" + re.escape(w) + r"\b", tl)]
    goals = [g for g in ["awareness","leads","thought leadership","brand","conversions","demand"] if g in tl]
    if re.search(r"\b(raised|raising|funding|seed|series\s?[a-d]|\$\s?\d|million|\bround\b)\b", tl): announce = "funding"
    elif re.search(r"\b(launch|launching|introducing|announcing|unveil|new product)\b", tl): announce = "product"
    elif re.search(r"\b(feature|new capability|update)\b", tl): announce = "feature"
    else: announce = ""
    if re.search(r"\b(motion|animation|animated|kinetic|graphics|\bui\b|on-?screen)\b", tl): motion = "heavy"
    elif re.search(r"\b(minimal|simple|clean|no motion|talking head)\b", tl): motion = "minimal"
    else: motion = None
    brands = []
    for v in VIDS:
        prim = re.split(r"[ (]", v["brand"])[0]
        if prim.lower() in BRAND_STOP or len(prim) < 4: continue
        if re.search(r"\b" + re.escape(prim) + r"\b", t, re.I): brands.append(v["brand"])
    brands = list(dict.fromkeys(brands))
    return ({"product": t, "audience": "", "vibe": vibe, "goals": " ".join(goals),
             "motion": motion, "announce": announce, "example_brands": brands},
            {"vibe": vibe, "goals": goals, "announce": announce, "motion": motion, "refs": brands})

def score(v, b):
    s = 0.0; why = []
    ov = set(x.lower() for x in v["vibe"]) & set(x.lower() for x in b.get("vibe", []))
    if ov: s += 3 * len(ov); why.append("vibe " + "/".join(sorted(ov)))
    vert = (v.get("vertical", "") or "").lower()
    for tok in re.findall(r"[a-z]+", (b.get("product", "") + " " + b.get("audience", "")).lower()):
        if len(tok) > 3 and tok in vert: s += 2; why.append(f"vertical ≈ {tok}"); break
    if b.get("motion") and v["motion_level"] == b.get("motion"): s += 2; why.append("motion match")
    for g, arch in GOAL_ARCH.items():
        if g in (b.get("goals", "") or "").lower() and v["broad"] in arch: s += 2; why.append(g)
    if ANNOUNCE_HAS.get(b.get("announce", "")) in v.get("has", []): s += 2; why.append(b.get("announce", ""))
    if b.get("preferred_arch") and v["broad"] == b["preferred_arch"]: s += 4; why.append("chosen type")
    if v["brand"] in (b.get("example_brands") or []): s += 6; why.append(f"they liked {v['brand']}")
    return s, [w for w in why if w]

def pick_directions(b, n=4):
    scored = sorted(((score(v, b), v) for v in VIDS if v["id"] not in EXCLUDE), key=lambda x: -x[0][0])
    picked, used = [], {}
    for (s, why), v in scored:
        if used.get(v["broad"], 0) >= 1 and len(picked) < n: continue
        picked.append((v, s, why)); used[v["broad"]] = used.get(v["broad"], 0) + 1
        if len(picked) >= n: break
    if len(picked) < n:
        for (s, why), v in scored:
            if v["id"] not in [p[0]["id"] for p in picked]: picked.append((v, s, why))
            if len(picked) >= n: break
    return picked

def video_dir(vid): return NOV if vid == "novella" else os.path.join(DBV, vid)
def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def fmt(s): m = divmod(int(s), 60); return f"{m[0]}:{m[1]:02d}"

_SEG = {}
def segs_of(vid):
    if vid not in _SEG:
        try: _SEG[vid] = json.load(open(os.path.join(video_dir(vid), "segments.json"), encoding="utf-8"))
        except Exception: _SEG[vid] = []
    return _SEG[vid]

TALK_ARCH = {"Founder / Talking-Head Explainer", "UI-Walkthrough Demo",
             "Testimonial / Customer-Proof", "Kinetic / Motion-Graphics"}
HOOK_CATS = [
 ("raise", "The Raise", "Opens on the funding number itself — “We raised $X…”. Instant credibility and stakes; the fastest scroll-stopper for a launch."),
 ("stat", "Shock Stat", "Leads with a surprising fact or figure (not the raise) that reframes the problem as bigger than the viewer assumed."),
 ("thesis", "Provocative Thesis", "A bold, debatable claim that challenges a belief — it earns attention precisely because it's arguable."),
 ("problem", "Problem-First", "Drops you straight into the pain the audience feels every day; the product then arrives as the relief."),
 ("curiosity", "Curiosity / Question", "Opens a loop — a question or piece of intrigue the viewer needs resolved, pulling them into the next line."),
 ("scene", "Scene / Skit-Style Cold-Open", "Opens on a staged moment, a line of in-scene dialogue, or a playful blooper before the real message — disarms and entertains, then pivots."),
 ("intro", "Direct Introduction", "Warm, human open — “Hi, I'm…” / “Meet…” / “Introducing…”. Works when the founder or product name already carries trust."),
 ("mission", "Mission / Vision", "An aspirational opener that sets the stakes high — best when the brand story matters more than any single feature."),
]
HOOK_OVERRIDE = {
 "li-7361808564790677506": "stat", "li-7384588798766026752": "problem",
 "li-7316127925580300290": "problem", "li-7389300003623833601": "intro",
 "naren-loan": "scene", "x-browserbase-288502": "scene", "post-7465436843": "intro",
 "li-7463268474828591104": "problem", "li-7453129372389003264": "scene",
 "x-josephsemrai-551986": "stat", "x-neiltewari-088657": "scene", "x-neiltewari-671960": "problem",
 "li-7379542048447791104": "problem", "x-ryanjdaniels-571641": "scene", "li-7381736552110063616": "intro",
 "lassie": "scene", "lassie-story": "scene", "x-mercor_ai-536653": "mission",
 "nooks": "stat", "nooks-sdr": "problem", "paraform": "scene",
 "li-7444776027047784448": "scene", "li-7399492221072371712": "problem", "li-7386793491064008704": "scene",
 "x-emkara-217696": "scene", "li-7323365246096633856": "scene", "x-a_reichenbach_-789013": "problem",
 "x-tilderesearch-131334": "curiosity", "x-jgreze-548549": "scene", "x-rronak_-730624": "intro",
 "li-7444773752418025472": "problem", "x-bnj-095039": "scene", "melisatokmak": "problem", "crosby": "scene",
}
def classify_hook(t):
    tl = (t or "").lower().strip()
    if (re.search(r"\b(raised?|raising|bet|backed)\b", tl) and re.search(r"\$|\bmillion\b|\bbillion\b|\bseries\b|\bseed\b|\bm\b", tl)) or re.search(r"\$\s?\d", tl): return "raise"
    if tl.endswith("?") or re.search(r"\bwhat if\b|\bimagine\b|sounds crazy|did you know|ever (wonder|notice)|can you tell", tl): return "curiosity"
    if re.search(r"\d", tl) and re.search(r"%|percent|americans|fortune 500|\bbillion\b|\bmillions?\b", tl): return "stat"
    if re.search(r"\b(drowning|manual|burn(t|ed)? out|burnout|struggl|wasted?|too much|bottleneck|painful|tedious|broken|fails?|chasing|bogged|slow|outdated|nightmare|mess)\b", tl): return "problem"
    if re.search(r"^(hi|hey|hello|i'?m |we'?re |meet |introducing|this is |today,? (we|i))", tl): return "intro"
    if re.search(r"\b(we believe|our mission|on a mission|the future|world where|should never|every (company|person|business|producer|marketer))\b", tl): return "mission"
    return "thesis"

def build_hooks():
    cats = {k: [] for k, _, _ in HOOK_CATS}
    for v in VIDS:
        if v["id"] in EXCLUDE or v["broad"] not in TALK_ARCH: continue
        segs = segs_of(v["id"])
        if not segs: continue
        s0 = segs[0]; txt = (s0.get("text") or "").strip()
        if len(txt) < 30 and len(segs) > 1: txt = (txt + " " + segs[1]["text"]).strip()
        if len(txt) < 16 or len(txt.split()) < 3: continue
        cat = HOOK_OVERRIDE.get(v["id"]) or classify_hook(txt)
        cats.setdefault(cat, []).append({"brand": v["brand"], "vid": v["id"], "text": txt[:200],
                                         "sec": int((s0["start"] + s0["end"]) / 2)})
    return cats
HOOKS = build_hooks()

# ---- NEN IMAGE SEARCH index (frames understood via script + CLIP tags + OCR) ----
IMG_STOP = {"the","a","an","to","of","and","for","with","our","we","is","in","on","that","this","it",
            "i","you","they","he","she","at","be","are","was","as","or","but","so","if","my","your",
            "me","us","do","does","can","will","just","not","no","yes","from","by","up","out","about",
            "what","who","when","how","there","here","im","its","re","ve","s","t"}
def _toks(s):
    return [w for w in re.findall(r"[a-z0-9$%.]+", (s or "").lower())
            if w not in IMG_STOP and len(w) > 1]
try:
    IMG_INDEX = json.load(open(os.path.join(DATA, "image_index.json"), encoding="utf-8"))
except Exception:
    IMG_INDEX = []
for e in IMG_INDEX:
    tg = " ".join(e.get("tags", []))
    e["_line"] = set(_toks(e.get("line", "")) + _toks(e.get("ctx", "")))
    e["_ocr"]  = set(_toks(e.get("ocr", "")))
    e["_tags"] = set(_toks(tg))
    e["_meta"] = set(_toks(e.get("brand", "")) + _toks(e.get("arch", "")))
    e["_blob"] = (e.get("line","") + " " + e.get("ocr","") + " " + tg).lower()

def image_search(q, k=15):
    qt = _toks(q); qs = set(qt); ql = (q or "").lower().strip()
    if not qs: return []
    scored = []
    for e in IMG_INDEX:
        sc = 3.0*len(qs & e["_line"]) + 3.2*len(qs & e["_ocr"]) + 2.2*len(qs & e["_tags"]) + 1.0*len(qs & e["_meta"])
        if sc == 0: continue
        if len(ql) >= 5 and ql in e["_blob"]: sc += 6        # exact phrase bonus
        scored.append((sc, e))
    scored.sort(key=lambda x: -x[0])
    out, per = [], {}
    for sc, e in scored:
        if per.get(e["vid"], 0) >= 3: continue              # diversity across videos
        per[e["vid"]] = per.get(e["vid"], 0) + 1
        out.append({"id": e["id"], "vid": e["vid"], "brand": e["brand"], "arch": e.get("arch",""),
                    "sec": e["sec"], "t": fmt(e["sec"]), "line": e.get("line",""),
                    "tags": e.get("tags", [])[:3], "score": round(sc,1)})
        if len(out) >= k: break
    return out

app = Flask(__name__)

# (no auth — unlisted: anyone with the URL can access. Don't share the link publicly.)

@app.route("/")
def index(): return send_from_directory(HERE, "index.html")
@app.route("/style.css")
def style(): return send_from_directory(HERE, "style.css")
@app.route("/fonts/<path:fn>")
def fonts(fn): return send_from_directory(os.path.join(HERE, "fonts"), fn)

@app.route("/frame")
def frame():
    vid = request.args.get("vid", ""); sec = request.args.get("sec", "0")
    fn = f"{vid}__{int(sec)}.jpg" if sec.lstrip("-").isdigit() else None
    p = os.path.join(FRAMES, fn) if fn else None
    if not p or not os.path.abspath(p).startswith(os.path.abspath(FRAMES)) or not os.path.exists(p):
        return ("not found", 404)
    return send_file(p, mimetype="image/jpeg")

@app.route("/img")
def img():
    """Serve an HD master frame by id (vid__sec). Optional ?w= downscales for thumbnails."""
    fid = request.args.get("id", "")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+__-?\d+", fid or ""): return ("bad id", 400)
    p = os.path.join(IMGS, fid + ".jpg")
    if not os.path.abspath(p).startswith(os.path.abspath(IMGS)) or not os.path.exists(p):
        return ("not found", 404)
    w = request.args.get("w", "")
    if w.isdigit() and Image is not None:
        try:
            im = Image.open(p).convert("RGB"); W = min(int(w), im.width)
            if W < im.width: im = im.resize((W, int(im.height*W/im.width)), Image.LANCZOS)
            buf = io.BytesIO(); im.save(buf, "JPEG", quality=82); buf.seek(0)
            return send_file(buf, mimetype="image/jpeg")
        except Exception: pass
    return send_file(p, mimetype="image/jpeg")

@app.route("/api/image_search")
def api_image_search():
    q = request.args.get("q", ""); k = request.args.get("k", "15")
    k = int(k) if k.isdigit() else 15
    return jsonify({"query": q, "count": len(IMG_INDEX), "results": image_search(q, min(k, 40))})

@app.route("/api/video_frames")
def api_video_frames():
    """All indexed frames from one video (for 'see other frames in this video')."""
    vid = request.args.get("vid", "")
    rs = sorted((e for e in IMG_INDEX if e["vid"] == vid), key=lambda e: e["sec"])
    brand = rs[0]["brand"] if rs else (BYID.get(vid, {}).get("brand", vid))
    return jsonify({"vid": vid, "brand": brand, "count": len(rs),
                    "results": [{"id": e["id"], "vid": e["vid"], "brand": e["brand"],
                                 "arch": e.get("arch",""), "sec": e["sec"], "t": fmt(e["sec"]),
                                 "line": e.get("line",""), "tags": e.get("tags", [])[:3]} for e in rs]})

@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    text = (request.get_json(force=True) or {}).get("text", "")
    brief, detected = parse_brief(text)
    dirs = pick_directions(brief, 4)
    directions = [{"brand": v["brand"], "broad": v["broad"], "fine": v["fine"], "why": why,
                   "vid": v["id"], "hero_sec": v.get("hero_sec", 1)} for v, s, why in dirs]
    return jsonify({"detected": detected, "directions": directions})

@app.route("/api/search_lines")
def api_search_lines():
    """For the Google Docs add-on: find Nen video frames whose spoken line matches a query."""
    q = (request.args.get("q") or "").lower().strip()
    qa = set(re.findall(r"[a-z0-9]+", q)) - {"the","a","an","to","of","and","for","with","our","we","is","in","on","that","this"}
    out = []
    for v in VIDS:
        if v["id"] in EXCLUDE: continue
        try: sec = json.load(open(os.path.join(video_dir(v["id"]), "sec.json"), encoding="utf-8"))
        except Exception: sec = {}
        for sg in segs_of(v["id"]):
            words = set(re.findall(r"[a-z0-9]+", (sg.get("text") or "").lower()))
            ov = len(qa & words)
            si = sec.get(str(sg["index"]))
            if ov and si is not None:
                out.append({"vid": v["id"], "brand": v["brand"], "sec": si,
                            "line": (sg["text"] or "")[:150], "score": ov,
                            "url": f"/frame?vid={v['id']}&sec={si}"})
    out.sort(key=lambda x: -x["score"])
    return jsonify({"results": out[:30]})

@app.route("/api/hooks")
def api_hooks():
    out = []
    for k, title, why in HOOK_CATS:
        hk = sorted(HOOKS.get(k, []), key=lambda h: h["brand"])
        if hk: out.append({"key": k, "title": title, "why": why, "count": len(hk), "hooks": hk})
    return jsonify({"categories": out})

@app.route("/script")
def script():
    vid = request.args.get("vid", ""); v = BYID.get(vid)
    if not v: return ("unknown video", 404)
    vd = video_dir(vid)
    try: segs = json.load(open(os.path.join(vd, "segments.json"), encoding="utf-8"))
    except Exception: segs = []
    try: sec = json.load(open(os.path.join(vd, "sec.json"), encoding="utf-8"))
    except Exception: sec = {}
    logline = ""
    try:
        yt = json.load(open(os.path.join(vd, "meta.json"), encoding="utf-8")).get("yt", {}) or {}
        logline = (yt.get("title") or "").replace("\n", " ").strip()[:160]
    except Exception: pass
    rows = []
    for sg in segs:
        si = sec.get(str(sg["index"]))
        imgh = (f'<div class="r"><img src="/frame?vid={vid}&sec={si}"><div class="cap">{fmt(si)}</div></div>') if si is not None else ""
        rows.append(f'<div class="beat"><div class="l"><div class="t">{fmt(sg["start"])}</div><p>{esc(sg["text"])}</p></div>{imgh}</div>')
    orig = URL_MAP.get(vid, "")
    origlink = f' &nbsp;·&nbsp; <a href="{orig}" target="_blank">original post ↗</a>' if orig else ""
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(v['brand'])} — script</title>
<link rel="stylesheet" href="/style.css"></head><body><div class="wrap">
<a class="back" href="/">← back</a>
<div class="kicker" style="text-align:left;margin-top:20px">reference script · {esc(v['broad']).lower()}</div>
<h1>{esc(v['brand'])}</h1><p class="sub">{esc(logline)}</p>
<div class="kicker" style="text-align:left">script · {len(segs)} lines{origlink}</div>
<hr class="rule">{''.join(rows) if rows else '<p class="sub">No transcript available.</p>'}
</div></body></html>"""
    return Response(html, mimetype="text/html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, threaded=True)
