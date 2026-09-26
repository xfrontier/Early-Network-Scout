import os
import glob
import re

def clean_markdown_formatting(text):
    """去除 Markdown 的结构和格式符号，还原为干净的无格式纯文本"""
    if not text:
        return ""
    # 移除标题前缀 #
    text = re.sub(r'#+\s*', '', text)
    # 移除加粗、斜体、删除线、行内代码符号 (*, _, ~, `)
    text = re.sub(r'[\*\_~`]', '', text)
    # 将链接 [文字](url) 替换为 "文字 (url)"
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1 (\2)', text)
    # 将无序列表横杠首缀统一规范为干净缩进
    text = re.sub(r'^\s*[-\*]\s+', '• ', text, flags=re.MULTILINE)
    return text.strip()

def export_reports_to_single_plain_txt():
    # 扫描 reports 目录下所有的 .md 报告文件
    report_files = sorted(glob.glob("reports/*.md"))
    output_txt_path = "reports/latest_opportunities_plain.txt"

    if not report_files:
        print("⚠️ 未在 reports/ 目录下找到任何 .md 文件。")
        return

    plain_lines = []
    plain_lines.append("==================================================")
    plain_lines.append("       EARLY NETWORK SCOUT - PLAIN TEXT REPORT     ")
    plain_lines.append("==================================================\n")

    for file_path in report_files:
        # 过滤排除自身以及汇总类的 txt/md 文件
        filename = os.path.basename(file_path)
        if "latest_opportunities" in filename:
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        cleaned_content = clean_markdown_formatting(raw_content)
        plain_lines.append(cleaned_content)
        plain_lines.append("\n" + "=" * 50 + "\n")

    # 确保 output 目录存在并写入/覆盖生成文件
    os.makedirs(os.path.dirname(output_txt_path), exist_ok=True)
    with open(output_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(plain_lines))

    print(f"✅ 成功提取 reports/ 下的 Markdown 文本并覆盖生成至: {output_txt_path}")

if __name__ == "__main__":
    export_reports_to_single_plain_txt()
