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
USED_ARTICLES_FILE = Path("./docs/used_articles.json")


# ─────────────────────────────────────────────────────────────
#  RSS FEEDY – zdroje AI noviniek
# ─────────────────────────────────────────────────────────────

AI_NEWS_FEEDS = [
    # Technologické médiá – svet
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://arstechnica.com/tag/ai/feed/",
    # Priamo od AI spoločností
    "https://openai.com/blog/rss.xml",
    "https://www.anthropic.com/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    # Komunita
    "https://hnrss.org/newest?q=LLM+AI+GPT+Claude&points=100",
    # MIT Technology Review
    "https://www.technologyreview.com/feed/",
    # EU / európska perspektíva
    "https://www.euractiv.com/sections/digital/feed/",
    "https://sciencebusiness.net/feed",
]

# Feedy špeciálne pre EU/SK sekciu
EU_SK_FEEDS = [
    "https://www.euractiv.com/sections/digital/feed/",
    "https://sciencebusiness.net/feed",
    "https://www.euractiv.com/sections/data-protection/feed/",
]


# ─────────────────────────────────────────────────────────────
#  POMOCNÉ FUNKCIE
# ─────────────────────────────────────────────────────────────

DAYS_SK = ["pondelok", "utorok", "streda", "štvrtok", "piatok", "sobota", "nedeľa"]

def get_today_sk() -> str:
    """Vráti dnešný dátum vrátane dňa v týždni po slovensky."""
    now = datetime.now()
    day_name = DAYS_SK[now.weekday()]
    date_part = now.strftime("%d. %m. %Y").lstrip("0").replace(". 0", ". ")
    return f"{day_name}, {date_part}"


def clean_markdown(text: str) -> str:
    """Odstráni markdown formátovanie, ktoré by TTS čítal ako slová (hviezdičky a pod.)."""
    # Tučné a kurzíva: **text** a *text*
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    # Nadpisy: # Nadpis
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Citácie: > text
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    # Markdown linky: [text](url)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Horizontálne čiary
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Odsadzovanie zoznamov: "- " alebo "* " na začiatku riadku
    text = re.sub(r'^[\-\*•]\s+', '', text, flags=re.MULTILINE)
    # Číslované zoznamy: "1. " na začiatku riadku (len ak nasledujú ďalší text)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    # Kód: `code`
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Viacnásobné prázdne riadky → jeden
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ─────────────────────────────────────────────────────────────
#  KROK 1: Stiahni novinky
# ─────────────────────────────────────────────────────────────

def _parse_feed_articles(feed_urls: list[str], max_per_feed: int = 5, max_age_days: int = 2) -> list[dict]:
    """Pomocná funkcia – stiahne a vyčistí články zo zoznamu feedov."""
    today = datetime.now(timezone.utc).date()
    articles = []
    for feed_url in feed_urls:
        try:
            feed = feedparser.parse(feed_url, agent="AI-Podcast-Bot/1.0")
            for entry in feed.entries[:max_per_feed]:
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_date = datetime(*pub[:6], tzinfo=timezone.utc).date()
                    if (today - pub_date).days > max_age_days:
                        continue
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "") or entry.get("description", "")
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
    return articles


def _deduplicate(articles: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for a in articles:
        key = a["title"].lower()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def load_used_articles(days: int = 7) -> set[str]:
    """Načíta URL a titulky článkov použitých v posledných N dňoch."""
    if not USED_ARTICLES_FILE.exists():
        return set()
    cutoff = datetime.now(timezone.utc).date()
    from datetime import timedelta
    cutoff -= timedelta(days=days)
    with open(USED_ARTICLES_FILE, encoding="utf-8") as f:
        records = json.load(f)
    used = set()
    for r in records:
        try:
            rec_date = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if rec_date >= cutoff:
            if r.get("url"):
                used.add(r["url"])
            if r.get("title"):
                used.add(r["title"].lower()[:60])
    return used


def save_used_articles(articles: list[dict], date_str: str) -> None:
    """Uloží použité články do súboru pre budúcu deduplikáciu."""
    USED_ARTICLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if USED_ARTICLES_FILE.exists():
        with open(USED_ARTICLES_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    new_records = [
        {"url": a.get("url", ""), "title": a.get("title", ""), "date": date_str}
        for a in articles
    ]
    # Zachovaj záznamy z posledných 14 dní
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=14)).isoformat()
    existing = [r for r in existing if r.get("date", "") >= cutoff]
    existing.extend(new_records)
    with open(USED_ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"  💾 Uložených {len(new_records)} článkov do histórie použitých")


def _filter_used(articles: list[dict], used: set[str]) -> list[dict]:
    """Vyfiltruje články, ktoré už boli použité v posledných epizódach."""
    fresh = []
    skipped = 0
    for a in articles:
        url_used = a.get("url", "") in used
        title_used = a.get("title", "").lower()[:60] in used
        if url_used or title_used:
            skipped += 1
        else:
            fresh.append(a)
    if skipped:
        print(f"  🔁 Preskočených {skipped} opakujúcich sa článkov")
    return fresh


def fetch_todays_ai_news(max_articles: int = MAX_ARTICLES, used: set[str] | None = None) -> list[dict]:
    """Stiahne dnešné AI novinky zo všetkých RSS feedov."""
    print("📰 Sťahujem AI novinky...")
    articles = _deduplicate(_parse_feed_articles(AI_NEWS_FEEDS))
    if used:
        articles = _filter_used(articles, used)
    print(f"  ✅ Nájdených {len(articles)} nových článkov, vyberám top {max_articles}")
    return articles[:max_articles]


def fetch_eu_sk_news(max_articles: int = 3, used: set[str] | None = None) -> list[dict]:
    """Stiahne novinky o AI zo zdrojov zameraných na EÚ/Slovensko."""
    print("🇪🇺 Sťahujem EÚ/SK AI novinky...")
    articles = _deduplicate(_parse_feed_articles(EU_SK_FEEDS, max_per_feed=5, max_age_days=4))
    if used:
        articles = _filter_used(articles, used)
    print(f"  ✅ Nájdených {len(articles)} nových EÚ/SK článkov, vyberám top {max_articles}")
    return articles[:max_articles]


def load_recent_episode_context(n: int = 3) -> str:
    """Vráti zoznam tém z posledných N epizód pre kontext LLM."""
    if not EPISODES_FILE.exists():
        return ""
    with open(EPISODES_FILE, encoding="utf-8") as f:
        episodes = json.load(f)
    recent = episodes[:n]
    if not recent:
        return ""
    lines = [f"- {ep['title']}: {ep['description'][:200]}" for ep in recent]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  KROK 2: Vygeneruj podcast skript
# ─────────────────────────────────────────────────────────────

def generate_podcast_script(
    articles: list[dict],
    episode_number: int,
    eu_articles: list[dict] | None = None,
    recent_context: str = "",
) -> tuple[str, str]:
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
        f"{i+1}. {a['title']}\n"
        f"Zdroj: {a['source']}\n"
        f"Obsah: {a['summary']}"
        for i, a in enumerate(articles)
    ])

    eu_section = ""
    if eu_articles:
        eu_text = "\n\n".join([
            f"{i+1}. {a['title']}\n"
            f"Zdroj: {a['source']}\n"
            f"Obsah: {a['summary']}"
            for i, a in enumerate(eu_articles)
        ])
        eu_section = f"""

EÚ / SLOVENSKO SPRÁVY (použi pre sekciu č. 3 nižšie):
{eu_text}"""

    today_sk = get_today_sk()

    recent_section = ""
    if recent_context:
        recent_section = f"""

NEDÁVNO PREBRANÉ TÉMY (posledné {min(3, recent_context.count(chr(10)) + 1)} epizódy) – VYHNI SA OPAKOVANIU týchto tém:
{recent_context}
Ak sa niektorý dnešný článok týka rovnakej témy ako vyššie, buď ho preskočь alebo ho spomeň len v kontexte nového vývoja oproti tomu, čo sme hovorili pred pár dňami."""

    prompt = f"""Si slovenský podcast moderátor pre show "Kolby AI Podcast".
Napíš prirodzený, plynulý podcast skript v slovenčine. Dnes je {today_sk}. Toto je epizóda číslo {episode_number}.

ŠTRUKTÚRA (dodržuj presne, v tomto poradí):
1. ÚVOD: Pozdrav poslucháčov, predstav sa ako Kolby AI Podcast (epizóda {episode_number}), povedz dnešný dátum (deň aj dátum), zhrň ČO KONKRÉTNE dnes pokryjeme – vymenuj všetky témy zo svetových správ aj z EÚ/SK sekcie
2. SVETOVÉ AI SPRÁVY: Prejdi KAŽDÚ jednu novinku z "DNEŠNÉ SPRÁVY" zvlášť – vysvetli o čo ide, prečo je dôležitá pre bežného človeka, pridaj vlastný komentár a zaujímavú analógiu
3. EÚ A SLOVENSKO V AI: Osobitná sekcia venovaná správam z Európskej únie a Slovenska v kontexte umelej inteligencie – regulácie, financovanie, dopady AI zákonov na nás, slovenské AI projekty a startupy. Použи správy z "EÚ / SLOVENSKO SPRÁVY" a doplň vlastným kontextom.
4. PRAKTICKÝ TIP DŇA: Jeden konkrétny, použiteľný tip ako využiť AI v praxi na základe dnešných správ – s krokovým príkladom ako to urobiť
5. ZÁVER: Stručné zhrnutie čo sme dnes prebrali (jedna veta ku každej téme), rozlúčka, pozvanie na zajtra

KRITICKÉ PRAVIDLÁ – porušenie je neprijateľné:
- KOMPLETNOSŤ: Ak v úvode sľubuješ tému, MUSÍŠ ju pokryť. Záver píš AŽ po pokrytí každej témy. Nekonči predčasne.
- DĹŽKA: Minimálne 3500 slov – nie kratšie. Každú tému rozvíjaj do hĺbky.
- SPRÁVNY DEŇ: V celej epizóde používaj presný deň a dátum: {today_sk}. Nikdy nepíš nesprávny deň.
- PLYNULOSŤ: Píš hovorovo – ako keby si rozprával priateľovi pri káve. Plynulé prechody medzi témami.
- ZROZUMITEĽNOSŤ: Vysvetľuj technické pojmy jednoducho, vždy s analógiou zo bežného života.
- ŽIVOSŤ: Pridávaj vlastné postrehy, humor, analógie zo slovenského kontextu.
- BEZ MARKDOWN: ABSOLÚTNE ZAKÁZANÉ používať hviezdičky (*), dvojité hviezdičky (**), mriežky (#), pomlčky ako odrážky (- text), citácie (> text) ani žiadne iné formátovacie znaky. Tieto znaky TTS číta ako slová a znie to absurdne. Iba čistý súvislý hovorený text.
- BEZ ZÁTVORIEK: Nepíš poznámky ani vysvetlivky v zátvorkách – hovorí sa to plynule.
- BEZ LINKOV: Žiadne URL adresy, žiadne webové adresy.
- ČÍSLA: Všetky čísla píš slovom (napr. "jeden milión" nie "1 000 000", "päťdesiat percent" nie "50%").
- NÁZOV SHOW: Vždy "Kolby AI Podcast", nikdy iné varianty.

FONETICKÉ PRAVIDLÁ – slovenský TTS číta anglické slová zle, VŽDY nahraď:
- "AI" → píš "AI" veľkými písmenami (TTS ho číta správne ako dve písmená); NIKDY "éj-aj" ani "ejaj"
- "OpenAI" → píš "Open AI" (s medzerou)
- "ChatGPT" → píš "čet dží pí tí"
- "GPT" → píš "dží pí tí"
- "cloud" → píš "klaud"
- "startup" → píš "štartap"
- "streaming" → píš "stríming"
- "online" → píš "onlajn"
- "update" / "upgrade" → píš "apdejt" / "apgreid"
- "app" → píš "apka" alebo "aplikácia"
- "prompt" → píš "promt"
- "benchmark" → píš "benčmark"
- "framework" → píš "frejmmvork"
- "fine-tuning" → píš "fajntjúning"
- "open source" → píš "óupnsors"
- "GitHub" → píš "gitHab"
- "API" → píš "A P I" (s medzerami medzi písmenami)
- "CEO" → píš "generálny riaditeľ"
- Iné anglické slová: nahraď slovenským prekladom alebo píš foneticky

DNEŠNÉ SPRÁVY (pokryj VŠETKY v sekcii č. 2):
{articles_text}{eu_section}{recent_section}

FORMÁT VÝSTUPU – PRVÝ RIADOK MUSÍ BYŤ PRÁVE TOTO:
NAZOV: Ep. {episode_number}: [kreatívny slovenský názov vystihujúci hlavnú tému, max 65 znakov]
Príklady: "NAZOV: Ep. 10: Brusel reguluje, Silicon Valley ignoruje" alebo "NAZOV: Ep. 11: Keď AI vstupuje do volebnej kabínky"
Potom prázdny riadok a začína hovorený skript. Žiadne ďalšie metadáta."""

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

    # Odstráň prípadné zvyšné markdown znaky
    script = clean_markdown(script)

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

    # 1. Novinky (s filtrom použitých článkov)
    used = load_used_articles(days=7)
    articles = fetch_todays_ai_news(used=used)
    if not articles:
        print("❌ Žiadne nové dnešné novinky. Skúsim bez filtra...")
        articles = fetch_todays_ai_news()

    eu_articles = fetch_eu_sk_news(used=used)

    # 2. Skript (s kontextom posledných epizód)
    recent_context = load_recent_episode_context(n=3)
    episode_title, script = generate_podcast_script(
        articles, episode_number, eu_articles, recent_context
    )

    # Ulož použité články do histórie
    save_used_articles(articles + (eu_articles or []), date_str)

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
