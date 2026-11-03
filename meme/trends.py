"""Record what the internet is talking about (free sources), to test later whether coins named after a hot topic do
better: Google Trends daily searches (US + worldwide-ish NL/GB), Wikipedia's most-read pages, CoinGecko trending coins.
Appends to trends/YYYY-MM.csv (t_utc, source, rank, term, extra). Run hourly from .github/workflows/trends.yml.
"""
import csv
import datetime as dt
import os
import re

import requests

UA = {"User-Agent": "meme-desk-research/1.0"}


def google(geo):
    x = requests.get(f"https://trends.google.com/trending/rss?geo={geo}", headers=UA, timeout=30).text
    out = []
    for i, item in enumerate(re.findall(r"<item>(.*?)</item>", x, re.S)):
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        tr = re.search(r"<ht:approx_traffic>(.*?)</ht:approx_traffic>", item)
        if t:
            out.append((f"google-{geo}", i + 1, t.group(1).strip(), tr.group(1) if tr else ""))
    return out


def wikipedia():
    d = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    u = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{d:%Y/%m/%d}"
    arts = requests.get(u, headers=UA, timeout=30).json()["items"][0]["articles"]
    skip = ("Main_Page", "Special:", "Wikipedia:", "Portal:", "File:")
    arts = [a for a in arts if not a["article"].startswith(skip)][:50]
    return [("wikipedia", a["rank"], a["article"].replace("_", " "), a["views"]) for a in arts]


def coingecko():
    j = requests.get("https://api.coingecko.com/api/v3/search/trending", headers=UA, timeout=30).json()
    return [("coingecko", i + 1, c["item"]["name"], c["item"]["symbol"]) for i, c in enumerate(j.get("coins", []))]


def main():
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for f, args in ((google, ("US",)), (google, ("GB",)), (google, ("NL",)), (coingecko, ())) + \
                   (((wikipedia, ()),) if now.hour == 6 else ()):
        try:
            rows += f(*args)
        except Exception as e:
            print(f.__name__, args, "failed:", repr(e)[:150])
    os.makedirs("trends", exist_ok=True)
    path = f"trends/{now:%Y-%m}.csv"
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["t_utc", "source", "rank", "term", "extra"])
        for r in rows:
            w.writerow([f"{now:%Y-%m-%d %H:%M}", *r])
    print(len(rows), "rows ->", path)


if __name__ == "__main__":
    main()
