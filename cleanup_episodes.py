import json

with open("docs/episodes.json", encoding="utf-8") as f:
    eps = json.load(f)

seen = {}
for ep in eps:
    eid = ep.get("id", "")
    if eid not in seen or ep["mp3_size"] > seen[eid]["mp3_size"]:
        seen[eid] = ep

clean = sorted(seen.values(), key=lambda e: e["pub_date"], reverse=True)

with open("docs/episodes.json", "w", encoding="utf-8") as f:
    json.dump(clean, f, ensure_ascii=False, indent=2)

print(f"Zostalo {len(clean)} epizod:")
for e in clean:
    print(f"  {e['id']} | {round(e['mp3_size']/1024/1024, 1)} MB | {e['duration']} | {e['title']}")
