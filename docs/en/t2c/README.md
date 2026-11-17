> English | [简体中文](../../../t2c/README.md)

# Vidance Natural Language to Command (T2C)

Chinese input -> Vidance CLI command. Model: fine-tuned mt5-small.

## Install
conda create -n t2c python=3.12 -y && conda activate t2c
pip install -r requirements.txt   # in mainland China, add -i https://pypi.tuna.tsinghua.edu.cn/simple

## Usage
python t2c.py 'help me generate a city nightscape video in auto mode'
# Output: python core/vidance.py auto "城市夜景"

python t2c.py            # interactive mode, type q to quit

Runs on CPU (no GPU needed); uses a GPU automatically when available.

## Training corpus (retraining data source)

- `t2c/corpus.jsonl`: the accumulated "spoken Chinese → vidance command" pairs of this repo; extended in step with every new command each version adds.
- Each jsonl line is `{text, command, tag}`; commands use the uniform `python core/vidance.py …` form (the UI auto-converts them to slash commands).
- Retraining flow: retrain mt5 on corpus.jsonl (+ old data from the historical training machine) → replace `t2c/model` → `restart api`.
