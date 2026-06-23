# GitHub Idea Finder V1.6

一个个人用的 GitHub 项目发现工具：找项目、看懂项目、点击跳转，并支持收藏、已看、跳过、备注、标签、GitHub 持久化、OpenRouter AI 分析、Smart Refill 与数据统计。

## V1.6 新增

- 隐藏页面上的 API Key 输入框
- 自动从 Streamlit Secrets / 环境变量读取：
  - `GITHUB_TOKEN`
  - `OPENAI_API_KEY`
  - `OPENROUTER_API_KEY`
- 只在页面显示 OpenRouter 模型选择
- 新增顶部统计面板：收藏、已看、跳过、累计项目

## 已有功能

- GitHub Search：按 keyword / topic / stars / language 搜项目
- Smart Refill：过滤已看、收藏、跳过后自动补足结果数
- GitHub 持久化存储：收藏、已看、跳过、备注、标签写回 `data-store` 分支
- OpenRouter AI 分析：对单个 GitHub 项目生成创业角度分析
- CSV 导出

## Streamlit Secrets 示例

```toml
STORAGE_BACKEND="github"
GITHUB_STORAGE_REPO="joly11207-lgtm/github-idea-finder"
GITHUB_STORAGE_BRANCH="data-store"
GITHUB_STORAGE_BASE_BRANCH="main"
GITHUB_STORAGE_DIR="data"
GITHUB_STORAGE_TOKEN="你的 GitHub fine-grained token"

GITHUB_TOKEN="你的 GitHub token，可选但推荐"
OPENROUTER_API_KEY="你的 OpenRouter key"
OPENROUTER_MODEL="openai/gpt-oss-20b:free"
OPENAI_API_KEY="你的 OpenAI key，可选"
```

## 运行

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```
