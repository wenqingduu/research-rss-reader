#!/usr/bin/env python3
"""Add Chinese paper/news titles using a local, open-source translation model.

No commercial translation API or account credentials. Translation models are
downloaded from the Argos Translate package index if they are not cached.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "articles.json"
MAX_NEW_TITLES = 180  # Backfill in batches across scheduled runs.
HAN = re.compile(r"[\u3400-\u9fff]")


def translator():
    import argostranslate.package as package
    import argostranslate.translate as translate

    languages = translate.get_installed_languages()
    english = next((x for x in languages if x.code == "en"), None)
    chinese = next((x for x in languages if x.code in ("zh", "zh-CN")), None)
    if not (english and chinese):
        print("Downloading free English→Chinese Argos model...", flush=True)
        package.update_package_index()
        matches = [p for p in package.get_available_packages()
                   if p.from_code == "en" and p.to_code in ("zh", "zh-CN")]
        if not matches:
            raise RuntimeError("No English-to-Chinese model found in Argos index")
        package.install_from_path(matches[0].download())
        languages = translate.get_installed_languages()
        english = next((x for x in languages if x.code == "en"), None)
        chinese = next((x for x in languages if x.code in ("zh", "zh-CN")), None)
        if not (english and chinese):
            raise RuntimeError("Language model was installed but is not usable")
    return english.get_translation(chinese)


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    articles = data.get("articles", [])
    if not isinstance(articles, list):
        raise ValueError("articles must be an array")

    # Process a fair share from every source, newest first, so each filter
    # gets translated titles as soon as possible.
    by_source = defaultdict(deque)
    for article in sorted(articles, key=lambda a: a.get("published", ""), reverse=True):
        if article.get("title") and not article.get("title_zh"):
            by_source[article.get("source") or "other"].append(article)
    count_left = sum(map(len, by_source.values()))
    if count_left == 0:
        print("All titles already have Chinese translations.")
        return 0
    print(f"Missing translations: {count_left}", flush=True)
    try:
        model = translator()
    except Exception as exc:
        print(f"WARNING: could not load free offline model: {exc}", file=sys.stderr)
        return 0  # Do not prevent RSS updates or publishing.

    sources = sorted(by_source)
    translated = 0
    started = time.monotonic()
    while translated < MAX_NEW_TITLES and any(by_source.values()):
        for source in sources:
            if translated >= MAX_NEW_TITLES:
                break
            if not by_source[source]:
                continue
            article = by_source[source].popleft()
            original = article["title"].strip()
            try:
                chinese = re.sub(r"\s+", " ", model.translate(original)).strip()
                if not HAN.search(chinese):
                    raise ValueError("Translation is not Chinese")
                article["title_zh"] = chinese
                translated += 1
            except Exception as exc:
                print(f"WARNING: skipping title in {source}: {exc}", file=sys.stderr)
            if time.monotonic() - started > 480:
                print("Stopping translation at eight-minute budget.")
                break
        if time.monotonic() - started > 480:
            break

    if translated:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"Translated {translated} new Chinese titles; remaining ~{count_left-translated}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
