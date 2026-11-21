# 信源 · AI 阅读器

极简 AI 资讯与研究论文阅读器。界面风格沿用「每日英语」，只有白底、黑字、少量分隔线；手机和电脑可用。

## 数据源

- **论文**：arXiv cs.AI / cs.CL / cs.IR / cs.LG / cs.CV、Hugging Face Daily Papers。
- **企业研究**：Google Research、Microsoft Research、Google DeepMind、Anthropic Research/Engineering。
- **资讯**：OpenAI News。

所有采集都来自公开 RSS/Atom 或 Hugging Face 开放接口。**Anthropic 两个 RSS 是第三方桥接**，页面中会标注「第三方 RSS」。企业研究博客文章不一定是学术论文，和 arXiv 论文分开展示。

## 功能

- 四个分类：全部 / AI 论文 / 企业研究 / 资讯。
- 主题筛选：Agent / RAG / LLM / 多模态 / 视频生成 / 模型训练。
- 搜索标题、摘要、来源；展开原始英文摘要；直达论文及 PDF。
- 去重、日期排序、历史数据保留和每日自动采集；**不使用付费 API**。
- 首次推送后，数据为空；在 GitHub Actions 手动运行一次可获取最新数据。

## 发布步骤

1. 在 GitHub 创建**公开仓库** `research-rss-reader`（main 分支），上传本项目全部文件，包括隐藏目录 `.github/workflows/publish.yml`。
2. 在 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
3. 到 **Actions → 更新并发布 AI 阅读器 → Run workflow** 手动运行一次。
4. 部署成功后打开 `https://wenqingduu.github.io/research-rss-reader/`（若不是这个 GitHub 用户，请替换用户名与仓库名）。

默认定时抓取：北京时间约 08:17、16:17、次日 00:17。GitHub Actions 的 `schedule` 可能延迟，不能保证精确到分钟。也支持手动执行 `workflow_dispatch`。

无需云服务器、数据库、OpenAI API Key，通常可使用 GitHub 免费额度。GitHub Pages 只有静态页面，抓取工作在 GitHub Actions 中进行，避免浏览器跨域（CORS）问题。

## 本地运行

```bash
python -m pip install -r requirements.txt
python scripts/update.py
python -m http.server 8000
```

访问 <http://localhost:8000>。不要直接用 `file://` 打开，因为浏览器可能拒绝读取本地 JSON。

## 备注

- 英文摘要没有自动翻译成中文：为避免使用收费翻译 API 和不准确的机器翻译，当前保留来源英文摘要。
- 部分来源可能限流、暂时不可访问、变更 RSS 地址；脚本会记录失败源并尽量保留旧数据。所有源都失败时本次任务报错，不会覆盖成空列表。
- 文章筛选基于关键词，可能漏掉个别相关论文，或误收少量边缘文章。
- 页面中的搜索和分类不会修改远程数据。