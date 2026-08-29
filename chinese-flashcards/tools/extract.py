#!/usr/bin/env python3
"""Read Chinese-vocabulary screenshots and write dictionary entries to raw/.

Each screenshot is usually a ChatGPT lookup of one word or a sentence containing
it. Claude reads the image, picks out the word that was actually being looked up,
and fills in pinyin, meaning and a usable example sentence.

    export ANTHROPIC_API_KEY=sk-ant-...
    pip install anthropic
    python3 tools/extract.py                  # everything in screenshots/
    python3 tools/extract.py --batch 3        # fewer images per request
    python3 tools/extract.py --force          # redo screenshots already done

Then run tools/build_deck.py to fold the results into the deck.
"""
import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "screenshots"
RAW = ROOT / "raw"
MODEL = "claude-opus-5"
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".webp": "image/webp"}

SYSTEM = """You are building a personal Chinese vocabulary dictionary from a learner's screenshots.

Most screenshots are ChatGPT conversations where the learner looked up a word, or a
sentence containing a word they didn't know. Some are dictionary apps, textbook pages,
subtitles or signs.

For each screenshot, identify the word or words the learner was actually looking up —
the subject of the lookup, not every Chinese character on screen. Skip UI chrome,
app names, and words that are only incidental context.

For each word return:
- simplified: the headword in simplified characters (convert traditional if needed)
- pinyin: tone marks, not tone numbers (shùnbiàn, never shun4bian4); lowercase except
  proper nouns; syllables of one word joined (chàbuduō)
- english: a concise gloss, semicolon-separated if there are distinct senses
- pos: short part of speech (n, v, adj, adv, n/v, measure word, ...)
- example: a short natural sentence using the word. Prefer the sentence from the
  screenshot when there is one; otherwise write one an adult learner would actually
  say. Give it in simplified characters, tone-marked pinyin, and English.

Skip a screenshot entirely if it contains no Chinese vocabulary being learned.
Never invent a word that is not on screen."""

SCHEMA = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "simplified": {"type": "string"},
                    "pinyin": {"type": "string"},
                    "english": {"type": "string"},
                    "pos": {"type": "string"},
                    "source_image": {"type": "string"},
                    "example": {
                        "type": "object",
                        "properties": {
                            "simplified": {"type": "string"},
                            "pinyin": {"type": "string"},
                            "english": {"type": "string"},
                        },
                        "required": ["simplified", "pinyin", "english"],
                        "additionalProperties": False,
                    },
                },
                "required": ["simplified", "pinyin", "english", "pos", "source_image", "example"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entries"],
    "additionalProperties": False,
}


def batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=4, help="images per request (default 4)")
    ap.add_argument("--force", action="store_true", help="re-extract already-processed images")
    args = ap.parse_args()

    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")

    RAW.mkdir(exist_ok=True)
    done = set()
    if not args.force:
        for path in RAW.glob("*.json"):
            for entry in json.loads(path.read_text(encoding="utf-8")).get("entries", []):
                done.add(entry.get("source_image", ""))

    images = [p for p in sorted(SHOTS.iterdir())
              if p.suffix.lower() in MEDIA and p.name not in done]
    if not images:
        sys.exit(f"Nothing to do — put screenshots in {SHOTS}/ (or pass --force).")

    client = anthropic.Anthropic()
    total = 0
    for n, batch in enumerate(batches(images, args.batch), start=1):
        content = []
        for path in batch:
            content.append({"type": "text", "text": f"Screenshot: {path.name}"})
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": MEDIA[path.suffix.lower()],
                    "data": base64.standard_b64encode(path.read_bytes()).decode(),
                },
            })
        content.append({"type": "text", "text": (
            "Extract the vocabulary from these screenshots. Set source_image on every "
            "entry to the filename given above that image.")})

        print(f"[{n}] reading {', '.join(p.name for p in batch)} ...", flush=True)
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        entries = json.loads(text)["entries"]
        for entry in entries:
            entry["source"] = entry.get("source_image") or batch[0].name
        out = RAW / f"batch-{n:04d}.json"
        out.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        total += len(entries)
        print(f"    {len(entries)} word(s) → {out.name}")

    print(f"\n{total} words from {len(images)} screenshots. Now run: python3 tools/build_deck.py")


if __name__ == "__main__":
    main()
