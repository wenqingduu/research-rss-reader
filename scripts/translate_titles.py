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
MAX_NEW_TITLES = 900  # The eight-minute runtime guard still applies.
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


def normalize_tech_terms(english: str, chinese: str) -> str:
    """Preserve common AI product names and correct frequent technical mistranslations."""
    replacements = [
        (r"\bGemini\b", [("双子座", "Gemini")]),
        (r"\bClaude\b", [("克劳德", "Claude"), ("克劳蒂", "Claude")]),
        (r"\bOpenAI\b", [("开放人工智能", "OpenAI")]),
        (r"\bAgent(?:s|ic)?\b", [("特工", "智能体"), ("代理人", "智能体")]),
        (r"\bBayesian\b", [("巴伊西亚", "贝叶斯")]),
        (r"\bstartups?\b", [("启动的", "初创企业的")]),
        (r"\blaunch\b", [("发射", "发布")]),
    ]
    for pattern, fixes in replacements:
        if re.search(pattern, english, re.I):
            for wrong, right in fixes:
                chinese = chinese.replace(wrong, right)
    return chinese


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
    corrections = 0
    for article in articles:
        if article.get("title_zh") and article.get("title"):
            fixed = normalize_tech_terms(article["title"], article["title_zh"])
            if fixed != article["title_zh"]:
                article["title_zh"] = fixed
                corrections += 1
    if count_left == 0:
        if corrections:
            DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"All titles translated; refined {corrections} existing Chinese titles.")
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
                chinese = normalize_tech_terms(original, re.sub(r"\s+", " ", model.translate(original)).strip())
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

    if translated or corrections:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"Translated {translated} new Chinese titles; remaining ~{count_left-translated}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
