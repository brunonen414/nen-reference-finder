"""Compute a per-frame CONTENT-TYPE score using the CLIP image embeddings we already have.
Lets the search steer/boost by type (talking head vs UI vs motion-text vs b-roll vs logos),
which fixes jargon queries like 'talking head' that raw CLIP text mis-encodes.
Outputs: data/type_scores.npy (N x T), data/types.json, data/type_text_vecs.npy (T x 512)."""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "data")
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

TYPES = {
  "talking_head": ["a person talking directly to the camera", "a founder speaking on camera in an interview",
                   "a talking-head shot of one person speaking", "a person being interviewed on camera",
                   "a man or woman speaking to the camera indoors"],
  "people_group": ["several people in a video call grid", "a group of people together on screen",
                   "multiple people shown at once"],
  "ui":           ["a screenshot of a software user interface", "an app dashboard with panels and buttons",
                   "a website or product UI screenshot", "a computer screen showing an application", "a data table or settings page"],
  "motion_text":  ["large kinetic typography text on a plain background", "big bold words displayed on screen",
                   "a title card with text", "a caption or quote on a solid color background", "a big number graphic"],
  "broll":        ["cinematic b-roll footage of a place or object", "an atmospheric scene with no text or interface",
                   "a location, product, or environment shot", "a person doing an activity, not talking to camera"],
  "logos":        ["a wall of company or investor logos", "brand logos displayed on screen"],
}

img_emb = np.load(os.path.join(DATA, "img_emb.npy")).astype("float32")
print("img_emb:", img_emb.shape)

import torch, open_clip
m, _, _ = open_clip.create_model_and_transforms("ViT-B-32-quickgelu", pretrained="openai"); m.eval()
tok = open_clip.get_tokenizer("ViT-B-32-quickgelu")
names = list(TYPES.keys()); vecs = []
for n in names:
    with torch.no_grad():
        t = m.encode_text(tok(TYPES[n])).float()
        t = (t / t.norm(dim=-1, keepdim=True)).mean(0)
        t = t / t.norm()
    vecs.append(t.numpy())
V = np.stack(vecs).astype("float32")                 # T x 512
scores = img_emb @ V.T                               # N x T
np.save(os.path.join(DATA, "type_scores.npy"), scores.astype("float32"))
np.save(os.path.join(DATA, "type_text_vecs.npy"), V)
json.dump(names, open(os.path.join(DATA, "types.json"), "w"))

# quick sanity: distribution of primary type
prim = scores.argmax(1)
print("primary type counts:", {names[i]: int((prim == i).sum()) for i in range(len(names))})
print("saved type_scores", scores.shape)
