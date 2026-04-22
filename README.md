# wechat-article-mcp

面向 Codex、OpenClaw 等 MCP 客户端的微信公众号文章工具。

让 Codex、OpenClaw 等支持 MCP 的客户端可以直接完成下面这些事情：

- 发起公众号后台扫码登录
- 复用本地保存的登录态
- 搜索公众号
- 拉取公众号文章列表
- 获取最近一篇文章
- 按时间范围筛选文章
- 抓取文章正文并输出标准化 `html`
- 直接把文章导出到本地文件

它不依赖 `wechat-article-exporter` 的 Nuxt 前端服务，可以单独运行。

## 当前状态

当前版本已经过真实请求验证，确认可用的能力包括：

- 二维码扫码登录
- 本地保存并复用登录账号
- 搜索公众号
- 获取最近一篇文章
- 按时间范围筛选文章
- 抓取文章正文
- 导出 `html`

## 安装

推荐在独立 Python 环境中安装：

```bash
python -m pip install -e .
```

如果你已经进入目标环境，也可以直接执行：

```bash
pip install -e .
```

## 启动

```bash
python -m wechat_article_mcp.server
```

## 使用示例

第一次使用：

1. 调用 `start_login_session`
2. 打开返回的二维码图片
3. 用公众号管理员微信扫码并确认
4. 调用 `check_login_session`
5. 当状态变成 `confirmed` 后，调用 `complete_login`

完成登录后，常见调用方式：

- 搜索公众号：`search_accounts(keyword="机器之心")`
- 获取最近一篇文章：`get_latest_article(account_name="机器之心")`
- 获取最近一篇文章正文 HTML：`get_latest_article_content(account_name="机器之心")`
- 导出最近一篇文章到本地 HTML：`export_article(url_or_account_name="机器之心", output_path="exports/jiqizhixin_latest.html")`
- 直接抓取单篇文章 HTML：`get_article_content(url="https://mp.weixin.qq.com/s/...")`

## MCP 工具

- `start_login_session`
  发起一次微信公众号后台扫码登录，并返回本地二维码文件路径。
- `check_login_session`
  轮询二维码登录状态。
- `complete_login`
  在扫码确认后完成登录，并把 cookie / token 保存到本地。
- `list_saved_accounts`
  查看当前本地保存的登录账号。
- `check_account_alive`
  检查当前保存的登录态是否仍然有效，可用于判断是否需要重新扫码登录。
- `set_default_account`
  切换默认登录账号。
- `search_accounts`
  按关键词搜索公众号。
- `list_articles`
  已知 `fakeid` 时，直接拉取该公众号文章列表。
- `get_latest_article`
  按公众号名称解析账号，并返回最近一篇文章。
- `get_latest_article_content`
  按公众号名称解析账号，直接返回最近一篇文章的标准化 HTML。
- `search_articles_by_date`
  按公众号名称分页抓取文章列表，并在本地按日期范围过滤。
- `get_article_content`
  直接抓取某篇微信文章链接的标准化 HTML。
- `export_article`
  输入文章链接，或输入公众号名称并默认取最近一篇，直接导出到本地 HTML 文件。

## 登录流程

1. 调用 `start_login_session`
2. 打开返回的 `qr_code_path`
3. 用公众号管理员微信扫码（需要注册微信公众号）
4. 轮询 `check_login_session`
5. 当状态变成 `confirmed` 后，调用 `complete_login`
6. 后续搜索和抓取都可以复用这个本地保存的登录态

如果你不确定当前登录态是否还有效，可以先调用 `check_account_alive`。

高频工具如 `search_accounts`、`list_articles`、`get_latest_article`、`get_latest_article_content`、`search_articles_by_date` 在底层依赖已保存登录态时，如果检测到登录态失效，也会直接返回重新扫码登录提示。

## Codex 配置示例

把下面这段加入 Codex 的 `config.toml` 配置文件：

```toml
[mcp_servers.wechat-article]
command = "/path/to/python"
args = ["-m", "wechat_article_mcp.server"]

[mcp_servers.wechat-article.env]
PYTHONIOENCODING = "utf-8"
PYTHONUTF8 = "1"
```

## 数据存储

默认情况下，运行时状态会保存在：

```text
<project-root>/.wechat_article_mcp
```

如果你想改到别的目录，可以设置环境变量：

```bash
WECHAT_ARTICLE_MCP_HOME=/path/to/data
```

这里面可能包含：

- 已保存的登录 cookie
- 已保存的账号 token
- 登录会话元数据
- 二维码图片文件

## 提交说明

以下目录属于本地运行产物，不应提交到 GitHub：

- `.wechat_article_mcp/`
- `exports/`
- `.tmp/`
- `src/wechat_article_mcp.egg-info/`
- `__pycache__/`

这些目录已经写入 `.gitignore`，提交前仍建议再检查一次工作区状态。

## 限制说明

- 本项目依赖当前微信公众号后台的现有行为；如果微信后续修改登录或文章接口，功能可能失效。
- “按时间搜索”不是微信接口直接支持的能力，而是在 MCP 层分页拉取后本地过滤实现的。
- 这个项目更适合本地单用户使用，不适合直接当作多人共享服务。
- 本地保存的登录态是敏感数据，请保护好数据目录。

## 开发验证

静态检查：

```bash
python -m py_compile src/wechat_article_mcp/*.py
```

## 许可证

MIT
