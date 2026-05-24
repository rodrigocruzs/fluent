/* report.js — receives data from Swift via window.loadReport(data) and window.loadSessions(sessions) */

(function () {
  'use strict';

  // ── Helpers ──────────────────────────────────────────────────────────────

  function esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function durationStr(seconds) {
    seconds = Math.round(seconds);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${h}h ${m}m ${s}s`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  }

  // ── Alignment ────────────────────────────────────────────────────────────

  function align() {
    const margin = document.getElementById('margin');
    const flags  = Array.from(document.querySelectorAll('mark.flag'));
    const notes  = Array.from(document.querySelectorAll('.note'));
    if (!margin || !flags.length) return;

    const stacked = window.matchMedia('(max-width: 900px)').matches;
    if (stacked) {
      notes.forEach(n => { n.style.top = ''; });
      margin.style.height = '';
      return;
    }

    const marginTop = margin.getBoundingClientRect().top + window.scrollY;
    const GAP = 24;
    let lastBottom = 0;

    flags.forEach(flag => {
      const id   = flag.dataset.issue;
      const note = document.querySelector(`.note[data-issue="${id}"]`);
      if (!note) return;
      const flagTop = flag.getBoundingClientRect().top + window.scrollY - marginTop;
      const top = Math.max(flagTop, lastBottom + GAP);
      note.style.top = top + 'px';
      lastBottom = top + note.offsetHeight;
    });

    margin.style.height = (lastBottom + 16) + 'px';
  }

  // ── Hover linking ─────────────────────────────────────────────────────────

  function wireHovers() {
    document.querySelectorAll('mark.flag').forEach(flag => {
      flag.addEventListener('mouseenter', () => setActive(flag.dataset.issue, true));
      flag.addEventListener('mouseleave', () => setActive(flag.dataset.issue, false));
    });
  }

  function setActive(id, on) {
    const flag = document.querySelector(`mark.flag[data-issue="${id}"]`);
    const note = document.querySelector(`.note[data-issue="${id}"]`);
    if (flag) flag.classList.toggle('is-active', on);
    if (note) note.classList.toggle('is-active', on);
  }

  // ── Build transcript with inline marks ───────────────────────────────────

  function buildTranscript(issues, transcriptText) {
    let text = transcriptText || '';

    issues.forEach((issue, idx) => {
      const n = idx + 1;
      const original = issue.original || '';
      if (!original || !text.includes(original)) return;
      const replacement =
        `<mark class="flag" data-issue="${n}">${esc(original)}` +
        `<span class="num">${n}</span></mark>`;
      text = text.replace(original, replacement);
    });

    const paras = text.split(/\n\n+/).filter(p => p.trim());
    if (!paras.length) paras.push(text);
    return paras.map(p => `<p>${p}</p>`).join('\n');
  }

  // ── Build notes column ────────────────────────────────────────────────────

  function buildNotes(issues) {
    return issues.map((issue, idx) => {
      const n = idx + 1;
      return `
      <article class="note" data-issue="${n}">
        <div class="note-head">
          <span class="note-num">${n}</span>
          <span class="note-category">${esc(issue.category || 'Phrasing')}</span>
        </div>
        <p class="note-try">${esc(issue.improved || issue.better_phrasing || '')}</p>
        <p class="note-explain">${esc(issue.explanation || '')}</p>
      </article>`.trim();
    }).join('\n');
  }

  // ── Sessions view ─────────────────────────────────────────────────────────

  function formatSessionName(slug) {
    const d = new Date(slug.replace('_', 'T').replace(/T(\d{2})-(\d{2})$/, 'T$1:$2'));
    if (isNaN(d)) return slug;
    return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  }

  function formatSessionDate(isoOrSlug) {
    const d = new Date(isoOrSlug.replace('_', 'T').replace(/T(\d{2})-(\d{2})$/, 'T$1:$2'));
    if (isNaN(d)) return isoOrSlug;
    const now   = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const day   = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff  = Math.round((today - day) / 86400000);
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Yesterday';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  window.loadSessions = function (sessions) {
    const sessionsPage = document.getElementById('sessions-page');
    const onboarding   = document.getElementById('onboarding');
    const page         = document.getElementById('page');
    const listEl       = document.getElementById('sessions-list');
    const summaryEl    = document.getElementById('sessions-summary');

    page.classList.remove('visible');
    page.innerHTML = '';
    if (onboarding) onboarding.style.display = 'none';

    if (!sessions || sessions.length === 0) {
      if (onboarding) { onboarding.style.display = ''; sessionsPage.style.display = 'none'; }
      return;
    }

    sessionsPage.style.display = '';

    const totalSec = sessions.reduce((s, r) => s + (r.duration || 0), 0);
    const totalMin = Math.round(totalSec / 60);
    const hrs = Math.floor(totalMin / 60);
    const mins = totalMin % 60;
    const timeLabel = hrs ? `${hrs}h ${mins}m` : `${totalMin} min`;
    const count = sessions.length;
    summaryEl.textContent =
      `${count} session${count !== 1 ? 's' : ''} — about ${timeLabel} of recorded speech.`;

    listEl.innerHTML = '';
    sessions.forEach(session => {
      const n = session.issue_count || 0;
      const countLabel = n === 0 ? 'No suggestions' : n === 1 ? '1 suggestion' : `${n} suggestions`;
      const dur = session.duration ? durationStr(session.duration) : '';
      const dateLabel = formatSessionDate(session.slug || session.date || '');
      const name = session.name || formatSessionName(session.slug || session.date || '');

      const btn = document.createElement('button');
      btn.className = 'session';
      btn.innerHTML = `
        <span class="session-name">${esc(name)}</span>
        <span class="session-date">${esc(dateLabel)}</span>
        <span class="session-duration">${esc(dur)}</span>
        <span class="session-count${n > 0 ? ' has-suggestions' : ''}">${esc(countLabel)}</span>
        <span class="session-chevron" aria-hidden="true">&rsaquo;</span>`;
      btn.addEventListener('click', () => {
        if (session.data) {
          window.loadReport(session.data);
        } else if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.openSession) {
          window.webkit.messageHandlers.openSession.postMessage(session.slug || session.date);
        }
      });
      listEl.appendChild(btn);
    });
  };

  // ── Main render ───────────────────────────────────────────────────────────

  window.loadReport = function (data) {
    const page         = document.getElementById('page');
    const onboarding   = document.getElementById('onboarding');
    const sessionsPage = document.getElementById('sessions-page');
    const issues       = Array.isArray(data.issues) ? data.issues : (Array.isArray(data) ? data : []);
    const transcript   = data.transcript || '';
    const duration     = data.duration   || 0;
    const date         = data.date       || new Date().toLocaleDateString('en-US', {
      month: 'long', day: 'numeric', year: 'numeric',
    });

    if (onboarding) onboarding.style.display = 'none';
    if (sessionsPage) sessionsPage.style.display = 'none';

    const n = issues.length;
    const summaryText = n === 0
      ? 'No suggestions — your English sounded natural and fluent.'
      : n === 1
        ? `1 suggestion across ${durationStr(duration)} of your speech.`
        : `${n} suggestions across ${durationStr(duration)} of your speech.`;

    let body = '';
    if (n === 0) {
      body = '<p class="empty">Nothing to flag — great session.</p>';
    } else {
      const transcriptHTML = buildTranscript(issues, transcript);
      const notesHTML      = buildNotes(issues);
      body = `
  <div class="layout">
    <aside class="margin" id="margin">
      ${notesHTML}
    </aside>
    <section>
      <div class="transcript-label">Transcript</div>
      <div class="transcript">
        ${transcriptHTML}
      </div>
    </section>
  </div>`;
    }

    page.innerHTML = `
  <header class="report-masthead">
    <button class="back-link" onclick="window.showSessions && window.showSessions()"><span class="arrow">&larr;</span> Sessions</button>
    <div class="report-wordmark">Fluent</div>
    <div class="session-meta">${esc(date)} &middot; ${esc(durationStr(duration))}</div>
    <p class="report-summary">${esc(summaryText)}</p>
  </header>
  ${body}`;

    page.classList.add('visible');

    requestAnimationFrame(() => {
      wireHovers();
      align();
    });
  };

  window.showSessions = function () {
    const page         = document.getElementById('page');
    const sessionsPage = document.getElementById('sessions-page');
    page.classList.remove('visible');
    page.innerHTML = '';
    if (sessionsPage) sessionsPage.style.display = '';
  };

  window.addEventListener('resize', align);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(align);

  // ── Recording controls ────────────────────────────────────────────────────

  const ENGINE_URL = 'http://127.0.0.1:2788';
  let _recording = false;
  let _polling = null;
  let _timerHandle = null;
  let _startedAt = null;

  function fmtTime(ms) {
    const total = Math.floor(ms / 1000);
    const m = Math.floor(total / 60).toString().padStart(2, '0');
    const s = (total % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }

  function startTimer() {
    _startedAt = Date.now();
    document.querySelectorAll('.rec-timer').forEach(el => { el.textContent = '00:00'; });
    _timerHandle = setInterval(() => {
      const elapsed = Date.now() - _startedAt;
      document.querySelectorAll('.rec-timer').forEach(el => { el.textContent = fmtTime(elapsed); });
    }, 250);
  }

  function stopTimer() {
    clearInterval(_timerHandle);
    _timerHandle = null;
    _startedAt = null;
    document.querySelectorAll('.rec-timer').forEach(el => { el.textContent = '00:00'; });
  }

  function setRecordingState(recording) {
    _recording = recording;
    document.querySelectorAll('.session-control').forEach(ctrl => {
      ctrl.classList.remove('is-recording', 'is-processing');
      if (recording) ctrl.classList.add('is-recording');
    });
    if (recording) {
      startTimer();
    } else {
      stopTimer();
    }
  }

  function setProcessingState() {
    stopTimer();
    document.querySelectorAll('.session-control').forEach(ctrl => {
      ctrl.classList.remove('is-recording');
      ctrl.classList.add('is-processing');
    });
    // Show "Analysing…" in the rec-label while processing
    document.querySelectorAll('.rec-label').forEach(el => { el.textContent = 'Analysing…'; });
  }

  function resetRecLabel() {
    document.querySelectorAll('.rec-label').forEach(el => { el.textContent = 'Recording'; });
  }

  async function startRecording() {
    try {
      const res = await fetch(ENGINE_URL + '/start', { method: 'POST' });
      const data = await res.json();
      if (data.recording) setRecordingState(true);
    } catch (e) {
      console.warn('[Fluent] engine not running');
    }
  }

  async function stopRecording() {
    setProcessingState();
    try {
      await fetch(ENGINE_URL + '/stop', { method: 'POST' });
    } catch (e) {
      console.warn('[Fluent] engine not running');
    }
  }

  // Reset controls when report arrives
  const _origLoadReport = window.loadReport;
  window.loadReport = function(data) {
    setRecordingState(false);
    resetRecLabel();
    if (_origLoadReport) _origLoadReport(data);
  };

  async function pollStatus() {
    try {
      const res = await fetch(ENGINE_URL + '/status');
      const data = await res.json();
      const ctrl = document.querySelector('.session-control');
      if (ctrl && !ctrl.classList.contains('is-processing') && data.recording !== _recording) {
        setRecordingState(data.recording);
      }
    } catch (_) {}
  }

  function initRecordingControls() {
    document.querySelectorAll('.start-button').forEach(btn => {
      btn.addEventListener('click', startRecording);
    });
    document.querySelectorAll('.rec-stop').forEach(btn => {
      btn.addEventListener('click', stopRecording);
    });
    pollStatus();
    if (_polling) clearInterval(_polling);
    _polling = setInterval(pollStatus, 3000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initRecordingControls);
  } else {
    initRecordingControls();
  }

})();
