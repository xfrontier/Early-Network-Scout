import os
import json
import re
from datetime import datetime
from urllib.parse import urlparse
from google import genai
from google.genai import types

# 1. 基础路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(BASE_DIR, "data", "project.json")
README_PATH = os.path.join(BASE_DIR, "README.md")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

# 2. 全局区块链领域的 Gemini 评估 Prompt 模板
PROMPT_TEMPLATE = """
You are an expert Web3 & Blockchain ecosystem analyst. 
Search the web for the top 10 most promising early-stage blockchain projects (across the entire Web3 ecosystem: L1/L2, AI x Crypto, DeFi, DePIN, RWA, Account Abstraction, etc.) for the current week ({current_week_str}).

CRITICAL IDENTIFIER RULE:
Here is the list of existing projects in our database:
{existing_projects_context}

If a project you find matches any project in the existing list above (by project name, official domain, or GitHub repo), YOU MUST REUSE ITS EXACT "id".
Only assign a new lowercase hyphenated slug for "id" if it is a completely new project not in the list.

Evaluate each project using a 100-point scale across 4 standardized core dimensions:
1. Developer & Code Ecosystem (Provide quantitative metrics: github_stars, github_forks, commits_30d, active_contributors, plus a brief summary)
2. On-Chain & Network Dynamics (Provide quantitative metrics: tx_count_7d, active_addresses_7d, volume_usd_7d, avg_gas_usd, tps_peak, plus a brief summary)
3. Value Capture Analysis (Provide summary and an array of 3 key value-capturing entities)
4. Actionable Path for Individuals (Provide summary and an array of 3 actionable pathways for developers/operators/users)

Output MUST strictly be a valid JSON list containing 10 project objects. Each project object must follow this exact schema:
[
  {{
    "id": "proj-unique-slug",
    "name": "Project Name",
    "category": "Project Category (e.g., DePIN, L2, AI x Crypto)",
    "first_seen": "{current_date_str}",
    "official_url": "https://...",
    "github_repo": "https://...",
    "weekly_snapshots": [
      {{
        "week": "{current_week_str}",
        "date": "{current_date_str}",
        "rank": 1,
        "score": 88,
        "is_in_top10": true,
        "status": "active",
        "card_details": {{
          "core_value": "Brief core value proposition sentence.",
          "developer_code_ecosystem": {{
            "summary": "Brief summary",
            "metrics": {{
              "github_stars": 1200,
              "github_forks": 150,
              "commits_30d": 30,
              "active_contributors": 10
            }}
          }},
          "onchain_network_dynamics": {{
            "summary": "Brief summary",
            "metrics": {{
              "tx_count_7d": 50000,
              "active_addresses_7d": 3000,
              "volume_usd_7d": 10000.0,
              "avg_gas_usd": 0.0001
            }}
          }},
          "value_capture_analysis": {{
            "summary": "Brief summary",
            "entities": ["Entity 1 description", "Entity 2 description", "Entity 3 description"]
          }},
          "actionable_path_for_individuals": {{
            "summary": "Brief summary",
            "paths": ["Path 1 description", "Path 2 description", "Path 3 description"]
          }}
        }}
      }}
    ]
  }}
]
"""

def slugify(text):
    """辅助函数：将文本转换为规范的 slug"""
    text = text.lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')

def generate_canonical_id(proj):
    """
    确定性 ID 生成算法（兜底逻辑）：
    优先基于 GitHub 仓库名或官网域名，次选基于规范化的项目名称生成。
    """
    github_url = proj.get("github_repo", "")
    if "github.com/" in github_url:
        path = urlparse(github_url).path.strip("/")
        if path:
            return path.lower().replace("/", "-")

    official_url = proj.get("official_url", "")
    if official_url and official_url.startswith("http"):
        domain = urlparse(official_url).netloc.replace("www.", "")
        if domain:
            return domain.lower().replace(".", "-")

    name = proj.get("name", "").lower()
    slug = slugify(name)
    return f"proj-{slug}"

def load_database():
    """读取现有 JSON 数据库"""
    if not os.path.exists(JSON_PATH):
        return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_database(data):
    """保存 JSON 数据库"""
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_top_projects_from_gemini(existing_db, current_week_str, current_date_str):
    """利用 Gemini API + Google Search Grounding 抓取并评估最新 Top 10 项目"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("⚠️ GEMINI_API_KEY missing. Skipping live AI scouting.")
        return None

    print("🔑 GEMINI_API_KEY detected. Initializing Gemini Client with Search Grounding...")
    client = genai.Client(api_key=api_key)
    
    # 提取现有数据库里的 ID 映射提示上下文
    existing_context = [
        {
            "id": p["id"],
            "name": p["name"],
            "official_url": p.get("official_url", ""),
            "github_repo": p.get("github_repo", "")
        }
        for p in existing_db
    ]

    prompt = PROMPT_TEMPLATE.format(
        current_week_str=current_week_str,
        current_date_str=current_date_str,
        existing_projects_context=json.dumps(existing_context, ensure_ascii=False, indent=2)
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}],
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"❌ Failed to fetch from Gemini API: {e}")
        return None

def merge_new_snapshots(existing_db, new_projects, current_week_str):
    """将 Gemini 最新分析到的 Top 10 快照追加合并至现有的 JSON 数据库中（含多重 ID 强校准机制）"""
    db_map = {proj["id"]: proj for proj in existing_db}

    # 建立名称/GitHub 仓库到已有 ID 的快速映射字典
    alias_to_id = {}
    for p in existing_db:
        p_id = p["id"]
        alias_to_id[p["name"].lower()] = p_id
        if p.get("github_repo"):
            gh_clean = p["github_repo"].lower().rstrip("/")
            alias_to_id[gh_clean] = p_id

    for rank, new_proj in enumerate(new_projects, start=1):
        # --- 多重 ID 强校准逻辑 ---
        gh = new_proj.get("github_repo", "").lower().rstrip("/")
        name_key = new_proj["name"].lower()
        provided_id = new_proj.get("id", "")

        # 优先匹配 GitHub 仓库/项目名称，其次校验 provided_id，最后触发确定性算法生成
        if gh and gh in alias_to_id:
            p_id = alias_to_id[gh]
        elif name_key in alias_to_id:
            p_id = alias_to_id[name_key]
        elif provided_id and provided_id in db_map:
            p_id = provided_id
        else:
            p_id = generate_canonical_id(new_proj)

        # 赋回校准后的统一 ID
        new_proj["id"] = p_id
        new_snapshot = new_proj["weekly_snapshots"][0]
        new_snapshot["rank"] = rank

        if p_id in db_map:
            # 如果项目已在数据库中，将当周快照覆盖或追加回该项目
            existing_snapshots = db_map[p_id]["weekly_snapshots"]
            snapshot_weeks = [s["week"] for s in existing_snapshots]
            if current_week_str in snapshot_weeks:
                idx = snapshot_weeks.index(current_week_str)
                existing_snapshots[idx] = new_snapshot
            else:
                existing_snapshots.append(new_snapshot)
        else:
            # 新项目则直接存入数据库，并更新别名映射字典
            db_map[p_id] = new_proj
            alias_to_id[name_key] = p_id
            if gh:
                alias_to_id[gh] = p_id

    return list(db_map.values())

def generate_report_cards(top_10_projects, current_week_str, current_date_str):
    """覆盖生成当周 Top 10 项目的独立 Opportunity Card Markdown 文件（100% 001 格式）"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    
    # 清空 reports 文件夹下的旧文件（只保留当周最新卡片）
    for file in os.listdir(REPORTS_DIR):
        file_path = os.path.join(REPORTS_DIR, file)
        if os.path.isfile(file_path):
            os.remove(file_path)

    card_file_map = {}

    for idx, item in enumerate(top_10_projects, start=1):
        snapshot = item["snapshot"]
        details = snapshot["card_details"]
        slug = slugify(item['name'])
        filename = f"{idx:03d}-{slug}.md"
        filepath = os.path.join(REPORTS_DIR, filename)

        dev_m = details.get("developer_code_ecosystem", {}).get("metrics", {})
        onchain_m = details.get("onchain_network_dynamics", {}).get("metrics", {})
        val_entities = details.get("value_capture_analysis", {}).get("entities", [])
        path_list = details.get("actionable_path_for_individuals", {}).get("paths", [])

        # 100% 对齐原版 001-x402-Payment-Rails.md 的格式
        card_md = f"""# Opportunity Card: {item['name']}

- **Project ID**: `{item['id']}`
- **Category**: {item['category']}
- **First Seen / Updated**: {current_date_str} ({current_week_str})
- **Weekly Score**: **{snapshot['score']} / 100** (Rank #{idx})
- **Official Links**: [Official Site]({item.get('official_url', '#')}) | [GitHub Repo]({item.get('github_repo', '#')})

---

## 📌 Core Value Proposition
{details.get('core_value', '')}

---

## 🛠️ 1. Developer & Code Ecosystem
- **Summary**: {details.get('developer_code_ecosystem', {}).get('summary', '')}
- **Hard Metrics**:
  - GitHub Stars: `{dev_m.get('github_stars', 'N/A')}`
  - GitHub Forks: `{dev_m.get('github_forks', 'N/A')}`
  - Commits (30d): `{dev_m.get('commits_30d', 'N/A')}`
  - Active Contributors: `{dev_m.get('active_contributors', 'N/A')}`

---

## ⛓️ 2. On-Chain & Network Dynamics
- **Summary**: {details.get('onchain_network_dynamics', {}).get('summary', '')}
- **Hard Metrics**:
  - 7d Transaction Volume: `{onchain_m.get('tx_count_7d', 'N/A')}` txs
  - 7d Active Addresses: `{onchain_m.get('active_addresses_7d', 'N/A')}`
  - 7d USD Volume: `${onchain_m.get('volume_usd_7d', 'N/A')}`
  - Avg Gas Fee: `${onchain_m.get('avg_gas_usd', 'N/A')}`

---

## 💰 3. Value Capture Analysis
{details.get('value_capture_analysis', {}).get('summary', '')}

### Key Value-Capturing Entities:
"""
        for entity in val_entities:
            card_md += f"1. {entity}\n"

        card_md += f"""
---

## 🎯 4. Actionable Path for Individuals
{details.get('actionable_path_for_individuals', {}).get('summary', '')}

### Action Pathways:
"""
        for path in path_list:
            card_md += f"1. {path}\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(card_md)

        card_file_map[item['id']] = f"reports/{filename}"

    print(f"✅ Cleaned old reports and generated 10 new Opportunity Cards in `reports/`!")
    return card_file_map

def render_readme(projects, current_week_str, current_date_str):
    """根据数据库最新快照生成 reports 文件并渲染 README.md（100% 原版 README 样式）"""
    active_projects = []
    
    for proj in projects:
        snapshots = proj.get("weekly_snapshots", [])
        if not snapshots:
            continue
        latest_snapshot = snapshots[-1]
        if latest_snapshot.get("is_in_top10", False) and latest_snapshot.get("status") == "active":
            active_projects.append({
                "id": proj.get("id"),
                "name": proj["name"],
                "category": proj["category"],
                "snapshot": latest_snapshot
            })

    # 按最新得分降序排列，取 Top 10
    active_projects.sort(key=lambda x: x["snapshot"]["score"], reverse=True)
    top_10 = active_projects[:10]

    # 1. 生成当周的 10 个 Card Markdown 文件
    card_file_map = generate_report_cards(top_10, current_week_str, current_date_str)

    # 2. 100% 还原原版 README.md 格式
    readme_content = f"""# Early Network Scout (Base / x402 Ecosystem)

Weekly automated scouting & evaluation system for identifying high-potential early network opportunities, protocol innovations, and micro-payment rails on Base / x402 ecosystem.

- **Last Updated**: `{current_date_str}`
- **Active Cycle**: `{current_week_str}`
- **Database Backend**: [`data/project.json`](data/project.json)

---

## 🏆 Current Top 10 Opportunities Leaderboard

| Rank | Project Name | Category | Score | Opportunity Card |
| :---: | :--- | :--- | :---: | :---: |
"""

    for idx, item in enumerate(top_10, start=1):
        snapshot = item["snapshot"]
        card_rel_path = card_file_map.get(item['id'], "#")
        card_link = f"[📖 View Card]({card_rel_path})"

        readme_content += f"| #{idx} | **{item['name']}** | `{item['category']}` | **{snapshot['score']}** | {card_link} |\n"

    readme_content += "\n---\n\n## 📌 Weekly Scout Summaries\n\n"

    for idx, item in enumerate(top_10, start=1):
        snapshot = item["snapshot"]
        details = snapshot["card_details"]
        card_rel_path = card_file_map.get(item['id'], "#")

        dev_m = details.get("developer_code_ecosystem", {}).get("metrics", {})
        onchain_m = details.get("onchain_network_dynamics", {}).get("metrics", {})
        val_summary = details.get("value_capture_analysis", {}).get("summary", "")
        path_summary = details.get("actionable_path_for_individuals", {}).get("summary", "")

        readme_content += f"### {idx}. [{item['name']}]({card_rel_path})\n"
        readme_content += f"- **Category**: {item['category']}\n"
        readme_content += f"- **Score**: {snapshot['score']} / 100\n"
        readme_content += f"- **Core Value**: {details.get('core_value', '')}\n"
        readme_content += f"- **Key Evaluation Dimensions**:\n"
        readme_content += f"  1. **Developer & Code Ecosystem**: {dev_m.get('github_stars', 'N/A')} Stars | {dev_m.get('github_forks', 'N/A')} Forks | {dev_m.get('commits_30d', 'N/A')} Commits (30d) — {details.get('developer_code_ecosystem', {}).get('summary', '')}\n"
        readme_content += f"  2. **On-Chain & Network Dynamics**: {onchain_m.get('tx_count_7d', 'N/A')} Txs (7d) | {onchain_m.get('active_addresses_7d', 'N/A')} Active Addrs — {details.get('onchain_network_dynamics', {}).get('summary', '')}\n"
        readme_content += f"  3. **Value Capture Analysis**: {val_summary}\n"
        readme_content += f"  4. **Actionable Path for Individuals**: {path_summary}\n\n"
        readme_content += f"👉 **[Read Full Opportunity Card]({card_rel_path})**\n\n---\n\n"

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"✅ README.md successfully rendered for week {current_week_str}!")

def main():
    now = datetime.utcnow()
    current_year, current_week, _ = now.isocalendar()
    current_week_str = f"{current_year}-W{current_week:02d}"
    current_date_str = now.strftime("%Y-%m-%d")

    # 1. 加载本地现有数据库
    db = load_database()

    # 2. 调用 Gemini API 联网抓取最新全网区块链 Top 10（带现有数据库上下文）
    new_projects = fetch_top_projects_from_gemini(db, current_week_str, current_date_str)

    # 3. 追加更新 JSON 数据库并保存
    if new_projects:
        db = merge_new_snapshots(db, new_projects, current_week_str)
        save_database(db)
        print(f"✅ Database `data/projects.json` successfully updated!")

    # 4. 生成当周 10 个 Card 并在 README.md 中建立关联跳转链接
    render_readme(db, current_week_str, current_date_str)

if __name__ == "__main__":
    main()
