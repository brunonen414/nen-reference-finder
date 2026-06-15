"""Standalone CLIP SimpleTokenizer (torch-free) — produces the exact token ids
open_clip's ViT-B-32 tokenizer produces, so the server can encode queries for the
ONNX text encoder without importing torch/open_clip. Canonical OpenAI CLIP BPE."""
import gzip, html
from functools import lru_cache
import regex as re
import numpy as np


@lru_cache()
def bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + \
         list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(2 ** 8):
        if b not in bs:
            bs.append(b); cs.append(2 ** 8 + n); n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


def get_pairs(word):
    pairs = set(); prev = word[0]
    for ch in word[1:]:
        pairs.add((prev, ch)); prev = ch
    return pairs


def basic_clean(text):
    return html.unescape(html.unescape(text)).strip()


def whitespace_clean(text):
    return re.sub(r"\s+", " ", text).strip()


class SimpleTokenizer:
    def __init__(self, bpe_path, context_length=77):
        self.byte_encoder = bytes_to_unicode()
        merges = gzip.open(bpe_path).read().decode("utf-8").split("\n")
        merges = merges[1:49152 - 256 - 2 + 1]
        merges = [tuple(m.split()) for m in merges]
        vocab = list(bytes_to_unicode().values())
        vocab = vocab + [v + "</w>" for v in vocab]
        for m in merges:
            vocab.append("".join(m))
        vocab.extend(["<|startoftext|>", "<|endoftext|>"])
        self.encoder = dict(zip(vocab, range(len(vocab))))
        self.bpe_ranks = dict(zip(merges, range(len(merges))))
        self.cache = {"<|startoftext|>": "<|startoftext|>", "<|endoftext|>": "<|endoftext|>"}
        self.pat = re.compile(
            r"""<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|[\p{L}]+|[\p{N}]|[^\s\p{L}\p{N}]+""",
            re.IGNORECASE)
        self.sot = self.encoder["<|startoftext|>"]
        self.eot = self.encoder["<|endoftext|>"]
        self.context_length = context_length

    def bpe(self, token):
        if token in self.cache:
            return self.cache[token]
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        pairs = get_pairs(word)
        if not pairs:
            return token + "</w>"
        while True:
            bigram = min(pairs, key=lambda p: self.bpe_ranks.get(p, float("inf")))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram; newword = []; i = 0
            while i < len(word):
                try:
                    j = word.index(first, i); newword.extend(word[i:j]); i = j
                except ValueError:
                    newword.extend(word[i:]); break
                if word[i] == first and i < len(word) - 1 and word[i + 1] == second:
                    newword.append(first + second); i += 2
                else:
                    newword.append(word[i]); i += 1
            word = tuple(newword)
            if len(word) == 1:
                break
            pairs = get_pairs(word)
        word = " ".join(word); self.cache[token] = word
        return word

    def encode(self, text):
        out = []
        text = whitespace_clean(basic_clean(text)).lower()
        for token in re.findall(self.pat, text):
            token = "".join(self.byte_encoder[b] for b in token.encode("utf-8"))
            out.extend(self.encoder[bt] for bt in self.bpe(token).split(" "))
        return out

    def __call__(self, texts, context_length=None):
        if isinstance(texts, str):
            texts = [texts]
        cl = context_length or self.context_length
        out = np.zeros((len(texts), cl), dtype=np.int64)
        for i, t in enumerate(texts):
            tokens = [self.sot] + self.encode(t) + [self.eot]
            if len(tokens) > cl:
                tokens = tokens[:cl]; tokens[-1] = self.eot
            out[i, :len(tokens)] = tokens
        return out
