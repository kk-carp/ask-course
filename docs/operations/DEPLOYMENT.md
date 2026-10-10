# 部署、备份与回滚

一期部署单副本。先在预发布完成本文演练；提供部署文件不代表完成真实生产验收。

## 配置和发布

1. 复制 `.env.example` 为 `.env.deploy`。设置 `APP_ENV=prod`、随机 `SECRET_KEY`、非默认 `DEMO_PASSWORD`、模型网关凭证和真实兜底联系人。
   按 [隐私与告警配置](PRIVACY_AND_SAFETY.md) 填写真实运营主体、隐私联系方式和模型服务商并人工确认；设置独立监控凭证、模型单价及每日预算。缺少隐私确认或监控凭证时生产启动会拒绝。
2. 增加 `POSTGRES_PASSWORD`，将 `DATABASE_URL` 指向 Compose 内的 `postgres:5432/arborseek_p0`。数据库 URL 中的密码需要 URL 编码。不要沿用本机 `localhost` 数据库地址。
3. 首次发布先保持 `PILOT_PERCENT=0`，不开放入口。准备本地 `data` 和 `docs`：课程原始资料不在仓库和镜像中，需通过受控渠道交付；本地运行资料整理/入库工具。挂载的资料需与代码版本一起备份。
4. `docker compose --env-file .env.deploy config --quiet` 验证配置；`docker compose --env-file .env.deploy build` 构建镜像。
5. 记录当前 Git 提交，将镜像标记为对应版本，例如 `ask-course:<commit>`，设置 `AGENT_IMAGE`。先备份数据库及资料，在数据库副本验证迁移；正式升级时先停止旧 API，再启动数据库，使用新镜像运行一次迁移，最后启动 API：

   ```powershell
   docker compose --env-file .env.deploy stop api
   docker compose --env-file .env.deploy up -d postgres
   docker compose --env-file .env.deploy run --rm --no-deps api python -m alembic upgrade head
   docker compose --env-file .env.deploy up -d --no-build api monitor
   ```

   迁移前确认数据库已就绪。任一迁移步骤失败时停止发布，按备份与迁移恢复方案处理；不要继续启动新 API。
6. 第一次启动可能下载模型，模型缓存持久化。确认 `/ready` 返回 200，再运行准出检查和真实课程评测。
7. 当前官网无法修改，可先由独立 HTTPS 网关代理到本服务的 `/consult` 验证游客流程。官网具备条件后再同源代理 `/agent/` 并剥离前缀；两种方式均须关闭 SSE 缓冲和共享缓存，读取超时至少 180 秒。API 只绑定本机端口，数据库与内部管理入口不向公众代理。测试移动端和购买跳转，官网身份联动另行签收。

`requirements.txt` 固定已验证的直接依赖版本；CI 使用不加载模型的 `requirements-ci.txt`。镜像版本及模型缓存固定后再发布，避免每次现场重新安装。CI 的虚构资料回归测试不能代替真实模型验收。

## 数据库升级

数据库结构由 Alembic 版本化迁移管理。应用启动要求版本已到当前代码的 `head`，不代替发布前迁移。首次基线接管旧结构并保留业务数据。升级前先备份，在数据库副本运行 `python -m alembic upgrade head`，核对文档、分片、向量、会话及完整消息后再升级正式库。迁移由单一发布步骤执行，不让多个副本同时迁移。删除或数据转换须有独立恢复方案，不能只靠应用镜像回退。

当前 `head` 为 `0004`，增加资料继承指针、审核记录和待审核内容去重索引。新上传只进入待审核；升级前已有的 `ready` 资料保持可用，不伪造历史审核记录，应由课程负责人逐份复核。数据库中有待审核资料或审核记录时拒绝降回 `0003`，避免丢失审核证据；`0003` 在客户数据存在时也拒绝降级。必须先停止旧 API、备份数据库与原文件、在副本验证 `python -m alembic upgrade head`，再部署新代码。不能回滚到会自动发布上传资料的旧应用；发生故障先关闭入口，保留兼容版本或恢复已验证的联合备份。撤回与生成竞争已在独立 PostgreSQL 测试库验证，生产恢复演练仍需另行签收。

## 备份与恢复演练

以下以 PowerShell 为例。备份文件包含会话与联系方式，仅保存在受控存储，不提交代码仓库。

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$taskDbContainer = docker compose --env-file .env.deploy ps -q postgres
docker exec $taskDbContainer pg_dump -U postgres -d arborseek_p0 -Fc -f /tmp/arborseek-backup.dump
docker cp "${taskDbContainer}:/tmp/arborseek-backup.dump" backups/arborseek-backup.dump
```

另行备份 `data/uploads`、课程事实/正文/审核目录，以及部署配置；数据库中的文件路径需要对应文件才能恢复。

恢复演练使用独立空库，不覆盖原库：

```powershell
docker exec $taskDbContainer createdb -U postgres arborseek_restore_check
docker exec $taskDbContainer pg_restore -U postgres -d arborseek_restore_check --exit-on-error /tmp/arborseek-backup.dump
docker exec $taskDbContainer psql -U postgres -d arborseek_restore_check -c "SELECT count(*) FROM documents; SELECT count(*) FROM chunks;"
```

将副本应用临时连接到恢复库，验证资料问答、会话、二维码和购买入口。记录备份时间、恢复耗时及数量比对；每天备份，保留最近 7 天及发布前备份。

## 回滚和容量验收

发现错误购买页、错误顾问或严重事实错误时，先把 `/pilot/control` 设置为 0，确认独立页和已接入的官网入口隐藏；官网接入后同时保留撤下注入脚本的回滚方式。

保留上一版本镜像、不可变 SHA256 ID、配置及匹配的本地资料。目标必须兼容 `0004` 且具备当前资料审核、隐私及监控保护，不能回退到自动发布资料的旧应用。执行 `python scripts/rollback_release.py --env-file .env.deploy --previous-image sha256:<完整64位镜像ID>`：先验证镜像安全/结构标签，关闭共享入口、停止 API，再切换 API 和监控镜像，核验 `/ready` 及入口仍为 0。失败时停止 API；不回退数据库、不自动开放灰度。成功后将 `.env.deploy` 的 `AGENT_IMAGE` 同步为核验 ID（脚本只覆盖本次进程），完成核心案例并由负责人签收后再开放。

API 故障时单独执行 `docker compose --env-file .env.deploy run --rm --no-deps api python -m backend.scripts.emergency_stop` 关闭共享入口。随后停止 API 或在网关关闭路由，才能阻断已在处理的请求；灰度开关只拒绝新请求。不要执行 `down -v`，它会删除数据库。

发布前运行 `python scripts/recovery_drill.py`。2026-10-10 已验证虚构资料的数据库/文件联合恢复、全部表行数/内容哈希一致、会话与审核记录保留、停用状态保留及危险降级拒绝。报告明确 `production_tested=false`、`image_rollback_tested=false`。预发布镜像演练另行记录当前/目标镜像 ID、数据备份路径、恢复耗时、实际问答案例及签收人。

使用 `scripts/load_test.py` 在预发布测试实际模型的 1、5、10 并发；观察错误率、P50/P95、请求日志的 `duration_ms`，同时确认健康检查不被慢咨询阻塞。先据实记录容量，再确定流量比例。共享限流和多副本不在本次单副本试运行范围。

CPU 部署支持 `EMBED_CPU_THREADS=2` 控制推理线程竞争，当前配置保持 20 个重排候选。阶段耗时通过管理员 `/metrics` 的 `latency_ms` 查看；优化前固定样本和版本，按证据定位瓶颈。过往少量采样或数据库计数不作为当前生产容量与恢复签收结果，需在预发布验证完整文件恢复、实际问答及镜像回滚。
