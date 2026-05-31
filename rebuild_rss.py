"""Zregeneruje feed.xml z episodes.json."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

PODCAST_TITLE = "Kolby AI Podcast"
PODCAST_DESCRIPTION = "Každý deň novinky zo sveta umelej inteligencie po slovensky."
PODCAST_LANGUAGE = "sk"
PODCAST_AUTHOR = "Andrej Kolbaský"
PODCAST_EMAIL = "andrej.kolbasky@gmail.com"
PODCAST_IMAGE_URL = "https://akalabeth77.github.io/ai-podcast/cover.png"
BASE_URL = "https://akalabeth77.github.io/ai-podcast"
RSS_FILE = Path("docs/feed.xml")
EPISODES_FILE = Path("docs/episodes.json")

with open(EPISODES_FILE, encoding="utf-8") as f:
    episodes = json.load(f)

itunes = "http://www.itunes.com/dtds/podcast-1.0.dtd"
rss = ET.Element("rss", version="2.0", attrib={
    "xmlns:itunes": itunes,
    "xmlns:content": "http://purl.org/rss/1.0/modules/content/"
})
channel = ET.SubElement(rss, "channel")

ET.SubElement(channel, "title").text = PODCAST_TITLE
ET.SubElement(channel, "description").text = PODCAST_DESCRIPTION
ET.SubElement(channel, "language").text = PODCAST_LANGUAGE
ET.SubElement(channel, "link").text = BASE_URL
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
ET.SubElement(image, "link").text = BASE_URL

for ep in episodes:
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = ep["title"]
    ET.SubElement(item, "description").text = ep["description"]
    ET.SubElement(item, "pubDate").text = ep["pub_date"]
    ET.SubElement(item, "guid").text = ep["mp3_url"]
    ET.SubElement(item, "enclosure", url=ep["mp3_url"],
                  length=str(ep["mp3_size"]), type="audio/mpeg")
    ET.SubElement(item, f"{{{itunes}}}duration").text = ep["duration"]

tree = ET.ElementTree(rss)
ET.indent(tree, space="  ")
with open(RSS_FILE, "wb") as f:
    f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(f, encoding="utf-8", xml_declaration=False)

print(f"RSS feed zregenerovaný s {len(episodes)} epizódami.")
