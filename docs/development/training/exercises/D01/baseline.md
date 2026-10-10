项目路径：D:\p0-arborseek-agent
python版本：Python 3.11.9
当前git提交：ae464f89882ea3305fc1b569b84ed18f58b72ad5
当前git有大量改动未提交

检查记录如下，命令均在项目根目录执行。结果来自我在训练聊天中提供的终端输出，本次整理没有重新运行测试。

## 内核自检

```powershell
.venv\Scripts\python.exe scripts/smoke_kernel.py
```

结果：36 项通过，0 项失败。

其中转人工检查使用了替身会话对象，产生缺少 scalars 方法的 AttributeError 日志。异常被捕获后返回 route="none"，符合自检允许的降级结果，因此该项通过。这不代表真实数据库断连行为已经验证。

## 指定文件的小测试

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_intent_router.py tests/test_qa_retrieval.py
```

结果：12 项通过，1 个警告，耗时 2.61 秒。

## 完整 pytest 检查

```powershell
.venv\Scripts\python.exe -m pytest -q
```

结果：308 项通过，41 项跳过，1 个警告，耗时 12.26 秒。跳过项不计为通过。

两次 pytest 输出中的警告均为 Starlette 引用已弃用的 AnyIO 别名，没有导致本次测试失败。

## 跳过原因核实

```powershell
.venv\Scripts\python.exe -m pytest -q -rs
```

已提供的跳过摘要显示：41 项均因未设置 TEST_POSTGRES_URL 而跳过，属于 PostgreSQL 集成测试。本次完整的通过数量和耗时未单独记录，不沿用上一次结果作为这次的结果。

## 尚未验证的范围

- 真实 PostgreSQL 集成行为尚未验证，包括相应迁移、资料发布、入库和并发归属等测试覆盖的行为。
- 真实模型调用和完整问答服务尚未验证。模型地址格式检查通过不能证明模型服务可连接。
- 当前提交号不包含工作区的未提交改动，因此仅凭提交号不能完整恢复本次测试的代码状态。
