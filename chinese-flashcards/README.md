# Words I've Looked Up

Turns a pile of Chinese-lookup screenshots into one dictionary and a flashcard deck.

Front of the card: the English word. Back: pinyin, the simplified characters set in
田字格 practice squares, the meaning, and an example sentence with its pinyin and
translation.

```
screenshots/  →  tools/extract.py  →  raw/*.json  ─┐
                                                   ├→ tools/build_deck.py → deck.json
                              vocab.json (by hand) ─┘                       anki.csv
                                                                            flashcards.html
```

## Getting screenshots in

The screenshots live in a phone gallery, so they have to be moved somewhere a script
can read. Any of these works:

1. **Google Drive** — on iOS, select the screenshots in Photos → Share → Save to Drive,
   into one folder. Claude can list that folder, pull the images down into
   `screenshots/`, and read them directly. Easiest from a phone.
2. **Straight into this folder** — AirDrop or copy them to a computer and drop them in
   `screenshots/`, then run the pipeline below.
3. **Paste into a conversation** — fine for a handful, tedious past twenty.

## Building the deck

```bash
pip install anthropic                 # only needed for extract.py
export ANTHROPIC_API_KEY=sk-ant-...
python3 tools/extract.py --estimate   # what it will cost; makes no API calls
python3 tools/extract.py --limit 40   # try a sample first
python3 tools/extract.py              # the rest
python3 tools/build_deck.py           # → deck.json, anki.csv, flashcards.html
open flashcards.html
```

### At camera-roll scale

A whole gallery is mostly not Chinese lookups, so `extract.py` runs two passes:

1. **Triage** — Claude Haiku answers one yes/no question per image: is there Chinese
   vocabulary being learned here? Images that fail are recorded in
   `raw/_no_vocabulary.json` and never looked at again.
2. **Extraction** — Claude Opus reads only the survivors, four per request.

Both passes run several requests in parallel (`--workers`) and are resumable: a
dropped connection or a failed batch costs you that batch, not the run. Rerunning
skips every image already extracted or already triaged out.

Rough cost, assuming a third of the roll has Chinese in it:

| screenshots | triage | extraction | total |
|---|---|---|---|
| 1,000 | $1.50 | $5.78 | **~$7** |
| 3,000 | $4.50 | $17.33 | **~$22** |
| 5,000 | $7.50 | $28.88 | **~$36** |

`--estimate` prints this for your actual folder. Run `--limit 40` first — it tells you
the real hit rate, which is the number the whole estimate hinges on.

Other flags: `--no-triage` extracts from every image (fine for small sets),
`--batch N` changes images per request, `--force` redoes everything.

`build_deck.py` validates every entry (pinyin has tone marks, not tone numbers;
characters are in the right field), drops duplicate headwords keeping whichever has an
example sentence, embeds the deck into `flashcards.html`, and writes an Anki-importable
CSV. Run it after any edit to `vocab.json`.

## Adding or fixing a word by hand

Edit `vocab.json` and re-run `build_deck.py`. One entry looks like:

```json
{
  "simplified": "顺便",
  "pinyin": "shùnbiàn",
  "english": "by the way; while you're at it",
  "pos": "adv",
  "example": {
    "simplified": "你去超市的时候，顺便帮我买点牛奶。",
    "pinyin": "Nǐ qù chāoshì de shíhou, shùnbiàn bāng wǒ mǎi diǎn niúnǎi.",
    "english": "When you go to the supermarket, grab me some milk while you're at it."
  }
}
```

`id` and `added` are filled in for you. Entries marked `"source": "sample"` are the
twelve placeholder words the app ships with; they disappear the moment real entries
exist.

## Using the app

Tap the card or press space to flip. `1` marks a word for another pass, `2` marks it
known — a 熟 seal stamps the corner. Words you miss go to the back of the pile.
Progress is stored in the browser, per device. The Dictionary tab lists everything and
searches characters, pinyin (with or without tone marks) or English.
