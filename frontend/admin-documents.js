/* Internal document maintenance. API permissions remain authoritative. */
(function () {
  window.createDocumentManager = function ({root, getUser, getCourseId, showError}) {
    let items = [];
    let generation = 0;
    let busy = false;
    const allowed = () => Boolean(getUser()?.can_manage_documents);
    const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
    const labels = {ready: '已发布', pending: '待审核', offline: '已撤回', failed: '入库失败', processing: '处理中'};

    function render() {
      if (!allowed()) { root.replaceChildren(); return; }
      const course = getCourseId();
      const visible = items.filter(item => !course || item.course_id === course);
      const target = document.getElementById('replacement-target');
      if (target) {
        const selected = target.value;
        target.innerHTML = '<option value="">新增独立资料</option>' + visible.filter(item => item.status === 'ready' && item.course_id === course)
          .map(item => `<option value="${escape(item.id)}">替换：${escape(item.title)}</option>`).join('');
        target.value = [...target.options].some(option => option.value === selected) ? selected : '';
      }
      root.innerHTML = `<button type="button" class="ghost" data-refresh ${busy ? 'disabled' : ''}>刷新资料</button>
        <p>${course ? `课程 ${escape(course)}` : '全部课程'} · ${visible.length} 份资料</p>` +
        visible.map(item => `<article class="document-card">
          <strong>${escape(item.title)}</strong>
          <div>课程 ${escape(item.course_id || '未标注')} · ${escape(item.space_id)} · ${escape(labels[item.status] || item.status)} · ${escape(item.chunk_count)} 片</div>
          ${item.error ? `<p class="err">失败原因：${escape(item.error)}</p>` : ''}
          ${item.reviews?.length ? `<details><summary>审核与撤回记录</summary>${item.reviews.map(review =>
            `<p>${escape({publish:'审核发布', withdraw:'主动撤回', superseded:'被新版替换'}[review.action] || review.action)} · ${escape(review.actor_id)} · ${escape(review.created_at)}<br>${escape(review.note)}</p>`).join('')}</details>` : ''}
          <div class="row-actions">
            <a href="/documents/${encodeURIComponent(item.id)}/file" download>下载原文</a>
            ${item.supersedes_id ? `<span>替换版本：${escape(item.supersedes_id)}</span>` : ''}
            ${item.status === 'pending' ? `<button type="button" class="ghost" data-action="publish" data-id="${escape(item.id)}" ${busy ? 'disabled' : ''}>审核并发布</button>` : ''}
            ${item.status === 'ready' ? `<button type="button" class="ghost" data-action="review" data-id="${escape(item.id)}" ${busy ? 'disabled' : ''}>复核安全并留档</button>` : ''}
            ${item.status === 'offline'
              ? `<button type="button" class="danger" data-action="delete" data-id="${escape(item.id)}" ${busy ? 'disabled' : ''}>永久删除</button>`
              : `<button type="button" class="ghost" data-action="offline" data-id="${escape(item.id)}" ${busy ? 'disabled' : ''}>撤回</button>`}
          </div></article>`).join('') + (visible.length ? '' : '<p>暂无资料。</p>');
    }

    function clear() {
      generation += 1;
      items = [];
      root.replaceChildren();
      const target = document.getElementById('replacement-target');
      if (target) target.innerHTML = '<option value="">新增独立资料</option>';
    }

    async function request(url, options) {
      const response = await fetch(url, {credentials: 'include', ...options});
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === 'string' ? body.detail : `资料操作失败（${response.status}）`);
      }
      return response.json();
    }

    async function refresh() {
      if (!allowed()) { clear(); return; }
      const current = ++generation;
      try {
        const result = await request('/documents');
        if (current !== generation || !allowed()) return;
        items = result;
        render();
      } catch (error) {
        if (current !== generation || !allowed()) return;
        items = [];
        render();
        showError(error.message || '资料列表加载失败，请重试。');
      }
    }

    root.addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button || busy || !allowed()) return;
      if (button.hasAttribute('data-refresh')) { showError(''); await refresh(); return; }
      const item = items.find(value => value.id === button.dataset.id);
      if (!item) return;
      const action = button.dataset.action;
      const reviewing = action === 'publish' || action === 'review';
      let note;
      if (reviewing) {
        note = window.prompt('请先核对原文，填写审核依据（如课程负责人确认记录、适用范围）：');
        if (!note?.trim()) return;
        note = note.trim();
      }
      const message = action === 'delete'
        ? `永久删除“${item.title}”？原文和检索片段将被删除，此操作不可恢复。`
        : reviewing ? `确认已逐项检查“${item.title}”：\n① 来源已公开且允许对外使用\n② 无密钥、个人信息、内部报价或合同\n③ 价格、功能和合作等商业信息已经负责人核对\n④ 无要求模型忽略规则的嵌入指令\n全部确认后留档。${action === 'publish' && item.supersedes_id ? '旧版将同时撤回。' : ''}`
        : `撤回“${item.title}”？正在生成且依赖该资料的回答将停止输出。`;
      if (!window.confirm(message)) return;
      const current = generation;
      busy = true;
      showError('');
      render();
      try {
        await request(`/documents/${encodeURIComponent(item.id)}${action === 'delete' ? '' : '/' + action}`,
          reviewing ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({note, safety_checks:{public_source:true, no_sensitive_data:true, business_verified:true, no_embedded_instructions:true}})}
            : {method: action === 'offline' ? 'POST' : 'DELETE'});
        if (current === generation && allowed()) await refresh();
      } catch (error) {
        if (current === generation && allowed()) showError(error.message || '操作失败，请重试。');
      } finally {
        busy = false;
        render();
      }
    });
    return {refresh, render, clear};
  };
})();
