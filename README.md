# Cardio Literature Collector

## 项目简介
Cardio Literature Collector 利用 GitHub Actions 每日自动检索心血管相关的最新学术文献，支持来自 PubMed、Crossref、OpenAlex 等数据库的整合，并将结果保存为 CSV 与 Markdown 摘要，方便进一步整理与引用。

## 快速开始
1. **Fork 或克隆本仓库。**
2. **确保默认分支已启用 GitHub Actions。**首次触发时，GitHub 会请求授权，请按提示开启。

## 修改检索关键词
- 默认关键词为 `aortic stenosis, mitral regurgitation, valvular heart disease, deep learning`。
- 若要修改定时任务使用的关键词，可直接编辑工作流文件 `.github/workflows/literature_collector.yml` 中的 `keywords` 默认值。
- 手动触发时也可自定义关键词，详见下节。

## 手动触发工作流
1. 在 GitHub 仓库页面点击 **Actions**。
2. 选择左侧的 **Cardio Literature Collector** 工作流。
3. 点击右侧的 **Run workflow** 按钮。
4. 在弹出的表单中填写：
   - `keywords`：以逗号分隔的检索词，例如 `aortic stenosis, valvular heart disease`。
   - `sources`：可选的数据源列表（`pubmed,crossref,openalex`），留空则使用默认值。
5. 点击 **Run workflow** 启动流程。

## 结果文件位置
- 所有结果保存在 `data/` 目录下：
  - `literature_results.csv`：始终覆盖为最近一次运行的汇总。
  - `literature_results_YYYYMMDD_HHMMSS.csv`：带时间戳的完整备份。
  - `literature_summary_YYYYMMDD_HHMMSS.md`：对应 CSV 的 Markdown 表格摘要，可直接用于分享或汇报。
- GitHub Actions 会在成功更新后自动提交并推送这些文件。

## 可选进阶设置
- **API Key**：
  - PubMed 与 Crossref 支持通过环境变量提供邮箱或 API Key，以获得更高的速率限制。可在工作流中新增 `env` 字段，并传入 `NCBI_API_KEY`、`CROSSREF_MAILTO` 等自定义值，再在 `fetch_papers.py` 中读取使用。
- **集成 Zotero 或 Notion**：
  - 可在脚本中追加推送逻辑，例如使用 Zotero API 上传条目，或调用 Notion API 写入数据库。
  - 建议将凭证存储在仓库的 **Settings → Secrets and variables → Actions** 中，并在工作流里通过环境变量注入。
- **扩展数据源**：
  - 参考 `fetch_papers.py` 中现有的 `fetch_*` 函数，新建 ArXiv 等来源的请求函数，并在 `fetchers` 字典中注册即可。

祝研究顺利！如有问题，欢迎在 Issues 中反馈或自行扩展功能。
