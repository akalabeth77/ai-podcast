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
PODCAST_DESCRIPTION = (
    "Kolby AI Podcast je denný slovenský podcast o umelej inteligencii. "
    "Každý deň ti v skratke poviem, čo sa nové deje vo svete AI – nové modely, "
    "nástroje, výskum aj praktické tipy ako AI využiť v bežnom živote. "
    "Moderuje AI hlas, obsah generuje Gemini, správy čerpám z overených zdrojov. "
    "Ideálne na rannú kávu alebo cestou do práce."
)
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

def generate_podcast_script(articles: list[dict], episode_number: int) -> tuple[str, str]:
    """
    Cez Gemini vygeneruje prirodzený slovenský podcast skript.
    Vracia (title, full_script).
    """
    if not articles:
        raise ValueError("Žiadne články na spracovanie!")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY nie je nastavený!")

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

    prompt = f"""Si slovenský podcast moderátor pre show "Kolby AI Podcast".
Napíš prirodzený, plynulý podcast skript v slovenčine na {today_sk}. Toto je epizóda číslo {episode_number}.

ŠTRUKTÚRA (dodržuj presne):
1. Úvod: Pozdrav poslucháčov, predstav sa ako Kolby AI Podcast (epizóda {episode_number}), zhrň ČO KONKRÉTNE dnes pokryjeme – vymenuj všetky témy, ktoré sa budú preberať
2. Hlavné správy: Prejdi KAŽDÚ jednu novinku zo zoznamu zvlášť – vysvetli o čo ide, prečo je dôležitá pre bežného človeka, pridaj vlastný komentár a zaujímavú analógiu
3. Praktický tip dňa: Jeden konkrétny, použiteľný tip ako využiť AI v praxi na základe dnešných správ – s konkrétnym príkladom ako to urobiť
4. Záver: Zhrň čo sme dnes prebrali, rozlúč sa, pozvи na zajtra

KRITICKÉ PRAVIDLÁ – porušenie je neprijateľné:
- KOMPLETNOSŤ: Ak v úvode spomínaš nejakú tému, MUSÍŠ ju v epizóde aj skutočne pokryť. Nikdy nesľubuj témy, ktoré nepokryješ. Každá téma zo zoznamu správ musí byť spracovaná pred záverom.
- DĹŽKA: Minimálne 3500 slov – epizóda musí byť kompletná. Nekončи pred záverom. Záver píš až keď si pokryl každú novinku.
- PLYNULOSŤ: Píš hovorovo, nie formálne – ako by si rozprával priateľovi pri káve
- ZROZUMITEĽNOSŤ: Vysvetľuj technické pojmy jednoducho (napr. "veľký jazykový model – to je mozog za ChatGPT")
- ŽIVOSŤ: Buď zaujímavý, pridávaj vlastné postrehy, humor a analógie zo slovenského kontextu
- BEZ STAGE DIRECTIONS: NEPÍŠ poznámky pre moderátora, zátvorky ani pokyny – iba hovorený text
- BEZ LINKOV: Úplne vynechaj URL adresy a webové linky
- NÁZOV SHOW: Nepoužívaj "AI Dnes" ani iné varianty – vždy "Kolby AI Podcast"

FONETICKÉ PRAVIDLÁ – toto je kľúčové pre správnu výslovnosť:
Slovenský text-to-speech číta anglické slová zle. Preto anglické technické pojmy VŽDY nahraď fonetickým zápisom:
- "cloud" → píš "klaud"
- "AI" → píš "éj-aj" (alebo "umelá inteligencia")
- "ChatGPT" → píš "čet-dží-pí-tí"
- "OpenAI" → píš "óupn éj-aj"
- "startup" → píš "štartap"
- "streaming" → píš "stríming"
- "online" → píš "onlajn"
- "update" / "upgrade" → píš "apdejt" / "apgreid"
- "app" → píš "apka" alebo "aplikácia"
- "prompt" → píš "promt"
- "benchmark" → píš "benčmark"
- "deployment" → píš "nasadenie" alebo "diploiment"
- "framework" → píš "frejmmvork"
- "training" (v kontexte AI) → píš "trénovanie"
- "fine-tuning" → píš "fajn-tjúning"
- "reinforcement learning" → píš "posilňovacie učenie"
- "deep learning" → píš "hlboké učenie"
- "neural network" → píš "neurónová sieť"
- "open source" → píš "óupn-sors"
- "multimodal" → píš "multimodálny"
- "token" (v kontexte AI) → píš "token" (toto je v poriadku)
- "GitHub" → píš "git-hab"
- "Google" → nechaj ako je (všeobecne známe)
- "Microsoft" → nechaj ako je
- Iné anglické slová: vždy nahraď slovenským ekvivalentom alebo fonetickým zápisom

DNEŠNÉ SPRÁVY (pokryj VŠETKY):
{articles_text}

FORMÁT VÝSTUPU – VEĽMI DÔLEŽITÉ:
Úplne prvý riadok musí byť IBA názov epizódy v tomto formáte:
NAZOV: Ep. {episode_number}: [kreatívny názov max 60 znakov]
Príklady: "NAZOV: Ep. 9: Keď laptopy začnú myslieť za nás" alebo "NAZOV: Ep. 9: Dátové centrá — drahé sny alebo nevyhnutnosť?"
Za názvom nasleduje prázdny riadok a potom začína samotný hovorený skript (bez akýchkoľvek ďalších metadát)."""

    print(f"🤖 Generujem skript cez Gemini ({LLM_MODEL})...")
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}]
    )
    full_output = response.choices[0].message.content.strip()

    # Extrahuj názov z prvého riadku
    lines = full_output.split("\n")
    episode_title = f"Ep. {episode_number}"
    script = full_output
    if lines[0].startswith("NAZOV:"):
        episode_title = lines[0].removeprefix("NAZOV:").strip().strip('"\'')
        script = "\n".join(lines[1:]).lstrip("\n").strip()

    word_count = len(script.split())
    if word_count < 2000:
        raise ValueError(
            f"Skript je príliš krátky: {word_count} slov (minimum 2000). "
            "Skontroluj limity API alebo zvýš max_tokens."
        )

    print(f"  ✅ Skript vygenerovaný: {word_count} slov | Názov: {episode_title}")
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
        with open(EPISODES_FILE, encoding="utf-8") as f:
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
    mp3_filename = f"kolby-ai-{date_str}.mp3"
    mp3_path = OUTPUT_DIR / mp3_filename

    # GitHub repo nastavenie (pre URL v RSS)
    github_user = os.environ.get("GITHUB_REPO_OWNER", "tvoje-meno")
    github_repo = os.environ.get("GITHUB_REPO_NAME", "ai-podcast")
    base_url = f"https://{github_user}.github.io/{github_repo}"
    # MP3 sú nahrané ako GitHub Release assets
    release_base = f"https://github.com/{github_user}/{github_repo}/releases/download/{date_str}"

    # Vypočítaj číslo epizódy
    episode_number = 1
    if EPISODES_FILE.exists():
        with open(EPISODES_FILE, encoding="utf-8") as f:
            existing = json.load(f)
        episode_number = len(existing) + 1

    # 1. Novinky
    articles = fetch_todays_ai_news()
    if not articles:
        print("❌ Žiadne dnešné novinky. Skúsim staršie (48h)...")
        articles = fetch_todays_ai_news(max_articles=MAX_ARTICLES)

    # 2. Skript
    episode_title, script = generate_podcast_script(articles, episode_number)

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
