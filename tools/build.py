#!/usr/bin/env python3
"""Turn digest scripts into mp3 episodes with Gemini TTS and rebuild the RSS feed.

Layout:
  scripts/YYYY-MM-DD.txt   digest text (written each morning)
  site/                    checkout of the gh-pages branch (what gets published)
    episodes/YYYY-MM-DD.mp3
    feed.xml, cover.png, index.html
"""
import base64, datetime as dt, email.utils, glob, html, json, os, re, struct, subprocess, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
EP_DIR = os.path.join(SITE, "episodes")
BASE_URL = os.environ.get("BASE_URL", "https://ghelmstetter.github.io/ai-news-digest").rstrip("/")
MODEL = os.environ.get("TTS_MODEL", "gemini-3.8-flash-tts")
VOICE = os.environ.get("TTS_VOICE", "Charon")
STYLE = os.environ.get("TTS_STYLE", "Warm, clear, engaged news-podcast host. Natural conversational pace, not rushed.")
KEEP = int(os.environ.get("KEEP_EPISODES", "30"))
API_KEY = os.environ.get("GEMINI_API_KEY", "")
TITLE = "AI News Digest"
FEED_DESC = "A private daily audio digest of AI newsletters."


def log(*a):
    print(*a, flush=True)


def chunks(text, limit=1500):
    """Group paragraphs into chunks under `limit` characters."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(p) > limit:  # split long paragraphs on sentences
            parts, buf = re.split(r"(?<=[.!?])\s+", p), ""
            for s in parts:
                if len(buf) + len(s) + 1 > limit and buf:
                    out.append(buf.strip()); buf = ""
                buf += s + " "
            p = buf.strip()
        if cur and len(cur) + len(p) + 2 > limit:
            out.append(cur); cur = ""
        cur = (cur + "\n\n" + p).strip()
    if cur:
        out.append(cur)
    return out


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def find_audio(obj):
    """Return the longest base64 string found under a 'data' key anywhere in the response."""
    best = ""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "data" and isinstance(v, str) and len(v) > len(best):
                    best = v
                else:
                    stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)
    return base64.b64decode(best) if best else b""


def pcm_to_wav(pcm, rate=24000):
    hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return hdr + b"data" + struct.pack("<I", len(pcm)) + pcm


def tts(text):
    """Try the Interactions API first, then generateContent. Returns WAV bytes."""
    base = "https://generativelanguage.googleapis.com/v1beta"
    attempts = [
        ("interactions", f"{base}/interactions", {
            "model": MODEL,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": text,
                        "annotations": [{"type": "speech_metadata", "style": STYLE}]}]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": VOICE}]},
        }),
        ("generateContent", f"{base}/models/{MODEL}:generateContent", {
            "contents": [{"parts": [{"text": text, "speech_metadata": {"style": STYLE}}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}},
        }),
        ("generateContent-plain", f"{base}/models/{MODEL}:generateContent", {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}},
        }),
    ]
    errors = []
    for name, url, body in attempts:
        for attempt in range(3):
            try:
                audio = find_audio(post(url, body))
                if not audio:
                    raise RuntimeError("response contained no audio")
                log(f"    ok via {name} ({len(audio)} bytes)")
                return audio if audio[:4] == b"RIFF" else pcm_to_wav(audio)
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:500]
                errors.append(f"{name}: HTTP {e.code} {msg}")
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(10 * (attempt + 1)); continue
                break  # schema/auth problem: try next API shape
            except Exception as e:
                errors.append(f"{name}: {e}")
                time.sleep(5)
    raise RuntimeError("TTS failed:\n" + "\n".join(errors))


def make_episode(script_path, mp3_path):
    text = open(script_path, encoding="utf-8").read()
    parts = chunks(text)
    tmp = mp3_path + ".parts"
    os.makedirs(tmp, exist_ok=True)
    listing = []
    for i, c in enumerate(parts):
        log(f"  chunk {i + 1}/{len(parts)} ({len(c)} chars)")
        wav = os.path.join(tmp, f"{i:03d}.wav")
        with open(wav, "wb") as f:
            f.write(tts(c))
        listing.append(f"file '{wav}'")
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("\n".join(listing))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-ac", "1", "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "64k", mp3_path], check=True)
    subprocess.run(["rm", "-rf", tmp])


def duration(mp3):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp3],
                         capture_output=True, text=True).stdout.strip()
    return int(float(out or 0))


def summary(script_path):
    meta = script_path[:-4] + ".json"
    if os.path.exists(meta):
        m = json.load(open(meta))
        return m.get("title"), m.get("description", "")
    return None, ""


def build_feed():
    eps = sorted(glob.glob(os.path.join(EP_DIR, "*.mp3")), reverse=True)
    items = []
    for mp3 in eps:
        day = os.path.basename(mp3)[:-4]
        d = dt.datetime.strptime(day, "%Y-%m-%d").replace(hour=12, tzinfo=dt.timezone.utc)
        t, desc = summary(os.path.join(ROOT, "scripts", day + ".txt"))
        title = t or f"{TITLE}: {d.strftime('%a, %b')} {d.day}, {d.year}"
        secs = duration(mp3)
        items.append(f"""    <item>
      <title>{html.escape(title)}</title>
      <description>{html.escape(desc)}</description>
      <guid isPermaLink="false">ai-news-digest-{day}</guid>
      <pubDate>{email.utils.format_datetime(d)}</pubDate>
      <enclosure url="{BASE_URL}/episodes/{day}.mp3" length="{os.path.getsize(mp3)}" type="audio/mpeg"/>
      <itunes:duration>{secs // 60}:{secs % 60:02d}</itunes:duration>
    </item>""")
    now = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{TITLE}</title>
    <link>{BASE_URL}/</link>
    <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    <description>{FEED_DESC}</description>
    <language>en-us</language>
    <lastBuildDate>{now}</lastBuildDate>
    <itunes:author>AI News Digest</itunes:author>
    <itunes:image href="{BASE_URL}/cover.png"/>
    <itunes:explicit>false</itunes:explicit>
    <itunes:block>Yes</itunes:block>
    <itunes:category text="Technology"/>
{chr(10).join(items)}
  </channel>
</rss>
"""
    open(os.path.join(SITE, "feed.xml"), "w", encoding="utf-8").write(feed)
    open(os.path.join(SITE, "index.html"), "w").write(
        '<!doctype html><meta name="robots" content="noindex"><title>Nothing here</title>')
    open(os.path.join(SITE, "robots.txt"), "w").write("User-agent: *\nDisallow: /\n")
    open(os.path.join(SITE, ".nojekyll"), "w").close()


def main():
    os.makedirs(EP_DIR, exist_ok=True)
    cover = os.path.join(ROOT, "tools", "cover.png")
    if os.path.exists(cover):
        subprocess.run(["cp", cover, os.path.join(SITE, "cover.png")])
    made = 0
    for script in sorted(glob.glob(os.path.join(ROOT, "scripts", "*.txt"))):
        day = os.path.basename(script)[:-4]
        mp3 = os.path.join(EP_DIR, day + ".mp3")
        redo = os.environ.get("REDO_DATE", "") == day
        too_old = dt.date.fromisoformat(day) < dt.date.today() - dt.timedelta(days=7)
        if (os.path.exists(mp3) or too_old) and not redo:
            continue
        if not API_KEY:
            sys.exit("GEMINI_API_KEY secret is not set")
        log(f"Generating {day}")
        make_episode(script, mp3)
        made += 1
    # keep only the newest KEEP episodes on the published site
    for old in sorted(glob.glob(os.path.join(EP_DIR, "*.mp3")), reverse=True)[KEEP:]:
        os.remove(old)
    build_feed()
    log(f"Done: {made} new episode(s); feed at {BASE_URL}/feed.xml")


if __name__ == "__main__":
    main()
