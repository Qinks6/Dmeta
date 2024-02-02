import os
import sys
import time
import hashlib
from tqdm import tqdm
import numpy as np
import requests

import logging
import functools
import tiktoken
from mteb import MTEB
#from sentence_transformers import SentenceTransformer
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

all_task_list = ['Classification', 'Clustering', 'Reranking', 'Retrieval', 'STS', 'PairClassification']
if len(sys.argv) > 1:
    task_list = [t for t in sys.argv[1].split(',') if t in all_task_list]
else:
    task_list = all_task_list

OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
EMB_CACHE_DIR = os.environ.get('EMB_CACHE_DIR', '.cache/embs')
os.makedirs(EMB_CACHE_DIR, exist_ok=True)

def uuid_for_text(text):
    return hashlib.md5(text.encode('utf8')).hexdigest()

def count_openai_tokens(text, model="text-embedding-3-large"):
    encoding = tiktoken.get_encoding("cl100k_base")
    #encoding = tiktoken.encoding_for_model(model)
    input_ids = encoding.encode(text)
    return len(input_ids)

def request_openai_emb(texts, model="text-embedding-3-large", 
        base_url='https://api.openai.com', prefix_url='/v1/embeddings', 
        timeout=120, retry=3, interval=60, caching=True):
    if isinstance(texts, str):
        texts = [texts]

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

    def __init__(self, model_name, model_dim, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_name = model_name
        self.model_dim = model_dim

    def encode(self, sentences, batch_size=32, **kwargs):
        i = 0
        max_tokens = 8000
        batch_tokens = 0
        batch = []
        batch_list = []
        while i < len(sentences):
            num_tokens = count_openai_tokens(sentences[i], 
                model=self.model_name)
            if batch_tokens+num_tokens > max_tokens:
                if batch:
                    batch_list.append(batch)
                    if num_tokens > max_tokens:
                        batch = [sentences[i][:2048]]
                        batch_tokens = count_openai_tokens(sentences[i][:2048],
                            model=self.model_name)
                    else:
                        batch = [sentences[i]]
                        batch_tokens = num_tokens
                else:
                    batch_list.append([sentences[i][:2048]])
            else:
                batch.append(sentences[i])
                batch_tokens += num_tokens
            i += 1
        if batch:
            batch_list.append(batch)
        #print(len(sentences), sum([len(x) for x in batch_list]))

        #batch_size = min(64, batch_size)
        #
        #for i in range(0, len(sentences), batch_size):
        #    batch_texts = sentences[i:i+batch_size]
        #    batch_list.append(batch_texts)

        embs = []
        waiting = 0
        for batch_i, batch_texts in enumerate(tqdm(batch_list)):
            batch_embs = request_openai_emb(batch_texts, model=self.model_name,
                caching=True, timeout=120, retry=3, interval=60)

            #assert len(batch_texts) == len(batch_embs), "The batch of texts and embs DONT match!"

            if len(batch_texts) == len(batch_embs):
                embs.extend(batch_embs)
                waiting = waiting // 2
            else:
                print(f"The batch-{batch_i} of texts and embs DONT match! {len(batch_texts)}:{len(batch_embs)}", file=sys.stderr)
                embs.extend([np.array([0.0 for j in range(self.model_dim)]) for i in range(len(batch_texts))])
                waiting = 120 if waiting <= 0 else waiting+120

            if waiting > 3600:
                print(f"Frequently failed, break down!", file=sys.stderr)
                break
            if waiting > 0:
                time.sleep(waiting)

        print(f'Encoded texts:embs={len(sentences)}:{len(embs)}')
        return embs


model_name = "text-embedding-3-large"
model_dim = 3072
model = OpenaiEmbModel(model_name, model_dim)

######
# test
#####
#embs = model.encode(['全国', '北京'])
#print(embs)
#exit()

# languages
task_langs=["zh", "zh-CN"]

evaluation = MTEB(task_types=task_list, task_langs=task_langs)
evaluation.run(model, output_folder=f"results/zh/{model_name.split('/')[-1]}")
