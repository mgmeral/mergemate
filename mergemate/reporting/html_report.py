"""
Standalone HTML report generator for MergeMate validation runs.

Produces a single self-contained HTML file (no external deps).
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timezone

from mergemate.reporting.surefire import SurefireResults


# ---------------------------------------------------------------------------
# CSS (embedded)
# ---------------------------------------------------------------------------

_CSS = """
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --card: #21262d;
  --border: #30363d;
  --text: #c9d1d9;
  --text-muted: #8b949e;
  --accent: #58a6ff;
  --success: #3fb950;
  --warning: #d29922;
  --danger: #f85149;
  --critical: #ff7b72;
  --low-bg: #0d4429;
  --medium-bg: #4d2d00;
  --high-bg: #5c1a1a;
  --critical-bg: #3d0000;
  --changed-bg: #0d2e14;
  --dependent-bg: #3d2c00;
  --dependency-bg: #1c2128;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  font-size: 14px;
  background: var(--bg);
  color: var(--text);
  padding: 1.5rem;
  line-height: 1.5;
}
h1 { font-size: 1.5rem; font-weight: 600; color: var(--accent); margin-bottom: 0.25rem; }
h2 { font-size: 1rem; font-weight: 600; color: var(--text); margin-bottom: 0.75rem; }
.subtitle { color: var(--text-muted); font-size: 0.85rem; margin-bottom: 1.5rem; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}
.card.full { grid-column: 1 / -1; }
.kv { display: grid; grid-template-columns: 180px 1fr; gap: 0.25rem 0.75rem; margin-bottom: 0.25rem; }
.kv-key { color: var(--text-muted); font-size: 0.85rem; }
.kv-val { font-family: monospace; font-size: 0.85rem; word-break: break-all; }
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.badge-success { background: #1a3c2a; color: var(--success); border: 1px solid var(--success); }
.badge-failure { background: #3c1a1a; color: var(--danger); border: 1px solid var(--danger); }
.badge-timeout { background: #3c2a00; color: var(--warning); border: 1px solid var(--warning); }
.badge-error   { background: #2a1a2a; color: #d2a8ff; border: 1px solid #d2a8ff; }
.badge-skipped { background: #1c2128; color: var(--text-muted); border: 1px solid var(--border); }
.badge-low      { background: var(--low-bg); color: var(--success); border: 1px solid var(--success); }
.badge-medium   { background: var(--medium-bg); color: var(--warning); border: 1px solid var(--warning); }
.badge-high     { background: var(--high-bg); color: var(--danger); border: 1px solid var(--danger); }
.badge-critical { background: var(--critical-bg); color: var(--critical); border: 1px solid var(--critical); }
.badge-changed    { background: var(--changed-bg); color: var(--success); border: 1px solid var(--success); }
.badge-dependent  { background: var(--dependent-bg); color: var(--warning); border: 1px solid var(--warning); }
.badge-dependency { background: var(--dependency-bg); color: var(--text-muted); border: 1px solid var(--border); }
.badge-passed  { background: var(--low-bg); color: var(--success); }
.badge-failed  { background: var(--high-bg); color: var(--danger); }
.badge-errored { background: #2a1a2a; color: #d2a8ff; }
.badge-skpd    { background: var(--dependency-bg); color: var(--text-muted); }
.badge-high-conf   { background: #0d2e14; color: var(--success); border: 1px solid var(--success); }
.badge-medium-conf { background: var(--medium-bg); color: var(--warning); border: 1px solid var(--warning); }
.badge-low-conf    { background: var(--dependency-bg); color: var(--text-muted); border: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
thead tr { border-bottom: 2px solid var(--border); }
tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:hover { background: rgba(255,255,255,0.03); }
th { color: var(--text-muted); font-weight: 500; padding: 0.5rem 0.75rem; text-align: left; }
td { padding: 0.5rem 0.75rem; font-family: monospace; }
.mono { font-family: monospace; font-size: 0.82rem; }
.cmd-block {
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-family: monospace;
  font-size: 0.82rem;
  color: var(--accent);
  white-space: pre-wrap;
  word-break: break-all;
}
.stat-num { font-size: 1.5rem; font-weight: 700; line-height: 1; }
.stat-label { font-size: 0.78rem; color: var(--text-muted); margin-top: 0.25rem; }
.risk-reasons { margin-top: 0.5rem; padding-left: 1rem; }
.risk-reasons li { color: var(--text-muted); font-size: 0.85rem; margin-bottom: 0.2rem; }
.score-bar { display: flex; align-items: center; gap: 0.5rem; }
.score-fill {
  height: 6px;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--success), var(--accent));
  transition: width 0.3s;
}
.reasons { color: var(--text-muted); font-size: 0.78rem; font-family: sans-serif; }
.empty { color: var(--text-muted); font-style: italic; font-size: 0.85rem; padding: 0.5rem 0; }
footer { margin-top: 2rem; color: var(--text-muted); font-size: 0.78rem; border-top: 1px solid var(--border); padding-top: 0.75rem; }
"""

# ---------------------------------------------------------------------------
# HTML builder helpers
# ---------------------------------------------------------------------------

def _h(s: object) -> str:
    return html.escape(str(s)) if s is not None else ""


def _badge(text: str, cls: str) -> str:
    return f'<span class="badge badge-{cls}">{_h(text)}</span>'


def _risk_badge(level: str) -> str:
    return _badge(level, level.lower())


def _status_badge(status: str) -> str:
    return _badge(status.upper(), status.lower())


def _conf_badge(conf: str) -> str:
    return _badge(conf, conf.lower() + "-conf")


def _module_badge(label: str) -> str:
    return _badge(label, label.lower())


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _header_section(report: dict) -> str:
    run_id = report.get("run_id", "unknown")
    execution = report.get("execution", {})
    status = execution.get("status", report.get("status", ""))
    duration = execution.get("duration_seconds", 0)
    started = report.get("started_at", "")

    status_html = _status_badge(status) if status else ""
    dur_str = f"{int(duration)}s" if duration else ""

    return f"""
<h1>MergeMate Validation Report</h1>
<div class="subtitle">
  Run ID: <span class="mono">{_h(run_id)}</span>
  &nbsp;&nbsp;{status_html}
  {"&nbsp;&nbsp;" + _h(dur_str) if dur_str else ""}
  {"&nbsp;&nbsp;Started: " + _h(started[:19].replace("T", " ")) + " UTC" if started else ""}
</div>"""


def _git_section(report: dict) -> str:
    source = report.get("source", "")
    target = report.get("target", "")
    merge_base = report.get("merge_base", "")
    changed_files = report.get("changed_files", [])

    rows = ""
    for cf in changed_files[:20]:
        status = cf.get("status", "modified")
        status_char = {"added": "A", "modified": "M", "deleted": "D", "renamed": "R", "copied": "C"}.get(status, "?")
        color = {"added": "success", "modified": "accent", "deleted": "danger", "renamed": "warning"}.get(status, "text-muted")
        rows += f'<tr><td style="color:var(--{color});width:20px">{status_char}</td><td>{_h(cf.get("path",""))}</td></tr>'

    if len(changed_files) > 20:
        rows += f'<tr><td colspan="2" class="empty">… and {len(changed_files)-20} more files</td></tr>'

    files_table = f'<table><tbody>{rows}</tbody></table>' if rows else '<p class="empty">(no changed files)</p>'

    return f"""
<div class="grid">
  <div class="card">
    <h2>Git</h2>
    <div class="kv"><span class="kv-key">Source</span><span class="kv-val">{_h(source)}</span></div>
    <div class="kv"><span class="kv-key">Target</span><span class="kv-val">{_h(target)}</span></div>
    <div class="kv"><span class="kv-key">Merge base</span><span class="kv-val">{_h(merge_base[:12] if merge_base else "")}</span></div>
    <div class="kv"><span class="kv-key">Changed files</span><span class="kv-val">{len(changed_files)}</span></div>
  </div>
  <div class="card">
    <h2>Changed Files</h2>
    {files_table}
  </div>
</div>"""


def _jdk_section(report: dict) -> str:
    jdk = report.get("jdk")
    if not jdk:
        return ""
    compatible = jdk.get("compatible", True)
    compat_badge = _badge("Compatible", "success") if compatible else _badge("Incompatible", "failure")
    return f"""
<div class="card">
  <h2>JDK</h2>
  <div class="kv"><span class="kv-key">Required</span><span class="kv-val">{_h(jdk.get("required_version",""))}</span></div>
  <div class="kv"><span class="kv-key">Runtime</span><span class="kv-val">{_h(jdk.get("runtime_java_version",""))}</span></div>
  <div class="kv"><span class="kv-key">Compatible</span><span class="kv-val">{compat_badge}</span></div>
  <div class="kv"><span class="kv-key">Detected from</span><span class="kv-val">{_h(jdk.get("detected_from",""))}</span></div>
</div>"""


def _impact_section(report: dict) -> str:
    impact = report.get("impact", {})
    if not impact:
        return ""

    strategy = impact.get("strategy", "")
    strategy_reason = impact.get("strategy_reason", "")
    changed_modules = impact.get("changed_modules", [])
    affected_modules = impact.get("affected_modules", [])
    risk_level = impact.get("risk_level", "LOW")
    risk_reasons = impact.get("risk_reasons", [])
    full_build = impact.get("full_build_recommended", False)

    strategy_badge = _badge("FULL BUILD", "high") if strategy == "full" else _badge("INCREMENTAL", "low")

    changed_html = "".join(f'<div class="mono" style="margin:0.2rem 0">{_h(m)}</div>' for m in changed_modules) or '<span class="empty">(none)</span>'

    module_rows = ""
    for m in affected_modules:
        module_rows += f"""<tr>
          <td class="mono">{_h(m.get("artifact_id",""))}</td>
          <td>{_module_badge(m.get("label",""))}</td>
          <td class="reasons">{_h(m.get("reason",""))}</td>
        </tr>"""

    modules_table = f"""<table>
      <thead><tr><th>Module</th><th>Role</th><th>Reason</th></tr></thead>
      <tbody>{module_rows}</tbody>
    </table>""" if module_rows else '<p class="empty">(no affected modules)</p>'

    risk_html = ""
    if risk_reasons:
        items = "".join(f"<li>{_h(r)}</li>" for r in risk_reasons)
        risk_html = f'<ul class="risk-reasons">{items}</ul>'

    full_build_str = "YES" if full_build else "NO"

    return f"""
<div class="card">
  <h2>Impact Analysis</h2>
  <div style="display:flex;gap:1rem;align-items:flex-start;flex-wrap:wrap;margin-bottom:0.75rem">
    <div>
      <div class="stat-num">{len(affected_modules)}</div>
      <div class="stat-label">Affected modules</div>
    </div>
    <div>
      <div class="stat-num">{len(changed_modules)}</div>
      <div class="stat-label">Changed modules</div>
    </div>
    <div style="margin-left:auto">
      {strategy_badge}
      <div class="stat-label" style="margin-top:0.4rem">{_h(strategy_reason)}</div>
    </div>
  </div>
  <div style="margin-bottom:0.75rem">
    <div style="margin-bottom:0.25rem;color:var(--text-muted);font-size:0.85rem">Changed modules</div>
    {changed_html}
  </div>
  <h2 style="margin-top:0.75rem">Affected Modules</h2>
  {modules_table}
</div>
<div class="card">
  <h2>Risk Assessment</h2>
  <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.5rem">
    {_risk_badge(risk_level)}
    <span class="kv-val">Full build recommended: <strong>{full_build_str}</strong></span>
  </div>
  {risk_html}
</div>"""


def _tests_section(report: dict) -> str:
    test_candidates = report.get("test_candidates", [])
    if not test_candidates:
        return ""

    rows = ""
    for c in test_candidates:
        score = c.get("score", 0.0)
        conf = c.get("confidence", "LOW")
        bar_width = int(score * 100)
        reasons_html = "; ".join(c.get("reasons", []))
        it_badge = ' <span class="badge badge-skpd">IT</span>' if c.get("is_integration_test") else ""
        rows += f"""<tr>
          <td class="mono">{_h(c.get("class_name",""))}{it_badge}</td>
          <td class="mono" style="color:var(--text-muted);font-size:0.78rem">{_h(c.get("module_artifact_id",""))}</td>
          <td>{_conf_badge(conf)}</td>
          <td>
            <div class="score-bar">
              <div class="score-fill" style="width:{bar_width}px;max-width:80px"></div>
              <span style="font-size:0.78rem;color:var(--text-muted)">{score:.2f}</span>
            </div>
          </td>
          <td class="reasons">{_h(reasons_html)}</td>
        </tr>"""

    return f"""
<div class="card">
  <h2>Selected Tests ({len(test_candidates)})</h2>
  <table>
    <thead><tr><th>Class</th><th>Module</th><th>Confidence</th><th>Score</th><th>Reasons</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def _command_section(report: dict) -> str:
    maven_command = report.get("maven_command")
    if not maven_command:
        return ""
    display = maven_command.get("display_command", "")
    goal = maven_command.get("goal", "")
    return f"""
<div class="card">
  <h2>Maven Command {_badge(goal, "dependency") if goal else ""}</h2>
  <div class="cmd-block">{_h(display)}</div>
</div>"""


def _surefire_section(surefire: SurefireResults | None) -> str:
    if surefire is None or not surefire.suites:
        return ""

    total_cls = "success" if surefire.all_passed else "failure"
    summary_badge = _badge("ALL PASSED", "success") if surefire.all_passed else _badge("FAILURES DETECTED", "failure")

    rows = ""
    for suite in sorted(surefire.suites, key=lambda s: s.name):
        status_cls = "failure" if (suite.failures + suite.errors) > 0 else "passed"
        rows += f"""<tr>
          <td class="mono" style="font-size:0.78rem">{_h(suite.name)}</td>
          <td style="color:var(--success)">{suite.passed}</td>
          <td style="color:{"var(--danger)" if suite.failures else "var(--text-muted)"}">{"" if not suite.failures else suite.failures}</td>
          <td style="color:{"var(--critical)" if suite.errors else "var(--text-muted)"}">{"" if not suite.errors else suite.errors}</td>
          <td style="color:var(--text-muted)">{suite.skipped or ""}</td>
          <td style="color:var(--text-muted)">{suite.time_seconds:.2f}s</td>
        </tr>"""

    return f"""
<div class="card">
  <h2>Test Results {summary_badge}</h2>
  <div style="display:flex;gap:1.5rem;margin-bottom:1rem">
    <div><div class="stat-num" style="color:var(--text)">{surefire.total_tests}</div><div class="stat-label">Total</div></div>
    <div><div class="stat-num" style="color:var(--success)">{surefire.total_passed}</div><div class="stat-label">Passed</div></div>
    <div><div class="stat-num" style="color:{"var(--danger)" if surefire.total_failures else "var(--text-muted)"}">{surefire.total_failures}</div><div class="stat-label">Failed</div></div>
    <div><div class="stat-num" style="color:var(--text-muted)">{surefire.total_skipped}</div><div class="stat-label">Skipped</div></div>
    <div><div class="stat-num" style="color:var(--text-muted)">{surefire.total_time:.1f}s</div><div class="stat-label">Total time</div></div>
  </div>
  <table>
    <thead><tr><th>Test Suite</th><th>Passed</th><th>Failed</th><th>Errors</th><th>Skipped</th><th>Time</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def build_html_report(
    report: dict,
    surefire: SurefireResults | None = None,
) -> str:
    """
    Build a standalone HTML report string.

    Args:
        report: dict as produced by file_report._build_report_dict()
        surefire: optional SurefireResults from collect_surefire_results()
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    body_parts = [
        _header_section(report),
        _git_section(report),
        _jdk_section(report),
        _impact_section(report),
        _tests_section(report),
        _command_section(report),
        _surefire_section(surefire),
        f'<footer>Generated by MergeMate &mdash; {generated_at}</footer>',
    ]

    body = "\n".join(p for p in body_parts if p)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MergeMate Report</title>
  <style>{_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""


def write_html_report(run_dir: str, report: dict, surefire: SurefireResults | None = None) -> str:
    """Write report.html to run_dir. Returns the path."""
    html_content = build_html_report(report, surefire)
    path = os.path.join(run_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return path
