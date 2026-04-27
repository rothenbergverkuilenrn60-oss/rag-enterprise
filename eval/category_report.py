# =============================================================================
# eval/category_report.py
# 按领域/子类分层统计评测结果，生成分类明细报告
# 在 ragas_runner.py 生成 EvalReport 后调用
# =============================================================================
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from eval.models import EvalReport, SingleEvalResult


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 分类聚合
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_METRIC_KEYS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_correctness",
)


def _safe_mean(values: list[float | None]) -> float | None:
    valid = [v for v in values if v is not None]
    return round(sum(valid) / len(valid), 4) if valid else None


def _group_results(
    results: list[SingleEvalResult],
    qa_meta: dict[int, dict[str, str]],   # idx → {domain, category, sub_category}
) -> dict[str, dict[str, Any]]:
    """
    按 domain（大类）和 category（细类）分组，计算各组均值。
    返回：{domain: {avg_xxx: float, sub_categories: {cat: {...}}}}
    """
    # 按 domain 分组
    domain_buckets: dict[str, list[SingleEvalResult]] = defaultdict(list)
    cat_buckets: dict[str, list[SingleEvalResult]] = defaultdict(list)

    for idx, r in enumerate(results):
        meta = qa_meta.get(idx, {})
        domain = meta.get("domain", "未知")
        category = meta.get("category", "未知")
        domain_buckets[domain].append(r)
        cat_buckets[category].append(r)

    report: dict[str, Any] = {}
    for domain, items in sorted(domain_buckets.items()):
        domain_stats: dict[str, Any] = {
            "total": len(items),
            "success": sum(1 for r in items if r.passed),
            "failed": sum(1 for r in items if not r.passed),
        }
        for key in _METRIC_KEYS:
            vals = [getattr(r, key) for r in items]
            domain_stats[f"avg_{key}"] = _safe_mean(vals)

        # 子类明细
        sub_cats: dict[str, Any] = {}
        for cat, cat_items in sorted(cat_buckets.items()):
            if not cat.startswith(domain):
                continue
            cat_stats: dict[str, Any] = {"total": len(cat_items)}
            for key in _METRIC_KEYS:
                vals = [getattr(r, key) for r in cat_items]
                cat_stats[f"avg_{key}"] = _safe_mean(vals)
            sub_cats[cat] = cat_stats

        domain_stats["sub_categories"] = sub_cats
        report[domain] = domain_stats

    return report


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 加载原始 QA metadata（获取 domain / category 信息）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_qa_meta(dataset_path: Path) -> dict[int, dict[str, str]]:
    """读取 eval dataset，返回 idx→metadata 的映射。"""
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    meta: dict[int, dict[str, str]] = {}
    for idx, pair in enumerate(raw.get("pairs", [])):
        m = pair.get("metadata", {})
        meta[idx] = {
            "domain": m.get("domain", ""),
            "category": m.get("category", ""),
            "sub_category": m.get("sub_category", ""),
        }
    return meta


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 生成分类报告 HTML
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_DOMAIN_COLORS = {
    "人事管理": "#3b82f6",
    "考勤管理": "#10b981",
    "财务管理": "#f59e0b",
    "资产管理": "#8b5cf6",
}

_METRIC_LABELS = {
    "avg_faithfulness": "忠实度",
    "avg_answer_relevancy": "答案相关性",
    "avg_context_precision": "上下文精确度",
    "avg_context_recall": "上下文召回率",
}


def _score_bar(score: float | None, width: int = 120) -> str:
    if score is None:
        return '<span style="color:#9ca3af">N/A</span>'
    pct = int(score * 100)
    color = "#16a34a" if score >= 0.75 else "#d97706" if score >= 0.5 else "#dc2626"
    bar_w = int(score * width)
    return (
        f'<div style="display:flex;align-items:center;gap:8px">'
        f'<div style="width:{width}px;background:#e5e7eb;border-radius:4px;height:10px">'
        f'<div style="width:{bar_w}px;background:{color};height:10px;border-radius:4px"></div></div>'
        f'<span style="font-weight:600;color:{color}">{score:.3f}</span></div>'
    )


def render_category_html(
    report: EvalReport,
    grouped: dict[str, Any],
) -> str:
    rows = ""
    for domain, dstats in grouped.items():
        color = _DOMAIN_COLORS.get(domain, "#6b7280")
        rows += f"""
        <tr style="background:#f8fafc">
          <td colspan="6" style="padding:12px 16px;font-weight:700;color:{color};font-size:1rem;border-left:4px solid {color}">
            📂 {domain}
            <span style="font-weight:400;color:#6b7280;font-size:.85rem;margin-left:8px">
              共 {dstats['total']} 题 / 成功 {dstats['success']} / 失败 {dstats['failed']}
            </span>
          </td>
        </tr>"""
        for metric_key, label in _METRIC_LABELS.items():
            val = dstats.get(metric_key)
            rows += f"""
        <tr>
          <td style="padding:8px 16px 8px 32px;color:#374151">{label}</td>
          <td colspan="5">{_score_bar(val)}</td>
        </tr>"""

        # 子类展开
        for cat, cstats in dstats.get("sub_categories", {}).items():
            sub = cat.split("-")[1] if "-" in cat else cat
            fth = cstats.get("avg_faithfulness")
            rel = cstats.get("avg_answer_relevancy")
            prec = cstats.get("avg_context_precision")
            rec = cstats.get("avg_context_recall")
            rows += f"""
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:6px 16px 6px 48px;color:#6b7280;font-size:.85rem">└ {sub}（{cstats['total']}题）</td>
          <td style="font-size:.8rem">{_score_bar(fth, 80)}</td>
          <td style="font-size:.8rem">{_score_bar(rel, 80)}</td>
          <td style="font-size:.8rem">{_score_bar(prec, 80)}</td>
          <td style="font-size:.8rem">{_score_bar(rec, 80)}</td>
          <td></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>分类评测报告 — {report.run_id}</title>
<style>
  body{{font-family:system-ui,sans-serif;background:#f8fafc;color:#1e293b;margin:0}}
  header{{background:#1e293b;color:white;padding:20px 40px}}
  header h1{{font-size:1.3rem}}
  header p{{font-size:.85rem;opacity:.75;margin-top:4px}}
  .wrap{{max-width:1100px;margin:32px auto;padding:0 32px}}
  table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;
         box-shadow:0 1px 4px rgba(0,0,0,.08);overflow:hidden}}
  th{{background:#1e293b;color:white;padding:10px 16px;text-align:left;font-size:.85rem}}
  td{{padding:6px 16px;border-bottom:1px solid #f1f5f9;font-size:.875rem}}
</style>
</head>
<body>
<header>
  <h1>📊 分类评测报告</h1>
  <p>Run: {report.run_id} &nbsp;|&nbsp; 数据集: {report.dataset_name}
     &nbsp;|&nbsp; Judge: {report.judge_model}
     &nbsp;|&nbsp; Overall: {report.overall_score if report.overall_score else 'N/A'}</p>
</header>
<div class="wrap">
<table>
  <thead>
    <tr>
      <th>类别 / 指标</th>
      <th>忠实度</th>
      <th>答案相关性</th>
      <th>上下文精确度</th>
      <th>上下文召回率</th>
      <th></th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
</div>
</body>
</html>"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 对外接口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_category_report(
    report: EvalReport,
    dataset_path: Path,
    report_dir: Path,
    ts: str,
) -> Path:
    """
    根据 EvalReport 和原始数据集元数据，生成分类维度的 HTML 报告。
    返回写出的 HTML 文件路径。
    """
    qa_meta = load_qa_meta(dataset_path)
    grouped = _group_results(report.results, qa_meta)

    html = render_category_html(report, grouped)
    out_path = report_dir / f"eval_{report.run_id}_{ts}_by_category.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
