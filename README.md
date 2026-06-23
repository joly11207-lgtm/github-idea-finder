# GitHub Idea Finder V1.3

一个极简 GitHub 项目发现工具：找项目、看懂项目、点击跳转，并支持收藏、已看、跳过、备注、标签。

V1.3 新增：**GitHub 持久化存储**。部署在 Streamlit Cloud 后，收藏夹、已看、跳过不再只保存在临时本地文件中，可以写回你的 GitHub 仓库。

## 功能

- 输入 keyword / topic
- 设置 star 范围，例如 1000-10000
- 调用 GitHub Search API 搜索仓库
- 展示项目名、stars、语言、更新时间、描述、topics、GitHub 链接
- 可选：读取 README 并用 OpenAI 生成一句话中文总结
- ✅ 标记已看
- ⭐ 收藏
- 🚫 跳过
- 📝 Notes
- 🏷 Tags
- 📁 导出 CSV
- 🔄 隐藏已看 / 已跳过 / 已收藏项目
- V1.3：支持把数据持久化到 GitHub 仓库分支

## 安装

```bash
pip install -r requirements.txt
```

## 本地运行

```bash
python -m streamlit run app.py
```

本地默认使用：

```text
data/seen.csv
data/favorites.csv
data/ignored.csv
```

## Streamlit Cloud 部署

Main file path：

```text
app.py
```

## Secrets 配置

在 Streamlit Cloud：

```text
App → Settings → Secrets
```

推荐配置：

```toml
GITHUB_TOKEN="你的 GitHub token"
OPENAI_API_KEY="你的 OpenAI key"  # 可选，用于 AI 总结

# V1.3 GitHub 持久化存储
STORAGE_BACKEND="github"
GITHUB_STORAGE_REPO="joly11207-lgtm/github-idea-finder"
GITHUB_STORAGE_BRANCH="data-store"
GITHUB_STORAGE_BASE_BRANCH="main"
GITHUB_STORAGE_DIR="data"
GITHUB_STORAGE_TOKEN="你的 GitHub token"
```

### Token 权限

如果使用 Fine-grained personal access token：

- Repository access：选择 `joly11207-lgtm/github-idea-finder`
- Contents：Read and write
- Metadata：Read-only

`GITHUB_TOKEN` 可以只读；`GITHUB_STORAGE_TOKEN` 必须能写仓库内容。

## 为什么推荐 data-store 分支？

如果把收藏数据直接写到 `main` 分支，每次收藏/跳过都会触发 Streamlit Cloud 重新部署。

推荐写入：

```text
data-store
```

App 会自动检查这个分支；如果不存在，会从 `main` 创建它。

这样：

- 代码仍然在 `main`
- 数据保存在 `data-store`
- 收藏/跳过不会频繁触发主应用重新部署

## 使用建议

V1.3 的核心目标是把工具变成你的 GitHub Opportunity Inbox：

1. 搜索关键词，例如 `ocr`、`pdf`、`rag`、`automation`
2. 快速看项目
3. 收藏值得研究的项目
4. 跳过不感兴趣的项目
5. 给收藏项目写备注和标签
6. 以后把收藏夹导出，进入产品验证工作流
