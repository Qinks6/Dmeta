import os
import sys
import time
import hashlib
import numpy as np
import requests

import logging
import functools
from mteb import MTEB
from sentence_transformers import SentenceTransformer
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
EMB_CACHE_DIR = os.environ.get('EMB_CACHE_DIR', '.cache/embs')
os.makedirs(EMB_CACHE_DIR, exist_ok=True)


def uuid_for_text(text):
    return hashlib.md5(text.encode('utf8')).hexdigest()

def request_openai_emb(texts, model="text-embedding-3-large", 
        base_url='https://api.openai.com', prefix_url='/v1/embeddings', 
        timeout=4, retry=3, interval=2, caching=True):
    if isinstance(texts, str):
        texts = [texts]
    assert len(texts) <= 256

    data = []
    if caching:
        for text in texts:
            emb_file = f"{EMB_CACHE_DIR}/{uuid_for_text(text)}"
            if os.path.isfile(emb_file) and os.path.getsize(emb_file) > 0:
                data.append(np.loadtxt(emb_file))
        if len(texts) == len(data):
            return data

    url = f"{OPENAI_BASE_URL}{prefix_url}" if OPENAI_BASE_URL else f"{base_url}{prefix_url}"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"input": texts, "model": model}

    while retry > 0 and len(data) == 0:
        try:
            r = requests.post(url, headers=headers, json=payload, 
                timeout=timeout)
            res = r.json()
            for x in res["data"]:
                data.append(np.array(x["embedding"]))
        except Exception as e:
            print(f"request openai, retry {retry}, error: {e}", file=sys.stderr)
        time.sleep(interval)
        retry -= 1

    if len(data) != len(texts):
        data = []

    if caching and len(data) > 0:
        for text, emb in zip(texts, data):
            emb_file = f"{EMB_CACHE_DIR}/{uuid_for_text(text)}"
            np.savetxt(emb_file, emb)

    return data


class OpenaiEmbModel:

    def encode(self, sentences, batch_size=32, **kwargs):
        batch_size = min(64, batch_size)

        embs = []
        for i in range(0, len(sentences), batch_size):
            batch_texts = sentences[i:i+batch_size]
            batch_embs = request_openai_emb(batch_texts, 
                caching=True, retry=3, interval=2)
            assert len(batch_texts) == len(batch_embs), "The batch of texts and embs DONT match!"
            embs.extend(batch_embs)

        return embs


model = OpenaiEmbModel()

######
# test
#####
#embs = model.encode(['全国', '北京'])
#print(embs)

# task_list
task_list = ['Classification', 'Clustering', 'Reranking', 'Retrieval', 'STS', 'PairClassification']
# languages
task_langs=["zh", "zh-CN"]

evaluation = MTEB(task_types=task_list, task_langs=task_langs)
evaluation.run(model, output_folder=f"results/zh/{model_name.split('/')[-1]}")
