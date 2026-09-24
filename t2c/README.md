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
