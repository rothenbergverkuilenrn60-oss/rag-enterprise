# =============================================================================
# eval/report_renderer.py
# RAGAS 评测 HTML 报告渲染器（Jinja2）
# =============================================================================
from __future__ import annotations

from eval.models import EvalReport

_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RAG 评测报告 — {{ report.run_id }}</title>
<style>
  :root {
    --blue: #2563eb; --green: #16a34a; --red: #dc2626;
    --amber: #d97706; --gray: #6b7280; --bg: #f8fafc;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: #1e293b; }
  header { background: var(--blue); color: white; padding: 24px 40px; }
  header h1 { font-size: 1.5rem; margin-bottom: 4px; }
  header p  { font-size: 0.875rem; opacity: 0.85; }
  .container { max-width: 1200px; margin: 0 auto; padding: 32px 40px; }

  /* 指标卡片 */
  .metrics-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }
  .metric-card  { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); text-align: center; }
  .metric-card .label { font-size: .75rem; color: var(--gray); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; }
  .metric-card .value { font-size: 2rem; font-weight: 700; }
  .score-high   { color: var(--green); }
  .score-mid    { color: var(--amber); }
  .score-low    { color: var(--red); }
  .score-na     { color: var(--gray); font-size: 1.25rem !important; }

  /* 总览卡片 */
  .overview { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 32px; }
  .overview h2 { font-size: 1rem; margin-bottom: 16px; color: var(--blue); }
  .overview table { width: 100%; border-collapse: collapse; font-size: .875rem; }
  .overview td { padding: 6px 12px; border-bottom: 1px solid #f1f5f9; }
  .overview td:first-child { color: var(--gray); width: 200px; }

  /* 明细表 */
  .detail { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  .detail h2 { font-size: 1rem; margin-bottom: 16px; color: var(--blue); }
  table.detail-table { width: 100%; border-collapse: collapse; font-size: .8rem; }
  table.detail-table th { background: #f1f5f9; padding: 8px 10px; text-align: left; font-weight: 600; }
  table.detail-table td { padding: 8px 10px; border-bottom: 1px solid #f8fafc; vertical-align: top; }
  table.detail-table tr:hover td { background: #f8fafc; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: .7rem; font-weight: 600; }
  .badge-ok  { background: #dcfce7; color: var(--green); }
  .badge-err { background: #fee2e2; color: var(--red); }
  .truncate { max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
</head>
<body>

<header>
  <h1>🔍 RAG 评测报告</h1>
  <p>Run ID: {{ report.run_id }} &nbsp;|&nbsp; 数据集: {{ report.dataset_name }} &nbsp;|&nbsp;
     Judge: {{ report.judge_model }} &nbsp;|&nbsp; {{ report.started_at.strftime('%Y-%m-%d %H:%M:%S') }} UTC</p>
</header>

<div class="container">

  <!-- 核心指标卡片 -->
  <div class="metrics-grid">
    {{ score_card("Overall", report.overall_score) }}
    {{ score_card("Faithfulness", report.avg_faithfulness) }}
    {{ score_card("Answer Relevancy", report.avg_answer_relevancy) }}
    {{ score_card("Context Precision", report.avg_context_precision) }}
    {{ score_card("Context Recall", report.avg_context_recall) }}
    {% if report.avg_answer_correctness is not none %}
    {{ score_card("Correctness", report.avg_answer_correctness) }}
    {% endif %}
    {{ latency_card(report.avg_latency_ms) }}
  </div>

  <!-- 总览信息 -->
  <div class="overview">
    <h2>📋 评测总览</h2>
    <table>
      <tr><td>总问题数</td><td>{{ report.total_questions }}</td></tr>
      <tr><td>成功评测</td><td>{{ report.successful_evals }}</td></tr>
      <tr><td>失败评测</td><td>{{ report.failed_evals }}</td></tr>
      <tr><td>开始时间</td><td>{{ report.started_at.strftime('%Y-%m-%d %H:%M:%S') }} UTC</td></tr>
      <tr><td>结束时间</td><td>{{ report.finished_at.strftime('%Y-%m-%d %H:%M:%S') }} UTC</td></tr>
      <tr><td>用时</td><td>{{ duration_str }}</td></tr>
    </table>
  </div>

  <!-- 明细表 -->
  <div class="detail">
    <h2>📊 逐题明细</h2>
    <table class="detail-table">
      <thead>
        <tr>
          <th>#</th>
          <th>问题</th>
          <th>Faithfulness</th>
          <th>Relevancy</th>
          <th>Precision</th>
          <th>Recall</th>
          <th>Latency</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        {% for r in report.results %}
        <tr>
          <td>{{ loop.index }}</td>
          <td class="truncate" title="{{ r.question }}">{{ r.question }}</td>
          <td>{{ fmt_score(r.faithfulness) }}</td>
          <td>{{ fmt_score(r.answer_relevancy) }}</td>
          <td>{{ fmt_score(r.context_precision) }}</td>
          <td>{{ fmt_score(r.context_recall) }}</td>
          <td>{% if r.latency_ms %}{{ "%.0f"|format(r.latency_ms) }}ms{% else %}—{% endif %}</td>
          <td>
            {% if r.error %}
            <span class="badge badge-err" title="{{ r.error }}">失败</span>
            {% else %}
            <span class="badge badge-ok">通过</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

</div>
</body>
</html>
"""

_MACROS = """\
{% macro score_class(v) %}{% if v is none %}score-na{% elif v >= 0.75 %}score-high{% elif v >= 0.5 %}score-mid{% else %}score-low{% endif %}{% endmacro %}
{% macro score_card(label, v) %}
<div class="metric-card">
  <div class="label">{{ label }}</div>
  <div class="value {{ score_class(v) }}">{% if v is none %}N/A{% else %}{{ "%.2f"|format(v) }}{% endif %}</div>
</div>
{% endmacro %}
{% macro latency_card(v) %}
<div class="metric-card">
  <div class="label">Avg Latency</div>
  <div class="value" style="font-size:1.4rem;color:var(--blue)">{% if v is none %}N/A{% else %}{{ "%.0f"|format(v) }}ms{% endif %}</div>
</div>
{% endmacro %}
{% macro fmt_score(v) %}{% if v is none %}—{% else %}{{ "%.3f"|format(v) }}{% endif %}{% endmacro %}
"""


def render_html_report(report: EvalReport) -> str:
    """使用 Jinja2 将 EvalReport 渲染为 HTML 字符串。"""
    from jinja2 import Environment, BaseLoader

    duration_secs = (report.finished_at - report.started_at).total_seconds()
    duration_str = f"{int(duration_secs // 60)}m {int(duration_secs % 60)}s"

    env = Environment(loader=BaseLoader(), autoescape=True)  # type: ignore[call-arg]
    template_str = _MACROS + _TEMPLATE
    tmpl = env.from_string(template_str)

    return tmpl.render(
        report=report,
        duration_str=duration_str,
    )
