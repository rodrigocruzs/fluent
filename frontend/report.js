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

  // ── Build transcript with inline marks ───────────────────────────────────

  function buildTranscript(issues, transcriptText, segments) {
    // Underline phrases that became coaching patterns. No numbers, no margin
    // notes — the transcript is a calm record, not the focus of the page.
    const markFor = (original) =>
      `<mark class="flag">${esc(original)}</mark>`;

    // Speaker-labeled chronological turns when diarized segments exist.
    if (Array.isArray(segments) && segments.length) {
      return segments.map((seg) => {
        let text = esc(seg.text || '');
        // Only the user's ("You") turns carry inline anchors.
        if (seg.speaker === 'You') {
          issues.forEach((issue) => {
            const original = issue.original || '';
            if (!original || !(seg.text || '').includes(original)) return;
            text = text.replace(esc(original), () => markFor(original));
          });
        }
        const who = esc(seg.speaker || 'Speaker');
        const cls = seg.speaker === 'You' ? 'turn turn-you' : 'turn';
        return `<div class="${cls}"><span class="turn-speaker">${who}</span>` +
               `<p class="turn-text">${text}</p></div>`;
      }).join('\n');
    }

    // Flat fallback (old sessions, or no diarization). Escape first, then
    // insert anchors against the escaped text (mirrors the segments path).
    const rawText = transcriptText || '';
    let text = esc(rawText);
    issues.forEach((issue) => {
      const original = issue.original || '';
      if (!original || !rawText.includes(original)) return;
      text = text.replace(esc(original), () => markFor(original));
    });
    const paras = text.split(/\n\n+/).filter(p => p.trim());
    if (!paras.length) paras.push(text);
    return paras.map(p => `<p>${p}</p>`).join('\n');
  }

  // ── Coaching model ────────────────────────────────────────────────────────
  // Maps the flat issue list (category / original / improved / explanation)
  // into a richer coaching structure. Resilient to missing fields. Diagnosis
  // and "rule to remember" are generated client-side from the category when the
  // backend doesn't supply them.

  let MEETING_TYPES = [
    'Internal Team Meeting',
    '1:1 with Manager',
    'Candidate Interview',
    'Customer Call',
    'Technical Discussion',
    'Stakeholder Update',
    'Behavioral Interview',
    'Other',
  ];
  let DEFAULT_MEETING_TYPE = 'Internal Team Meeting';

  // Short, lower-cased phrase describing the setting, used inside "why this
  // matters" sentences ("In internal meetings, …").
  function meetingContext(type) {
    switch (type) {
      case '1:1 with Manager':    return 'in a 1:1 with your manager';
      case 'Candidate Interview': return 'in a candidate interview';
      case 'Customer Call':       return 'on a customer call';
      case 'Technical Discussion':return 'in a technical discussion';
      case 'Stakeholder Update':  return 'in a stakeholder update';
      case 'Behavioral Interview':return 'in a behavioral interview';
      case 'Other':               return 'in a professional conversation';
      default:                    return 'in internal meetings';
    }
  }

  // Per-category coaching scaffolding. DEFAULT covers anything unmapped.
  const CATEGORY_COACHING = {
    'Clarity': {
      diagnosis: 'You used wording that made your point less clear.',
      rule: 'Use the simplest natural business phrase that preserves the meaning.',
      why: 'unclear phrasing can make technical or commercial points harder for others to act on.',
    },
    'Confidence': {
      diagnosis: 'Your phrasing softened a point you could have stated plainly.',
      rule: 'State your view directly; drop hedges that weaken it.',
      why: 'tentative wording can make a solid point land as uncertain.',
    },
    'Directness': {
      diagnosis: 'You led with context before getting to the point.',
      rule: 'Answer first, then explain why.',
      why: 'burying the conclusion makes your point harder to follow.',
    },
    'Natural Business English': {
      diagnosis: 'A phrase came across as slightly unnatural for the setting.',
      rule: 'Prefer the phrasing a fluent colleague would naturally use.',
      why: 'unnatural phrasing can pull attention away from your message.',
    },
    'Professional Tone': {
      diagnosis: 'The tone was a little off for the moment.',
      rule: 'Match the level of formality the room expects.',
      why: 'tone shapes how seriously your point is taken.',
    },
    'Executive Communication': {
      diagnosis: 'The message could be tighter and more decisive.',
      rule: 'Lead with the decision or ask, then support it briefly.',
      why: 'senior audiences act faster on a crisp, decisive message.',
    },
    'DEFAULT': {
      diagnosis: 'There was a clearer, more natural way to make this point.',
      rule: 'Use the simplest natural business phrase that preserves the meaning.',
      why: 'clearer phrasing makes it easier for others to follow and act on your point.',
    },
  };

  function coachingFor(category) {
    return CATEGORY_COACHING[category] || CATEGORY_COACHING.DEFAULT;
  }

  // Per-category "biggest lesson" headline + description builder.
  const LESSON_BY_CATEGORY = {
    'Directness': {
      headline: 'Lead with the answer.',
      desc: (ctx) => `Several of your responses started with context before the conclusion. ${capFirst(ctx)}, this can make your point harder to follow. Try answering directly first, then explaining why.`,
    },
    'Clarity': {
      headline: 'Say it the simple way.',
      desc: (ctx) => `A few of your points were phrased in a way that took an extra beat to parse. ${capFirst(ctx)}, the simplest wording that keeps your meaning is usually the strongest. Aim for the clearest version first.`,
    },
    'Confidence': {
      headline: 'State it, don’t soften it.',
      desc: (ctx) => `You hedged a few points that you could have stated plainly. ${capFirst(ctx)}, confident, direct wording helps your ideas land. Make the claim, then back it up.`,
    },
    'DEFAULT': {
      headline: 'Make each point easier to act on.',
      desc: (ctx) => `A few moments could have been phrased more clearly. ${capFirst(ctx)}, small wording changes make it easier for others to follow and act on what you say.`,
    },
  };

  function capFirst(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  // Group issues by category to drive occurrence counts and the biggest lesson.
  function countByCategory(issues) {
    const counts = {};
    issues.forEach(i => {
      const c = i.category || 'Clarity';
      counts[c] = (counts[c] || 0) + 1;
    });
    return counts;
  }

  function topCategory(issues) {
    const counts = countByCategory(issues);
    let best = null, bestN = 0;
    Object.keys(counts).forEach(c => { if (counts[c] > bestN) { best = c; bestN = counts[c]; } });
    return best;
  }

  // ── Section renderers ─────────────────────────────────────────────────────

  function renderMeetingTypeSelector(current) {
    const opts = MEETING_TYPES.map(t =>
      `<option value="${esc(t)}"${t === current ? ' selected' : ''}>${esc(t)}</option>`
    ).join('');
    return `
      <div class="meeting-type">
        <span class="meeting-type-label">Coaching based on:</span>
        <span class="meeting-type-select-wrap">
          <select class="meeting-type-select" id="meeting-type-select" aria-label="Meeting type">${opts}</select>
          <span class="meeting-type-caret" aria-hidden="true"><svg width="9" height="6" viewBox="0 0 9 6" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M1 1l3.5 3.5L8 1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
        </span>
      </div>`;
  }

  // mode: 'coaching' (has improvement patterns), 'wentWell' (no issues but real
  // backend strengths to celebrate), 'clean' (a substantial meeting with nothing
  // to flag), or 'thin' (too little speech to coach — no praise).
  function renderHero(mode, meetingType) {
    if (mode === 'thin') {
      return `
      <div class="coaching-hero">
        <h2 class="coaching-hero-title">Not much to coach from this one.</h2>
        <p class="coaching-hero-sub" id="hero-sub">This recording was too short to pull out a meaningful communication pattern. Your next longer meeting will have more to work with.</p>
      </div>`;
    }
    if (mode === 'clean') {
      return `
      <div class="coaching-hero">
        <h2 class="coaching-hero-title">Nothing major to improve from this meeting.</h2>
        <p class="coaching-hero-sub" id="hero-sub">Your communication came across clearly — there wasn&rsquo;t a pattern worth flagging this time.</p>
      </div>`;
    }
    if (mode === 'wentWell') {
      return `
      <div class="coaching-hero">
        <h2 class="coaching-hero-title">Nothing major to improve from this meeting.</h2>
        <p class="coaching-hero-sub" id="hero-sub">A couple of things you did well are below.</p>
      </div>`;
    }
    return `
      <div class="coaching-hero">
        <h2 class="coaching-hero-title">Your biggest opportunities from this meeting</h2>
        <p class="coaching-hero-sub" id="hero-sub">Based on this being ${heroContext(meetingType)}.</p>
      </div>`;
  }

  // Count the user's own spoken words — from "You" diarized turns when present,
  // otherwise the flat transcript (single-speaker sessions). Used to tell a
  // genuinely thin recording apart from a substantial one that simply had no
  // issues to flag.
  function userWordCount(transcriptText, segments) {
    let text;
    if (Array.isArray(segments) && segments.length) {
      const youTurns = segments.filter(s => s.speaker === 'You');
      // If diarization ran but tagged no "You" turns, fall back to all turns.
      const turns = youTurns.length ? youTurns : segments;
      text = turns.map(s => s.text || '').join(' ');
    } else {
      text = transcriptText || '';
    }
    const words = text.trim().split(/\s+/).filter(Boolean);
    return words.length;
  }

  // Below this many of the user's own words, with no issues found, we treat the
  // session as too thin to coach (calm empty state, no fabricated strengths).
  const MIN_WORDS_TO_COACH = 25;

  // "an Internal Team Meeting" / "a Customer Call" with correct article.
  function heroContext(type) {
    const article = /^[AEIOU]/i.test(type) ? 'an' : 'a';
    return `${article} ${esc(type)}`;
  }

  function renderBiggestLesson(coaching, meetingType) {
    const { headline, desc } = coaching.lesson;
    return `
      <section class="lesson">
        <div class="lesson-eyebrow">Today’s biggest lesson</div>
        <h3 class="lesson-headline">${esc(headline)}</h3>
        <p class="lesson-desc" id="lesson-desc">${esc(desc(meetingContext(meetingType)))}</p>
      </section>`;
  }

  function renderPatterns(patterns, meetingType) {
    if (!patterns.length) return '';
    const items = patterns.map((p, idx) => renderPattern(p, idx, meetingType)).join('\n');
    return `<section class="patterns">${items}</section>`;
  }

  function renderPattern(p, idx, meetingType) {
    const c = coachingFor(p.category);
    const why = p.whyMatters
      ? esc(p.whyMatters)
      : `${capFirst(meetingContext(meetingType))}, ${esc(c.why)}`;
    const countLine = p.count > 1
      ? `<p class="pattern-count">Seen ${p.count} times today.</p>`
      : '';
    const tryThis = p.tryThis ? `
        <div class="pattern-block">
          <div class="pattern-block-label">Try this next time</div>
          <p class="pattern-try">${esc(p.tryThis)}</p>
        </div>` : '';
    const said = p.said ? `
        <div class="pattern-block">
          <div class="pattern-block-label">What you said</div>
          <p class="pattern-said">${esc(p.said)}</p>
        </div>` : '';
    return `
      <article class="pattern" data-why-template="${p.whyMatters ? '' : esc(c.why)}">
        <div class="pattern-category">${esc(p.category || 'Clarity')}</div>
        <p class="pattern-diagnosis">${esc(p.diagnosis || c.diagnosis)}</p>
        <div class="pattern-why">
          <span class="pattern-why-label">Why this matters</span>
          <span class="pattern-why-text" data-meeting-why="${p.whyMatters ? '0' : '1'}">${why}</span>
        </div>
        ${said}${tryThis}
        <p class="pattern-rule"><span class="pattern-rule-label">Rule to remember</span> ${esc(p.rule || c.rule)}</p>
        ${countLine}
      </article>`;
  }

  function renderStrengths(strengths) {
    if (!strengths.length) return '';
    const items = strengths.map(s =>
      `<li class="strength">${esc(s)}</li>`
    ).join('\n');
    return `
      <section class="strengths">
        <div class="strengths-eyebrow">What you did well</div>
        <ul class="strengths-list">${items}</ul>
      </section>`;
  }

  function renderTranscriptSection(transcriptHTML) {
    return `
      <section class="transcript-section">
        <button class="transcript-toggle" id="transcript-toggle" type="button" aria-expanded="false">
          <span class="transcript-toggle-arrow" aria-hidden="true">&rsaquo;</span>
          <span class="transcript-toggle-label">Show transcript</span>
        </button>
        <div class="transcript transcript-collapsed" id="transcript-body" hidden>
          ${transcriptHTML}
        </div>
      </section>`;
  }

  // Builds the full coaching model from raw data + the chosen meeting type.
  function buildCoaching(issues, data, meetingType) {
    const counts = countByCategory(issues);
    const patterns = issues.map(issue => {
      const category = issue.category || 'Clarity';
      const c = coachingFor(category);
      return {
        category,
        diagnosis: c.diagnosis,
        whyMatters: issue.explanation || '',
        said: issue.original || '',
        tryThis: issue.improved || issue.better_phrasing || '',
        rule: c.rule,
        count: counts[category] || 1,
      };
    });

    // Biggest lesson: backend-supplied, else synthesized from the top category.
    let lesson;
    if (data.biggest_lesson && data.biggest_lesson.headline) {
      const bl = data.biggest_lesson;
      lesson = {
        headline: bl.headline,
        desc: () => bl.description || '',
      };
    } else {
      const top = topCategory(issues) || 'DEFAULT';
      lesson = LESSON_BY_CATEGORY[top] || LESSON_BY_CATEGORY.DEFAULT;
    }

    // Strengths come only from the backend — we never fabricate praise. A
    // session with no real strengths data shows no "What you did well" section.
    const strengths = (Array.isArray(data.strengths) && data.strengths.length)
      ? data.strengths.slice(0, 3)
      : [];

    return { patterns, lesson, strengths };
  }

  // Meeting type comes from the backend session record. No localStorage.
  function meetingTypeForSlug(slug, backendType) {
    return (backendType && MEETING_TYPES.includes(backendType))
      ? backendType : DEFAULT_MEETING_TYPE;
  }

  function getMeetingType(data) {
    return meetingTypeForSlug(data.slug || '', data.meeting_type);
  }

  // Persist a session-page meeting-type change to the backend.
  function saveMeetingType(slug, type) {
    if (!slug) return;
    apiFetch('/sessions/' + encodeURIComponent(slug), {
      method: 'PATCH',
      body: { meeting_type: type },
    }).catch(() => {});
  }

  // A read-only meeting-type chip for History rows. Once a meeting has happened
  // its type is fixed from the home page — the user changes it on the session
  // page instead. Looks like the editable chip but is static (no caret, no
  // pointer, not focusable).
  function renderMeetingTypeStatic(current) {
    return `<span class="session-type"><span class="session-type-static">${esc(current)}</span></span>`;
  }

  // ── Coming Up meeting type ────────────────────────────────────────────────
  // Calendar events have no session slug yet, so their chosen type is stored
  // per calendar event id. (Threading this through to the recorded session's
  // slug is a follow-up — see TODO in renderUpNext.)
  function upnextTypeKey(eventId) { return 'fluent_upnext_type_' + (eventId || 'unknown'); }

  function upnextTypeForEvent(eventId) {
    try {
      const saved = localStorage.getItem(upnextTypeKey(eventId));
      if (saved && MEETING_TYPES.includes(saved)) return saved;
    } catch (_) {}
    return DEFAULT_MEETING_TYPE;
  }

  function saveUpnextType(eventId, type) {
    try { localStorage.setItem(upnextTypeKey(eventId), type); } catch (_) {}
  }

  // Editable type chip for a Coming Up row, keyed by calendar event id.
  function renderUpnextTypeChip(eventId, current) {
    const opts = MEETING_TYPES.map(t =>
      `<option value="${esc(t)}"${t === current ? ' selected' : ''}>${esc(t)}</option>`
    ).join('');
    return `
      <span class="session-type">
        <select class="upnext-type-select" data-event-id="${esc(eventId)}" aria-label="Meeting type">${opts}</select>
        <span class="session-type-caret" aria-hidden="true"><svg width="8" height="5" viewBox="0 0 9 6" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M1 1l3.5 3.5L8 1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
      </span>`;
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

  // ── Communication Profile ─────────────────────────────────────────────────
  // A calm coaching summary shown above Coming Up. The profile is generated by
  // the backend from real meeting analysis (GET /profile) and regenerated after
  // each new session. Until the first meeting is analysed there is no profile,
  // so we show an honest empty state rather than inventing strengths.

  // Canonical type → description. Used to fill in the description if the backend
  // returns a known type without one. These are the only valid profile types.
  const PROFILE_DESCRIPTIONS = {
    'Clear Explainer':        'You’re good at making complex ideas easier to understand.',
    'Thoughtful Collaborator':'You build on others’ ideas and create space for discussion.',
    'Strategic Communicator': 'You connect details to priorities, risks and business outcomes.',
    'Direct Decision-Maker':  'You communicate recommendations clearly and get to the point quickly.',
    'Diplomatic Challenger':  'You challenge ideas constructively without sounding aggressive.',
    'Confident Presenter':    'You speak with structure, presence and conviction.',
    'Developing Communicator':'You’re still building consistency across clarity, confidence and structure.',
  };

  // A profile is "real" only when the backend has a type plus at least one
  // strength or opportunity to show. Anything less → empty state.
  function _hasProfile(p) {
    if (!p || typeof p !== 'object' || !p.type) return false;
    const hasStrengths = Array.isArray(p.strengths) && p.strengths.length > 0;
    const hasOpps      = Array.isArray(p.opportunities) && p.opportunities.length > 0;
    return hasStrengths || hasOpps;
  }

  // Last profile we rendered, so showSessions() can re-render without refetching.
  let _lastProfile = null;

  // Render the profile section in one of three states: filled (a real profile),
  // loading (opts.loading — generation in flight), or the empty "created after
  // your first meeting" message. Pass `profile` to update the cached value;
  // pass undefined to re-render the last known state (e.g. on page re-entry).
  function renderCommunicationProfile(profile, opts) {
    opts = opts || {};
    const section  = document.getElementById('profile-section');
    const emptyEl  = document.getElementById('profile-empty');
    const loadEl   = document.getElementById('profile-loading');
    const bodyEl   = document.getElementById('profile-body');
    if (!section || !emptyEl || !bodyEl) return;

    if (profile !== undefined) _lastProfile = profile;
    const p = _lastProfile;

    section.style.display = '';

    if (_hasProfile(p)) {
      emptyEl.style.display = 'none';
      if (loadEl) loadEl.style.display = 'none';
      bodyEl.style.display  = '';

      const typeEl = document.getElementById('profile-type');
      const descEl = document.getElementById('profile-description');
      if (typeEl) typeEl.textContent = p.type;
      if (descEl) descEl.textContent = p.description || PROFILE_DESCRIPTIONS[p.type] || '';

      const bullets = (items) => (Array.isArray(items) ? items : []).slice(0, 3)
        .map(t => `<li>${esc(t)}</li>`).join('');
      const strengthsEl = document.getElementById('profile-strengths');
      const oppsEl      = document.getElementById('profile-opportunities');
      if (strengthsEl) strengthsEl.innerHTML = bullets(p.strengths);
      if (oppsEl)      oppsEl.innerHTML      = bullets(p.opportunities);
      return;
    }

    bodyEl.style.display = 'none';
    if (opts.loading && loadEl) {
      // Generation is in flight (e.g. first load for a user with history) —
      // show "Building your profile…" instead of the first-meeting message.
      emptyEl.style.display = 'none';
      loadEl.style.display  = '';
    } else {
      // No analysed meetings yet — show the "created after your first meeting"
      // message instead of fabricated coaching.
      if (loadEl) loadEl.style.display = 'none';
      emptyEl.style.display = '';
    }
  }

  // Hydrate the meeting-type list from the backend (single source of truth).
  // Falls back to the built-in list if the call fails.
  function loadMeetingTypes(token) {
    token = token || _token();
    if (!token) return;
    apiFetch('/meeting-types')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && Array.isArray(data.types) && data.types.length) {
          MEETING_TYPES = data.types;
          if (data.default) DEFAULT_MEETING_TYPE = data.default;
        }
      })
      .catch(() => {});
  }

  // Fetch the profile from the backend (web/Windows path). On Mac, Swift injects
  // it through loadSessions instead, since the file:// webview can't fetch.
  // `hasSessions` lets us show "Building your profile…" while the backend
  // generates one on-demand for a user who already has meetings, rather than
  // flashing the empty "first meeting" message.
  function loadProfile(token, hasSessions) {
    token = token || _token();
    if (!token) return;
    // Only show the loading state when we don't already have a profile and the
    // user has history to build one from.
    if (hasSessions && !_hasProfile(_lastProfile)) {
      renderCommunicationProfile(undefined, { loading: true });
    }
    apiFetch('/profile')
      .then(r => r.ok ? r.json() : null)
      .then(profile => renderCommunicationProfile(profile || null))
      .catch(() => renderCommunicationProfile(_lastProfile));
  }

  window.loadSessions = function (sessions, upNext, profile) {
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

    // Swift passes the profile through; the web path fetches it itself.
    if (profile !== undefined) {
      renderCommunicationProfile(profile);
    } else {
      const hasSessions = Array.isArray(sessions) && sessions.length > 0;
      renderCommunicationProfile(null);  // honest default until /profile responds
      loadMeetingTypes(_token());
      loadProfile(_token(), hasSessions);
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
    if (!listEl) return;

    if (!sessions || sessions.length === 0) {
      listEl.innerHTML = '';
      return;
    }

    listEl.innerHTML = '';

    sessions.forEach(session => {
      const n = session.issue_count || 0;
      const countLabel = n === 0 ? 'No suggestions' : n === 1 ? '1 suggestion' : `${n} suggestions`;
      const dur = session.duration ? durationStr(session.duration) : '';
      const dateLabel = formatSessionDate(session.slug || session.date || '');
      const name = session.name || formatSessionName(session.slug || session.date || '');
      const slug = session.slug || session.date || '';
      const meetingType = meetingTypeForSlug(slug, session.meeting_type);

      // Row is a div (not a button) so it can hold an interactive <select>.
      const row = document.createElement('div');
      row.className = 'session';
      row.setAttribute('role', 'button');
      row.setAttribute('tabindex', '0');
      // History rows are past meetings: the type is shown read-only here and
      // can only be changed on the session page.
      row.innerHTML = `
        <span class="session-name">${esc(name)}</span>
        ${renderMeetingTypeStatic(meetingType)}
        <span class="session-date">${esc(dateLabel)}</span>
        <span class="session-duration">${esc(dur)}</span>
        <span class="session-count${n > 0 ? ' has-suggestions' : ''}">${esc(countLabel)}</span>
        <span class="session-chevron" aria-hidden="true">&rsaquo;</span>`;

      const open = () => {
        console.log('[Fluent] session clicked:', session.slug, 'data:', !!session.data);
        if (session.data) {
          window.loadReport(session.data);
          return;
        }
        const s = session.slug || session.date;
        if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.openSession) {
          window.webkit.messageHandlers.openSession.postMessage(s);
        } else {
          const token = _token();
          if (!token) return;
          const url = BACKEND_URL + '/sessions/' + encodeURIComponent(s);
          fetch(url, { headers: { 'Authorization': 'Bearer ' + token } })
            .then(r => r.ok ? r.json() : null)
            .then(data => { if (data) window.loadReport(data); })
            .catch(e => { console.error('[Fluent] fetch error:', e); });
        }
      };

      row.addEventListener('click', open);
      row.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });

      listEl.appendChild(row);
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

    const meetingType = getMeetingType(data);

    let body;
    if (!hasTranscript) {
      // Nothing was captured — don't pretend to grade silence. Unchanged.
      body = `
  <div class="no-transcript">
    <div class="no-transcript-eyebrow">No transcript</div>
    <h2 class="no-transcript-title">Nothing was transcribed in this session.</h2>
    <p class="no-transcript-body">The recording ran for ${esc(durationLong(duration))} &mdash; too short to capture any speech, or no one spoke. There&rsquo;s nothing to review here.</p>
    <p class="no-transcript-hint">If you expected feedback, check your microphone and make sure recording continues while you&rsquo;re speaking.</p>
  </div>`;
    } else {
      const hasIssues = issues.length > 0;
      const coaching  = buildCoaching(issues, data, meetingType);

      // Pick a hero mode:
      //  - coaching: we found improvement patterns.
      //  - wentWell: no issues, but the backend gave real strengths to show.
      //  - clean:    no issues, no strengths data, but the user spoke enough
      //              that "nothing to flag" is a genuine compliment.
      //  - thin:     no issues and barely any of the user's own speech — a very
      //              short recording. Calm empty state, no invented praise.
      let mode;
      if (hasIssues) {
        mode = 'coaching';
      } else if (coaching.strengths.length) {
        mode = 'wentWell';
      } else if (userWordCount(transcript, segments) >= MIN_WORDS_TO_COACH) {
        mode = 'clean';
      } else {
        mode = 'thin';
      }

      const captureNotice = (!systemCaptured && segments.length === 0)
        ? '<p class="capture-notice">Only your microphone was captured this session — other participants weren&rsquo;t recorded.</p>'
        : '';
      const transcriptHTML = captureNotice + buildTranscript(issues, transcript, segments);

      const lessonHTML   = hasIssues ? renderBiggestLesson(coaching, meetingType) : '';
      const patternsHTML = hasIssues ? renderPatterns(coaching.patterns, meetingType) : '';

      body = `
  ${renderHero(mode, meetingType)}
  ${lessonHTML}
  ${patternsHTML}
  ${renderStrengths(coaching.strengths)}
  ${renderTranscriptSection(transcriptHTML)}`;
    }

    page.innerHTML = `
  <header class="report-masthead">
    <button class="back-link" onclick="window.showSessions && window.showSessions()"><span class="arrow">&larr;</span> Sessions</button>
    <h1 class="report-title">${esc(title)}</h1>
    <div class="session-meta">${metaParts.join(' &middot; ')}</div>
    ${renderMeetingTypeSelector(meetingType)}
  </header>
  ${body}`;

    page.classList.add('visible');

    // Stash what live re-rendering needs (meeting-type changes update hero,
    // lesson, and pattern "why this matters" without a full reload).
    _reportState = { slug, issues, data };

    requestAnimationFrame(() => {
      wireMeetingTypeSelector();
      wireTranscriptToggle();
    });
  };

  // ── Live meeting-type wiring ──────────────────────────────────────────────

  let _reportState = null;

  function wireMeetingTypeSelector() {
    const sel = document.getElementById('meeting-type-select');
    if (!sel) return;
    sel.addEventListener('change', () => {
      const type = sel.value;
      if (_reportState) saveMeetingType(_reportState.slug, type);
      rerenderMeetingTypeDependent(type);
    });
  }

  // Re-render only the parts that name the meeting type, in place.
  function rerenderMeetingTypeDependent(type) {
    if (!_reportState) return;
    const { issues, data } = _reportState;

    const sub = document.getElementById('hero-sub');
    if (sub && issues.length) sub.innerHTML = `Based on this being ${heroContext(type)}.`;

    const lessonDesc = document.getElementById('lesson-desc');
    if (lessonDesc && issues.length) {
      const coaching = buildCoaching(issues, data, type);
      lessonDesc.textContent = coaching.lesson.desc(meetingContext(type));
    }

    // Each pattern's "why this matters" — only the generated ones (no backend
    // explanation), which begin with the meeting context.
    document.querySelectorAll('.pattern').forEach(el => {
      const whyEl = el.querySelector('.pattern-why-text');
      if (!whyEl || whyEl.dataset.meetingWhy !== '1') return;
      const tmpl = el.dataset.whyTemplate || '';
      whyEl.textContent = `${capFirst(meetingContext(type))}, ${tmpl}`;
    });
  }

  function wireTranscriptToggle() {
    const btn  = document.getElementById('transcript-toggle');
    const body = document.getElementById('transcript-body');
    if (!btn || !body) return;
    btn.addEventListener('click', () => {
      const expanded = btn.getAttribute('aria-expanded') === 'true';
      const next = !expanded;
      btn.setAttribute('aria-expanded', String(next));
      btn.classList.toggle('is-open', next);
      body.hidden = !next;
      btn.querySelector('.transcript-toggle-label').textContent =
        next ? 'Hide transcript' : 'Show transcript';
    });
  }

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
      const eventId  = ev.id || '';
      const type     = upnextTypeForEvent(eventId);
      return `<div class="session upnext-row">
        <span class="session-name">${esc(ev.title)}</span>
        ${renderUpnextTypeChip(eventId, type)}
        <span class="session-date upnext-time">${dayLabel}${esc(time)}</span>
        <button class="upnext-record-btn" type="button">
          <span class="dot"></span>Start recording
        </button>
      </div>`;
    }).join('');

    list.querySelectorAll('.upnext-record-btn').forEach((btn, i) => {
      const title   = events[i] && events[i].title ? events[i].title : 'Recording';
      const eventId = events[i] && events[i].id ? events[i].id : '';
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        // Carry the chosen meeting type into the recording so it lands on the
        // saved session (shown on the session page / History afterwards).
        openRecordingPage(title, upnextTypeForEvent(eventId));
      });
    });

    // Editable meeting-type chip per Coming Up event (these meetings haven't
    // happened yet, so the user can still set how they'll be coached).
    list.querySelectorAll('.upnext-type-select').forEach(select => {
      ['click', 'mousedown', 'keydown'].forEach(evt =>
        select.addEventListener(evt, e => e.stopPropagation()));
      select.addEventListener('change', e => {
        e.stopPropagation();
        saveUpnextType(select.dataset.eventId, select.value);
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
    renderCommunicationProfile();  // re-render last known profile

    // Re-fetch the History list every time we open it, so sessions recorded
    // while a report was on screen still appear (the post-recording refresh in
    // loadReport is skipped while the report page is visible). We also use the
    // count to decide whether to show "Building your profile…" while /profile
    // is generated on-demand for a user who already has meetings.
    const token = _token();
    if (token) {
      apiFetch('/sessions')
        .then(r => r.ok ? r.json() : null)
        .then(sessions => {
          if (sessions) renderSessionsList(sessions);
          const hasSessions = Array.isArray(sessions) && sessions.length > 0;
          loadProfile(token, hasSessions);  // refresh in case a meeting changed it
        })
        .catch(() => loadProfile(token));
    } else {
      loadProfile();
    }
  };

  // Open the dedicated recording page for a "Coming up" meeting and start recording.
  window.openRecordingPage = function (title, meetingType) {
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

    // Remember the meeting title + type so the created session keeps them.
    _sessionName = title || null;
    _sessionType = (meetingType && MEETING_TYPES.includes(meetingType)) ? meetingType : null;

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


  // ── Recording controls ────────────────────────────────────────────────────

  const ENGINE_URL = 'http://127.0.0.1:2788';
  let _recording = false;
  let _polling = null;
  let _timerHandle = null;
  let _startedAt = null;
  // Title of the meeting being recorded (from a "Coming up" row), so the
  // created session keeps that name instead of a generic "Morning session".
  let _sessionName = null;
  // Meeting type chosen on the "Coming up" row, carried into the saved session
  // so it shows on the session page / History (null = let the user set it later).
  let _sessionType = null;

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
    const body = {};
    if (_sessionName) body.session_name = _sessionName;
    if (_sessionType) body.meeting_type = _sessionType;
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
    _sessionType = null;
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
          _sessionType = null;
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
