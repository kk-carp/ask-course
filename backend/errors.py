"""业务错误语义：503 系统未就绪，502 上游失败；二者都不是知识库未命中。"""


class ServiceUnavailableError(RuntimeError):
    """系统依赖未就绪或不可用。"""


class UpstreamServiceError(RuntimeError):
    """上游模型服务调用失败。"""
