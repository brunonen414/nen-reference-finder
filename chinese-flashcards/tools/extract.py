#!/usr/bin/env python3
"""Read Chinese-vocabulary screenshots and write dictionary entries to raw/.

Each screenshot is usually a ChatGPT lookup of one word or a sentence containing
it. Claude reads the image, picks out the word that was actually being looked up,
and fills in pinyin, meaning and a usable example sentence.

Built for a camera roll, not a handful: a cheap triage pass throws out the
screenshots with no Chinese vocabulary in them before the expensive pass runs, and
both passes are resumable — rerun after a dropped connection and it picks up where
it stopped.

    export ANTHROPIC_API_KEY=sk-ant-...
    pip install anthropic
    python3 tools/extract.py                  # triage, then extract
    python3 tools/extract.py --no-triage      # extract every image (small sets)
    python3 tools/extract.py --workers 8      # more requests in flight
    python3 tools/extract.py --estimate       # what it would cost; makes no calls
    python3 tools/extract.py --limit 40       # stop after N images (try before you buy)
    python3 tools/extract.py --force          # redo screenshots already done

Then run tools/build_deck.py to fold the results into the deck.
"""
import argparse
import base64
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "screenshots"
RAW = ROOT / "raw"
MODEL = "claude-opus-5"
TRIAGE_MODEL = "claude-haiku-4-5"
SKIPPED = RAW / "_no_vocabulary.json"
# Rough per-image token cost of a phone screenshot, for --estimate only.
TOKENS_PER_IMAGE = 1500
PRICES = {  # $ per million tokens, input/output
    "claude-opus-5": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
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


TRIAGE_PROMPT = (
    "Does this screenshot show Chinese vocabulary that someone is learning or looking "
    "up — a word lookup, a translation, a dictionary entry, a sentence being explained, "
    "subtitles, or a sign being read? Answer with one word: YES or NO. Answer NO for "
    "screenshots with no Chinese text, and for Chinese text that is only interface "
    "chrome (menus, app names, buttons) rather than something being learned."
)


def block(path):
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": MEDIA[path.suffix.lower()],
            "data": base64.standard_b64encode(path.read_bytes()).decode(),
        },
    }


def triage(client, images, workers):
    """Cheap yes/no pass so the expensive model never sees a cat photo."""
    keep, drop, lock = [], [], threading.Lock()
    done = 0

    def check(path):
        nonlocal done
        try:
            r = client.messages.create(
                model=TRIAGE_MODEL, max_tokens=8,
                messages=[{"role": "user", "content": [block(path),
                                                       {"type": "text", "text": TRIAGE_PROMPT}]}],
            )
            yes = "YES" in "".join(b.text for b in r.content if b.type == "text").upper()
        except Exception as exc:                     # a failed check is not a verdict
            print(f"    ! {path.name}: {exc}", file=sys.stderr)
            yes = True                               # let the extraction pass decide
        with lock:
            (keep if yes else drop).append(path)
            done += 1
            if done % 25 == 0 or done == len(images):
                print(f"    triaged {done}/{len(images)} — keeping {len(keep)}", flush=True)

    print(f"Triage: checking {len(images)} screenshots with {TRIAGE_MODEL} ...", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(check, images))

    if drop:
        previous = []
        if SKIPPED.exists():
            previous = json.loads(SKIPPED.read_text(encoding="utf-8"))
        SKIPPED.write_text(
            json.dumps(sorted(set(previous) | {p.name for p in drop}), indent=2) + "\n",
            encoding="utf-8")
    print(f"    {len(keep)} with vocabulary, {len(drop)} set aside "
          f"(listed in {SKIPPED.name})\n")
    return sorted(keep)


def estimate(count):
    ti, to = PRICES[TRIAGE_MODEL]
    ei, eo = PRICES[MODEL]
    triage_cost = count * TOKENS_PER_IMAGE / 1e6 * ti
    # Assume roughly a third survive triage, ~400 output tokens each.
    kept = max(1, round(count * 0.33))
    extract_cost = kept * TOKENS_PER_IMAGE / 1e6 * ei + kept * 400 / 1e6 * eo
    print(f"{count} screenshots")
    print(f"  triage   ({TRIAGE_MODEL}):  ~${triage_cost:.2f}")
    print(f"  extract  ({MODEL}, ~{kept} kept): ~${extract_cost:.2f}")
    print(f"  total:                      ~${triage_cost + extract_cost:.2f}")
    print("\nVery rough — real cost depends on how many screenshots actually have "
          "Chinese in them.\nRun with --limit 40 first to see the real hit rate.")


def batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=4, help="images per request (default 4)")
    ap.add_argument("--workers", type=int, default=4, help="requests in flight (default 4)")
    ap.add_argument("--no-triage", action="store_true",
                    help="skip the cheap filter and extract from every image")
    ap.add_argument("--limit", type=int, help="stop after N unprocessed images")
    ap.add_argument("--estimate", action="store_true",
                    help="print a rough cost and exit without calling the API")
    ap.add_argument("--force", action="store_true", help="re-extract already-processed images")
    args = ap.parse_args()

    RAW.mkdir(exist_ok=True)
    done = set()
    if not args.force:
        for path in RAW.glob("*.json"):
            if path.name == SKIPPED.name:
                continue
            for entry in json.loads(path.read_text(encoding="utf-8")).get("entries", []):
                done.add(entry.get("source_image", ""))
        if SKIPPED.exists():
            done |= set(json.loads(SKIPPED.read_text(encoding="utf-8")))

    images = [p for p in sorted(SHOTS.iterdir())
              if p.suffix.lower() in MEDIA and p.name not in done]
    if args.limit:
        images = images[:args.limit]
    if not images:
        sys.exit(f"Nothing to do — put screenshots in {SHOTS}/ (or pass --force).")

    if args.estimate:
        return estimate(len(images))

    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    client = anthropic.Anthropic()

    if not args.no_triage:
        images = triage(client, images, args.workers)
        if not images:
            sys.exit("No screenshots with Chinese vocabulary in them.")

    groups = list(batches(images, args.batch))
    existing = len(list(RAW.glob("batch-*.json")))
    lock = threading.Lock()
    counts = []

    def run(job):
        n, group = job
        content = []
        for path in group:
            content.append({"type": "text", "text": f"Screenshot: {path.name}"})
            content.append(block(path))
        content.append({"type": "text", "text": (
            "Extract the vocabulary from these screenshots. Set source_image on every "
            "entry to the filename given above that image.")})

        try:
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
        except Exception as exc:
            # One failed batch must not lose the rest; rerun picks it up next time.
            print(f"[{n}] failed ({exc}) — will retry on the next run", file=sys.stderr)
            return

        for entry in entries:
            entry["source"] = entry.get("source_image") or group[0].name
        out = RAW / f"batch-{n:04d}.json"
        out.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        with lock:
            counts.append(len(entries))
            print(f"[{len(counts)}/{len(groups)}] {out.name}: {len(entries)} word(s) "
                  f"from {', '.join(p.name for p in group)}", flush=True)

    jobs = [(existing + i, g) for i, g in enumerate(groups, start=1)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, jobs))

    print(f"\n{sum(counts)} words from {len(images)} screenshots. "
          f"Now run: python3 tools/build_deck.py")


if __name__ == "__main__":
    main()
