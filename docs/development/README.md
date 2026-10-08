# 开发指南

[文档导航](../README.md) · [当前实现](../architecture/current-system.md)

## 代码入口

- [main.py](../../backend/main.py)：启动、模型加载、中间件与路由挂载。
- `backend/routes/`：HTTP 请求、身份解析及响应适配。
- `backend/services/`：问答、意图分流、入库、课程目录和转人工流程。
- `backend/domain/`：课程内容校验、游客权限等领域规则。
- `backend/infra/`：解析、分块、向量检索、重排和模型调用。
- [schemas.py](../../backend/schemas.py)、[models.py](../../backend/models.py)、[config.py](../../backend/config.py)：接口契约、数据库模型及配置。
- [frontend/index.html](../../frontend/index.html)：内部演示 UI，无需前端构建即可运行。

项目只保留售前主链路及课程资料管理，路由挂载范围以 `backend/main.py` 为准。

## 本地检查

先完成[本地启动](../getting-started/README.md)的依赖安装，在项目根目录使用虚拟环境执行：

```powershell
python scripts/smoke_kernel.py
python -m pytest tests
```

首次咨询和多问题性能回归：`python -m pytest tests/test_response_latency.py`。
用 `python scripts/benchmark_response_latency.py` 对比串行参考路径与最多三项并行的调度耗时；基准模拟每项 120 ms 上游等待，不连接数据库、官网或模型，不代表线上绝对耗时。真实请求按管理员 `/metrics` 的 `latency_ms` 和访问日志的 `duration_ms` 核验。

内核自检不需要数据库、模型或 API Key。资料门禁与联网金标评测见 [L0 手册](../operations/L0_OPERATIONS.md)，单元测试通过不能代替业务验收。

## 同步维护

接口变更同步接口契约和[接口示例](../reference/api-examples.md)；规则或路由变更同步[当前实现](../architecture/current-system.md)；内容准入规则变更同步 [L0 手册](../operations/L0_OPERATIONS.md)及[课程模板](../templates/课程内容模板.md)。

旧 FDE 批量搬运脚本已删除，避免重新引入学院专用模块或覆盖售前改造。

清理说明与已有数据库兼容策略见[售前代码边界](../architecture/presales-scope.md)。
