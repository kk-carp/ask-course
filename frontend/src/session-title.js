// 根据用户提问提炼主题，不增加模型调用，也不把推断写成课程事实。
export function sessionTitle(turns, courseTitle = '') {
  const text = turns.map(turn => turn.question).join(' ');
  const subject = /四足|机器狗/.test(text) ? '四足机器人' : /机械臂|抓取/.test(text) ? '智能机械臂' : /大模型|\bAI\b|人工智能/i.test(text) ? 'AI 大模型' : courseTitle;
  const topics = [
    [/推荐|选课|适合/, '选课建议'], [/基础|零基础|入门/, '学习基础'],
    [/硬件|设备|电脑|机器人.*购买/, '设备要求'], [/价格|多少钱|费用/, '课程费用'],
    [/目录|内容|项目|学什么/, '课程内容'], [/顾问|人工|联系/, '顾问咨询'],
  ].filter(([pattern]) => pattern.test(text)).map(([, label]) => label).slice(0, 2);
  const summary = topics.length ? `${subject ? subject + '：' : ''}${topics.join('与')}` : (subject || turns[0]?.question || '新会话');
  const normalized = summary.replace(/[\r\n\t]+/g, ' ').replace(/\s+/g, ' ').trim();
  return [...normalized].length > 26 ? [...normalized].slice(0, 25).join('') + '…' : normalized;
}
