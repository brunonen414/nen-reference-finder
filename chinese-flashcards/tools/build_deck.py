#!/usr/bin/env python3
"""Merge, validate and dedupe vocab.json -> deck.json, anki.csv, and the flashcard app.

Reads vocab.json plus any raw/*.json produced by extraction, drops the shipped
sample entries once real ones exist, and writes the deck into flashcards.html
between the DECK markers so the app is a single self-contained file.

    python3 tools/build_deck.py
"""
import csv
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB = ROOT / "vocab.json"
RAW = ROOT / "raw"
DECK = ROOT / "deck.json"
ANKI = ROOT / "anki.csv"
APP = ROOT / "flashcards.html"

REQUIRED = ("simplified", "pinyin", "english")
HANZI = re.compile(r"[一-鿿]")
# Pinyin written with tone marks: letters plus the combining diacritics, ü, spaces, punctuation.
TONED = re.compile(r"^[a-zA-ZüÜÀ-ɏǕ-ǜ\s',.!?;:\-·]+$")


def slug(simplified: str, pinyin: str) -> str:
    """Stable id from the toneless pinyin, falling back to a codepoint tag."""
    bare = unicodedata.normalize("NFD", pinyin)
    bare = "".join(c for c in bare if unicodedata.category(c) != "Mn")
    bare = re.sub(r"[^a-z]+", "", bare.lower().replace("ü", "v"))
    if bare:
        return bare
    return "w" + "".join(f"{ord(c):x}" for c in simplified)


def load_entries():
    entries, seen_files = [], []
    if VOCAB.exists():
        entries += json.loads(VOCAB.read_text(encoding="utf-8")).get("entries", [])
        seen_files.append(VOCAB.name)
    for path in sorted(RAW.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        batch = blob.get("entries", blob) if isinstance(blob, dict) else blob
        for entry in batch:
            entry.setdefault("source", path.stem)
        entries += batch
        seen_files.append(path.name)
    return entries, seen_files


def validate(entry, problems):
    where = entry.get("simplified") or entry.get("english") or "<blank>"
    for field in REQUIRED:
        if not str(entry.get(field, "")).strip():
            problems.append(f"{where}: missing '{field}'")
            return False
    if not HANZI.search(entry["simplified"]):
        problems.append(f"{where}: 'simplified' has no Chinese characters")
        return False
    if HANZI.search(entry["pinyin"]):
        problems.append(f"{where}: 'pinyin' contains Chinese characters")
        return False
    if not TONED.match(entry["pinyin"]):
        problems.append(f"{where}: 'pinyin' has unexpected characters — check tone marks")
    ex = entry.get("example") or {}
    if ex and not all(str(ex.get(k, "")).strip() for k in REQUIRED):
        problems.append(f"{where}: example is present but incomplete")
    return True


def main():
    entries, files = load_entries()
    if not entries:
        sys.exit("No entries found. Add words to vocab.json or drop batches in raw/.")

    real = [e for e in entries if e.get("source") != "sample"]
    if real:
        dropped = len(entries) - len(real)
        entries = real
        if dropped:
            print(f"Dropped {dropped} sample entries — real vocabulary present.")

    problems, deck, by_id = [], [], {}
    for entry in entries:
        if not validate(entry, problems):
            continue
        entry["id"] = entry.get("id") or slug(entry["simplified"], entry["pinyin"])
        entry.setdefault("added", date.today().isoformat())
        key = entry["simplified"]
        if key in by_id:
            # Same headword seen twice: keep the one with an example sentence.
            kept = by_id[key]
            if entry.get("example") and not kept.get("example"):
                deck[deck.index(kept)] = entry
                by_id[key] = entry
            continue
        by_id[key] = entry
        deck.append(entry)

    deck.sort(key=lambda e: e["id"])
    DECK.write_text(json.dumps({"built": date.today().isoformat(), "count": len(deck),
                                "cards": deck}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")

    with ANKI.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Front (English)", "Back (Chinese)", "Pinyin", "Example", "Example pinyin",
                    "Example English"])
        for e in deck:
            ex = e.get("example") or {}
            w.writerow([e["english"], e["simplified"], e["pinyin"], ex.get("simplified", ""),
                        ex.get("pinyin", ""), ex.get("english", "")])

    if APP.exists():
        html = APP.read_text(encoding="utf-8")
        payload = json.dumps(deck, ensure_ascii=False, indent=2)
        new, n = re.subn(r"(/\* DECK:START \*/)(.*?)(/\* DECK:END \*/)",
                         lambda m: f"{m.group(1)}\nconst DECK = {payload};\n{m.group(3)}",
                         html, flags=re.S)
        if n:
            APP.write_text(new, encoding="utf-8")
            print(f"Embedded {len(deck)} cards into {APP.name}")
        else:
            print(f"Warning: DECK markers not found in {APP.name} — app not updated.")

    print(f"Read {', '.join(files)} → {len(deck)} cards in deck.json and anki.csv")
    if problems:
        print(f"\n{len(problems)} thing(s) to look at:")
        for p in problems:
            print(f"  - {p}")


if __name__ == "__main__":
    main()
