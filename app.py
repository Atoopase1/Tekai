"""
Tekai AI — app.py
Clean Flask backend for the standalone HTML/CSS/JS frontend.

Setup:
    pip install -r requirements.txt

Run:
    python app.py

Environment variables (optional — hardcoded defaults work out of the box):
    SUPABASE_URL   — your Supabase project URL
    SUPABASE_KEY   — your Supabase anon/publishable key
    FLASK_SECRET   — secret key for sessions (auto-generated if not set)
    PORT           — port to listen on (default 5000)
"""

import os
import base64
import uuid
import json
import traceback
from io import BytesIO

from flask import Flask, send_from_directory, request, jsonify, redirect
from flask_cors import CORS

# ── Optional deps (graceful fallback) ─────────────────────────────────────────
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    print("[WARN] openai not installed — /api/chat will not work")

try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    print("[WARN] duckduckgo-search not installed — web research disabled")

try:
    from PyPDF2 import PdfReader
    HAS_PDF = True
except ImportError:
    try:
        from pypdf import PdfReader
        HAS_PDF = True
    except ImportError:
        HAS_PDF = False
        print("[WARN] PyPDF2/pypdf not installed — PDF uploads disabled")

try:
    from supabase import create_client, Client as SupabaseClient
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    print("[WARN] supabase not installed — auth/db features disabled")

# ── Config ────────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ihayzyjgezqmmzvvtwfg.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_KET96WWCMODHQIYOriiCDg_-b9H7C2b")
PORT         = int(os.environ.get("PORT", 5000))

# ── App ───────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static"
)
app.secret_key = os.environ.get("FLASK_SECRET", "tekai-" + str(uuid.uuid4()))
CORS(app, origins="*")

# ── Supabase client (lazy) ────────────────────────────────────────────────────
_sb: "SupabaseClient | None" = None

def get_supabase():
    global _sb
    if _sb is None and HAS_SUPABASE and SUPABASE_URL and SUPABASE_KEY:
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb


# ── LLM client factory ────────────────────────────────────────────────────────
def get_llm_client(provider: str, api_key: str):
    if not HAS_OPENAI:
        return None
    if provider == "groq":
        return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    if provider == "openrouter":
        return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    return None


# ── Web search ────────────────────────────────────────────────────────────────
def search_web(query: str) -> str:
    if not HAS_DDGS:
        return "(Web search unavailable — install duckduckgo-search)"
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=4):
                results.append(
                    f"Title: {r['title']}\nSource: {r['href']}\nSnippet: {r['body']}\n"
                )
        return "\n".join(results) or "No results found."
    except Exception as e:
        return f"Search error: {e}"


# ── Image generation (free, no key needed) ────────────────────────────────────
def make_image_url(prompt: str) -> str:
    clean = prompt.strip().replace(" ", "%20")
    return f"https://pollinations.ai/p/{clean}?width=1024&height=1024&seed=42&model=flux"


# ── DB helpers ────────────────────────────────────────────────────────────────
def db_load_messages(session_id: str) -> list:
    sb = get_supabase()
    if not sb:
        return []
    try:
        res = (sb.table("conversations")
               .select("*")
               .eq("session_id", session_id)
               .order("created_at")
               .execute())
        msgs = []
        for row in res.data:
            m = {"role": row["role"], "content": row["content"]}
            if row.get("image_url"):
                m["image"] = row["image_url"]
            msgs.append(m)
        return msgs
    except Exception:
        return []


def db_save_message(session_id: str, role: str, content: str,
                    image_url: str | None = None, user_id: str | None = None):
    sb = get_supabase()
    if not sb:
        return
    try:
        row = {"session_id": session_id, "role": role, "content": content,
               "image_url": image_url}
        if user_id:
            row["user_id"] = user_id
        sb.table("conversations").insert(row).execute()
    except Exception:
        pass


def db_get_sessions(user_id: str) -> list:
    sb = get_supabase()
    if not sb or not user_id:
        return []
    try:
        res = (sb.table("conversations")
               .select("session_id, content, created_at")
               .eq("user_id", user_id)
               .order("created_at")
               .execute())
        seen = {}
        for row in res.data:
            sid = row["session_id"]
            if sid not in seen:
                seen[sid] = {
                    "session_id": sid,
                    "preview": row["content"][:60] + "…",
                    "created_at": row["created_at"][:10]
                }
        return list(reversed(list(seen.values())))
    except Exception:
        return []


def db_get_avatar(user_id: str) -> str | None:
    sb = get_supabase()
    if not sb:
        return None
    try:
        res = (sb.table("user_profiles")
               .select("avatar_url")
               .eq("user_id", user_id)
               .execute())
        if res.data and res.data[0].get("avatar_url"):
            return res.data[0]["avatar_url"]
    except Exception:
        pass
    return None


def db_save_avatar(user_id: str, avatar_url: str):
    sb = get_supabase()
    if not sb:
        return
    try:
        sb.table("user_profiles").upsert(
            {"user_id": user_id, "avatar_url": avatar_url}
        ).execute()
    except Exception:
        pass


# ═════════════════════════════ ROUTES ═════════════════════════════════════════

@app.route("/")
def index():
    """Serve the standalone index.html (no Jinja — config is fetched via /api/config)."""
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/config")
def api_config():
    """Expose Supabase public credentials to the frontend (safe — publishable key)."""
    return jsonify({
        "supabase_url": SUPABASE_URL,
        "supabase_key": SUPABASE_KEY,
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    Send a message to the AI and return the reply.

    Body (JSON):
        provider   — "groq" | "openrouter"
        api_key    — user's API key
        model      — model string
        messages   — list of {role, content}
        web_search — bool
        image_b64  — data:image/…;base64,… (optional, for vision)
    """
    data       = request.get_json(force=True)
    provider   = data.get("provider", "groq")
    api_key    = data.get("api_key", "").strip()
    model      = data.get("model", "llama-3.3-70b-versatile")
    messages   = data.get("messages", [])
    do_search  = bool(data.get("web_search"))
    image_b64  = data.get("image_b64")  # full data-URL

    if not api_key:
        return jsonify({"error": "API key required"}), 400
    if not messages:
        return jsonify({"error": "No messages"}), 400

    client = get_llm_client(provider, api_key)
    if not client:
        return jsonify({"error": "openai package not installed on this server"}), 500

    system = (
        "You are Nova, a helpful and expert AI assistant built into Tekai. "
        "Be concise, professional, and accurate. "
        "Show steps when answering math or logic. "
        "When an image is provided, describe and analyze it in detail. "
        "When a document is provided, use its contents to answer the question."
    )

    api_msgs = [{"role": "system", "content": system}]

    # Add all but the last message as-is
    for m in messages[:-1]:
        api_msgs.append({"role": m["role"], "content": m["content"]})

    last_user_text = messages[-1]["content"] if messages else ""

    # Optionally append web-search context
    if do_search:
        ctx = search_web(last_user_text)
        last_user_text += f"\n\n[Real-time web context]\n{ctx}"

    try:
        if image_b64:
            # Groq vision model
            vision_model = (
                "meta-llama/llama-3.2-90b-vision-instruct"
                if provider == "openrouter"
                else "llama-3.2-90b-vision-preview"
            )
            api_msgs.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": last_user_text},
                    {"type": "image_url", "image_url": {"url": image_b64}}
                ]
            })
            resp = client.chat.completions.create(
                model=vision_model, messages=api_msgs, max_tokens=2048)
        else:
            api_msgs.append({"role": "user", "content": last_user_text})
            resp = client.chat.completions.create(
                model=model, messages=api_msgs, max_tokens=2048)

        reply = resp.choices[0].message.content
        return jsonify({"reply": reply})

    except Exception as e:
        err = str(e)
        if "401" in err or "auth" in err.lower() or "invalid_api_key" in err.lower():
            return jsonify({"error": "Invalid API key — check your key and try again"}), 401
        if "429" in err or "rate" in err.lower():
            return jsonify({"error": "Rate limited — wait a moment then retry"}), 429
        if "model" in err.lower() and "not found" in err.lower():
            return jsonify({"error": f"Model not found: {model}"}), 400
        return jsonify({"error": err}), 500


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """
    Accept a file upload, return:
      - {type:'image', data_url:'data:...', name:'...'}
      - {type:'document', text:'...', name:'...'}
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f    = request.files["file"]
    mime = f.mimetype or ""
    name = f.filename or "upload"

    # ── Image ──
    if mime.startswith("image/") or name.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
        raw = f.read()
        if len(raw) > 20 * 1024 * 1024:
            return jsonify({"error": "Image too large (max 20 MB)"}), 400
        b64 = base64.b64encode(raw).decode()
        # Normalise mime
        ext = name.rsplit(".", 1)[-1].lower()
        ext_mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}
        actual_mime = mime if mime.startswith("image/") else ext_mime.get(ext, "image/png")
        return jsonify({
            "type": "image",
            "data_url": f"data:{actual_mime};base64,{b64}",
            "name": name
        })

    # ── PDF ──
    if "pdf" in mime or name.lower().endswith(".pdf"):
        if not HAS_PDF:
            return jsonify({"error": "PyPDF2 not installed on server"}), 500
        raw = BytesIO(f.read())
        try:
            reader = PdfReader(raw)
            text = ""
            for page in reader.pages[:30]:
                text += page.extract_text() or ""
            return jsonify({"type": "document", "text": text[:12000], "name": name})
        except Exception as e:
            return jsonify({"error": f"PDF read error: {e}"}), 500

    # ── Plain text ──
    if mime.startswith("text/") or name.lower().endswith((".txt", ".md", ".csv", ".py", ".js")):
        text = f.read().decode("utf-8", errors="ignore")
        return jsonify({"type": "document", "text": text[:12000], "name": name})

    return jsonify({"error": f"Unsupported file type: {mime or name}"}), 400


@app.route("/api/image", methods=["POST"])
def api_image():
    """Generate an image URL via Pollinations.ai (free, no key needed)."""
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "No prompt"}), 400
    return jsonify({"url": make_image_url(prompt)})


@app.route("/auth/callback")
def auth_callback():
    """Supabase implicit-flow tokens land in the URL hash (client-side only)."""
    return redirect("/#auth-callback")


@app.route("/api/sessions")
def api_sessions():
    user_id = request.args.get("user_id", "")
    return jsonify(db_get_sessions(user_id))


@app.route("/api/messages")
def api_messages():
    sid = request.args.get("session_id", "")
    return jsonify(db_load_messages(sid))


@app.route("/api/save_message", methods=["POST"])
def api_save_message():
    d = request.get_json(force=True)
    db_save_message(
        d.get("session_id", ""),
        d.get("role", "user"),
        d.get("content", ""),
        d.get("image_url"),
        d.get("user_id")
    )
    return jsonify({"ok": True})


@app.route("/api/profile", methods=["GET", "POST"])
def api_profile():
    if request.method == "GET":
        uid = request.args.get("user_id", "")
        return jsonify({"avatar_url": db_get_avatar(uid)})
    d = request.get_json(force=True)
    db_save_avatar(d.get("user_id", ""), d.get("avatar_url", ""))
    return jsonify({"ok": True})


# Serve static files from /static/
@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory(os.path.join(BASE_DIR, "static"), path)


if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════╗
║         Tekai AI — Flask Backend         ║
╠══════════════════════════════════════════╣
║  URL  : http://localhost:{PORT:<17}║
║  Auth : Supabase Google OAuth            ║
║  AI   : Groq / OpenRouter                ║
║  DB   : Supabase (conversations)         ║
╚══════════════════════════════════════════╝

Tip: Get a free Groq API key at https://console.groq.com
""")
    app.run(debug=True, host="0.0.0.0", port=PORT)
