# 部署、备份与回滚

一期部署单副本。先在预发布完成本文演练；提供部署文件不代表完成真实生产验收。

## 配置和发布

1. 复制 `.env.example` 为 `.env.deploy`。设置 `APP_ENV=prod`、随机 `SECRET_KEY`、非默认 `DEMO_PASSWORD`、模型网关凭证和真实兜底联系人。
2. 增加 `POSTGRES_PASSWORD`，将 `DATABASE_URL` 指向 Compose 内的 `postgres:5432/arborseek_p0`。数据库 URL 中的密码需要 URL 编码。不要沿用本机 `localhost` 数据库地址。
3. 首次发布先保持 `PILOT_PERCENT=0`，不开放入口。准备本地 `data` 和 `docs`：课程原始资料不在仓库和镜像中，需通过受控渠道交付；本地运行资料整理/入库工具。挂载的资料需与代码版本一起备份。
4. `docker compose --env-file .env.deploy config --quiet` 验证配置；`docker compose --env-file .env.deploy build` 构建镜像。
5. 记录当前 Git 提交，将镜像标记为对应版本，例如 `ask-course:<commit>`，设置 `AGENT_IMAGE`。先备份数据库及资料，在数据库副本验证迁移；正式升级时先停止旧 API，再启动数据库，使用新镜像运行一次迁移，最后启动 API：

   ```powershell
   docker compose --env-file .env.deploy stop api
   docker compose --env-file .env.deploy up -d postgres
   docker compose --env-file .env.deploy run --rm --no-deps api python -m alembic upgrade head
   docker compose --env-file .env.deploy up -d --no-build api
   ```

   迁移前确认数据库已就绪。任一迁移步骤失败时停止发布，按备份与迁移恢复方案处理；不要继续启动新 API。
6. 第一次启动可能下载模型，模型缓存持久化。确认 `/ready` 返回 200，再运行准出检查和真实课程评测。
7. 官网同源代理 `/agent/` 到本服务，去掉前缀，关闭 SSE 缓冲，代理读取超时至少 180 秒。API 只绑定本机端口，由官网提供 HTTPS。测试移动端、登录和购买跳转。

`requirements.txt` 固定已验证的直接依赖版本；CI 使用不加载模型的 `requirements-ci.txt`。镜像版本及模型缓存固定后再发布，避免每次现场重新安装。CI 的虚构资料回归测试不能代替真实模型验收。

## 数据库升级

数据库结构由 Alembic 版本化迁移管理。应用启动要求版本已到当前代码的 `head`，不代替发布前迁移。首次基线接管旧结构并保留业务数据。升级前先备份，在数据库副本运行 `python -m alembic upgrade head`，核对文档、分片、向量、会话及完整消息后再升级正式库。迁移由单一发布步骤执行，不让多个副本同时迁移。删除或数据转换须有独立恢复方案，不能只靠应用镜像回退。

当前 `head` 为 `0003`，新增官网客户主体与咨询排他所有者约束。升级保留旧游客消息和活动时间。仅在没有客户主体与客户咨询数据时允许降回 `0002`；存在客户数据时迁移主动拒绝降级。旧应用的游客清理规则不兼容客户保留期，不能仅回退旧镜像继续运行，需保持兼容版本或采用已验证的备份恢复方案。

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

发现错误购买页、错误顾问或严重事实错误时，先把 `/pilot/control` 设置为 0，确认官网入口隐藏；官网同时保留撤下注入脚本的回滚方式。

保留上一版本镜像及匹配的本地资料，修改 `AGENT_IMAGE` 为上一版本后执行 `docker compose --env-file .env.deploy up -d --no-build api`，检查 `/ready` 与核心案例。不要执行 `down -v`，它会删除持久化数据库。

使用 `scripts/load_test.py` 在预发布测试实际模型的 1、5、10 并发；观察错误率、P50/P95、请求日志的 `duration_ms`，同时确认健康检查不被慢咨询阻塞。先据实记录容量，再确定流量比例。共享限流和多副本不在本次单副本试运行范围。

CPU 部署支持 `EMBED_CPU_THREADS=2` 控制推理线程竞争，保持 20 个重排候选。2026-09-30 本地 5 并发、5 请求零错误，但 P95 为 56.761 秒，不满足流畅体验。减少到 8 候选未改善采样耗时，因此没有更改默认候选数。阶段耗时通过管理员 `/metrics` 的 `latency_ms` 查看。该少量采样不能作为生产容量结论。

同日已完成当前数据库的独立空库恢复演练：原库与恢复库均为 8 个文档、112 个分片，恢复向量维度 1024。备份仅在本地，恢复验证库为 `arborseek_restore_check_20260930`。尚需在预发布用完整上传文件恢复并验证问答，以及执行镜像切换回滚。
