# 贡献指南 / Contributing

> English below / 英文在下方

感谢关注 Vidance！欢迎通过 Issue 反馈问题、提交 PR 改进代码或文档。

## 提交 Issue

- **Bug**：请用 [Bug 报告模板](.github/ISSUE_TEMPLATE/bug_report.yml)，附上 `python core/vidance.py --version`、`python core/vidance.py doctor` 输出与报错日志
- **功能建议**：请用 [功能建议模板](.github/ISSUE_TEMPLATE/feature_request.yml)
- 提交前请先搜索是否已有同类 Issue

## 开发环境

```bash
git clone <your-fork-url> && cd vidance

# 最小依赖（纯 CPU 即可开发/跑测试，无需 GPU 与模型）
python -m venv .venv && source .venv/bin/activate
pip install numpy pillow fastapi faiss-cpu tenacity scipy onnxruntime pyyaml requests httpx

# 完整部署（GPU 档位、模型服务）见 README「按档位部署」与 docs/instructions/deploy-tiers.md
```

## 运行测试

18 套单测均为直跑脚本（无 pytest 依赖），模型缺失的测试会自动跳过：

```bash
for t in tests/test_*.py; do python "$t" || echo "FAIL: $t"; done
```

## 提交 PR

1. Fork → 建分支（`feat/xxx` 或 `fix/xxx`）→ 提交
2. 确保全部测试通过（CI 会自动跑 py3.10/py3.12 两档）
3. 填写 [PR 模板](.github/PULL_REQUEST_TEMPLATE.md) 检查清单
4. 新增功能请同步更新：`docs/usage/`、`CHANGELOG.md`、README（如影响快速开始）

## 代码约定（摘自 AGENTS.md，完整版见根目录）

- 产出统一落 `output/{时间戳}_{任务}/`，`/tmp` 只放临时文件
- 每次生成用随机 seed；单镜 ≤5s；视频编码统一 `yuv420p`
- `config/config.json` 入库的是**占位符模板**，真实 key 放 `config/config.local.json`（已 gitignore）——**严禁提交真实 key**（新配置项同步占位符模板）
- utils/ 薄壳转发真身在 agents/ 下的分层结构不要打破

---

# Contributing (English)

Thanks for your interest in Vidance! Feel free to open issues or submit pull requests.

## Opening Issues

- **Bugs**: use the [bug report form](.github/ISSUE_TEMPLATE/bug_report.yml); include `python core/vidance.py --version`, `python core/vidance.py doctor` output and error logs
- **Feature requests**: use the [feature request form](.github/ISSUE_TEMPLATE/feature_request.yml)
- Please search for existing issues first

## Dev Setup

```bash
git clone <your-fork-url> && cd vidance

# Minimal deps (pure CPU dev/test, no GPU or models needed)
python -m venv .venv && source .venv/bin/activate
pip install numpy pillow fastapi faiss-cpu tenacity scipy onnxruntime pyyaml requests httpx

# Full deployment (GPU tiers, model services) see README "Deployment" and docs/instructions/deploy-tiers.md
```

## Running Tests

The 18 test suites are standalone scripts (no pytest); model-dependent tests skip automatically when models are missing:

```bash
for t in tests/test_*.py; do python "$t" || echo "FAIL: $t"; done
```

## Submitting PRs

1. Fork → branch (`feat/xxx` / `fix/xxx`) → commit
2. Make sure all tests pass (CI runs py3.10/py3.12 automatically)
3. Fill in the [PR template](.github/PULL_REQUEST_TEMPLATE.md) checklist
4. For new features, update `docs/usage/`, `CHANGELOG.md`, and the README quick-start if affected

## Conventions (excerpt from AGENTS.md, full version in repo root)

- All artifacts go to `output/{timestamp}_{task}/`; `/tmp` is for temp files only
- Random seed per generation; shots ≤5s; video encoded as `yuv420p`
- `config/config.json` is committed as a **placeholder template**; real keys live in `config/config.local.json` (gitignored) — **never commit real keys** (keep new config items in sync with the placeholder template)
- Keep the thin-shell utils/ → agents/ layering intact
