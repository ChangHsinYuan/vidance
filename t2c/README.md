# Vidance 自然语言转命令 (T2C)

中文输入 -> Vidance CLI 命令。模型: mt5-small 微调。

## 安装
conda create -n t2c python=3.12 -y && conda activate t2c
pip install -r requirements.txt   # 国内可加 -i https://pypi.tuna.tsinghua.edu.cn/simple

## 使用
python t2c.py '帮我用auto模式生成一个城市夜景的视频'
# 输出: python core/vidance.py auto "城市夜景"

python t2c.py            # 交互模式，输入 q 退出

CPU 即可运行（无需 GPU），有 GPU 自动使用。

## 训练语料（重训数据源）

- `t2c/corpus.jsonl`：本仓库累积的「中文口语 → vidance 命令」配对，逐版指令新增时同步补写。
- jsonl 每行 `{text, command, tag}`；command 统一 `python core/vidance.py …` 形态（UI 会自动转斜杠命令）。
- 重训流程：以 corpus.jsonl（+ 历史训练机旧数据）重训 mt5 → 替换 `t2c/model` → `restart api`。
