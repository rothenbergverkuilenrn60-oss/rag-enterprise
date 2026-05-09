(function(){
  "use strict";

  async function ask(){
    const q = document.getElementById('q').value.trim();
    if(!q) return;
    const top_k = parseInt(document.getElementById('topk').value) || 5;
    const out = document.getElementById('out');
    const btn = document.getElementById('btn');
    btn.disabled = true;
    out.innerHTML = '<p class="loading">查询中...</p>';
    try {
      const r = await fetch('/api/v1/query', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({query: q, top_k, include_images: true})
      });
      const j = await r.json();
      if(!j.success){
        out.innerHTML = '<p class="err">错误：' + (j.error || '未知') + '</p>';
        return;
      }
      let h = '<h2>答案</h2><div class="answer">' + esc(j.data.answer) + '</div>';
      h += '<h2>来源（' + (j.data.sources || []).length + '）</h2>';
      (j.data.sources || []).forEach((s, i) => {
        const m = s.metadata || {};
        const score = s.final_score || s.rerank_score || s.rrf_score || s.dense_score || 0;
        h += '<div class="source"><div class="meta">来源' + (i+1) + ' · 页=' + (m.page_number ?? '?') + ' · 类型=' + (m.chunk_type || '?') + ' · score=' + score.toFixed(3) + '</div>';
        h += '<div>' + esc(s.content) + '</div>';
        if(m.image_b64) h += '<img src="data:image/png;base64,' + m.image_b64 + '">';
        h += '</div>';
      });
      out.innerHTML = h;
    } catch(e){
      out.innerHTML = '<p class="err">请求失败：' + e + '</p>';
    } finally {
      btn.disabled = false;
    }
  }

  function esc(s){
    return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn').addEventListener('click', ask);
    document.getElementById('q').addEventListener('keydown', e => {
      if(e.ctrlKey && e.key === 'Enter') ask();
    });
  });
})();
