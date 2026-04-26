"""Probe estructura completa ESPN core API stats."""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

req = lambda url: json.loads(urllib.request.urlopen(
    urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15
).read())

EVT = "http://sports.core.api.espn.com/v2/sports/soccer/leagues/arg.1/events/694171?lang=en"
data = req(EVT)
comp0 = data["competitions"][0]
team0 = comp0["competitors"][0]
print(f"Match: {data.get('name')}, date: {data.get('date')}")

# Score
score = req(team0["score"]["$ref"])
print(f"  score: {score.get('value')}")

# Statistics
stats_data = req(team0["statistics"]["$ref"])
splits = stats_data.get("splits", {})
cats = splits.get("categories", [])
print(f"\n  Statistics splits — {len(cats)} categories:")
for cat in cats:
    cat_name = cat.get("name") or cat.get("displayName") or "unnamed"
    stats_list = cat.get("stats", [])
    print(f"    [{cat_name}] {len(stats_list)} stats:")
    for s in stats_list:
        nm = s.get("name") or s.get("abbreviation") or "?"
        val = s.get("value")
        disp = s.get("displayValue")
        if any(kw in (nm or "").lower() for kw in ["shot", "corner", "target", "goal"]):
            print(f"      {nm:<30} = {val}  (display: {disp})")
