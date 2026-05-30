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

  function buildTranscript(issues, transcriptText) {
    let text = transcriptText || '';

    issues.forEach((issue, idx) => {
      const n = idx + 1;
      const original = issue.original || '';
      if (!original || !text.includes(original)) return;
      const replacement =
        `<mark class="flag" data-issue="${n}" id="flag-${n}">${esc(original)}` +
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

  window.loadSessions = function (sessions) {
    const sessionsPage = document.getElementById('sessions-page');
    const authPage     = document.getElementById('auth-page');
    const settingsPage = document.getElementById('settings-page');
    const page         = document.getElementById('page');
    const listEl       = document.getElementById('sessions-list');
    const summaryEl    = document.getElementById('sessions-summary');

    page.classList.remove('visible');
    page.innerHTML = '';
    if (authPage)       authPage.style.display = 'none';
    if (settingsPage)   settingsPage.style.display = 'none';

    sessionsPage.style.display = '';
    loadUpNext();

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
    const sessionsPage = document.getElementById('sessions-page');
    const issues       = Array.isArray(data.issues) ? data.issues : (Array.isArray(data) ? data : []);
    const transcript   = data.transcript || '';
    const duration     = data.duration   || 0;
    const date         = data.date       || new Date().toLocaleDateString('en-US', {
      month: 'long', day: 'numeric', year: 'numeric',
    });

    if (sessionsPage) sessionsPage.style.display = 'none';

    const n = issues.length;
    const summaryText = n === 0
      ? 'No suggestions — your English sounded natural and fluent.'
      : n === 1
        ? `1 suggestion across ${durationStr(duration)} of your speech.`
        : `${n} suggestions across ${durationStr(duration)} of your speech.`;

    const transcriptHTML = buildTranscript(issues, transcript);
    const noIssuesNote   = n === 0
      ? '<p class="empty">Nothing to flag — great session.</p>'
      : '';
    const notesHTML = buildNotes(issues);

    let body;
    if (n === 0) {
      body = `
  ${noIssuesNote}
  <div class="layout">
    <aside class="margin" id="margin"></aside>
    <section>
      <div class="transcript-label">Transcript</div>
      <div class="transcript">
        ${transcriptHTML}
      </div>
    </section>
  </div>`;
    } else {
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

  window.showOnboarding = function () {
    const page         = document.getElementById('page');
    const sessionsPage = document.getElementById('sessions-page');
    const authPage     = document.getElementById('auth-page');
    const settingsPage = document.getElementById('settings-page');
    if (page)         { page.classList.remove('visible'); page.innerHTML = ''; }
    if (sessionsPage)   sessionsPage.style.display = 'none';
    if (settingsPage)   settingsPage.style.display = 'none';
    if (authPage)       authPage.style.display = '';
  };

  // ── Auth page logic ───────────────────────────────────────────────────────

  const BACKEND_URL = 'https://fluent-lemon.vercel.app/api';

  function _token() { return localStorage.getItem('fluent_token'); }
  function _saveToken(t) { localStorage.setItem('fluent_token', t); }
  function _clearToken() { localStorage.removeItem('fluent_token'); }

  (function initAuth() {
    const authPage  = document.getElementById('auth-page');
    if (!authPage) return;

    const heading   = document.getElementById('auth-heading');
    const subhead   = document.getElementById('auth-subhead');
    const submitBtn = document.getElementById('auth-submit');
    const errorEl   = document.getElementById('auth-error');
    const password  = document.getElementById('auth-password');

    const copy = {
      signin: { heading: 'Welcome back.', subhead: 'Sign in to see your coaching reports.', submit: 'Sign in', passAuto: 'current-password', passPlaceholder: 'Your password' },
      signup: { heading: 'Create your account.', subhead: 'Seven days free. Cancel anytime from the app.', submit: 'Start free trial', passAuto: 'new-password', passPlaceholder: 'At least 8 characters' },
    };

    let currentMode = 'signin';

    function setMode(mode) {
      currentMode = mode;
      authPage.classList.toggle('mode-signin', mode === 'signin');
      authPage.classList.toggle('mode-signup', mode === 'signup');
      const c = copy[mode];
      heading.textContent  = c.heading;
      subhead.textContent  = c.subhead;
      submitBtn.textContent = c.submit;
      password.setAttribute('autocomplete', c.passAuto);
      password.setAttribute('placeholder', c.passPlaceholder);
      errorEl.textContent = '';
      authPage.querySelectorAll('.mode-toggle button').forEach(b => {
        const on = b.dataset.mode === mode;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }

    authPage.querySelectorAll('[data-mode]').forEach(btn => {
      btn.addEventListener('click', () => setMode(btn.dataset.mode));
    });

    setMode('signin');

    // Google sign-in: open the local backend OAuth endpoint in the system browser.
    // The backend redirects to Google, which redirects back via fluent://auth?token=...
    // Swift intercepts that URL and calls handleGoogleAuthCallback.
    const googleBtn = authPage.querySelector('.auth-providers .auth-provider:first-child');
    if (googleBtn) {
      googleBtn.addEventListener('click', () => {
        const googleAuthURL = 'http://localhost:8001/auth/google';
        if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.openURL) {
          window.webkit.messageHandlers.openURL.postMessage(googleAuthURL);
        } else {
          window.open(googleAuthURL, '_blank');
        }
      });
    }

    document.getElementById('auth-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('auth-email').value.trim();
      const pw    = document.getElementById('auth-password').value;
      errorEl.textContent = '';

      if (!email || !email.includes('@')) { errorEl.textContent = 'Please enter a valid email.'; return; }
      if (pw.length < 8) { errorEl.textContent = 'Password must be at least 8 characters.'; return; }

      submitBtn.disabled = true;
      const endpoint = currentMode === 'signin' ? '/auth/login' : '/auth/register';
      try {
        const res = await fetch(BACKEND_URL + endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password: pw }),
        });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.detail || 'Something went wrong.'; return; }
        _saveToken(data.token);
        authPage.style.display = 'none';
        // Tell Swift the user is now signed in so it can load sessions
        if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.authComplete) {
          window.webkit.messageHandlers.authComplete.postMessage(data.token);
        }
      } catch (err) {
        errorEl.textContent = 'Could not connect: ' + err.message + ' (url: ' + BACKEND_URL + ')';
      } finally {
        submitBtn.disabled = false;
      }
    });
  })();

  // ── Calendar / Up Next ───────────────────────────────────────────────────

  function _formatEventTime(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    if (isNaN(d)) return '';
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  function _formatEventDuration(startIso, endIso) {
    const start = new Date(startIso);
    const end   = new Date(endIso);
    if (isNaN(start) || isNaN(end)) return '';
    const mins = Math.round((end - start) / 60000);
    if (mins < 60) return `${mins} min`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m ? `${h}h ${m}m` : `${h}h`;
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

  function loadUpNext() {
    const token = _token();
    if (!token) return;
    const list = document.getElementById('upnext-list');
    if (!list) return;

    fetch(BACKEND_URL + '/calendar/upcoming', {
      headers: { 'Authorization': 'Bearer ' + token },
    })
      .then(r => r.ok ? r.json() : null)
      .then(events => {
        if (!events || !events.length) {
          list.innerHTML = '<div class="session upnext-empty"><span class="session-name" style="color:#b5b5b5">No upcoming meetings</span></div>';
          return;
        }
        list.innerHTML = events.map(ev => {
          const time     = _formatEventTime(ev.start);
          const duration = _formatEventDuration(ev.start, ev.end);
          const day      = _formatEventDay(ev.start);
          const dayLabel = day !== 'Today' ? `<span class="upnext-day">${esc(day)}</span> ` : '';
          return `<div class="session">
            <span class="session-name">${esc(ev.title)}</span>
            <span class="session-date upnext-time">${dayLabel}${esc(time)}</span>
            <span class="session-duration">${esc(duration)}</span>
          </div>`;
        }).join('');
      })
      .catch(() => {});
  }

  window.showSessions = function () {
    const page         = document.getElementById('page');
    const sessionsPage = document.getElementById('sessions-page');
    const settingsPage = document.getElementById('settings-page');
    page.classList.remove('visible');
    page.innerHTML = '';
    if (settingsPage) settingsPage.style.display = 'none';
    if (sessionsPage) sessionsPage.style.display = '';
    _resetBillingDetailsFlag();
    loadUpNext();
  };

  window.showSettings = function () {
    const page         = document.getElementById('page');
    const sessionsPage = document.getElementById('sessions-page');
    const authPage     = document.getElementById('auth-page');
    const settingsPage = document.getElementById('settings-page');
    if (page)         { page.classList.remove('visible'); page.innerHTML = ''; }
    if (sessionsPage)   sessionsPage.style.display = 'none';
    if (authPage)       authPage.style.display = 'none';
    if (settingsPage)   settingsPage.style.display = 'block';

    const token = localStorage.getItem('fluent_token');
    if (!token) return;

    // Fetch account info
    fetch(BACKEND_URL + '/auth/me', { headers: { 'Authorization': 'Bearer ' + token } })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        const emailEl = document.getElementById('settings-email');
        if (emailEl) emailEl.textContent = data.email;
        const billingEmailEl = document.getElementById('settings-billing-email-val');
        if (billingEmailEl) billingEmailEl.textContent = data.email;
      })
      .catch(() => {});

    // Sync billing status live from Stripe, then fall back to cached status
    fetch(BACKEND_URL + '/billing/sync', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) { renderBillingStatus(data); return; }
        // Fallback: use cached status from DB
        return fetch(BACKEND_URL + '/billing/status', {
          headers: { 'Authorization': 'Bearer ' + token },
          cache: 'no-store',
        }).then(r => r.ok ? r.json() : null).then(d => { if (d) renderBillingStatus(d); });
      })
      .catch(() => {});
  };

  window.syncBillingStatus = function () {
    const settingsPage = document.getElementById('settings-page');
    if (!settingsPage || settingsPage.style.display === 'none') return;
    const token = localStorage.getItem('fluent_token');
    if (!token) return;
    fetch(BACKEND_URL + '/billing/sync', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    })
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
    const token = localStorage.getItem('fluent_token');
    if (!token) return;
    fetch(BACKEND_URL + '/billing/invoices', { headers: { 'Authorization': 'Bearer ' + token } })
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
        <span class="settings-card-brand">${brand}</span>
        <div>
          <div class="settings-card-num"><span class="settings-card-dots">&bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull;</span>${card.last4}</div>
          <div class="settings-card-exp">Expires ${month} / ${year}</div>
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
      const link   = inv.pdf ? `<a class="settings-invoice-link" href="${inv.pdf}" target="_blank">Download &rarr;</a>` : '<span></span>';
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
    const pwForm     = document.getElementById('settings-pw-form');
    const pwError    = document.getElementById('settings-pw-error');
    const pwCancel   = document.getElementById('settings-pw-cancel');
    const emailForm  = document.getElementById('settings-email-form');
    const emailError = document.getElementById('settings-email-error');
    const emailCancel = document.getElementById('settings-email-cancel');
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
        const token = localStorage.getItem('fluent_token');
        if (!token) return;
        fetch(BACKEND_URL + '/billing/sync', {
          method: 'POST', headers: { 'Authorization': 'Bearer ' + token },
        })
          .then(r => r.ok ? r.json() : null)
          .then(data => { if (data) renderBillingStatus(data); })
          .catch(() => {});
        setTimeout(poll, 3000);
      }
      setTimeout(poll, 3000);
    }

    async function openCheckout() {
      const token = localStorage.getItem('fluent_token');
      if (!token) return;
      try {
        const res = await fetch(BACKEND_URL + '/billing/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
          body: JSON.stringify({}),
        });
        const data = await res.json();
        if (data.url) openExternal(data.url);
      } catch (e) { console.warn('[Fluent] checkout error', e); }
    }

    async function openPortal() {
      const token = localStorage.getItem('fluent_token');
      if (!token) return;
      try {
        const res = await fetch(BACKEND_URL + '/billing/portal', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token },
        });
        const data = await res.json();
        if (data.url) openExternal(data.url);
        else if (res.status === 400) openCheckout();
      } catch (e) { console.warn('[Fluent] portal error', e); }
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

    if (emailCancel) emailCancel.addEventListener('click', () => {
      const details = emailCancel.closest('details');
      if (details) details.open = false;
    });

    if (emailForm) emailForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (emailError) emailError.textContent = '';
      const newEmail = document.getElementById('settings-new-email').value.trim();
      const password = document.getElementById('settings-email-pw').value;
      if (!newEmail) { if (emailError) emailError.textContent = 'Enter a new email address.'; return; }
      const token = localStorage.getItem('fluent_token');
      if (!token) { if (emailError) emailError.textContent = 'Not signed in.'; return; }
      const submitBtn = emailForm.querySelector('button[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await fetch(BACKEND_URL + '/auth/change-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
          body: JSON.stringify({ new_email: newEmail, password }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          if (emailError) emailError.textContent = data.detail || 'Could not update email.';
        } else {
          const emailEl = document.getElementById('settings-email');
          const billingEmailEl = document.getElementById('settings-billing-email-val');
          if (emailEl) emailEl.textContent = newEmail;
          if (billingEmailEl) billingEmailEl.textContent = newEmail;
          emailForm.reset();
          const details = emailForm.closest('details');
          if (details) details.open = false;
        }
      } catch (err) {
        if (emailError) emailError.textContent = 'Could not connect: ' + err.message;
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });

    if (pwCancel) pwCancel.addEventListener('click', () => {
      const details = pwCancel.closest('details');
      if (details) details.open = false;
    });

    if (pwForm) pwForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (pwError) pwError.textContent = '';
      const current = document.getElementById('settings-current-pw').value;
      const next    = document.getElementById('settings-new-pw').value;
      if (next.length < 8) {
        if (pwError) pwError.textContent = 'New password must be at least 8 characters.';
        return;
      }
      const token = localStorage.getItem('fluent_token');
      if (!token) { if (pwError) pwError.textContent = 'Not signed in.'; return; }
      const submitBtn = pwForm.querySelector('button[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await fetch(BACKEND_URL + '/auth/change-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
          body: JSON.stringify({ current_password: current, new_password: next }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          if (pwError) pwError.textContent = data.detail || 'Could not update password.';
        } else {
          pwForm.reset();
          const details = pwForm.closest('details');
          if (details) details.open = false;
        }
      } catch (err) {
        if (pwError) pwError.textContent = 'Could not connect: ' + err.message;
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });

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
      const token = localStorage.getItem('fluent_token');
      if (!token) { window.showOnboarding && window.showOnboarding(); return; }
      try {
        await fetch(BACKEND_URL + '/auth/delete-account', {
          method: 'DELETE',
          headers: { 'Authorization': 'Bearer ' + token },
        });
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

  // Reset controls when report arrives, then refresh sessions list
  const _origLoadReport = window.loadReport;
  window.loadReport = function(data) {
    setRecordingState(false);
    resetRecLabel();
    if (_origLoadReport) _origLoadReport(data);
    // Refresh sessions data in background without navigating away from the report
    const token = localStorage.getItem('fluent_token');
    if (token) {
      fetch(BACKEND_URL + '/sessions', { headers: { 'Authorization': 'Bearer ' + token } })
        .then(r => r.ok ? r.json() : [])
        .then(sessions => {
          // Only update the list if the report page is not currently visible
          const page = document.getElementById('page');
          if (!page || !page.classList.contains('visible')) {
            if (window.loadSessions) window.loadSessions(sessions);
          }
        })
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
