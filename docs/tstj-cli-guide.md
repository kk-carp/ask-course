# 天树 CLI 使用与接口清单

整理日期：2026-10-09。按当前 CLI 源码、后端路由及 AK/SK 白名单核对，未逐项验证线上部署。示例中的 ID、分类和文件路径需要替换为实际值。

本文先说明怎么用，再列对应接口。CLI 使用账号的 AK/SK，能够操作的范围由“接口白名单 + 账号权限 + 内容归属或星球成员资格”共同决定。

快速定位：[配置与权限](#2-开始使用先配置再查权限) · [资讯](#3-资讯上传草稿--发布--按-id-修正) · [星球文章](#4-星球文章先查发帖权限再投稿或修改) · [书刊论文与价格](#5-书刊与论文入库价格上架和修改) · [页面与文件](#6-html-页面与通用文件上传) · [视频](#7-视频导出清单再下载) · [更新规则](#8-按-id-修改与参数区别) · [接口对照表](#9-对应-http-接口) · [常见问题](#10-常见问题)。

## 1. 能做什么

| 模块 | 查询 | 新建 / 上传 | 修改 | 发布 / 后续处理 | 权限范围 |
| --- | --- | --- | --- | --- | --- |
| 资讯 `news` | 分类、本人 CLI 稿件列表和详情 | 上传 HTML，保存草稿 | 按原 ID 修改正文和资料 | 单独 `publish`，立即公开 | 管理员及 `miniapp-news-feed`；仅本人 CLI 创建的资讯 |
| 星球文章 `community` | 星球、成员权限、文章列表和正文 | 向指定星球投稿 | 按原 ID 修改文章 | 是否立即发布按星球审核规则 | 普通账号可用；发布人需有效成员资格及发帖权限 |
| 书刊论文 `library` | 管理列表、详情、价格、PDF 状态 | 书刊或论文入库，默认草稿 | 按原 ID 修改资料、价格、阅读文件 | 上架、提交 PDF 分页任务 | 管理员及 `community-library`；管理权限范围内的内容库 |
| HTML 页面 `pages` | 本人 API 页面列表和详情 | 创建后立即发布 | 标题、HTML、链接别名 | 无独立发布命令 | 管理员及 `operation-page`；仅本人 API 创建的页面 |
| 文件 `upload` | 上传完成后返回文件链接 | 向七牛上传新文件 | 不覆盖已有对象 | 后端确认文件后返回 `preview_url` | 管理员及 `cloud-resource` |
| 视频 `videos` | 分类、列表 | 导出 CSV 清单 | 无 | 按清单下载视频及可选文稿 | 网站查询、导出需管理员及 `operation-video-storage`；本地清单下载无需网站凭证 |
| 身份与权限 | `whoami`、`permissions` | 无 | 无 | 无 | `whoami` 查询本人；`permissions` 为后台权限查询 |

当前没有 CLI 删除、下架、审核、支付、退款、账户修改、课程管理、源宝聊天或课程助手聊天命令。管理员也不能越过 AK/SK 白名单调用这些接口。

## 2. 开始使用：先配置，再查权限

需要 Node.js 20+。安装入口在网站“个人中心 → API 密钥 → 安装 CLI”；安装目录为 `~/.tstj/cli`。下文使用短命令 `tstj`，未配置 PATH 时替换为：

```sh
node "$HOME/.tstj/cli/tstj.mjs" --help
```

在自己的交互式终端输入凭证：

```sh
tstj auth login
tstj whoami
tstj permissions
```

连接其他后端时：

```sh
tstj auth login --server https://your-backend.example.com
```

- 后端地址必须是 HTTPS 源站，不带 `/api`、`/miniapp` 或其他路径。本机开发地址允许 HTTP。
- `auth login` 保存本机配置，**不会验证线上连接**；随后用 `whoami` 验证。
- `whoami` 返回身份、权限及 `data.access_policy.endpoints`。这个列表表示服务端向 AK 开放的接口，具体操作仍需满足账号和业务权限。
- `permissions` 返回后台账号权限，不替代 `whoami` 的接口白名单，也不代表星球成员权益。
- 凭证保存在 `~/.tstj/credentials.json`。环境变量 `TSTJ_BASE_URL`、`TSTJ_AK`、`TSTJ_SK` 可覆盖本机配置。SK 在登录时不回显，不要放进命令参数或文档。

## 3. 资讯：上传草稿 → 发布 → 按 ID 修正

### 常用命令

```sh
# 先查询分类 ID
tstj news categories

# 上传 HTML，默认草稿
tstj news upload --file ./news.html --title "机器人资讯" --category 1

# 使用上传返回的 data.id 发布；123 为示例 ID
tstj news publish 123

# 查询状态或修改原文
tstj news list
tstj news show 123
tstj news update 123 --file ./corrected.html --title "修正后的标题"
```

### 参数

| 参数 | 含义 | upload | update |
| --- | --- | --- | --- |
| `--file` | HTML 正文文件，1 字节～2 MB | 必填 | 可选 |
| `--title` | 标题，最多 256 字符 | 必填 | 可选 |
| `--category` | 已启用的资讯分类 **数字 ID** | 必填 | 可选 |
| `--summary` | 摘要，最多 512 字符 | 可选 | 可选 |
| `--cover` | HTTP(S) 图片地址；不能直接传本地图片路径 | 可选 | 可选 |
| `--tags` | 逗号分隔，最多 10 项，每项最多 30 字符 | 可选 | 可选 |
| `--published-at` | 显示时间，支持北京时间字符串或 Unix 秒 | 可选 | 可选 |

```sh
# 修正时间；publish 也支持此参数
tstj news update 123 --published-at "2026-10-09 10:30:00"

# 清空可选字段
tstj news update 123 --summary "" --cover "" --tags ""
```

行为说明：

- `upload` 不发布、不进入自动审核；`publish` 立即公开，无需人工或 AI 审核，并返回 `article_url`。
- `--published-at` 是显示时间，**不是定时发布**；Unix 值使用秒，不使用毫秒。
- 修改已发布资讯立即生效，修改草稿仍保留草稿。保留 ID、链接、作者、统计值和发布、审核状态。
- 只能操作本人通过 CLI 创建的合规草稿或已发布稿件；不能修改他人、历史网站稿件或恢复下架、审核失败内容。
- `news list` 当前不接受筛选或分页参数。需要翻页时使用文末的 `request GET`。

## 4. 星球文章：先查发帖权限，再投稿或修改

```sh
tstj community planets --keyword "机器人" --page 1 --page-size 20
tstj community planet 12
tstj community articles 12 --page 1 --page-size 20
tstj community article 456

# 新建一篇文章
tstj community publish --planet 12 --file ./article.html --title "机器人实践"

# 修改原文章，不新建
tstj community update 456 --file ./corrected.html --title "修正标题"
```

| 参数 | 含义 |
| --- | --- |
| `--planet` | 新建时必填的星球 ID；更新不能用它移动文章 |
| `--file` | 新建必填正文文件，最多 2 MB / 100000 字符；按原文保存 |
| `--title` | 新建必填标题，最多 200 字符；更新可选 |
| `--summary` | 摘要，最多 500 字符 |
| `--cover` | HTTP(S) 封面地址 |
| `--topics` | 话题，逗号分隔，最多 10 项，每项最多 30 字符 |
| `--visibility` | `public` 或 `members`，新建默认 `public` |
| `--published-at` | 北京时间 `YYYY-MM-DD HH:mm:ss`，仅控制显示时间 |
| `--author` | 发布人 **账号数字 ID**；默认密钥所属账号 |
| `--id` | 仅用于 `community publish --id 456 ...`，效果等同于更新原文章 |

发布人规则：

- 普通账号只能使用本人身份。调用者有后台 `community-content` 权限时，可指定其他正常账号作为发布人。
- 被指定发布人仍需有效星球成员资格，遵守禁言、成员发帖设置和审核规则。后台权限不替代其成员权益。
- `--author` 也适用于 `planet`、`articles`、`article` 和 `update`。更新时用于选择原文章所属的发布身份，**不更换文章作者**。

```sh
# 有内容管理权限的调用者，以账号 101 的发布身份查询并修正原文
tstj community planet 12 --author 101
tstj community update 456 --author 101 --file ./corrected.html
```

`planet` 返回 `permissions.can_publish`、`can_read_articles`、`requires_review`、`reason`。提交返回 `pending` 表示待审核，`published` 才表示公开。正文有变化时会重新判断审核规则，已发布文章可能转为待审核。

不带文章 ID 的 `publish` 每次都是新建，不按标题去重。当前 community 命令不接受空字符串参数，不能照搬资讯的 `--summary ""` 清空写法。

## 5. 书刊与论文：入库、价格、上架和修改

### 5.1 新建书刊

```sh
# EPUB 可读取内置标题、作者和封面；默认免费草稿
tstj library upload --kind book --file ./book.epub --category "机器人"

# Markdown 书刊：价格 9.90 元，试读比例 10%，立即上架
tstj library upload --kind book --file ./book.md \
  --title "机器人入门" --category "机器人" --cover ./cover.png \
  --price 9.90 --free-percent 10 --publish
```

### 5.2 新建论文

```sh
# 本地 PDF + Markdown 解读，默认保存草稿
tstj library upload --kind paper --file ./paper.pdf \
  --content-file ./interpretation.md --title "论文标题" \
  --category "人工智能" --author "论文作者" --price 0

# 已有七牛 / CDN PDF 链接，无需重新上传
tstj library upload --kind paper --file-url https://example.com/paper.pdf \
  --content-file ./interpretation.md --title "论文标题" \
  --category "人工智能" --cover https://example.com/cover.png --price 9.90

# 仅录入 Markdown 解读，也可以入库
tstj library upload --kind paper --file ./interpretation.md \
  --title "论文解读" --category "人工智能"
```

### 5.3 参数速查

| 参数 | 含义与规则 |
| --- | --- |
| `--kind` | 新建必填：`book` 书刊或 `paper` 论文 |
| `--category` | 新建必填：**分类文字**，最多 80 字符，不是资讯分类 ID |
| `--title` | 标题，最多 255 字符；新建 EPUB 可从文件读取，其余格式必填 |
| `--file` | 本地阅读文件；与 `--file-url` 二选一 |
| `--file-url` | 已有 HTTPS PDF 链接，URL 路径必须以 `.pdf` 结尾，可带查询参数 |
| `--content-file` | 论文 UTF-8 Markdown 解读，可与 PDF 同时提供；不用于书刊 |
| `--cover` | 本地 PNG/JPEG/WebP/GIF 或 HTTPS 图片链接；书刊上架必须有封面，EPUB 可用内置封面 |
| `--price` | **单位元**，范围 0～99999999.99，最多两位小数；新建默认 0，表示免费 |
| `--free-percent` | 免费阅读比例，0～99；默认 10 |
| `--author` | 作者 **展示文字**，最多 255 字符，不是发布人账号 |
| `--summary` | 摘要，最多 5000 字符 |
| `--tags` | 逗号分隔，最多 10 项，每项最多 40 字符 |
| `--publisher`、`--identifier` | 出版方、ISBN / arXiv 等编号，各最多 255 字符 |
| `--published-date` | 出版日期 `YYYY-MM-DD`，与资讯、星球文章的显示时间不同 |
| `--page-count`、`--sort-order` | 页数、排序值，范围 0～100000 |
| `--featured` | 标为精选；更新时可用 `--unfeatured` 取消 |
| `--publish` | 仅用于 upload：立即上架；不传保存草稿 |

新建至少提供阅读文件、PDF 地址或论文解读之一。书刊支持 EPUB、TXT、MD/Markdown、PDF；论文支持 PDF、MD/Markdown。大小上限：EPUB/PDF 50 MB、书刊文本 10 MB、论文 Markdown 2 MB、封面 5 MB。

EPUB 和文本书刊由后端解析为私有章节；PDF 和封面使用七牛存储。书库专用上传使用 `community-library` 权限，无需额外授予通用上传的 `cloud-resource`。

### 5.4 查结果、上架、生成 PDF 分页

```sh
tstj library list --kind paper --status draft --keyword "机器人" --page 1
tstj library show 123
tstj library publish 123
tstj library generate-pdf 123
```

- 列表每页 20 条，按 ID 倒序；可查管理权限范围内的全库记录，不限本人 CLI 新建内容。
- 草稿上架用 `publish ID`，保留原 ID。`upload --publish` 已上架的记录无需再执行一次 publish。
- **PDF 入库不等于分页完成**：`generate-pdf` 提交 `library_pdf` 队列；`queued` 只表示已排队。用 `show` 查询 `pdf_status`，等到 `ready` 再验收阅读。EPUB、文本不需要分页任务。

### 5.5 修改原记录

```sh
# 改价格或资料
tstj library update 123 --price 19.90 --title "修正标题"

# 更换 PDF 或论文解读
tstj library update 123 --file-url https://example.com/corrected.pdf
tstj library update 123 --content-file ./corrected.md

# 换 EPUB，或清空可选字段、取消精选
tstj library update 123 --file ./corrected.epub
tstj library update 123 --summary "" --tags "" --unfeatured
```

更新只发送提供的字段。没传 `--price` 就保留原价，没传文件就保留原阅读内容；保留 ID、类型、上架状态、订单和书架关联。

`--kind` 在 update 中只核对现有类型，不能把书刊改成论文。update 不接受 `--publish`；要上架使用 `publish ID`。替换 PDF 后需重新执行 `generate-pdf ID`；只修改论文解读会保留原 PDF。

摘要、封面、作者、出版方、编号可以用空字符串清空，标签用 `--tags ""` 清空；已上架书刊仍须保留有效封面。

## 6. HTML 页面与通用文件上传

```sh
# 通用文件上传：成功后取 data.preview_url 用于正文或封面
tstj upload ./cover.png

# 创建并立即发布 HTML 页面
tstj pages create --file ./page.html --title "活动页面" --slug campaign

# 查询或修改原页面
tstj pages list
tstj pages show 123
tstj pages update 123 --file ./corrected.html --title "修正标题"
tstj pages update 123 --slug new-campaign
```

- 通用文件上传上限为 CLI 100 MB，后端还校验存储配置上限；仅上传新对象，不覆盖已有对象。
- 页面新建必填 `--file`、`--title`，`--slug` 可选；HTML 文件最多 2 MB。页面标题、内容、slug 可分别修改。
- slug 是 `/page/` 后的链接别名，仅小写字母、数字和单连字符，最长 100 字符且全站唯一。改别名会让旧链接失效，不自动重定向。
- 页面仅可操作本人通过 API 创建的记录，不能修改历史网站页面或他人页面。

## 7. 视频：导出清单，再下载

```sh
tstj videos categories
tstj videos list --category 3 --keyword "课程" --page 1 --page-size 100

# 全部匹配记录导出，不只当前页
tstj videos export --category 3 --out ./videos.csv

# 也可按视频 ID 导出；不能与分类等筛选同时使用
tstj videos export --ids 12,15 --out ./selected.csv

# 先查看下载计划
tstj videos download --manifest ./videos.csv --dir ./downloads --dry-run

# 下载视频及配套文稿
tstj videos download --manifest ./videos.csv --dir ./downloads --with-documents
```

列表和导出支持 `--category`、`--keyword`、`--uploader`；列表另支持 `--page`、`--page-size`（最多 100）。`--uploader` 为上传人筛选值，不切换认证身份。

导出清单的父目录须存在，已有 CSV 不覆盖；无筛选导出全部视频。下载只需本地 CSV，不需网站凭证；已有同名目标文件跳过，不覆盖。存在下载失败项时退出码为 1，下载结果包含路径、状态及成功文件的 SHA-256。

视频模块管理的是“视频存储”清单，不是上传或修改星智源的视频栏目。

## 8. 按 ID 修改与参数区别

| 要做的事 | 正确命令 | 说明 |
| --- | --- | --- |
| 修改资讯 | `tstj news update 123 ...` | 保留原 ID、链接和未传字段 |
| 修改星球文章 | `tstj community update 456 ...` | 保留原 ID，但按星球规则可能重新审核 |
| 修改书刊或论文 | `tstj library update 789 ...` | 保留原 ID、类型、上架状态和关联 |
| 修改页面 | `tstj pages update 123 ...` | 保留原 ID；显式改 slug 会改变公开链接 |

不存在或无权限的 ID 会报错，**更新失败不回退为新建**。更新至少提供一个待修改字段。所有写请求都不自动重试；新建超时后先查列表，确认是否已经保存，避免重复记录。

| 易混参数 | 资讯 | 星球文章 | 书刊论文 |
| --- | --- | --- | --- |
| `--category` | 数字分类 ID | 无此参数 | 分类文字 |
| `--author` | 不支持指定作者 | 发布人账号数字 ID | 作者展示文字 |
| 时间 | `--published-at`，北京时间或 Unix 秒 | `--published-at`，北京时间字符串 | `--published-date`，出版日期 |
| 本地封面 | 先 `upload`，再传返回 URL | 先 `upload`，再传返回 URL | `--cover` 可直接传本地图片 |
| 发布 | upload 后单独 publish | 投稿后遵循审核规则 | upload 加 `--publish` 或单独 publish |

## 9. 对应 HTTP 接口

以下路径已列入当前源码的 AK/SK 白名单。CLI 自动完成签名，通常无需手写 HTTP 请求。三类正文更新都使用 PUT；通用 `request` 命令只允许 GET，不能用它发 PUT、POST 或 DELETE。

| 模块 | 方法与完整路径 | CLI 对应动作 |
| --- | --- | --- |
| 身份 | GET `/miniapp/open/me` | `whoami` |
| 权限 | GET `/miniapp/admin/auth/permissions` | `permissions` |
| 资讯 | GET `/miniapp/admin/automation/news/categories` | `news categories` |
| 资讯 | GET `/miniapp/admin/automation/news` | `news list` |
| 资讯 | GET `/miniapp/admin/automation/news/{id}` | `news show ID` |
| 资讯 | POST `/miniapp/admin/automation/news` | `news upload` |
| 资讯 | PUT `/miniapp/admin/automation/news/{id}` | `news update ID` |
| 资讯 | POST `/miniapp/admin/automation/news/{id}/publish` | `news publish ID` |
| 星球 | GET `/miniapp/open/community/planets` | `community planets` |
| 星球 | GET `/miniapp/open/community/planets/{id}` | `community planet ID` |
| 星球 | GET `/miniapp/open/community/planets/{id}/articles` | `community articles ID` |
| 星球 | GET `/miniapp/open/community/articles/{id}` | `community article ID` |
| 星球 | POST `/miniapp/open/community/planets/{id}/articles` | `community publish --planet ID` |
| 星球 | PUT `/miniapp/open/community/articles/{id}` | `community update ID` 或 `publish --id ID` |
| 书库 | GET `/miniapp/admin/automation/library` | `library list` |
| 书库 | GET `/miniapp/admin/automation/library/{id}` | `library show ID` |
| 书库 | POST `/miniapp/admin/automation/library` | `library upload` |
| 书库 | PUT `/miniapp/admin/automation/library/{id}` | `library update ID` |
| 书库 | POST `/miniapp/admin/automation/library/{id}/publish` | `library publish ID` |
| 书库 | POST `/miniapp/admin/automation/library/{id}/generate-pdf` | `library generate-pdf ID` |
| 书库 | POST `/miniapp/admin/automation/library/uploads` | 本地 PDF、封面的自动上传步骤 |
| 书库 | POST `/miniapp/admin/automation/library/uploads/{id}/complete` | 自动确认书库文件上传 |
| 文件 | POST `/miniapp/admin/automation/uploads` | `upload` 自动申请凭证 |
| 文件 | POST `/miniapp/admin/automation/uploads/{id}/complete` | `upload` 自动确认文件 |
| 页面 | GET `/miniapp/admin/automation/pages` | `pages list` |
| 页面 | GET `/miniapp/admin/automation/pages/{id}` | `pages show ID` |
| 页面 | POST `/miniapp/admin/automation/pages` | `pages create` |
| 页面 | PUT `/miniapp/admin/automation/pages/{id}` | `pages update ID` |
| 视频 | GET `/miniapp/admin/video-storage/categories` | `videos categories` |
| 视频 | GET `/miniapp/admin/video-storage/files` | `videos list` |
| 视频 | POST `/miniapp/admin/video-storage/files/export` | `videos export`，只读导出 |

需要资讯或页面列表翻页时：

```sh
tstj request GET '/miniapp/admin/automation/news?page=2&per_page=20'
tstj request GET '/miniapp/admin/automation/pages?page=2&per_page=20'
```

## 10. 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 找不到 `tstj` 命令 | 使用 `node "$HOME/.tstj/cli/tstj.mjs" ...`；或把安装目录加入 PATH |
| CLI 没有 library / update 命令 | 更新本机 CLI；同时确认站点下载包包含新命令 |
| 返回 401 或签名失败 | 检查凭证是否过期、作废，后端源站地址及本机时间是否正确 |
| 返回 403 | 先用 `whoami` 查接口白名单，再查模块权限、内容归属或星球成员权益 |
| library upload 可用，list / show 被拒绝 | 检查线上是否部署两个 library GET 白名单及刷新配置缓存 |
| 返回 422 | 检查分类 ID / 文字、作者 ID / 文字、日期格式、必填字段和文件限制 |
| 发布后内容仍未公开 | 星球文章看是否 `pending`；书库看上架状态；PDF 另看 `pdf_status` |
| 上传或新建超时 | 先查对应列表和详情，确认结果后再决定是否重新提交 |

本地命令存在不代表线上接口已开放；上线需同步后端、路由和配置缓存以及前端 CLI 下载资源，再更新本机安装。本文没有执行上传、发布或修改线上内容。

详细资料：[安装说明](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/docs/cli-installation.md)、[书刊论文](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/docs/library-cli.md)、[资讯](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/docs/news-cli.md)、[视频清单](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/docs/video-storage-cli.md)、[AK/SK 接口与发布人规则](/Users/shengli/Documents/mulu/Project/gitlab/tstj_admin/docs/member-access-keys.md)。
