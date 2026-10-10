"""公开、动态的隐私告知，不返回凭证或内部配置。"""

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from backend.config import settings

router = APIRouter(tags=["privacy"])


def privacy_notice() -> dict:
    return {
        "version": "2026-10-10",
        "operator": settings.privacy_operator or "运营主体尚未配置（本地测试）",
        "contact": settings.privacy_contact or "联系渠道尚未配置（本地测试）",
        "model_provider": settings.privacy_model_provider or "模型服务商尚未确认（本地测试）",
        "sections": [
            ("用途与范围", "用于课程咨询、多轮上下文、历史记录、人工咨询跳转和服务安全运维。处理你输入的问题及回答、课程页面编号、学习需求摘要、会话名称和必要的会话标识；若官网身份联动已启用，还处理官网提供的用户编号。不会要求提供身份证、支付密码、银行卡或合同，请勿在问题或对话名称中输入敏感信息。"),
            ("浏览器存储", f"使用 Cookie 和本地会话编号维持身份与历史访问。游客标识 Cookie 最长保存 {settings.visitor_cookie_max_age // 86400} 天，内部登录 Cookie 最长 7 天；本地会话编号可通过清除站点数据删除。打开组件也会记录展示、打开等运行事件。"),
            ("保存与删除", f"游客咨询按最后活动保留 {settings.visitor_consultation_hours} 小时；官网登录用户咨询按最后活动保留 {settings.customer_consultation_days} 天；内部工具会话按最后更新保留 {settings.data_retention_days} 天。运行事件保留 30 天。到期由约 5 分钟一次的清理任务删除。支持历史功能时可在历史列表删除会话；也可通过下述联系渠道申请访问、更正或删除。备份、访问日志的保留期和删除处理由运营方另行确认，数据库自动清理不等于备份立即删除。"),
            ("模型与人工服务", "生成回答时会把当前问题、必要的近期对话或摘要以及相关已发布课程片段发送到配置的模型服务商。服务商的处理地点、保留政策及是否用于训练应由运营方审核并提供说明，本告知不承诺其不留存或不训练。打开顾问二维码或外部网站后，由相应服务方按其规则处理信息。咨询记录不会自动作为课程知识库资料发布。"),
            ("安全与选择", "应用运行指标不记录问题正文；运维人员按权限处理服务记录。你可停止使用、删除已有咨询或联系运营方处理数据请求。AI 回答仅供参考，重要课程及交易信息请向课程顾问确认。"),
        ],
    }


@router.get("/privacy/notice")
def get_privacy_notice() -> dict:
    return privacy_notice()


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
def privacy_page() -> HTMLResponse:
    notice = privacy_notice()
    sections = "".join(f"<h2>{escape(title)}</h2><p>{escape(body)}</p>" for title, body in notice["sections"])
    return HTMLResponse(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>课程咨询隐私告知</title><style>body{max-width:760px;margin:32px auto;padding:0 20px;'
        'font:16px/1.8 system-ui;color:#243047}h2{font-size:19px}</style>'
        '<main><h1>课程咨询隐私告知</h1>'
        f'<p>版本：{notice["version"]}<br>运营主体：{escape(notice["operator"])}'
        f'<br>联系渠道：{escape(notice["contact"])}<br>模型服务商：{escape(notice["model_provider"])}</p>'
        f'{sections}</main></html>', headers={"Cache-Control": "no-store"},
    )
