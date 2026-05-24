"""
Generates an HTML coaching report and opens it in the default browser.

Design: typographic, editor's-margin-notes style. Single accent colour
(#C96442) used only for "Try this" text. Two-column layout — suggestions
on the left, annotated transcript on the right.
"""

import html
import json
import webbrowser
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path.home() / ".fluent" / "reports"

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fluent — {date}</title>
<style>
  :root {{
    --ink:        #1a1a1a;
    --ink-2:      #2a2a2a;
    --gray-1:     #555555;
    --gray-2:     #8a8a8a;
    --gray-3:     #b5b5b5;
    --gray-4:     #d8d8d6;
    --rule:       #e8e8e6;
    --accent:     #C96442;
    --bg:         #ffffff;
  }}

  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                 "Helvetica Neue", system-ui, sans-serif;
    background: var(--bg);
    color: var(--ink);
    -webkit-font-smoothing: antialiased;
    line-height: 1.55;
    text-rendering: optimizeLegibility;
  }}

  .page {{
    max-width: 1040px;
    margin: 0 auto;
    padding: 96px 48px 160px;
  }}

  /* ── Masthead ── */
  .masthead {{
    max-width: 600px;
    margin-bottom: 72px;
  }}
  .wordmark {{
    font-size: 13px;
    color: var(--gray-3);
    letter-spacing: 0.02em;
    font-weight: 500;
  }}
  .session-meta {{
    font-size: 13px;
    color: var(--gray-2);
    margin-top: 4px;
    font-variant-numeric: tabular-nums;
  }}
  .session-summary {{
    font-size: 18px;
    color: var(--ink-2);
    margin-top: 32px;
    line-height: 1.45;
    letter-spacing: -0.005em;
  }}

  /* ── No-issues state ── */
  .no-issues {{
    font-size: 16px;
    color: var(--gray-2);
    margin-top: 48px;
  }}

  /* ── Two-column layout ── */
  .layout {{
    display: grid;
    grid-template-columns: 300px minmax(0, 600px);
    column-gap: 72px;
  }}

  /* ── Transcript ── */
  .transcript-label {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--gray-3);
    font-weight: 500;
    margin-bottom: 24px;
  }}
  .transcript {{
    font-size: 16px;
    color: var(--ink-2);
    line-height: 1.75;
  }}
  .transcript p {{ margin: 0 0 1.1em; }}

  mark.flag {{
    background: transparent;
    color: inherit;
    border-bottom: 1px solid var(--gray-4);
    padding-bottom: 1px;
    transition: border-color 140ms ease, color 140ms ease;
    cursor: default;
  }}
  mark.flag:hover,
  mark.flag.is-active {{
    border-bottom-color: var(--accent);
  }}
  mark.flag .num {{
    font-size: 10px;
    color: var(--gray-2);
    vertical-align: super;
    line-height: 0;
    margin-left: 3px;
    font-weight: 500;
    letter-spacing: 0.02em;
    transition: color 140ms ease;
  }}
  mark.flag:hover .num,
  mark.flag.is-active .num {{
    color: var(--accent);
  }}

  /* ── Margin notes ── */
  .margin {{ position: relative; }}

  .note {{
    position: absolute;
    left: 0;
    right: 0;
    padding-top: 2px;
  }}

  .note-head {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 10px;
  }}
  .note-num {{
    font-size: 12px;
    color: var(--gray-3);
    font-weight: 500;
    letter-spacing: 0.02em;
    min-width: 16px;
    font-variant-numeric: tabular-nums;
  }}
  .note-category {{
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--gray-2);
    font-weight: 500;
  }}
  .note-try {{
    font-size: 17px;
    line-height: 1.5;
    color: var(--accent);
    font-weight: 500;
    margin: 0 0 8px;
    padding-left: 26px;
    letter-spacing: -0.005em;
  }}
  .note-explain {{
    font-size: 14px;
    line-height: 1.55;
    color: var(--gray-2);
    margin: 0;
    padding-left: 26px;
  }}

  /* ── Narrow: stack ── */
  @media (max-width: 900px) {{
    .page {{ padding: 64px 24px 120px; }}
    .layout {{ grid-template-columns: minmax(0, 1fr); }}
    .layout > section {{ order: 1; }}
    .layout > .margin {{ order: 2; margin-top: 56px; padding-top: 32px; border-top: 1px solid var(--rule); }}
    .note {{ position: static !important; margin-bottom: 32px; }}
    .margin::before {{
      content: "Notes";
      display: block;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--gray-3);
      font-weight: 500;
      margin-bottom: 24px;
    }}
  }}
</style>
</head>
<body>
<main class="page">

  <header class="masthead">
    <div class="wordmark">Fluent</div>
    <div class="session-meta">{date} &middot; {duration}</div>
    <p class="session-summary">{summary}</p>
  </header>

  {body}

</main>
<script>
(function () {{
  const margin = document.getElementById('margin');
  const flags  = Array.from(document.querySelectorAll('mark.flag'));
  const notes  = Array.from(document.querySelectorAll('.note'));

  const isStacked = () => window.matchMedia('(max-width: 900px)').matches;

  function align() {{
    if (isStacked()) {{
      notes.forEach(n => {{ n.style.top = ''; }});
      if (margin) margin.style.height = '';
      return;
    }}
    if (!margin) return;
    const marginTop = margin.getBoundingClientRect().top + window.scrollY;
    const GAP = 24;
    let lastBottom = 0;
    flags.forEach(flag => {{
      const id   = flag.dataset.issue;
      const note = document.querySelector('.note[data-issue="' + id + '"]');
      if (!note) return;
      const flagTop = flag.getBoundingClientRect().top + window.scrollY - marginTop;
      const top = Math.max(flagTop, lastBottom + GAP);
      note.style.top = top + 'px';
      lastBottom = top + note.offsetHeight;
    }});
    margin.style.height = (lastBottom + 16) + 'px';
  }}

  function setActive(id, on) {{
    const flag = document.querySelector('mark.flag[data-issue="' + id + '"]');
    const note = document.querySelector('.note[data-issue="' + id + '"]');
    if (flag) flag.classList.toggle('is-active', on);
    if (note) note.classList.toggle('is-active', on);
  }}

  flags.forEach(flag => {{
    flag.addEventListener('mouseenter', () => setActive(flag.dataset.issue, true));
    flag.addEventListener('mouseleave', () => setActive(flag.dataset.issue, false));
  }});

  window.addEventListener('load', align);
  window.addEventListener('resize', align);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(align);
  align();
}})();
</script>
</body>
</html>
"""

NOTE_TEMPLATE = """\
      <article class="note" data-issue="{n}">
        <div class="note-head">
          <span class="note-num">{n}</span>
          <span class="note-category">{category}</span>
        </div>
        <p class="note-try">{improved}</p>
        <p class="note-explain">{explanation}</p>
      </article>"""

TRANSCRIPT_MARK = (
    '<mark class="flag" data-issue="{n}">{original}'
    '<span class="num">{n}</span></mark>'
)


def _duration_str(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _esc(text: str) -> str:
    return html.escape(str(text))


def _build_transcript_html(issues: list[dict], transcript: str) -> str:
    """
    Mark up the transcript text, wrapping each 'original' phrase with a
    numbered flag. Falls back gracefully if the phrase isn't found verbatim.
    """
    marked = transcript
    for i, issue in enumerate(issues, 1):
        original = issue.get("original", "")
        if original and original in marked:
            replacement = TRANSCRIPT_MARK.format(
                n=i,
                original=_esc(original),
            )
            marked = marked.replace(original, replacement, 1)

    # Wrap in paragraphs (split on double newlines, or treat as one block)
    paragraphs = [p.strip() for p in marked.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [marked]
    return "\n".join(f"        <p>{p}</p>" for p in paragraphs)


def generate_report(
    coaching_data: dict | list,
    duration_seconds: float,
    transcript: str = "",
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str  = now.strftime("%B %d, %Y · %H:%M")
    slug      = now.strftime("%Y-%m-%d_%H-%M")
    dur_str   = _duration_str(duration_seconds)
    name      = now.strftime("%b %d, %Y · %H:%M")

    issues = coaching_data if isinstance(coaching_data, list) else coaching_data.get("issues", [])

    n_issues = len(issues)
    dur_label = _duration_str(duration_seconds)
    if n_issues == 0:
        summary = "No suggestions — your English sounded natural and fluent."
    elif n_issues == 1:
        summary = f"1 suggestion across {dur_label} of your speech."
    else:
        summary = f"{n_issues} suggestions across {dur_label} of your speech."

    if not issues:
        body = '<p class="no-issues">Nothing to flag — great session.</p>'
    else:
        # Build margin notes
        notes_html = "\n".join(
            NOTE_TEMPLATE.format(
                n=i,
                category=_esc(issue.get("category", "Phrasing")),
                improved=_esc(issue.get("improved", issue.get("better_phrasing", ""))),
                explanation=_esc(issue.get("explanation", "")),
            )
            for i, issue in enumerate(issues, 1)
        )

        # Build transcript column
        if transcript:
            transcript_html = _build_transcript_html(issues, transcript)
        else:
            # No transcript: show original phrases as plain text with flags
            frags = []
            for i, issue in enumerate(issues, 1):
                original = _esc(issue.get("original", issue.get("you_said", "")))
                frags.append(
                    f'        <p><mark class="flag" data-issue="{i}">'
                    f'{original}<span class="num">{i}</span></mark></p>'
                )
            transcript_html = "\n".join(frags)

        body = f"""\
  <div class="layout">
    <aside class="margin" id="margin">
{notes_html}
    </aside>
    <section>
      <div class="transcript-label">Transcript</div>
      <div class="transcript">
{transcript_html}
      </div>
    </section>
  </div>"""

    html_out = HTML_TEMPLATE.format(
        date=date_str,
        duration=dur_str,
        summary=_esc(summary),
        body=body,
    )

    out_path = REPORTS_DIR / f"{slug}.html"
    out_path.write_text(html_out, encoding="utf-8")

    # Write latest.json for Swift to inject on app launch
    latest_payload = {
        "issues": issues,
        "transcript": transcript,
        "duration": duration_seconds,
        "date": date_str,
        "slug": slug,
        "name": name,
    }
    (REPORTS_DIR / "latest.json").write_text(
        json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _update_sessions_manifest(slug, duration_seconds, issues, latest_payload, name=name)

    return out_path


def rebuild_sessions_manifest() -> None:
    """Rebuild sessions.json by scanning all per-session .json files in REPORTS_DIR."""
    import re as _re
    sessions = []
    for p in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        if p.stem in ("latest", "sessions"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        slug = p.stem
        name = data.get("name") or data.get("date") or slug
        sessions.append({
            "slug": slug,
            "name": name,
            "duration": data.get("duration", 0),
            "issue_count": len(data.get("issues", [])),
            "data": data,
        })
    (REPORTS_DIR / "sessions.json").write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _update_sessions_manifest(slug: str, duration_seconds: float, issues: list[dict], coaching_data, name: str = "") -> None:
    """Append/update a sessions.json manifest used by the WebView sessions list."""
    manifest_path = REPORTS_DIR / "sessions.json"
    try:
        sessions = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    except (json.JSONDecodeError, OSError):
        sessions = []

    entry = {
        "slug": slug,
        "name": name or slug,
        "duration": duration_seconds,
        "issue_count": len(issues),
        "data": coaching_data if isinstance(coaching_data, dict) else {"issues": issues},
    }

    sessions = [s for s in sessions if s.get("slug") != slug]
    sessions.insert(0, entry)

    manifest_path.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")


def open_report(path: Path):
    webbrowser.open(f"file://{path.resolve()}")
