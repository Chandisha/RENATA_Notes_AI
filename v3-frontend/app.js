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
                break;
            case 'search':
                await loadSearchStats();
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

            // Recent Reports List
            const recentList = document.getElementById('recent-list');
            if (recentList) {
                recentList.innerHTML = '';
                (data.recent_meetings || []).forEach(m => {
                    const item = document.createElement('div');
                    item.className = 'list-item';
                    item.innerHTML = `
                        <div class="item-icon"><i data-feather="file-text"></i></div>
                        <div class="item-details">
                            <span class="item-title">${m.title || 'Untitled'}</span>
                            <span class="item-meta">${m.start_time}</span>
                        </div>
                        <div class="item-actions">
                            <span class="badge ${m.status}">${m.status.toUpperCase()}</span>
                            <button class="icon-btn" onclick="window.location.hash='#reports'"><i data-feather="chevron-right"></i></button>
                        </div>
                    `;
                    recentList.appendChild(item);
                });
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

    async function loadReportsData() {
        try {
            const res = await apiFetch("/reports_data");
            const data = await res.json();
            const grid = document.getElementById('reports-grid');
            if (!grid) return;
            grid.innerHTML = '';

            if (data.meetings.length === 0) {
                grid.innerHTML = '<div class="card" style="grid-column: 1/-1; padding:40px; text-align:center;"><p class="muted">No reports generated yet. Renata will start populating this as you join meetings.</p></div>';
            }

            data.meetings.forEach(m => {
                const pdfName = m.pdf_path ? m.pdf_path.split(/[\\/]/).pop() : null;
                const pdfLink = pdfName ? `${API_BASE}/download/pdf/${pdfName}` : '#';
                
                const card = document.createElement('div');
                card.className = 'report-card';
                card.innerHTML = `
                    <div class="report-header">
                        <span class="report-date">${m.start_time}</span>
                        <span class="badge ${m.status}">${m.status.toUpperCase()}</span>
                    </div>
                    <h3 class="report-title">${m.title || 'Untitled Meeting'}</h3>
                    <div class="report-footer" style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="muted" style="font-size:0.8rem;">${m.participant_count || 0} participants</span>
                        ${pdfName ? `<a href="${pdfLink}" target="_blank" class="btn-sm primary-btn" style="text-decoration:none;">Open PDF</a>` : `<span class="muted" style="font-size:0.85rem;">Processing...</span>`}
                    </div>
                `;
                grid.appendChild(card);
            });
            feather.replace();
        } catch (err) { }
    }

    async function loadAnalyticsData() {
        try {
            const res = await apiFetch("/analytics/data");
            const stats = await res.json();

            const mVal = document.getElementById('ana-total-meetings');
            const tVal = document.getElementById('ana-total-time');
            const eVal = document.getElementById('ana-total-engagement');
            const aVal = document.getElementById('ana-app-time');

            if (mVal) mVal.textContent = stats.total_meetings || 0;
            if (tVal) tVal.textContent = (stats.total_duration_hours || 0).toFixed(1) + 'h';
            if (eVal) eVal.textContent = (stats.engagement_score || 0) + '%';
            if (aVal) aVal.textContent = (stats.app_engagement_minutes || 0) + 'm';

            // Analytics Trends Chart
            const ctx = document.getElementById('analyticsChart')?.getContext('2d');
            if (ctx) {
                if (window.anaChartInstance) window.anaChartInstance.destroy();
                window.anaChartInstance = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: ['Session 1', 'Session 2', 'Session 3', 'Session 4', 'Session 5'],
                        datasets: [{
                            label: 'Productivity Trend',
                            data: [60, 75, 70, 85, 95],
                            borderColor: '#8b5cf6',
                            tension: 0.4,
                            fill: true,
                            backgroundColor: 'rgba(139, 92, 246, 0.1)'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: { y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' } } }
                    }
                });
            }
        } catch (err) { }
    }

    async function loadSearchStats() {
        try {
            const res = await apiFetch("/search/status");
            const data = await res.json();
            const pc = document.getElementById("pdf-count");
            const sc = document.getElementById("seg-count");
            if (pc) pc.textContent = data.pdf_count || 0;
            if (sc) sc.textContent = data.indexed_segments || 0;
        } catch (err) { }
    }

    async function loadLiveStatus() {
        if (window.location.hash !== '#live') return;
        try {
            const res = await apiFetch("/live/status");
            const data = await res.json();
            if (data.meeting) {
                showBotActive(data.status, data.meeting.bot_status_note);
            } else {
                showBotIdle();
            }
        } catch (err) { }
    }

    function showBotActive(status, note) {
        const idle = document.getElementById('bot-idle-msg');
        const steps = document.getElementById('bot-steps');
        const pulse = document.getElementById('bot-pulse');
        if (idle) idle.style.display = 'none';
        if (steps) steps.style.display = 'grid';
        if (pulse) { pulse.style.background = '#10b981'; pulse.style.animation = 'pulse 1.5s infinite'; }
        
        document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
        const nt = document.getElementById('bot-note');
        if (nt) nt.textContent = note || '';

        if (status.includes("PENDING") || status.includes("JOINING")) document.getElementById("step-dispatching")?.classList.add("active");
        else if (status.includes("FETCHING")) document.getElementById("step-fetching")?.classList.add("active");
        else if (status.includes("CONNECTING") || status.includes("LOBBY")) document.getElementById("step-connecting")?.classList.add("active");
        else if (status.includes("CONNECTED") || status.includes("LIVE")) document.getElementById("step-live")?.classList.add("active");
    }

    function showBotIdle() {
        const idle = document.getElementById('bot-idle-msg');
        const steps = document.getElementById('bot-steps');
        const pulse = document.getElementById('bot-pulse');
        if (idle) idle.style.display = 'block';
        if (steps) steps.style.display = 'none';
        if (pulse) { pulse.style.background = '#64748b'; pulse.style.animation = 'none'; }
    }

    window.dispatchRenata = async (url) => {
        if (!url) return alert("Please enter a meeting link.");
        const fd = new FormData();
        fd.append('meeting_url', url);
        try {
            const res = await apiFetch("/live/join", { method: 'POST', body: fd });
            const data = await res.json();
            if (data.success) {
                showBotActive("JOIN_PENDING", data.message);
                if (window.closeModal) window.closeModal();
            } else alert("Error: " + (data.message || "Failed to dispatch."));
        } catch (err) { alert("Server error."); }
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

    const mJoin = document.getElementById('manual-join');
    if (mJoin) mJoin.addEventListener('click', () => dispatchRenata(document.getElementById('manual-url')?.value));

    // Chat
    const cin = document.getElementById('chat-input');
    const sBtn = document.getElementById('send-chat');
    async function askAI() {
        const q = cin.value; if (!q) return;
        const box = document.getElementById('chat-box');
        const uM = document.createElement('div'); uM.className = 'message user'; uM.innerHTML = `<p>${q}</p>`;
        box.appendChild(uM); cin.value = ''; box.scrollTop = box.scrollHeight;
        try {
            const fd = new FormData(); fd.append('question', q);
            const r = await apiFetch("/search/ask", { method: 'POST', body: fd });
            const d = await r.json();
            const aM = document.createElement('div'); aM.className = 'message assistant'; aM.innerHTML = `<p>${d.answer}</p>`;
            box.appendChild(aM); box.scrollTop = box.scrollHeight;
        } catch (err) { }
    }
    if (sBtn) sBtn.addEventListener('click', askAI);
    if (cin) cin.addEventListener('keypress', (e) => { if (e.key === 'Enter') askAI(); });

    setInterval(loadLiveStatus, 5000);
});
