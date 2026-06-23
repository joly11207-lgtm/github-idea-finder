import base64
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

load_dotenv()

GITHUB_API = "https://api.github.com"
DATA_DIR = Path("data")
STORE_COLUMNS = ["repo", "github_url", "stars", "language", "note", "tags", "created_at"]
STORE_FILES = {
    "seen": "seen.csv",
    "favorites": "favorites.csv",
    "ignored": "ignored.csv",
}

st.set_page_config(
    page_title="GitHub Idea Finder V1.3",
    page_icon="🔎",
    layout="wide",
)


def get_secret(name: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets.get(name)  # type: ignore[attr-defined]
        if value is not None:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)


# -----------------------------
# GitHub API helpers
# -----------------------------

def github_headers(token: str = "") -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@st.cache_data(ttl=60 * 30, show_spinner=False)
def github_get(url: str, token: str = "", params: Optional[Dict] = None) -> Dict:
    resp = requests.get(url, headers=github_headers(token), params=params, timeout=30)
    if resp.status_code == 403:
        reset = resp.headers.get("X-RateLimit-Reset")
        reset_text = ""
        if reset and reset.isdigit():
            reset_text = datetime.fromtimestamp(int(reset)).strftime("%Y-%m-%d %H:%M:%S")
        raise RuntimeError(f"GitHub API rate limited or forbidden. Reset: {reset_text or 'unknown'}")
    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def github_request(method: str, url: str, token: str = "", **kwargs) -> requests.Response:
    resp = requests.request(method, url, headers=github_headers(token), timeout=30, **kwargs)
    return resp


@st.cache_data(ttl=60 * 60, show_spinner=False)
def fetch_readme(owner: str, repo: str, token: str = "") -> str:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/readme"
    data = github_get(url, token=token)
    content = data.get("content", "")
    encoding = data.get("encoding", "")
    if encoding == "base64" and content:
        return base64.b64decode(content).decode("utf-8", errors="ignore")
    return ""


# -----------------------------
# Persistent storage
# -----------------------------

def empty_store() -> pd.DataFrame:
    return pd.DataFrame(columns=STORE_COLUMNS)


def normalize_store(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_store()
    for col in STORE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[STORE_COLUMNS].fillna("")


class Storage:
    def __init__(self) -> None:
        self.backend = get_secret("STORAGE_BACKEND", "local").strip().lower() or "local"
        self.repo = get_secret("GITHUB_STORAGE_REPO", "").strip()
        self.branch = get_secret("GITHUB_STORAGE_BRANCH", "main").strip() or "main"
        self.token = get_secret("GITHUB_STORAGE_TOKEN", "").strip()
        self.base_branch = get_secret("GITHUB_STORAGE_BASE_BRANCH", "main").strip() or "main"
        self.data_dir = get_secret("GITHUB_STORAGE_DIR", "data").strip().strip("/") or "data"
        self.github_enabled = self.backend == "github" and self.repo and self.token
        if not self.github_enabled:
            self.backend = "local"

    def label(self) -> str:
        if self.github_enabled:
            return f"GitHub: {self.repo}@{self.branch}/{self.data_dir}"
        return "Local CSV: ./data"

    def ensure(self) -> None:
        if self.github_enabled:
            self.ensure_github_branch()
            for filename in STORE_FILES.values():
                self.ensure_github_file(filename)
        else:
            DATA_DIR.mkdir(exist_ok=True)
            for filename in STORE_FILES.values():
                path = DATA_DIR / filename
                if not path.exists():
                    empty_store().to_csv(path, index=False, encoding="utf-8-sig")

    def local_path(self, filename: str) -> Path:
        return DATA_DIR / filename

    def github_path(self, filename: str) -> str:
        return f"{self.data_dir}/{filename}"

    def ensure_github_branch(self) -> None:
        # If the data branch exists, do nothing. If not, create it from base_branch.
        ref_url = f"{GITHUB_API}/repos/{self.repo}/git/ref/heads/{self.branch}"
        resp = github_request("GET", ref_url, self.token)
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            raise RuntimeError(f"检查 GitHub 数据分支失败：{resp.status_code} {resp.text[:300]}")

        base_url = f"{GITHUB_API}/repos/{self.repo}/git/ref/heads/{self.base_branch}"
        base_resp = github_request("GET", base_url, self.token)
        if base_resp.status_code >= 400:
            raise RuntimeError(f"读取 base branch 失败：{base_resp.status_code} {base_resp.text[:300]}")
        sha = base_resp.json()["object"]["sha"]
        create_resp = github_request(
            "POST",
            f"{GITHUB_API}/repos/{self.repo}/git/refs",
            self.token,
            json={"ref": f"refs/heads/{self.branch}", "sha": sha},
        )
        if create_resp.status_code not in (200, 201):
            raise RuntimeError(f"创建 GitHub 数据分支失败：{create_resp.status_code} {create_resp.text[:300]}")

    def get_github_file(self, filename: str) -> Tuple[Optional[str], str]:
        path = self.github_path(filename)
        url = f"{GITHUB_API}/repos/{self.repo}/contents/{path}"
        resp = github_request("GET", url, self.token, params={"ref": self.branch})
        if resp.status_code == 404:
            return None, ""
        if resp.status_code >= 400:
            raise RuntimeError(f"读取 GitHub 存储文件失败：{resp.status_code} {resp.text[:300]}")
        data = resp.json()
        content = data.get("content", "")
        text = ""
        if data.get("encoding") == "base64" and content:
            text = base64.b64decode(content).decode("utf-8-sig", errors="ignore")
        return data.get("sha"), text

    def ensure_github_file(self, filename: str) -> None:
        sha, _ = self.get_github_file(filename)
        if sha:
            return
        self.put_github_file(filename, empty_store(), message=f"init {filename}")

    def put_github_file(self, filename: str, df: pd.DataFrame, message: str) -> None:
        path = self.github_path(filename)
        sha, _ = self.get_github_file(filename)
        csv_text = normalize_store(df).to_csv(index=False)
        payload = {
            "message": message,
            "content": base64.b64encode(csv_text.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha
        resp = github_request(
            "PUT",
            f"{GITHUB_API}/repos/{self.repo}/contents/{path}",
            self.token,
            json=payload,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"写入 GitHub 存储失败：{resp.status_code} {resp.text[:500]}")

    def load(self, key: str) -> pd.DataFrame:
        filename = STORE_FILES[key]
        self.ensure()
        if self.github_enabled:
            _, text = self.get_github_file(filename)
            if not text.strip():
                return empty_store()
            from io import StringIO
            return normalize_store(pd.read_csv(StringIO(text)))
        path = self.local_path(filename)
        try:
            return normalize_store(pd.read_csv(path))
        except Exception:
            return empty_store()

    def save(self, key: str, df: pd.DataFrame) -> None:
        filename = STORE_FILES[key]
        df = normalize_store(df)
        if self.github_enabled:
            self.put_github_file(filename, df, message=f"update {filename}")
        else:
            DATA_DIR.mkdir(exist_ok=True)
            df.to_csv(self.local_path(filename), index=False, encoding="utf-8-sig")


storage = Storage()


def load_store(key: str) -> pd.DataFrame:
    return storage.load(key)


def save_store(key: str, df: pd.DataFrame) -> None:
    storage.save(key, df)


def repo_set(key: str) -> set:
    df = load_store(key)
    if df.empty or "repo" not in df.columns:
        return set()
    return set(df["repo"].dropna().astype(str).tolist())


def upsert_repo(key: str, row: Dict, note: str = "", tags: str = "") -> None:
    df = load_store(key)
    repo_name = str(row.get("repo", ""))
    new_row = {
        "repo": repo_name,
        "github_url": row.get("github_url", ""),
        "stars": row.get("stars", ""),
        "language": row.get("language", ""),
        "note": note,
        "tags": tags,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if not df.empty and repo_name in set(df["repo"].astype(str)):
        for col, value in new_row.items():
            df.loc[df["repo"].astype(str) == repo_name, col] = value
    else:
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_store(key, df)


def remove_repo(key: str, repo_name: str) -> None:
    df = load_store(key)
    if not df.empty and "repo" in df.columns:
        df = df[df["repo"].astype(str) != str(repo_name)]
        save_store(key, df)


def mark_seen(row: Dict, note: str = "", tags: str = "") -> None:
    upsert_repo("seen", row, note=note, tags=tags)


def mark_favorite(row: Dict, note: str = "", tags: str = "") -> None:
    upsert_repo("favorites", row, note=note, tags=tags)
    upsert_repo("seen", row, note=note, tags=tags)
    remove_repo("ignored", str(row.get("repo", "")))


def mark_ignored(row: Dict, note: str = "", tags: str = "") -> None:
    upsert_repo("ignored", row, note=note, tags=tags)
    upsert_repo("seen", row, note=note, tags=tags)
    remove_repo("favorites", str(row.get("repo", "")))


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def summarize_project(repo: Dict, readme: str, openai_key: str = "") -> str:
    description = repo.get("description") or ""
    topics = ", ".join(repo.get("topics") or [])
    language = repo.get("language") or ""

    if not openai_key or OpenAI is None:
        pieces = []
        if description:
            pieces.append(description)
        if language:
            pieces.append(f"主要语言：{language}")
        if topics:
            pieces.append(f"Topics：{topics}")
        return "；".join(pieces)[:300] or "暂无摘要"

    client = OpenAI(api_key=openai_key)
    readme_excerpt = readme[:6000]
    prompt = f"""
你是产品研究助手。请根据 GitHub 仓库信息，用中文输出一句话总结：这个项目是做什么的、主要帮谁解决什么问题。

要求：
- 只输出一句话
- 不要创业建议
- 不要评分
- 不要夸张
- 不确定就说“从描述看，似乎是...”。

仓库名：{repo.get('full_name')}
描述：{description}
语言：{language}
Topics：{topics}
README 摘录：
{readme_excerpt}
""".strip()

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=160,
        )
        return res.choices[0].message.content.strip()
    except Exception as exc:
        return f"AI 总结失败：{exc}"


def build_query(keyword: str, min_stars: int, max_stars: int, language: str, topic_mode: bool) -> str:
    parts = [f"stars:{min_stars}..{max_stars}"]
    keyword = keyword.strip()
    if keyword:
        if topic_mode:
            parts.append(f"topic:{keyword}")
        else:
            parts.append(keyword)
    if language and language != "Any":
        parts.append(f"language:{language}")
    return " ".join(parts)


def search_repos(query: str, sort: str, per_page: int, pages: int, token: str) -> List[Dict]:
    results: List[Dict] = []
    for page in range(1, pages + 1):
        params = {
            "q": query,
            "sort": sort,
            "order": "desc",
            "per_page": per_page,
            "page": page,
        }
        data = github_get(f"{GITHUB_API}/search/repositories", token=token, params=params)
        items = data.get("items", [])
        results.extend(items)
        if len(items) < per_page:
            break
        time.sleep(0.2)
    return results


def repo_to_row(repo: Dict, summary: str) -> Dict:
    return {
        "repo": repo.get("full_name"),
        "stars": repo.get("stargazers_count"),
        "language": repo.get("language"),
        "updated_at": repo.get("updated_at", "")[:10],
        "description": repo.get("description") or "",
        "topics": ", ".join(repo.get("topics") or []),
        "what_it_does": summary,
        "github_url": repo.get("html_url"),
    }


def row_to_dict(row: pd.Series) -> Dict:
    return {
        "repo": row.get("repo", ""),
        "github_url": row.get("github_url", ""),
        "stars": row.get("stars", ""),
        "language": row.get("language", ""),
    }


def render_saved_table(title: str, key: str, allow_remove: bool = True) -> None:
    st.subheader(title)
    df = load_store(key)
    if df.empty:
        st.info("暂无数据。")
        return

    for _, row in df.iterrows():
        repo_name = str(row.get("repo", ""))
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"### [{repo_name}]({row.get('github_url', '')})")
                st.caption(f"⭐ {row.get('stars', '')} | {row.get('language', '')} | {row.get('created_at', '')}")
                if str(row.get("tags", "")).strip():
                    st.write(f"🏷 {row.get('tags', '')}")
                if str(row.get("note", "")).strip():
                    st.write(f"📝 {row.get('note', '')}")
            with c2:
                st.link_button("打开 GitHub", row.get("github_url", ""), use_container_width=True)
                if allow_remove:
                    if st.button("移除", key=f"remove_{key}_{repo_name}", use_container_width=True):
                        remove_repo(key, repo_name)
                        st.rerun()

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        f"下载 {title} CSV",
        data=csv,
        file_name=STORE_FILES[key],
        mime="text/csv",
        key=f"download_{key}",
    )


# -----------------------------
# UI
# -----------------------------

try:
    storage.ensure()
except Exception as exc:
    st.error(f"存储初始化失败：{exc}")
    st.info("如果你在 Streamlit Cloud 上使用 GitHub 持久化，请检查 Secrets 里的 GITHUB_STORAGE_TOKEN / GITHUB_STORAGE_REPO / GITHUB_STORAGE_BRANCH。")
    st.stop()

st.title("🔎 GitHub Idea Finder V1.3")
st.caption("找项目、看懂项目、点击跳转，并支持已看、收藏、跳过、备注、标签；V1.3 支持 GitHub 持久化存储。")

with st.sidebar:
    st.header("搜索条件")
    keyword = st.text_input("Keyword / Topic", value="ocr", help="例如：ocr, ai, automation, pdf, scraping")
    topic_mode = st.checkbox("按 topic 搜索", value=False, help="勾选后会使用 topic:keyword")
    col_a, col_b = st.columns(2)
    with col_a:
        min_stars = st.number_input("Min stars", min_value=0, value=1000, step=100)
    with col_b:
        max_stars = st.number_input("Max stars", min_value=1, value=10000, step=100)
    language = st.selectbox("Language", ["Any", "Python", "TypeScript", "JavaScript", "Go", "Rust", "Java", "C++", "PHP", "Ruby"])
    sort = st.selectbox("Sort by", ["stars", "updated"], index=0)
    per_page = st.slider("每页数量", 10, 100, 30, 10)
    pages = st.slider("页数", 1, 5, 1)

    st.header("过滤")
    hide_seen = st.checkbox("隐藏已看项目", value=True)
    hide_ignored = st.checkbox("隐藏已跳过项目", value=True)
    hide_favorites = st.checkbox("隐藏已收藏项目", value=False)

    st.header("API Keys")
    github_token = st.text_input("GITHUB_TOKEN", value=get_secret("GITHUB_TOKEN", ""), type="password")
    openai_key = st.text_input("OPENAI_API_KEY（可选）", value=get_secret("OPENAI_API_KEY", ""), type="password")
    use_readme = st.checkbox("抓 README 用于总结", value=True)
    use_ai = st.checkbox("使用 AI 生成一句话总结", value=bool(get_secret("OPENAI_API_KEY", "")))

    st.header("数据")
    st.caption(f"存储：{storage.label()}")
    fav_count = len(load_store("favorites"))
    seen_count = len(load_store("seen"))
    ignored_count = len(load_store("ignored"))
    st.caption(f"⭐ 收藏：{fav_count} | ✅ 已看：{seen_count} | 🚫 跳过：{ignored_count}")

query = build_query(keyword, int(min_stars), int(max_stars), language, topic_mode)
st.code(query, language="text")

main_tab, fav_tab, seen_tab, ignored_tab = st.tabs(["🔎 搜索", "⭐ 收藏夹", "✅ 已看", "🚫 已跳过"])

with main_tab:
    if st.button("搜索 GitHub 项目", type="primary"):
        if int(min_stars) > int(max_stars):
            st.error("Min stars 不能大于 Max stars")
            st.stop()

        with st.spinner("正在搜索 GitHub..."):
            try:
                repos = search_repos(query, sort, per_page, pages, github_token)
            except Exception as exc:
                st.error(str(exc))
                st.stop()

        if not repos:
            st.warning("没有找到项目。换个关键词或扩大 star 范围试试。")
            st.stop()

        rows = []
        progress = st.progress(0)
        status = st.empty()

        for i, repo in enumerate(repos, start=1):
            status.text(f"处理中 {i}/{len(repos)}：{repo.get('full_name')}")
            readme = ""
            if use_readme:
                try:
                    readme = fetch_readme(repo["owner"]["login"], repo["name"], github_token)
                except Exception:
                    readme = ""
            summary = summarize_project(repo, readme, openai_key if use_ai else "")
            rows.append(repo_to_row(repo, summary))
            progress.progress(i / len(repos))

        status.empty()
        progress.empty()

        df = pd.DataFrame(rows)
        st.session_state["results_df"] = df

    if "results_df" in st.session_state:
        df = st.session_state["results_df"].copy()

        hidden = set()
        if hide_seen:
            hidden |= repo_set("seen")
        if hide_ignored:
            hidden |= repo_set("ignored")
        if hide_favorites:
            hidden |= repo_set("favorites")
        if hidden and not df.empty:
            df = df[~df["repo"].astype(str).isin(hidden)]

        st.subheader(f"结果：{len(df)} 个项目")
        if df.empty:
            st.info("当前过滤条件下没有新项目。可以取消隐藏已看/已跳过，或换关键词继续搜。")

        favorite_repos = repo_set("favorites")
        ignored_repos = repo_set("ignored")
        seen_repos = repo_set("seen")

        for _, row in df.iterrows():
            repo_name = str(row["repo"])
            with st.container(border=True):
                left, right = st.columns([4, 1])
                with left:
                    badges = []
                    if repo_name in favorite_repos:
                        badges.append("⭐ 已收藏")
                    if repo_name in ignored_repos:
                        badges.append("🚫 已跳过")
                    if repo_name in seen_repos:
                        badges.append("✅ 已看")
                    badge_text = "  ".join(badges)
                    st.markdown(f"### [{row['repo']}]({row['github_url']}) {badge_text}")
                    st.write(row["what_it_does"])
                    st.caption(row["description"])
                    meta = f"⭐ {row['stars']}  |  {row['language'] or 'Unknown'}  |  Updated: {row['updated_at']}"
                    if row["topics"]:
                        meta += f"  |  Topics: {row['topics']}"
                    st.caption(meta)

                    default_tags = ""
                    if row["topics"]:
                        default_tags = ", ".join([t.strip() for t in str(row["topics"]).split(",")[:3]])
                    note = st.text_area("📝 Notes", key=f"note_{repo_name}", height=80, placeholder="为什么值得看？可以做什么方向？")
                    tags = st.text_input("🏷 Tags", key=f"tags_{repo_name}", value=default_tags, placeholder="ocr, pdf, ai")

                with right:
                    st.link_button("打开 GitHub", row["github_url"], use_container_width=True)
                    row_dict = row_to_dict(row)
                    if st.button("✅ 标记已看", key=f"seen_{repo_name}", use_container_width=True):
                        mark_seen(row_dict, note=note, tags=tags)
                        st.success("已标记为已看")
                        st.rerun()
                    if st.button("⭐ 收藏", key=f"fav_{repo_name}", use_container_width=True):
                        mark_favorite(row_dict, note=note, tags=tags)
                        st.success("已收藏")
                        st.rerun()
                    if st.button("🚫 跳过", key=f"ignore_{repo_name}", use_container_width=True):
                        mark_ignored(row_dict, note=note, tags=tags)
                        st.success("已跳过")
                        st.rerun()

        if not df.empty:
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "下载当前结果 CSV",
                data=csv,
                file_name="github_idea_finder_results.csv",
                mime="text/csv",
            )

with fav_tab:
    render_saved_table("收藏夹", "favorites")

with seen_tab:
    render_saved_table("已看项目", "seen")

with ignored_tab:
    render_saved_table("已跳过项目", "ignored")
