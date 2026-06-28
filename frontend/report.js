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

  // Long form for the report meta line, e.g. "10 sec", "2 min", "1 hr 5 min".
  function durationLong(seconds) {
    seconds = Math.round(seconds);
    if (seconds < 60) return `${seconds} sec`;
    const h = Math.floor(seconds / 3600);
    const m = Math.round((seconds % 3600) / 60);
    if (h) return m ? `${h} hr ${m} min` : `${h} hr`;
    return `${m} min`;
  }

  // Pull "HH:MM" out of a session slug like "2026-06-13_09-31".
  function timeFromSlug(slug) {
    const m = String(slug || '').match(/_(\d{2})-(\d{2})/);
    return m ? `${m[1]}:${m[2]}` : '';
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
      const id = flag.dataset.issue;
      flag.addEventListener('mouseenter', () => setActive(id, true));
      flag.addEventListener('mouseleave', () => setActive(id, false));
      flag.addEventListener('click', () => {
        const note = document.getElementById('note-' + id);
        if (note) note.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
    document.querySelectorAll('.note').forEach(note => {
      const id = note.dataset.issue;
      note.style.cursor = 'pointer';
      note.addEventListener('mouseenter', () => setActive(id, true));
      note.addEventListener('mouseleave', () => setActive(id, false));
      note.addEventListener('click', () => {
        const flag = document.getElementById('flag-' + id);
        if (flag) flag.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
  }

  function setActive(id, on) {
    const flag = document.querySelector(`mark.flag[data-issue="${id}"]`);
    const note = document.querySelector(`.note[data-issue="${id}"]`);
    if (flag) flag.classList.toggle('is-active', on);
    if (note) note.classList.toggle('is-active', on);
  }

  // ── Build transcript with inline marks ───────────────────────────────────

  function buildTranscript(issues, transcriptText, segments) {
    // Speaker-labeled chronological turns when diarized segments exist.
    if (Array.isArray(segments) && segments.length) {
      return segments.map((seg) => {
        let text = esc(seg.text || '');
        // Only the user's ("You") turns carry inline issue marks.
        if (seg.speaker === 'You') {
          issues.forEach((issue, idx) => {
            const n = idx + 1;
            const original = issue.original || '';
            if (!original || !(seg.text || '').includes(original)) return;
            const mark =
              `<mark class="flag" data-issue="${n}" id="flag-${n}">${esc(original)}` +
              `<span class="num">${n}</span></mark>`;
            text = text.replace(esc(original), () => mark);
          });
        }
        const who = esc(seg.speaker || 'Speaker');
        const cls = seg.speaker === 'You' ? 'turn turn-you' : 'turn';
        return `<div class="${cls}"><span class="turn-speaker">${who}</span>` +
               `<p class="turn-text">${text}</p></div>`;
      }).join('\n');
    }

    // Flat fallback (old sessions, or no diarization). Escape first, then
    // insert issue marks against the escaped text (mirrors the segments path).
    const rawText = transcriptText || '';
    let text = esc(rawText);
    issues.forEach((issue, idx) => {
      const n = idx + 1;
      const original = issue.original || '';
      if (!original || !rawText.includes(original)) return;
      const replacement =
        `<mark class="flag" data-issue="${n}" id="flag-${n}">${esc(original)}` +
        `<span class="num">${n}</span></mark>`;
      text = text.replace(esc(original), () => replacement);
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
      <article class="note" data-issue="${n}" id="note-${n}">
        <div class="note-head">
          <span class="note-num">${n}</span>
          <span class="note-category">${esc(issue.category || 'Phrasing')}</span>
        </div>
        <p class="note-said-label">You said</p>
        <p class="note-said">${esc(issue.original || '')}</p>
        <p class="note-try-label">Try this</p>
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

  window._t0 = performance.now();
  console.log('[Fluent] page ready at', window._t0.toFixed(0), 'ms');

  window.loadSessions = function (sessions, upNext) {
    console.log('[Fluent] loadSessions called at', performance.now().toFixed(0), 'ms (+' + (performance.now() - window._t0).toFixed(0) + 'ms after page ready)');
    const sessionsPage = document.getElementById('sessions-page');
    const authPage     = document.getElementById('auth-page');
    const settingsPage = document.getElementById('settings-page');
    const page         = document.getElementById('page');

    page.classList.remove('visible');
    page.innerHTML = '';
    if (authPage)       authPage.style.display = 'none';
    if (settingsPage)   settingsPage.style.display = 'none';

    sessionsPage.style.display = '';
    if (upNext !== undefined) {
      renderUpNext(upNext);
    } else {
      loadUpNext(_token());
    }

    renderSessionsList(sessions);
  };

  // Swift calls this to refresh the History list after a recording finishes,
  // without switching the visible page (so it doesn't yank the user off the
  // report they're viewing). The webview can't fetch the backend itself due to
  // CORS, so Swift fetches natively and hands us the parsed sessions array.
  window.refreshSessionsList = function (sessions) {
    renderSessionsList(sessions);
  };

  // Render just the History list + summary (no page switching). Shared by
  // loadSessions (initial inject from Swift) and showSessions (live refetch).
  function renderSessionsList(sessions) {
    const listEl    = document.getElementById('sessions-list');
    const summaryEl = document.getElementById('sessions-summary');
    if (!listEl || !summaryEl) return;

    if (!sessions || sessions.length === 0) {
      listEl.innerHTML = '';
      summaryEl.textContent = '';
      return;
    }

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
        console.log('[Fluent] session clicked:', session.slug, 'data:', !!session.data);
        if (session.data) {
          window.loadReport(session.data);
          return;
        }
        const slug = session.slug || session.date;
        console.log('[Fluent] slug:', slug);
        if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.openSession) {
          console.log('[Fluent] sending openSession to Swift');
          window.webkit.messageHandlers.openSession.postMessage(slug);
        } else {
          const token = _token();
          console.log('[Fluent] no Swift bridge, token present:', !!token);
          if (!token) return;
          const url = BACKEND_URL + '/sessions/' + encodeURIComponent(slug);
          console.log('[Fluent] fetching:', url);
          fetch(url, { headers: { 'Authorization': 'Bearer ' + token } })
            .then(r => { console.log('[Fluent] response status:', r.status); return r.ok ? r.json() : null; })
            .then(data => { console.log('[Fluent] session data:', data); if (data) window.loadReport(data); })
            .catch(e => { console.error('[Fluent] fetch error:', e); });
        }
      });
      listEl.appendChild(btn);
    });
  };

  // ── Main render ───────────────────────────────────────────────────────────

  window.loadReport = function (data) {
    const page         = document.getElementById('page');
    const sessionsPage = document.getElementById('sessions-page');
    const issues       = Array.isArray(data.issues) ? data.issues : (Array.isArray(data) ? data : []);
    const transcript   = data.transcript || '';
    const segments     = Array.isArray(data.segments) ? data.segments : [];
    const systemCaptured = data.system_audio_captured !== false;
    const duration     = data.duration   || 0;
    const slug         = data.slug || '';
    const date         = data.date       || formatSessionName(slug) || new Date().toLocaleDateString('en-US', {
      month: 'long', day: 'numeric', year: 'numeric',
    });
    const title        = data.name || formatSessionName(slug) || 'Session';
    const time         = timeFromSlug(slug);

    if (sessionsPage) sessionsPage.style.display = 'none';
    const recordingPage = document.getElementById('recording-page');
    if (recordingPage) recordingPage.style.display = 'none';

    // Meta line: "June 13, 2026 · 09:31 · 10 sec"
    const metaParts = [esc(date), time && esc(time), esc(durationLong(duration))].filter(Boolean);

    const hasTranscript = transcript.trim().length > 0 || segments.length > 0;

    let body;
    if (!hasTranscript) {
      // Nothing was captured — don't pretend to grade silence.
      body = `
  <div class="no-transcript">
    <div class="no-transcript-eyebrow">No transcript</div>
    <h2 class="no-transcript-title">Nothing was transcribed in this session.</h2>
    <p class="no-transcript-body">The recording ran for ${esc(durationLong(duration))} &mdash; too short to capture any speech, or no one spoke. There&rsquo;s nothing to review here.</p>
    <p class="no-transcript-hint">If you expected feedback, check your microphone and make sure recording continues while you&rsquo;re speaking.</p>
  </div>`;
    } else {
      const n = issues.length;
      const summaryText = n === 0
        ? 'No suggestions — your English sounded natural and fluent.'
        : n === 1
          ? `1 suggestion across ${durationStr(duration)} of your speech.`
          : `${n} suggestions across ${durationStr(duration)} of your speech.`;

      const captureNotice = (!systemCaptured && segments.length === 0)
        ? '<p class="capture-notice">Only your microphone was captured this session — other participants weren&rsquo;t recorded.</p>'
        : '';
      const transcriptHTML = captureNotice + buildTranscript(issues, transcript, segments);
      const noIssuesNote   = n === 0
        ? '<p class="empty">Nothing to flag — great session.</p>'
        : '';
      const notesHTML = buildNotes(issues);

      body = `
  <p class="report-summary">${esc(summaryText)}</p>
  ${noIssuesNote}
  <div class="layout">
    <aside class="margin" id="margin">
      ${n === 0 ? '' : notesHTML}
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
    <h1 class="report-title">${esc(title)}</h1>
    <div class="session-meta">${metaParts.join(' &middot; ')}</div>
  </header>
  ${body}`;

    page.classList.add('visible');

    requestAnimationFrame(() => {
      wireHovers();
      align();
    });
  };

  window.showOnboarding = function () {
    const page          = document.getElementById('page');
    const sessionsPage  = document.getElementById('sessions-page');
    const authPage      = document.getElementById('auth-page');
    const settingsPage  = document.getElementById('settings-page');
    const recordingPage = document.getElementById('recording-page');
    if (page)         { page.classList.remove('visible'); page.innerHTML = ''; }
    if (sessionsPage)   sessionsPage.style.display = 'none';
    if (settingsPage)   settingsPage.style.display = 'none';
    if (recordingPage)  recordingPage.style.display = 'none';
    if (authPage)       authPage.style.display = '';
  };

  // ── Auth page logic ───────────────────────────────────────────────────────

  const BACKEND_URL = 'https://www.tryfluent.co/api';

  function _token() { return localStorage.getItem('fluent_token') || window._fluentToken || null; }
  function _saveToken(t) { localStorage.setItem('fluent_token', t); }
  function _clearToken() { localStorage.removeItem('fluent_token'); }

  // ── Backend access ──────────────────────────────────────────────────────────
  // The webview is served from a file:// origin, so direct fetch() to the API is
  // blocked by CORS. When running inside the app we proxy authenticated requests
  // through the native Swift bridge (which holds the keychain token); in a real
  // browser (future web client) we fall back to a normal fetch().
  const _hasNativeBridge = !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.apiRequest);
  const _apiPending = {};
  window.__apiResolve = function (id, result) {
    const r = _apiPending[id];
    if (!r) return;
    delete _apiPending[id];
    r(result); // { ok, status, body }
  };

  // fetch-like wrapper. `path` is relative to the API root (e.g. "/auth/me").
  // Returns { ok, status, json(), text() } so callers read like a fetch Response.
  function apiFetch(path, opts) {
    opts = opts || {};
    const method = opts.method || 'GET';
    let bodyObj = null;
    if (opts.body != null) {
      try { bodyObj = typeof opts.body === 'string' ? JSON.parse(opts.body) : opts.body; }
      catch (_) { bodyObj = opts.body; }
    }

    if (_hasNativeBridge) {
      return new Promise(resolve => {
        const id = 'api_' + Date.now() + '_' + Math.random().toString(36).slice(2);
        _apiPending[id] = (res) => {
          const text = res.body || '';
          resolve({
            ok: res.ok,
            status: res.status,
            json: () => Promise.resolve(text ? JSON.parse(text) : null),
            text: () => Promise.resolve(text),
          });
        };
        window.webkit.messageHandlers.apiRequest.postMessage({ id, method, path, body: bodyObj });
      });
    }

    // Browser fallback: real fetch with the bearer token.
    const token = _token();
    const headers = Object.assign({}, opts.headers || {});
    if (token) headers['Authorization'] = 'Bearer ' + token;
    if (bodyObj != null) headers['Content-Type'] = 'application/json';
    return fetch(BACKEND_URL + path, {
      method,
      headers,
      cache: opts.cache,
      body: bodyObj != null ? JSON.stringify(bodyObj) : undefined,
    });
  }

  (function initAuth() {
    const authPage  = document.getElementById('auth-page');
    if (!authPage) return;

    // Google sign-in: open the local backend OAuth endpoint in the system browser.
    // The backend redirects to Google, which redirects back via fluent://auth?token=...
    // Swift intercepts that URL and calls handleGoogleAuthCallback.
    const googleBtn = authPage.querySelector('.auth-providers .auth-provider:first-child');
    if (googleBtn) {
      googleBtn.addEventListener('click', () => {
        const googleAuthURL = 'https://www.tryfluent.co/api/auth/google';
        if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.openURL) {
          window.webkit.messageHandlers.openURL.postMessage(googleAuthURL);
        } else {
          window.open(googleAuthURL, '_blank');
        }
      });
    }
  })();

  // ── Calendar / Up Next ───────────────────────────────────────────────────

  function _formatEventTime(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    if (isNaN(d)) return '';
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  function _formatEventDay(isoString) {
    if (!isoString) return '';
    const d     = new Date(isoString);
    const today = new Date();
    const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
    if (d.toDateString() === today.toDateString())    return 'Today';
    if (d.toDateString() === tomorrow.toDateString()) return 'Tomorrow';
    return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
  }

  function renderUpNext(events) {
    const list = document.getElementById('upnext-list');
    if (!list) return;
    if (!events || !events.length) {
      list.innerHTML = '<div class="session upnext-empty"><span class="session-name" style="color:#b5b5b5">No upcoming meetings</span></div>';
      return;
    }
    list.innerHTML = events.map(ev => {
      const time     = _formatEventTime(ev.start);
      const day      = _formatEventDay(ev.start);
      const dayLabel = day ? `<span class="upnext-day">${esc(day)}</span> ` : '';
      return `<div class="session upnext-row">
        <span class="session-name">${esc(ev.title)}</span>
        <span class="session-date upnext-time">${dayLabel}${esc(time)}</span>
        <button class="upnext-record-btn" type="button">
          <span class="dot"></span>Start recording
        </button>
      </div>`;
    }).join('');

    list.querySelectorAll('.upnext-record-btn').forEach((btn, i) => {
      const title = events[i] && events[i].title ? events[i].title : 'Recording';
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openRecordingPage(title);
      });
    });
  }

  function loadUpNext(token) {
    token = token || _token();
    if (!token) return;
    const list = document.getElementById('upnext-list');
    if (!list) return;

    apiFetch('/calendar/upcoming')
      .then(r => r.ok ? r.json() : null)
      .then(events => renderUpNext(events))
      .catch(() => {});
  }

  window.showSessions = function () {
    const page          = document.getElementById('page');
    const sessionsPage  = document.getElementById('sessions-page');
    const settingsPage  = document.getElementById('settings-page');
    const recordingPage = document.getElementById('recording-page');
    page.classList.remove('visible');
    page.innerHTML = '';
    if (settingsPage)  settingsPage.style.display = 'none';
    if (recordingPage) recordingPage.style.display = 'none';
    if (sessionsPage)  sessionsPage.style.display = '';
    _resetBillingDetailsFlag();
    loadUpNext();

    // Re-fetch the History list every time we open it, so sessions recorded
    // while a report was on screen still appear (the post-recording refresh in
    // loadReport is skipped while the report page is visible).
    const token = _token();
    if (token) {
      apiFetch('/sessions')
        .then(r => r.ok ? r.json() : null)
        .then(sessions => { if (sessions) renderSessionsList(sessions); })
        .catch(() => {});
    }
  };

  // Open the dedicated recording page for a "Coming up" meeting and start recording.
  window.openRecordingPage = function (title) {
    const page          = document.getElementById('page');
    const sessionsPage  = document.getElementById('sessions-page');
    const settingsPage  = document.getElementById('settings-page');
    const authPage      = document.getElementById('auth-page');
    const recordingPage = document.getElementById('recording-page');
    const titleEl       = document.getElementById('recording-title');

    if (page)         { page.classList.remove('visible'); page.innerHTML = ''; }
    if (sessionsPage)   sessionsPage.style.display = 'none';
    if (settingsPage)   settingsPage.style.display = 'none';
    if (authPage)       authPage.style.display = 'none';
    if (titleEl)        titleEl.textContent = title || 'Recording';
    if (recordingPage)  recordingPage.style.display = '';

    // Remember the meeting title so the created session keeps this name.
    _sessionName = title || null;

    // Reset the recording control to a clean "recording" state, then start.
    resetRecLabel();
    startRecording();
  };

  window.showSettings = function () {
    const page          = document.getElementById('page');
    const sessionsPage  = document.getElementById('sessions-page');
    const authPage      = document.getElementById('auth-page');
    const settingsPage  = document.getElementById('settings-page');
    const recordingPage = document.getElementById('recording-page');
    if (page)         { page.classList.remove('visible'); page.innerHTML = ''; }
    if (sessionsPage)   sessionsPage.style.display = 'none';
    if (authPage)       authPage.style.display = 'none';
    if (recordingPage)  recordingPage.style.display = 'none';
    if (settingsPage)   settingsPage.style.display = 'block';

    const token = _token();
    if (!token) return;

    // Fetch account info
    apiFetch('/auth/me')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        const emailEl = document.getElementById('settings-email');
        if (emailEl) emailEl.textContent = data.email;
        const billingEmailEl = document.getElementById('settings-billing-email-val');
        if (billingEmailEl) billingEmailEl.textContent = data.email;
      })
      .catch(() => {});

    // Fallback: use cached status from the DB. /billing/status returns 200 for
    // any authenticated user (defaulting to a trial), so this reliably reveals
    // the Plan + Billing sections even when the live Stripe sync can't run
    // (e.g. user has no Stripe customer yet, or the sync request errors out).
    const showCachedStatus = () =>
      apiFetch('/billing/status', { cache: 'no-store' })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) renderBillingStatus(d); })
        .catch(() => {});

    // Sync billing status live from Stripe, then fall back to cached status.
    apiFetch('/billing/sync', { method: 'POST' })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) { renderBillingStatus(data); return; }
        return showCachedStatus();
      })
      .catch(() => showCachedStatus());
  };

  window.syncBillingStatus = function () {
    const settingsPage = document.getElementById('settings-page');
    if (!settingsPage || settingsPage.style.display === 'none') return;
    const token = _token();
    if (!token) return;
    apiFetch('/billing/sync', { method: 'POST' })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) renderBillingStatus(data); })
      .catch(() => {});
  };

  function renderBillingStatus(data) {
    const { plan_status, trial_ends_at, current_period_end, cancel_at_period_end } = data;

    // Plan section
    const planSection = document.getElementById('settings-plan-section');
    if (planSection) planSection.style.display = 'block';

    const trialEl    = document.getElementById('settings-plan-trial');
    const activeEl   = document.getElementById('settings-plan-active');
    const canceledEl = document.getElementById('settings-plan-canceled');

    [trialEl, activeEl, canceledEl].forEach(el => { if (el) el.style.display = 'none'; });

    function fmtDate(ts) {
      if (!ts) return '';
      return new Date(ts * 1000).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    }

    if (plan_status === 'trial' && trialEl) {
      const daysLeft = trial_ends_at ? Math.max(0, Math.ceil((trial_ends_at * 1000 - Date.now()) / 86400000)) : 0;
      const trialMeta = trialEl.querySelector('.settings-plan-trial-meta');
      const trialDate = trialEl.querySelector('.settings-plan-billing-date');
      if (trialMeta) trialMeta.textContent = `Free trial · ${daysLeft} day${daysLeft !== 1 ? 's' : ''} remaining`;
      if (trialDate) trialDate.textContent = `Billing starts ${fmtDate(trial_ends_at)}.`;
      trialEl.style.display = 'block';
    } else if (plan_status === 'active' && cancel_at_period_end && canceledEl) {
      const accessDate = canceledEl.querySelector('.settings-plan-access-date');
      if (accessDate) accessDate.textContent = `Canceled · access through ${fmtDate(current_period_end)}`;
      canceledEl.style.display = 'block';
    } else if (plan_status === 'active' && activeEl) {
      const renewDate = activeEl.querySelector('.settings-plan-renew-date');
      if (renewDate) renewDate.textContent = `Renews ${fmtDate(current_period_end)}.`;
      activeEl.style.display = 'block';
    } else if (plan_status === 'canceled' && canceledEl) {
      const accessDate = canceledEl.querySelector('.settings-plan-access-date');
      if (accessDate) accessDate.textContent = `Canceled · access through ${fmtDate(current_period_end)}`;
      canceledEl.style.display = 'block';
    }

    // Billing section
    const billingSection = document.getElementById('settings-billing-section');
    if (billingSection) billingSection.style.display = 'block';

    if (!_billingDetailsFetched) {
      _billingDetailsFetched = true;
      fetchBillingDetails();
    }
  }

  let _billingDetailsFetched = false;

  // Reset flag when settings page is hidden so it re-fetches next open
  function _resetBillingDetailsFlag() { _billingDetailsFetched = false; }

  function fetchBillingDetails() {
    const token = _token();
    if (!token) return;
    apiFetch('/billing/invoices')
      .then(r => {
        if (!r.ok) { r.text().then(t => console.warn('[Fluent] /billing/invoices error', r.status, t)); return null; }
        return r.json();
      })
      .then(data => {
        if (!data) return;
        renderCardOnFile(data.card);
        renderInvoices(data.invoices);
      })
      .catch(e => console.warn('[Fluent] /billing/invoices fetch failed', e));
  }

  function renderCardOnFile(card) {
    const cardRow         = document.getElementById('settings-card-row');
    const cardVal         = document.getElementById('settings-card-val');
    const placeholderRow  = document.getElementById('settings-card-placeholder-row');
    if (!card || !card.last4) return;
    const brand = (card.brand || '').toUpperCase().slice(0, 4);
    const month = String(card.exp_month || '').padStart(2, '0');
    const year  = String(card.exp_year || '').slice(-2);
    cardVal.innerHTML = `
      <div class="settings-card-on-file">
        <span class="settings-card-brand">${esc(brand)}</span>
        <div>
          <div class="settings-card-num"><span class="settings-card-dots">&bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull;</span>${esc(card.last4)}</div>
          <div class="settings-card-exp">Expires ${esc(month)} / ${esc(year)}</div>
        </div>
      </div>`;
    if (cardRow)        cardRow.style.display = '';
    if (placeholderRow) placeholderRow.style.display = 'none';
  }

  function renderInvoices(invoices) {
    const row  = document.getElementById('settings-invoices-row');
    const list = document.getElementById('settings-invoices-list');
    if (!invoices || !invoices.length || !row || !list) return;
    list.innerHTML = invoices.map(inv => {
      const date   = inv.date ? new Date(inv.date * 1000).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }) : '—';
      const amount = inv.amount != null ? (inv.currency === 'usd' ? '$' : '') + (inv.amount / 100).toFixed(2) : '—';
      const link   = inv.pdf ? `<a class="settings-invoice-link" href="${esc(inv.pdf)}" target="_blank">Download &rarr;</a>` : '<span></span>';
      return `<div class="settings-invoice">
        <span class="settings-invoice-date">${date}</span>
        <span class="settings-invoice-amount">${amount}</span>
        ${link}
      </div>`;
    }).join('');
    row.style.display = '';
  }

  // ── Settings page wiring ──────────────────────────────────────────────────

  (function initSettings() {
    const backBtn    = document.getElementById('settings-back');
    const signoutBtn = document.getElementById('settings-signout-btn');
    const deleteBtn  = document.getElementById('settings-delete-btn');

    // Plan action buttons — open Stripe checkout or portal
    function openExternal(url) {
      if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.openURL) {
        window.webkit.messageHandlers.openURL.postMessage(url);
      } else {
        window.location.href = url;
      }
      // Poll for plan changes after the user returns from Stripe
      _pollBillingAfterStripe();
    }

    function _pollBillingAfterStripe() {
      let attempts = 0;
      function poll() {
        attempts++;
        if (attempts > 8) return;
        const token = _token();
        if (!token) return;
        apiFetch('/billing/sync', { method: 'POST' })
          .then(r => r.ok ? r.json() : null)
          .then(data => { if (data) renderBillingStatus(data); })
          .catch(() => {});
        setTimeout(poll, 3000);
      }
      setTimeout(poll, 3000);
    }

    async function openCheckout() {
      const token = _token();
      if (!token) return;
      try {
        const res = await apiFetch('/billing/checkout', { method: 'POST', body: {} });
        const data = await res.json().catch(() => null);
        if (res.ok && data && data.url) { openExternal(data.url); return; }
        console.warn('[Fluent] checkout failed', res.status, data);
        alert((data && data.detail) || 'Could not start checkout. Please try again.');
      } catch (e) {
        console.warn('[Fluent] checkout error', e);
        alert('Could not start checkout. Please try again.');
      }
    }

    async function openPortal() {
      const token = _token();
      if (!token) return;
      try {
        const res = await apiFetch('/billing/portal', { method: 'POST' });
        const data = await res.json().catch(() => null);
        if (res.ok && data && data.url) { openExternal(data.url); return; }
        if (res.status === 400) { openCheckout(); return; }
        console.warn('[Fluent] portal failed', res.status, data);
        alert((data && data.detail) || 'Could not open billing. Please try again.');
      } catch (e) {
        console.warn('[Fluent] portal error', e);
        alert('Could not open billing. Please try again.');
      }
    }

    const upgradeBtn             = document.getElementById('settings-upgrade-btn');
    const cancelTrialBtn         = document.getElementById('settings-cancel-trial-btn');
    const cancelPlanBtn          = document.getElementById('settings-cancel-plan-btn');
    const resumePlanBtn          = document.getElementById('settings-resume-plan-btn');
    const updateCardBtn          = document.getElementById('settings-update-card-btn');
    const updateCardPlaceholder  = document.getElementById('settings-update-card-placeholder-btn');
    if (upgradeBtn)            upgradeBtn.addEventListener('click', openCheckout);
    if (cancelTrialBtn)        cancelTrialBtn.addEventListener('click', openPortal);
    if (cancelPlanBtn)         cancelPlanBtn.addEventListener('click', openPortal);
    if (resumePlanBtn)         resumePlanBtn.addEventListener('click', openCheckout);
    if (updateCardBtn)         updateCardBtn.addEventListener('click', openPortal);
    if (updateCardPlaceholder) updateCardPlaceholder.addEventListener('click', openPortal);

    if (backBtn) backBtn.addEventListener('click', () => window.showSessions && window.showSessions());

    if (signoutBtn) signoutBtn.addEventListener('click', () => {
      localStorage.removeItem('fluent_token');
      if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.signOut) {
        window.webkit.messageHandlers.signOut.postMessage(null);
      } else {
        fetch('http://127.0.0.1:2788/signout', { method: 'POST' }).catch(() => {});
        window.showOnboarding && window.showOnboarding();
      }
    });

    if (deleteBtn) deleteBtn.addEventListener('click', async () => {
      if (!confirm('Delete your account? All data will be removed within 24 hours. This cannot be undone.')) return;
      const token = _token();
      if (!token) { window.showOnboarding && window.showOnboarding(); return; }
      try {
        await apiFetch('/auth/delete-account', { method: 'DELETE' });
      } catch (_) {}
      localStorage.removeItem('fluent_token');
      if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.signOut) {
        window.webkit.messageHandlers.signOut.postMessage(null);
      } else {
        window.showOnboarding && window.showOnboarding();
      }
    });
  })();

  window.addEventListener('resize', align);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(align);

  // ── Recording controls ────────────────────────────────────────────────────

  const ENGINE_URL = 'http://127.0.0.1:2788';
  let _recording = false;
  let _polling = null;
  let _timerHandle = null;
  let _startedAt = null;
  // Title of the meeting being recorded (from a "Coming up" row), so the
  // created session keeps that name instead of a generic "Morning session".
  let _sessionName = null;

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
    const body = _sessionName ? { session_name: _sessionName } : {};
    try {
      await fetch(ENGINE_URL + '/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (e) {
      console.warn('[Fluent] engine not running');
    }
  }

  // Reset controls when report arrives, then refresh sessions list
  const _origLoadReport = window.loadReport;
  window.loadReport = function(data) {
    setRecordingState(false);
    resetRecLabel();
    _sessionName = null;
    if (_origLoadReport) _origLoadReport(data);
    // Refresh the History list in the background so a just-finished recording
    // appears as soon as the user navigates back. Re-render the (hidden)
    // sessions list directly rather than calling loadSessions(), which would
    // switch the visible page and yank the user off the report they're viewing.
    const token = _token();
    if (token) {
      apiFetch('/sessions')
        .then(r => r.ok ? r.json() : null)
        .then(sessions => { if (sessions) renderSessionsList(sessions); })
        .catch(() => {});
    }
  };

  async function pollStatus() {
    try {
      const res = await fetch(ENGINE_URL + '/status');
      const data = await res.json();
      const ctrl = document.querySelector('.session-control');
      // If the engine says it's no longer analysing but the UI is stuck in is-processing, reset it.
      if (ctrl && ctrl.classList.contains('is-processing') && data.analysing === false) {
        setRecordingState(false);
        resetRecLabel();
        // If we're still on the recording page, no report arrived (e.g. session too
        // short to analyse). Fall back to the sessions list rather than stranding the user.
        const recordingPage = document.getElementById('recording-page');
        if (recordingPage && recordingPage.style.display !== 'none') {
          _sessionName = null;
          window.showSessions && window.showSessions();
        }
      } else if (ctrl && !ctrl.classList.contains('is-processing') && data.recording !== _recording) {
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
    const recordingBack = document.getElementById('recording-back');
    if (recordingBack) {
      recordingBack.addEventListener('click', () => window.showSessions && window.showSessions());
    }
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
