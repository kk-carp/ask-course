# 项目文档导航

[项目首页](../README.md)

## 按任务阅读

- 首次运行：[本地启动](getting-started/README.md) → [接口操作示例](reference/api-examples.md)。
- 运营验收：[L0 内部运营](operations/L0_OPERATIONS.md) → [官网试运行准出](operations/PILOT_LAUNCH.md) → [课程内容模板](templates/课程内容模板.md)。
- 开发维护：[当前实现](architecture/current-system.md) → [开发指南](development/README.md)。
- 产品评审：[需求分析报告](product/售前Agent助手_需求分析报告.html) → [PRD 骨架](product/售前Agent助手_PRD骨架.html) → [问诊与推荐规则设计](product/售前Agent助手_问诊与推荐规则设计.html)。
- 官网对接：[全站接入实施计划](integration/官网全站接入实施计划.md) → [官网试运行准出](operations/PILOT_LAUNCH.md) → [接入方式调研](research/售前Agent助手_接入方式调研.html) → [对接确认清单](integration/售前Agent_对接确认清单.html)。
- 了解精简范围：[售前代码边界](architecture/presales-scope.md)。
- 理解复用背景：[P0 独立部署与 FDE 复用方案](architecture/售前Agent助手_P0独立部署与FDE复用方案.html)。

## 文档状态与维护方式

最新接入进度：Vue + Ant Design Vue 界面已推送；已实现全站游客入口、服务端历史和 Alembic 迁移，未公开发布。接入步骤见[游客全站接入](integration/游客全站接入.md)。后续会员身份和生产存储方案需确认。具体范围、接口和验收条件见[全站接入实施计划第 7 节](integration/官网全站接入实施计划.md#7-下一步改进方案与实施顺序)。

`getting-started/`、`operations/`、`reference/`、`development/` 和 `architecture/current-system.md` 维护当前操作方法与实现说明。L0 手册中的准出条件属于验收目标，必须以实际评测和业务确认结果判断是否达成。

`product/`、`research/`、`integration/` 及 FDE 复用方案包含规划、调研和协作材料，既有 HTML 保留供浏览器阅读。[全站接入实施计划](integration/官网全站接入实施计划.md) 维护最新接入范围和实施顺序。这些材料可能包含历史路径、待确认项或尚未实现的能力，不作为当前运行状态的证明。原复用方案提到的 `P0_REUSE.md` 未随项目提供，复用背景请阅读方案本身。

新增文档按用途放入对应目录，并更新本导航；根 README 只保留项目介绍、能力边界和入口。命令默认从项目根目录执行，文档链接则相对当前文档编写。功能行为变化时同步更新当前实现和相关操作说明，避免重复维护完整步骤。

`templates/` 保存可复用模板；`data/` 中的课程语料和上传文件由运行流程管理。旧的 `docs/L0_OPERATIONS.md` 仅作为兼容入口。
