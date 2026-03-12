// RENATA Frontend Logic
const API_BASE = window.location.origin;

// Helper for API calls
async function apiFetch(endpoint, options = {}) {
    const headers = {
        'ngrok-skip-browser-warning': 'true',
        ...options.headers
    };
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers,
        credentials: 'include'
    });

    if (response.status === 401) {
        window.location.href = "/login";
        return;
    }

    return response;
}

document.addEventListener('DOMContentLoaded', () => {
    feather.replace();

    // Navigation Logic
    const navItems = document.querySelectorAll('.nav-item');
    const pages = document.querySelectorAll('.page');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetPage = item.getAttribute('data-page');
            window.location.hash = targetPage;
            showPage(targetPage);
        });
    });

    function showPage(pageId) {
        if (!pageId) pageId = 'dashboard';

        navItems.forEach(i => {
            i.classList.toggle('active', i.getAttribute('data-page') === pageId);
        });

        const targetElement = document.getElementById(`${pageId}-page`);
        if (targetElement) {
            pages.forEach(p => p.classList.remove('active'));
            targetElement.classList.add('active');
            loadPageData(pageId);
        }
    }

    const initialPage = window.location.hash.replace('#', '') || 'dashboard';
    showPage(initialPage);

    window.addEventListener('hashchange', () => {
        const newPage = window.location.hash.replace('#', '') || 'dashboard';
        showPage(newPage);
    });

    // --- DATA LOADING LOGIC ---

    async function loadPageData(page) {
        switch (page) {
            case 'dashboard':
                await loadDashboardData();
                break;
            case 'reports':
                await loadReportsData();
                break;
            case 'analytics':
                await loadAnalyticsData();
                startAnalyticsAutoRefresh();
                break;
            case 'search':
                await loadSearchStats();
                await loadChatSessions();
                break;
            case 'live':
                await loadLiveStatus();
                break;
            case 'settings':
            case 'integrations':
                await loadIntegrationsData();
                await loadDashboardData();
                break;
        }
    }

    async function loadDashboardData() {
        try {
            const res = await apiFetch("/dashboard_data");
            const data = await res.json();

            // Profile
            if (data.user) {
                const userNameEl = document.querySelector('.user-name');
                const userAvatarEl = document.querySelector('.avatar');
                if (userNameEl) userNameEl.textContent = data.user.name;
                if (userAvatarEl && data.user.picture) userAvatarEl.src = data.user.picture;
                
                const pName = document.getElementById('pref-user-name');
                const pEmail = document.getElementById('pref-user-email');
                if (pName) pName.value = data.user.name;
                if (pEmail) pEmail.value = data.user.email;
            }

            // Dashboard Stats
            const statsArr = document.querySelectorAll('#dashboard-page .stat-value');
            if (data.stats && statsArr.length >= 4) {
                statsArr[0].textContent = data.stats.total_meetings || 0;
                statsArr[1].textContent = (data.stats.total_duration_hours || 0).toFixed(1) + 'h';
                statsArr[2].textContent = data.stats.action_items_count || 0;
                statsArr[3].textContent = (data.stats.participant_count || 0).toFixed(1);
            }

            // Recent Reports List (PDFs only)
            const recentList = document.getElementById('recent-list');
            if (recentList) {
                recentList.innerHTML = '';
                const recentPdfs = (data.recent_meetings || []).filter(m => m.pdf_path).slice(0, 5);
                
                if (recentPdfs.length === 0) {
                    recentList.innerHTML = '<p class="muted" style="padding:10px;">No reports generated yet.</p>';
                } else {
                    recentPdfs.forEach(m => {
                        const item = document.createElement('div');
                        item.className = 'list-item';
                        item.innerHTML = `
                            <div class="item-icon"><i data-feather="file-text"></i></div>
                            <div class="item-details">
                                <span class="item-title">${m.title || 'Meeting Report'}</span>
                                <span class="item-meta">Generated ${timeAgo(m.updated_at || m.created_at)}</span>
                            </div>
                            <div class="item-actions">
                                <button class="btn-sm primary-btn" onclick="window.location.hash='#reports'">View</button>
                            </div>
                        `;
                        recentList.appendChild(item);
                    });
                }
            }

            // Calendar
            const calendarGrid = document.getElementById('calendar-grid');
            if (calendarGrid) {
                calendarGrid.innerHTML = '';
                if ((data.events || []).length === 0) {
                    calendarGrid.innerHTML = '<p class="muted" style="padding:20px;">No upcoming meetings found in your calendar.</p>';
                } else {
                    data.events.forEach(ev => {
                        const card = document.createElement('div');
                        card.className = 'meeting-card';
                        card.innerHTML = `
                            <div class="meeting-card-top">
                                <span class="status-badge">Calendar</span>
                                <span class="meeting-time">${ev.start_time}</span>
                            </div>
                            <div class="meeting-title">${ev.summary}</div>
                            <div class="meeting-actions">
                                <button class="btn-sm primary-btn" onclick="dispatchRenata('${ev.link}')">Dispatch Renata</button>
                            </div>
                        `;
                        calendarGrid.appendChild(card);
                    });
                }
            }

            // Preferences
            if (data.preferences) {
                const bName = document.getElementById('pref-bot-name');
                const aj = document.getElementById('pref-auto-join');
                const rec = document.getElementById('pref-recording');
                if (bName) bName.value = data.preferences.bot_name;
                if (aj) aj.checked = data.preferences.auto_join;
                if (rec) rec.checked = data.preferences.recording;
            }

            feather.replace();
        } catch (err) { console.error(err); }
    }

    function timeAgo(date) {
        if (!date) return "recently";
        const d = typeof date === 'string' ? new Date(date.replace(' ', 'T')) : new Date(date);
        if (isNaN(d.getTime())) return "recently";
        
        const seconds = Math.floor((new Date() - d) / 1000);
        if (seconds < 60) return "just now";
        let interval = seconds / 31536000;
        if (interval > 1) return Math.floor(interval) + " years ago";
        interval = seconds / 2592000;
        if (interval > 1) return Math.floor(interval) + " months ago";
        interval = seconds / 86400;
        if (interval > 1) return Math.floor(interval) + " days ago";
        interval = seconds / 3600;
        if (interval > 1) return Math.floor(interval) + " hours ago";
        interval = seconds / 60;
        if (interval > 1) return Math.floor(interval) + " minutes ago";
        return Math.floor(seconds) + " seconds ago";
    }

    async function loadReportsData() {
        const refreshIcon = document.querySelector('#refresh-reports-btn i');
        if (refreshIcon) refreshIcon.classList.add('spin');

        try {
            const res = await apiFetch("/reports_data");
            const data = await res.json();
            const grid = document.getElementById('reports-grid');
            if (!grid) return;
            grid.innerHTML = '';

            // Filter only meetings that have a PDF generated
            const pdfMeetings = (data.meetings || []).filter(m => m.pdf_path);

            if (pdfMeetings.length === 0) {
                grid.innerHTML = '<div class="card" style="grid-column: 1/-1; padding:40px; text-align:center;"><p class="muted">No reports generated yet. Reports will appear here once meeting processing is complete.</p></div>';
                if (refreshIcon) refreshIcon.classList.remove('spin');
                return;
            }

            pdfMeetings.forEach((m, index) => {
                const pdfName = m.pdf_path.split(/[\\/]/).pop();
                const pdfLink = `${API_BASE}/download/pdf/${pdfName}`;
                const generatedTime = timeAgo(m.updated_at || m.created_at);
                
                const card = document.createElement('div');
                card.className = 'report-card';
                card.style.display = 'flex';
                card.style.alignItems = 'center';
                card.style.justifyContent = 'space-between';
                card.style.padding = '20px';
                
                card.innerHTML = `
                    <div style="display:flex; align-items:center; gap:20px;">
                        <div class="report-number" style="font-size: 1.2rem; font-weight: 800; color: var(--accent-purple); opacity: 0.5;">#${pdfMeetings.length - index}</div>
                        <div>
                            <h3 class="report-title" style="margin:0; font-size:1.1rem;">${m.title || 'Meeting Report'}</h3>
                            <span class="muted" style="font-size:0.85rem;">Generated ${generatedTime}</span>
                        </div>
                    </div>
                    <div style="display:flex; gap:12px; align-items:center;">
                        <a href="${pdfLink}" target="_blank" class="primary-btn" style="text-decoration:none; padding: 10px 20px;">
                            <i data-feather="file-text" style="width:16px; margin-right:8px;"></i> View PDF
                        </a>
                        <button class="delete-btn" onclick="deleteReport('${m.meeting_id}')" title="Delete Permanentely">
                            <i data-feather="trash-2" style="width:16px;"></i>
                        </button>
                    </div>
                `;
                grid.appendChild(card);
            });
            feather.replace();
        } catch (err) { 
            console.error(err); 
        } finally {
            if (refreshIcon) {
                // Keep spinning for at least 500ms for visual feedback
                setTimeout(() => refreshIcon.classList.remove('spin'), 500);
            }
        }
    }

    window.deleteReport = async function(mId) {
        if (!confirm("Are you sure? This will permanently delete the PDF and all meeting data from the database.")) return;
        try {
            const res = await apiFetch(`/reports/${mId}`, { method: 'DELETE' });
            if (res.ok) {
                loadReportsData();
                loadAnalyticsData(); // Update stats since meeting deleted
            } else {
                alert("Failed to delete report.");
            }
        } catch (err) {
            console.error(err);
        }
    }

    async function loadAnalyticsData() {
        try {
            const res = await apiFetch("/analytics/data");
            const stats = await res.json();

            const mVal = document.getElementById('ana-total-meetings');
            const rVal = document.getElementById('ana-total-reports');
            const eVal = document.getElementById('ana-total-engagement');
            const uVal = document.getElementById('ana-upcoming');

            if (mVal) mVal.textContent = stats.total_meetings || 0;
            if (rVal) rVal.textContent = stats.total_reports || 0;
            if (eVal) eVal.textContent = (stats.engagement_score || 0) + '%';
            if (uVal) uVal.textContent = stats.upcoming_count || 0;

            // Analytics Trends Chart (Dynamic)
            const ctx = document.getElementById('analyticsChart')?.getContext('2d');
            if (ctx) {
                if (window.anaChartInstance) window.anaChartInstance.destroy();
                window.anaChartInstance = new Chart(ctx, {
                    type: 'bar', // Better for daily activity
                    data: {
                        labels: stats.chart_labels,
                        datasets: [{
                            label: 'Daily Engagement',
                            data: stats.chart_data,
                            backgroundColor: 'rgba(242, 113, 33, 0.7)',
                            borderColor: '#f27121',
                            borderWidth: 1,
                            borderRadius: 6
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { 
                            legend: { display: false },
                            tooltip: {
                                backgroundColor: '#1e293b',
                                titleColor: '#fff',
                                bodyColor: '#cbd5e1',
                                borderColor: 'rgba(255,255,255,0.1)',
                                borderWidth: 1
                            }
                        },
                        scales: { 
                            y: { 
                                beginAtZero: true, 
                                max: 100,
                                grid: { color: 'rgba(255,255,255,0.05)' },
                                ticks: { color: '#94a3b8' }
                            },
                            x: {
                                grid: { display: false },
                                ticks: { color: '#94a3b8' }
                            }
                        }
                    }
                });
            }
        } catch (err) { console.error("Analytics Error:", err); }
    }

    let analyticsInterval = null;
    function startAnalyticsAutoRefresh() {
        if (analyticsInterval) clearInterval(analyticsInterval);
        analyticsInterval = setInterval(() => {
            if (window.location.hash === '#analytics') {
                loadAnalyticsData();
            } else {
                clearInterval(analyticsInterval);
                analyticsInterval = null;
            }
        }, 30000); // 30 seconds
    }

    async function loadSearchStats() {
        try {
            const res = await apiFetch("/search/status");
            const data = await res.json();
            const pc = document.getElementById("report-count");
            if (pc) pc.textContent = (data.pdf_count || 0) + " Reports";
        } catch (err) { }
    }

    // --- CHAT SESSION LOGIC ---
    let currentSessionId = localStorage.getItem('renata_chat_session');

    async function loadChatSessions() {
        try {
            const res = await apiFetch("/chat/sessions");
            const data = await res.json();
            const list = document.getElementById('chat-session-list');
            if (!list) return;

            list.innerHTML = '';
            if (!data.sessions || data.sessions.length === 0) {
                list.innerHTML = '<div class="history-item empty">No history yet</div>';
                return;
            }

            // Persistence: If no currentSessionId is set, pick the most recent
            if (!currentSessionId && data.sessions.length > 0) {
                currentSessionId = data.sessions[0].session_id;
                localStorage.setItem('renata_chat_session', currentSessionId);
            }

            data.sessions.forEach(s => {
                const item = document.createElement('div');
                item.className = `history-item ${s.session_id === currentSessionId ? 'active' : ''}`;
                item.setAttribute('data-session', s.session_id);
                item.innerHTML = `<i data-feather="message-square"></i> <span>${s.title || 'Conversation'}</span>`;
                item.onclick = () => selectSession(s.session_id);
                list.appendChild(item);
            });

            // Auto-load messages for current session if not already loaded
            if (currentSessionId && document.getElementById('chat-box')?.children.length <= 1) {
                selectSession(currentSessionId);
            }

            feather.replace();
        } catch (err) { console.error(err); }
    }

    async function selectSession(sessionId) {
        currentSessionId = sessionId;
        localStorage.setItem('renata_chat_session', sessionId);
        document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
        const activeItem = document.querySelector(`.history-item[data-session="${sessionId}"]`);
        if (activeItem) activeItem.classList.add('active');

        // Load messages
        try {
            const res = await apiFetch(`/chat/sessions/${sessionId}/messages`);
            const data = await res.json();
            const box = document.getElementById('chat-box');
            if (!box) return;

            box.innerHTML = '';
            if (!data.messages || data.messages.length === 0) {
                box.innerHTML = '<div class="message assistant"><p>How can I help you with your meeting reports today?</p></div>';
            } else {
                data.messages.forEach(m => {
                    const msgDiv = document.createElement('div');
                    msgDiv.className = `message ${m.role}`;
                    msgDiv.innerHTML = `<p>${m.content}</p>`;
                    box.appendChild(msgDiv);
                });
            }
            box.scrollTop = box.scrollHeight;
        } catch (err) { console.error(err); }
        loadChatSessions(); // Update UI
    }

    async function createNewChat() {
        try {
            const res = await apiFetch("/chat/sessions", { method: 'POST' });
            const data = await res.json();
            currentSessionId = data.session_id;
            localStorage.setItem('renata_chat_session', currentSessionId);
            const box = document.getElementById('chat-box');
            if (box) {
                box.innerHTML = '<div class="message assistant"><p>Started a new conversation. Ask me anything about your reports!</p></div>';
            }
            loadChatSessions();
        } catch (err) { console.error(err); }
    }

    const newChatBtn = document.getElementById('new-chat-sidebar-btn');
    if (newChatBtn) newChatBtn.onclick = createNewChat;

    // ─── Timer for live call duration ───
    let _liveTimerInterval = null;
    let _liveStartTs = null;

    function _startLiveTimer() {
        if (_liveTimerInterval) return; // already running
        _liveStartTs = Date.now();
        const el = document.getElementById('bot-live-timer');
        if (el) el.style.display = 'block';
        _liveTimerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - _liveStartTs) / 1000);
            const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
            const s = String(elapsed % 60).padStart(2, '0');
            const el2 = document.getElementById('bot-live-timer');
            if (el2) el2.textContent = `● ${m}:${s}`;
        }, 1000);
    }

    function _stopLiveTimer() {
        if (_liveTimerInterval) { clearInterval(_liveTimerInterval); _liveTimerInterval = null; }
        const el = document.getElementById('bot-live-timer');
        if (el) el.style.display = 'none';
    }

    // ─── Phase helpers ───
    const PHASES = ['dispatching','navigating','lobby','live','processing'];

    function _setPhase(activePhase, completeUpTo) {
        PHASES.forEach((ph, idx) => {
            const el = document.getElementById(`phase-${ph}`);
            if (!el) return;
            el.classList.remove('active','complete');
            if (completeUpTo !== undefined && idx < completeUpTo) el.classList.add('complete');
            else if (ph === activePhase) el.classList.add('active');
        });
    }

    function _setLog(msg) {
        const el = document.getElementById('bot-log-text');
        if (el) el.innerHTML = '» ' + msg;
    }

    function _setProgress(pct, label) {
        const bar = document.getElementById('live-progress-bar');
        const lbl = document.getElementById('progress-label');
        const pct_el = document.getElementById('progress-percent');
        if (bar) bar.style.width = pct + '%';
        if (lbl) lbl.textContent = label || '';
        if (pct_el) pct_el.textContent = pct + '%';
    }

    function _setBadge(text, color) {
        const el = document.getElementById('bot-status-badge');
        if (el) { el.textContent = text; el.style.color = color || 'var(--text-secondary)'; }
    }

    function showBotActive(status, note) {
        const idle = document.getElementById('bot-idle-msg');
        const tracker = document.getElementById('bot-tracker');
        const pulse = document.getElementById('bot-pulse');

        if (idle) idle.style.display = 'none';
        if (tracker) tracker.style.display = 'block';

        const logMsg = note || status;

        if (status === 'JOIN_PENDING' || status === 'DISPATCHING') {
            pulse.style.background = '#f27121'; pulse.style.animation = 'pulse 1.5s infinite';
            _setPhase('dispatching', 0); _setProgress(12, 'Sending request to bot pilot...'); _setBadge('Dispatching…', '#f27121');
            _setLog('Request queued — waiting for bot pilot to pick up the job...');
            _stopLiveTimer();
        } else if (status === 'JOINING' || status === 'FETCHING') {
            pulse.style.background = '#f27121';
            _setPhase('navigating', 1); _setProgress(35, 'Bot is launching browser...'); _setBadge('Launching Browser', '#f27121');
            _setLog(logMsg || 'Playwright browser is starting and navigating to the meeting URL...');
            _stopLiveTimer();
        } else if (status === 'CONNECTING' || status.includes('LOBBY') || status.includes('LOGIN')) {
            pulse.style.background = '#f59e0b';
            _setPhase('lobby', 2); _setProgress(62, 'Waiting in meeting lobby...'); _setBadge('In Lobby', '#f59e0b');
            _setLog(logMsg || 'Bot is in the waiting room — waiting for host to admit Renata...');
            _stopLiveTimer();
        } else if (status === 'CONNECTED' || status.includes('LIVE')) {
            pulse.style.background = '#10b981';
            _setPhase('live', 4); _setProgress(85, 'Bot is LIVE in the meeting!'); _setBadge('🟢 Bot Active — Recording', '#10b981');
            _setLog('✅ Renata has joined the meeting and is capturing intelligence. Recording in progress...');
            _startLiveTimer();
        } else if (status === 'PROCESSING') {
            pulse.style.background = '#8b5cf6'; pulse.style.animation = 'pulse 1.5s infinite';
            _setPhase('processing', 4); _setProgress(95, 'Generating AI report...'); _setBadge('Processing Report', '#8b5cf6');
            _setLog('Meeting ended. Gemini AI is transcribing and generating your intelligence report...');
            _stopLiveTimer();
        } else if (status === 'COMPLETED') {
            pulse.style.background = '#10b981'; pulse.style.animation = 'none';
            PHASES.forEach(ph => { const el = document.getElementById(`phase-${ph}`); if(el) { el.classList.remove('active'); el.classList.add('complete'); } });
            _setProgress(100, 'Report ready! ✅'); _setBadge('✅ Completed', '#10b981');
            _setLog('All done! Your meeting report is now available in the <b>Reports</b> tab.');
            _stopLiveTimer();
        } else if (status === 'FAILED') {
            pulse.style.background = '#ef4444'; pulse.style.animation = 'none';
            _setProgress(100, 'Failed'); _setBadge('❌ Failed', '#ef4444');
            _setLog('⚠️ ' + (logMsg || 'An error occurred. The bot could not join the meeting.'));
            _stopLiveTimer();
        }
    }

    function showBotIdle() {
        const idle = document.getElementById('bot-idle-msg');
        const tracker = document.getElementById('bot-tracker');
        const pulse = document.getElementById('bot-pulse');
        if (idle) idle.style.display = 'block';
        if (tracker) tracker.style.display = 'none';
        if (pulse) { pulse.style.background = '#64748b'; pulse.style.animation = 'none'; }
        _setBadge('Idle', 'var(--text-secondary)');
        _stopLiveTimer();
    }

    async function loadLiveStatus() {
        if (window.location.hash !== '#live') return;
        try {
            const res = await apiFetch("/live/status");
            const data = await res.json();
            if (data.meeting && data.status && data.status !== 'IDLE') {
                showBotActive(data.status, data.meeting.bot_status_note);
            } else {
                showBotIdle();
            }
        } catch (err) { }
    }

    window.dispatchRenata = async (url) => {
        if (!url) return alert('Please enter a meeting link.');
        const btn = document.getElementById('manual-join');
        if (btn) btn.disabled = true;
        const fd = new FormData();
        fd.append('meeting_url', url);
        try {
            const res = await apiFetch('/live/join', { method: 'POST', body: fd });
            const data = await res.json();
            if (data.success) {
                showBotActive('JOIN_PENDING', data.message);
                if (window.closeModal) window.closeModal();
            } else {
                alert('Error: ' + (data.message || 'Failed to dispatch.'));
            }
        } catch (err) { alert('Server error. Is your pilot script running?'); }
        finally { if (btn) btn.disabled = false; }
    };

    // Integrations Data
    async function loadIntegrationsData() {
        try {
            const res = await apiFetch("/dashboard_data");
            const data = await res.json();
            if (data.integrations) {
                const gs = document.getElementById('google-status');
                const zs = document.getElementById('zoom-status');
                if (gs) gs.textContent = data.integrations.google ? 'Connected' : 'Disconnected';
                if (zs) zs.textContent = data.integrations.zoom ? 'Connected' : 'Disconnected';
            }
        } catch (err) { }
    }

    // Modal
    const jBtn = document.getElementById('join-btn');
    const modal = document.getElementById('join-modal');
    if (jBtn) jBtn.addEventListener('click', () => modal.classList.add('active'));
    window.closeModal = () => modal.classList.remove('active');

    const refRBtn = document.getElementById('refresh-reports-btn');
    if (refRBtn) refRBtn.onclick = () => loadReportsData();

    const refABtn = document.getElementById('refresh-analytics-btn');
    if (refABtn) refABtn.onclick = () => loadAnalyticsData();

    const mJoin = document.getElementById('manual-join');
    if (mJoin) mJoin.addEventListener('click', () => dispatchRenata(document.getElementById('manual-url')?.value));

    // Chat
    const cin = document.getElementById('chat-input');
    const sBtn = document.getElementById('send-chat');
    async function askAI() {
        const q = cin.value.trim();
        if (!q) return;

        // Auto-create session if none active
        if (!currentSessionId) {
            await createNewChat();
        }

        const box = document.getElementById('chat-box');
        const uM = document.createElement('div');
        uM.className = 'message user';
        uM.innerHTML = `<p>${q}</p>`;
        box.appendChild(uM);
        cin.value = '';
        box.scrollTop = box.scrollHeight;

        try {
            const fd = new FormData();
            fd.append('question', q);
            if (currentSessionId) fd.append('session_id', currentSessionId);

            const r = await apiFetch("/search/ask", { method: 'POST', body: fd });
            const d = await r.json();
            
            const aM = document.createElement('div');
            aM.className = 'message assistant';
            aM.innerHTML = `<p>${d.answer}</p>`;
            box.appendChild(aM);
            box.scrollTop = box.scrollHeight;
            
            // Refresh history text if it's the first message
            loadChatSessions();
        } catch (err) {
            const eM = document.createElement('div');
            eM.className = 'message assistant';
            eM.innerHTML = `<p>Sorry, I encountered an error processing your request.</p>`;
            box.appendChild(eM);
        }
    }
    if (sBtn) sBtn.addEventListener('click', askAI);
    if (cin) cin.addEventListener('keypress', (e) => { if (e.key === 'Enter') askAI(); });

    // AUTO-REFRESH DATA (Every 3 seconds for Live, 15 for others)
    setInterval(() => {
        const currentHash = window.location.hash.replace('#', '');
        if (currentHash === 'analytics') loadAnalyticsData();
        if (currentHash === 'live' || currentHash === 'dashboard') loadLiveStatus();
    }, 3000);
});
