#!/usr/bin/env python3
"""
Denný AI Podcast Generátor
--------------------------
Každý deň:
1. Stiahne najnovšie AI novinky z RSS feedov
2. Vygeneruje podcast skript cez Claude API (Haiku - veľmi lacné)
3. Skonvertuje text na reč cez edge-tts (ZADARMO, slovenský hlas)
4. Uloží MP3 a aktualizuje RSS feed pre Spotify

Prerekvizity:
    pip install feedparser openai edge-tts httpx python-dateutil
"""

import asyncio
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import edge_tts
import feedparser
import httpx
from openai import OpenAI


# ─────────────────────────────────────────────────────────────
#  KONFIGURÁCIA – uprav podľa seba
# ─────────────────────────────────────────────────────────────

PODCAST_TITLE = "Kolby AI Podcast"
PODCAST_DESCRIPTION = "Každý deň novinky zo sveta umelej inteligencie po slovensky."
PODCAST_LANGUAGE = "sk"
PODCAST_AUTHOR = "Andrej Kolbaský"
PODCAST_EMAIL = "andrej.kolbasky@gmail.com"
PODCAST_IMAGE_URL = "https://akalabeth77.github.io/ai-podcast/cover.png"

# Slovenský hlas (edge-tts): Lukáš alebo Viktória
# Všetky dostupné hlasy: edge-tts --list-voices | grep sk-SK
TTS_VOICE = "sk-SK-LukasNeural"  # alebo "sk-SK-ViktoriaNeural"

# Tempo reči: +0% = normálne, +10% = rýchlejšie, -10% = pomalšie
TTS_RATE = "+5%"

# Koľko článkov spracovať (viac = dlhší podcast)
MAX_ARTICLES = 8

# Google Gemini – 1500 požiadaviek/deň zadarmo, bez rate limitov
LLM_MODEL = "gemini-2.5-flash"

# Výstupné súbory
OUTPUT_DIR = Path("./output")
RSS_FILE = Path("./docs/feed.xml")   # GitHub Pages slúži z ./docs
EPISODES_FILE = Path("./docs/episodes.json")


# ─────────────────────────────────────────────────────────────
#  RSS FEEDY – zdroje AI noviniek
# ─────────────────────────────────────────────────────────────

AI_NEWS_FEEDS = [
    # Technologické médiá
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://arstechnica.com/tag/ai/feed/",
    # Priamo od AI spoločností
    "https://openai.com/blog/rss.xml",
    "https://www.anthropic.com/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    # Komunita
    "https://hnrss.org/newest?q=LLM+AI+GPT+Claude&points=100",
    # MIT Technology Review – AI sekcia
    "https://www.technologyreview.com/feed/",
]


# ─────────────────────────────────────────────────────────────
#  KROK 1: Stiahni novinky
# ─────────────────────────────────────────────────────────────

def fetch_todays_ai_news(max_articles: int = MAX_ARTICLES) -> list[dict]:
    """Stiahne dnešné AI novinky zo všetkých RSS feedov."""
    today = datetime.now(timezone.utc).date()
    articles = []

    print("📰 Sťahujem AI novinky...")

    for feed_url in AI_NEWS_FEEDS:
        try:
            feed = feedparser.parse(feed_url, agent="AI-Podcast-Bot/1.0")
            for entry in feed.entries[:5]:  # max 5 z každého zdroja
                # Skontroluj čerstvosť (max 48h staré)
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_date = datetime(*pub[:6], tzinfo=timezone.utc).date()
                    if (today - pub_date).days > 2:
                        continue

                title = entry.get("title", "").strip()
                summary = entry.get("summary", "") or entry.get("description", "")
                # Odistrihni HTML tagy
                summary = re.sub(r"<[^>]+>", " ", summary).strip()
                summary = re.sub(r"\s+", " ", summary)[:800]

                if title and len(title) > 10:
                    articles.append({
                        "title": title,
                        "summary": summary,
                        "url": entry.get("link", ""),
                        "source": feed.feed.get("title", feed_url),
                    })
        except Exception as e:
            print(f"  ⚠️  Chyba pri {feed_url}: {e}")

    # Odober duplikáty podľa podobného názvu
    seen_titles = set()
    unique = []
    for a in articles:
        key = a["title"].lower()[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(a)

    print(f"  ✅ Nájdených {len(unique)} článkov, vyberám top {max_articles}")
    return unique[:max_articles]


# ─────────────────────────────────────────────────────────────
#  KROK 2: Vygeneruj podcast skript
# ─────────────────────────────────────────────────────────────

def generate_podcast_script(articles: list[dict]) -> tuple[str, str]:
    """
    Cez OpenRouter vygeneruje prirodzený slovenský podcast skript.
    Vracia (title, full_script).
    """
    if not articles:
        raise ValueError("Žiadne články na spracovanie!")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY nie je nastavený!")

    # OpenRouter je OpenAI-kompatibilný – stačí zmeniť base_url
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    articles_text = "\n\n".join([
        f"**{i+1}. {a['title']}**\n"
        f"Zdroj: {a['source']}\n"
        f"Obsah: {a['summary']}"
        for i, a in enumerate(articles)
    ])

    today_sk = datetime.now().strftime("%d. %m. %Y").lstrip("0").replace(". 0", ". ")

    prompt = f"""Si slovenský podcast moderátor pre show "AI Dnes".
Napíš prirodzený, plynulý podcast skript v slovenčine na {today_sk}.

ŠTRUKTÚRA (dodržuj):
1. Úvod (30 sekúnd): Pozdrav, čo poslucháč dnes uslyší
2. Hlavné správy (15-18 minút): Prejdi každú novinku, vysvetli kontext, prečo je dôležitá pre bežného človeka
3. Praktický tip (2-3 minúty): Na základe dnešných správ jeden konkrétny tip ako využiť AI v bežnom živote
4. Záver (30 sekúnd): Rozlúčenie

PRAVIDLÁ:
- Píš hovorovo, nie formálne – ako by si rozprával priateľovi
- Vysvetľuj technické pojmy jednoducho (napr. "LLM – to sú veľké jazykové modely, v skratke mozog za ChatGPT")
- Pridávaj vlastné komentáre a postrehy, buď živý a zaujímavý
- Dĺžka: cca 2000-2500 slov (zodpovedá 20 minútam)
- NEPÍŠ stage directions ako [pauza] alebo [hudba] – iba hovorený text
- Úplne vynechaj URL adresy

DNEŠNÉ SPRÁVY:
{articles_text}

Začni priamo skriptom, bez akýchkoľvek úvodných poznámok."""

    print(f"🤖 Generujem skript cez Gemini ({LLM_MODEL})...")
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )
    script = response.choices[0].message.content.strip()

    title_response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=80,
        messages=[{"role": "user", "content": (
            f"Na základe tohto podcast skriptu vygeneruj krátky, výstižný názov epizódy "
            f"(max 60 znakov, po slovensky, bez úvodzoviek):\n\n{script[:500]}"
        )}]
    )
    episode_title = title_response.choices[0].message.content.strip().strip('"\'')

    print(f"  ✅ Skript vygenerovaný: {len(script)} znakov | Názov: {episode_title}")
    return episode_title, script


# ─────────────────────────────────────────────────────────────
#  KROK 3: Text → Reč (edge-tts, zadarmo)
# ─────────────────────────────────────────────────────────────

async def text_to_speech(script: str, output_path: Path) -> None:
    """Skonvertuje skript na MP3 pomocou Microsoft Edge TTS (zadarmo)."""
    print(f"🔊 Konvertujem text na reč ({TTS_VOICE})...")
    communicate = edge_tts.Communicate(script, TTS_VOICE, rate=TTS_RATE)
    await communicate.save(str(output_path))
    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  ✅ Audio uložené: {output_path} ({size_mb:.1f} MB)")


# ─────────────────────────────────────────────────────────────
#  KROK 4: Aktualizuj RSS feed
# ─────────────────────────────────────────────────────────────

def update_rss_feed(episode_title: str, mp3_filename: str, mp3_size: int,
                    script: str, base_url: str) -> None:
    """
    Aktualizuje RSS XML súbor pre Spotify/podcast aplikácie.
    base_url: URL kde sú MP3 súbory hostované (napr. GitHub Releases URL)
    """
    RSS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EPISODES_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Načítaj existujúce epizódy
    episodes = []
    if EPISODES_FILE.exists():
        with open(EPISODES_FILE) as f:
            episodes = json.load(f)

    now = datetime.now(timezone.utc)
    pub_date = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
    episode_id = now.strftime("%Y-%m-%d")
    mp3_url = f"{base_url.rstrip('/')}/{mp3_filename}"

    # Vypočítaj reálne trvanie z MP3
    duration_str = "00:20:00"
    mp3_path = OUTPUT_DIR / mp3_filename
    if mp3_path.exists():
        try:
            from mutagen.mp3 import MP3
            audio = MP3(str(mp3_path))
            total_sec = int(audio.info.length)
            duration_str = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}:{total_sec % 60:02d}"
        except Exception:
            pass

    new_episode = {
        "id": episode_id,
        "title": episode_title,
        "description": script[:500] + "...",
        "pub_date": pub_date,
        "mp3_url": mp3_url,
        "mp3_size": mp3_size,
        "duration": duration_str,
    }

    # Nahraď existujúcu epizódu pre daný dátum, alebo pridaj novú
    episodes = [ep for ep in episodes if ep.get("id") != episode_id]
    episodes.insert(0, new_episode)
    episodes = episodes[:60]

    with open(EPISODES_FILE, "w", encoding="utf-8") as f:
        json.dump(episodes, f, ensure_ascii=False, indent=2)

    # Vygeneruj RSS XML
    rss_url = f"{base_url.rstrip('/')}/feed.xml"

    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
    })
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "description").text = PODCAST_DESCRIPTION
    ET.SubElement(channel, "language").text = PODCAST_LANGUAGE
    ET.SubElement(channel, "link").text = base_url

    itunes = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    ET.SubElement(channel, f"{{{itunes}}}author").text = PODCAST_AUTHOR
    ET.SubElement(channel, f"{{{itunes}}}explicit").text = "false"
    ET.SubElement(channel, f"{{{itunes}}}category", attrib={"text": "Technology"})
    ET.SubElement(channel, f"{{{itunes}}}image", attrib={"href": PODCAST_IMAGE_URL})
    owner = ET.SubElement(channel, f"{{{itunes}}}owner")
    ET.SubElement(owner, f"{{{itunes}}}name").text = PODCAST_AUTHOR
    ET.SubElement(owner, f"{{{itunes}}}email").text = PODCAST_EMAIL

    image = ET.SubElement(channel, "image")
    ET.SubElement(image, "url").text = PODCAST_IMAGE_URL
    ET.SubElement(image, "title").text = PODCAST_TITLE
    ET.SubElement(image, "link").text = base_url

    for ep in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep["title"]
        ET.SubElement(item, "description").text = ep["description"]
        ET.SubElement(item, "pubDate").text = ep["pub_date"]
        ET.SubElement(item, "guid").text = ep["mp3_url"]
        ET.SubElement(item, "enclosure", url=ep["mp3_url"],
                      length=str(ep["mp3_size"]), type="audio/mpeg")
        ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration").text = ep["duration"]

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    with open(RSS_FILE, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)

    print(f"  ✅ RSS feed aktualizovaný: {RSS_FILE}")


# ─────────────────────────────────────────────────────────────
#  HLAVNÁ FUNKCIA
# ─────────────────────────────────────────────────────────────

async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    mp3_filename = f"ai-dnes-{date_str}.mp3"
    mp3_path = OUTPUT_DIR / mp3_filename

    # GitHub repo nastavenie (pre URL v RSS)
    github_user = os.environ.get("GITHUB_REPO_OWNER", "tvoje-meno")
    github_repo = os.environ.get("GITHUB_REPO_NAME", "ai-podcast")
    base_url = f"https://{github_user}.github.io/{github_repo}"
    # MP3 sú nahrané ako GitHub Release assets
    release_base = f"https://github.com/{github_user}/{github_repo}/releases/download/{date_str}"

    # 1. Novinky
    articles = fetch_todays_ai_news()
    if not articles:
        print("❌ Žiadne dnešné novinky. Skúsim staršie (48h)...")
        articles = fetch_todays_ai_news(max_articles=MAX_ARTICLES)

    # 2. Skript
    episode_title, script = generate_podcast_script(articles)

    # Ulož skript pre debugovanie
    script_path = OUTPUT_DIR / f"script-{date_str}.txt"
    script_path.write_text(f"{episode_title}\n\n{script}", encoding="utf-8")
    print(f"  💾 Skript uložený: {script_path}")

    # 3. TTS → MP3
    await text_to_speech(script, mp3_path)

    # 4. RSS
    mp3_size = mp3_path.stat().st_size
    update_rss_feed(episode_title, mp3_filename, mp3_size, script, release_base)

    print(f"\n😙️  Hotovo! Epizóda: {episode_title}")
    print(f"   MP3: {mp3_path}")
    print(f"   RSS: {RSS_FILE}")
    print(f"\n   Pre Spotify: {base_url}/feed.xml")


if __name__ == "__main__":
    asyncio.run(main())
