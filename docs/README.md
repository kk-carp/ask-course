# 项目文档导航

[项目首页](../README.md)

## 开始使用

- [本地启动](getting-started/README.md)：依赖、数据库迁移、构建与页面入口。
- [内部运营](operations/L0_OPERATIONS.md)：课程正文、联系人、入库与内部试用。
- [接口操作示例](reference/api-examples.md)：本项目 API 的使用方式。
- [开发指南](development/README.md)：代码入口、回归与 PostgreSQL 集成检查。

## 需求、实现与下一步

- [产品需求与规则](product/requirements.md)：目标、业务规则和暂缓范围。
- [当前实现与边界](architecture/current-system.md)：已实现能力与尚未验收的条件。
- [改进计划](development/roadmap.md)：剩余差距、实施顺序及完成标准。
- [售前代码边界与兼容](architecture/presales-scope.md)：保留/移除能力及旧数据库兼容。
- [成熟项目对标依据](research/mature-project-benchmarks-2026-10-09.md)：2026-10-09 的一手资料研究快照，不是性能实测或选型结果。

## 接入与发布

- [游客接入](integration/游客接入.md)：独立 `/consult`、官网脚本、游客历史协议。
- [官网客户身份与历史归属](integration/官网客户身份与历史归属.md)：主体、权限、关联及保留规则。
- [官网身份校验接口](integration/官网身份校验接口.md)：已观察请求、适配器行为和撤销限制。
- [官网身份事件接入](integration/官网身份事件接入.md)：助手清理通知桥及尚未接入的官网事件。
- [官网对接问题清单](integration/官网对接问题清单.md)：具备接入条件后需要确认的外部事项。
- [试运行准出](operations/PILOT_LAUNCH.md)：审核、门禁、灰度和关闭条件。
- [预发布验收](operations/ACCEPTANCE.md)：人工质量、身份隔离和环境签收。
- [部署、备份与回滚](operations/DEPLOYMENT.md)：部署配置、迁移、恢复和容量验证。
- [隐私、资料检查与告警](operations/PRIVACY_AND_SAFETY.md)：用户告知、发布扫描、历史复核及独立监控。

## 资料与维护

- [课程内容模板](templates/课程内容模板.md)。
- [官网外部接口资料](reference/official/README.md)：用户提供的 API 与 CLI 原文，与本项目实现分开。

当前能力只在 `architecture/current-system.md` 维护；需求、改进计划和操作手册各司其职，不重复累积提交历史和测试计数。功能变化同步相关说明，测试与生产签收分别记录。删除的早期方案和进度快照可从 Git 历史恢复，不再保留旧路径跳转页。

本次整理只处理版本管理中的项目说明。课程原始语料、教师资料、图片附件、上传文件和原始评测结果属于业务资料，不按旧文档删除；通过受控目录及存储维护，不提交敏感凭证。
