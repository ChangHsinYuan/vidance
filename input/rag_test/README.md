# RAG 小说问答测试材料

## 文件
- `nahan.txt` — 鲁迅《吶喊》全文（Project Gutenberg #27166，公版，繁体，281KB）
- `rag_qa_test.py` — 自动化端到端测试脚本（检索→组上下文→LLM 问答）

## 快速开始（三种姿势）

### 姿势一：网页 UI（最直观）
1. 打开 http://127.0.0.1:8894/ui
2. 输入框输入：`/rag search 孔乙己的长衫 --key 454eb1f2`
3. 或直接问：`孔乙己为什么"站着喝酒而穿长衫"？`（聊天链路自动检索注入）
4. 容器端口换成 http://127.0.0.1:9401/ui 同样可用

### 姿势二：命令行直测
```bash
cd /mnt/disk_sdb/zxy/vidance

# 1. 上传建索引（一次性，~2 分钟：embedding 237 chunk CPU + LLM 抽人物卡）
curl -F "file=@input/rag_test/nahan.txt" http://127.0.0.1:8894/api/rag/upload
# 返回 {"doc_key": "…", "indexing": true} —— 记下 doc_key

# 2. 轮询直到 indexed:true（人物卡最后完成）
curl -s "http://127.0.0.1:8894/api/rag/status?doc_key=<你的doc_key>"

# 3. 检索测试
curl -s "http://127.0.0.1:8894/api/rag/search?q=华老栓买的什么药&k=3&doc_key=<你的doc_key>"

# 4. 自动化问答（3 道题，编辑脚本里的 KEY 换成你的 doc_key）
python input/rag_test/rag_qa_test.py
```

### 姿势三：跑现成自动化测试
```bash
# 本材料的端到端问答（需改脚本内 KEY）
python input/rag_test/rag_qa_test.py

# 代码级单测（46 项，不连 LLM）
python tests/test_rag.py        # 基础 21 项
python tests/test_rag_novel.py  # 小说 25 项（含篇名切分/人物卡采样）
```

## 当前已建好的索引
- doc_key: `454eb1f2826b56685bf7ab155c6eb06e`（就是 nahan.txt 的 md5）
- 14 篇章 / 195 chunks / 8 张人物卡（孔乙己/华老栓/狂人/N先生/方玄绰/陈士成等）
- 查看全部索引：`curl -s http://127.0.0.1:8894/api/rag/status`

## 概念说明
- **doc_key**：文档在本地索引库的档案号（内容 md5），不是 API key
- **API key**：你的 LLM 服务密钥，在 config/config.json 的 llm.api_key
- 同一文件重复上传不会重建索引（md5 命中缓存直接返回）
