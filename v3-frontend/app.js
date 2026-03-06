// RENATA Frontend Logic
const API_BASE = window.location.origin; // Dynamically use the same host on Vercel

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
    // Initialize Feather icons
    feather.replace();

    // Navigation Logic
    const navItems = document.querySelectorAll('.nav-item');
    const pages = document.querySelectorAll('.page');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            const targetPage = item.getAttribute('data-page');
            window.location.hash = targetPage;
            showPage(targetPage);
        });
    });

    function showPage(pageId) {
        if (!pageId) pageId = 'dashboard';

        // Update Active Nav
        navItems.forEach(i => {
            i.classList.toggle('active', i.getAttribute('data-page') === pageId);
        });

        // Show Target Page
        const targetElement = document.getElementById(`${pageId}-page`);
        if (targetElement) {
            pages.forEach(p => p.classList.remove('active'));
            targetElement.classList.add('active');
            loadPageData(pageId);
        }
    }

    // Handle initial load
    const initialPage = window.location.hash.replace('#', '') || 'dashboard';
    showPage(initialPage);

    // Handle back/forward and manual hash changes
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
            case 'search':
                await loadSearchStats();
                break;
            case 'live':
                await loadLiveStatus();
                break;
        }
    }

    async function loadDashboardData() {
        try {
            // Stats & Recent
            const res = await apiFetch("/dashboard_data");
            const data = await res.json();

            // Update User Profile
            if (data.user) {
                const userNameEl = document.querySelector('.user-name');
                const userAvatarEl = document.querySelector('.avatar');
                const prefUserName = document.getElementById('pref-user-name');
                const prefUserEmail = document.getElementById('pref-user-email');

                if (userNameEl) userNameEl.textContent = data.user.name;
                if (userAvatarEl && data.user.picture) userAvatarEl.src = data.user.picture;
                if (prefUserName) prefUserName.value = data.user.name;
                if (prefUserEmail) prefUserEmail.value = data.user.email;
            }

            // Update Stats
            if (data.stats) {
                document.querySelector('.stat-card:nth-child(1) .stat-value').textContent = data.stats.total_meetings || 0;
                document.querySelector('.stat-card:nth-child(2) .stat-value').textContent = (data.stats.total_hours || 0).toFixed(1) + 'h';
                document.querySelector('.stat-card:nth-child(3) .stat-value').textContent = data.stats.action_items_count || 0;
                document.querySelector('.stat-card:nth-child(4) .stat-value').textContent = (data.stats.participant_count || 0).toFixed(1);
            }

            // Update Recent List
            const recentList = document.getElementById('recent-list');
            recentList.innerHTML = '';
            (data.recent_meetings || []).forEach(m => {
                const item = document.createElement('div');
                item.className = 'list-item';
                item.innerHTML = `
                    <div class="item-icon"><i data-feather="file"></i></div>
                    <div class="item-details">
                        <span class="item-title">${m.title || 'Untitled'}</span>
                        <span class="item-meta">${m.start_time}</span>
                    </div>
                    <div class="item-actions">
                        <span class="badge blue">${m.status}</span>
                        <button class="icon-btn" onclick="window.location.hash='#reports'"><i data-feather="chevron-right"></i></button>
                    </div>
                `;
                recentList.appendChild(item);
            });

            // Update Calendar
            const calendarGrid = document.getElementById('calendar-grid');
            if (calendarGrid) {
                calendarGrid.innerHTML = '';
                if ((data.events || []).length === 0) {
                    calendarGrid.innerHTML = `
                        <p class="muted">No upcoming meetings found.</p>
                        <button onclick="window.location.href=API_BASE+'/auth/google'" class="btn-sm secondary-btn">Sync Google Calendar</button>
                    `;
                } else {
                    (data.events || []).forEach(event => {
                        const card = document.createElement('div');
                        card.className = 'meeting-card';
                        card.innerHTML = `
                            <div class="meeting-card-top">
                                <span class="status-badge">Upcoming</span>
                                <span class="meeting-time">${event.start_time}</span>
                            </div>
                            <div class="meeting-title">${event.summary}</div>
                            <div class="meeting-actions">
                                <button class="btn-sm primary-btn" onclick="dispatchRenata('${event.link}')">Send Renata</button>
                            </div>
                        `;
                        calendarGrid.appendChild(card);
                    });
                }
            }

            // Update Integrations
            if (data.integrations) {
                const gStatus = document.getElementById('google-status');
                const zStatus = document.getElementById('zoom-status');
                if (gStatus) {
                    gStatus.textContent = data.integrations.google ? 'Connected' : 'Disconnected';
                    gStatus.style.color = data.integrations.google ? 'var(--accent-green)' : 'var(--text-secondary)';
                }
                if (zStatus) {
                    zStatus.textContent = data.integrations.zoom ? 'Connected' : 'Disconnected';
                    zStatus.style.color = data.integrations.zoom ? 'var(--accent-green)' : 'var(--text-secondary)';
                }
            }

            // Update Preferences
            if (data.preferences) {
                const botNameInput = document.getElementById('pref-bot-name');
                const autoJoinCheck = document.getElementById('pref-auto-join');
                const recordingCheck = document.getElementById('pref-recording');
                if (botNameInput) botNameInput.value = data.preferences.bot_name || '';
                if (autoJoinCheck) autoJoinCheck.checked = data.preferences.auto_join;
                if (recordingCheck) recordingCheck.checked = data.preferences.recording;
            }

            feather.replace();
        } catch (err) {
            console.error("Dashboard load failed", err);
        }
    }

    async function loadReportsData() {
        try {
            const res = await apiFetch("/reports_data");
            const data = await res.json();
            const grid = document.getElementById('reports-grid');
            grid.innerHTML = '';

            data.meetings.forEach(m => {
                const card = document.createElement('div');
                card.className = 'report-card';
                card.innerHTML = `
                    <div class="report-header">
                        <span class="report-date">${m.start_time}</span>
                        <span class="badge">${m.status}</span>
                    </div>
                    <h3 class="report-title">${m.title}</h3>
                    <div class="report-footer">
                        <div class="engagement-mini">Score: ${m.engagement_score || 0}%</div>
                        <a href="${API_BASE}/download/pdf/${m.pdf_path.split(/[\\/]/).pop()}" target="_blank" class="btn-sm primary-btn">PDF</a>
                    </div>
                `;
                grid.appendChild(card);
            });
        } catch (err) {
            console.error("Reports load failed", err);
        }
    }


    // Server Status Checker
    async function checkServerStatus() {
        const dot = document.querySelector('.status-dot');
        const text = document.querySelector('.status-text');
        try {
            const res = await apiFetch("/health");
            if (res.ok) {
                dot.style.background = 'var(--accent-green)';
                text.textContent = 'Server: Connected';
                dot.classList.add('pulse');
            } else {
                throw new Error();
            }
        } catch (err) {
            dot.style.background = '#ef4444';
            text.textContent = 'Server: Offline';
            dot.classList.remove('pulse');
        }
    }

    window.dispatchRenata = async (url) => {
        if (!url) {
            alert("Please enter a meeting link.");
            return;
        }
        const formData = new FormData();
        formData.append('meeting_url', url);
        try {
            const res = await apiFetch("/live/join", { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) {
                showBotActive("JOIN_PENDING", data.message);
                if (window.closeModal) window.closeModal();
            } else {
                alert("Error: " + (data.message || data.detail || "Renata could not be dispatched."));
            }
        } catch (err) {
            console.error(err);
            alert("Could not connect to server. Ensure it's reachable.");
        }
    };

    function showBotActive(status, note) {
        const idleMsg = document.getElementById('bot-idle-msg');
        const steps = document.getElementById('bot-steps');
        const pulse = document.getElementById('bot-pulse');
        if (idleMsg) idleMsg.style.display = 'none';
        if (steps) steps.style.display = 'grid';
        if (pulse) { pulse.style.background = 'var(--accent-green)'; pulse.style.animation = 'pulse 1.5s infinite'; }
        updateBotVisuals(status, note);
    }

    function showBotIdle() {
        const idleMsg = document.getElementById('bot-idle-msg');
        const steps = document.getElementById('bot-steps');
        const pulse = document.getElementById('bot-pulse');
        if (idleMsg) idleMsg.style.display = 'block';
        if (steps) steps.style.display = 'none';
        if (pulse) { pulse.style.background = '#64748b'; pulse.style.animation = 'none'; }
        const noteEl = document.getElementById('bot-note'); if (noteEl) noteEl.textContent = '';
    }

    function updateBotVisuals(status, note) {
        // Reset steps
        document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
        const noteEl = document.getElementById('bot-note');
        if (noteEl) noteEl.textContent = note || '';

        if (status === "JOIN_PENDING" || status === "JOINING") {
            document.getElementById("step-dispatching").classList.add("active");
        } else if (status === "FETCHING") {
            document.getElementById("step-fetching").classList.add("active");
        } else if (status === "CONNECTING" || status === "IN_LOBBY") {
            document.getElementById("step-connecting").classList.add("active");
        } else if (status === "CONNECTED" || status === "LIVE") {
            document.getElementById("step-live").classList.add("active");
        }
    }

    async function loadLiveStatus() {
        if (window.location.hash !== '#live') return;
        try {
            const res = await apiFetch("/live/status");
            const data = await res.json();
            if (data.active) {
                showBotActive(data.status, data.note);
            } else {
                showBotIdle();
            }
        } catch (err) { }
    }

    async function loadSearchStats() {
        try {
            const res = await apiFetch("/search/status");
            const data = await res.json();
            const pdfCount = document.getElementById("pdf-count");
            const segCount = document.getElementById("seg-count");
            if (pdfCount) pdfCount.textContent = data.pdf_count || 0;
            if (segCount) segCount.textContent = data.indexed_segments || 0;
        } catch (err) { }
    }

    const syncBtn = document.getElementById("sync-kb-btn");
    if (syncBtn) {
        syncBtn.addEventListener("click", async () => {
            syncBtn.disabled = true;
            syncBtn.innerHTML = '<i data-feather="loader"></i> Syncing...';
            feather.replace();

            try {
                const res = await apiFetch("/search/index", { method: 'POST' });
                const data = await res.json();
                alert(data.message);
                loadSearchStats();
            } catch (err) {
                alert("Failed to sync knowledge base.");
            } finally {
                syncBtn.disabled = false;
                syncBtn.innerHTML = '<i data-feather="refresh-cw"></i> Sync Knowledge Base';
                feather.replace();
            }
        });
    }

    // Save Profile (Name Change)
    const profileForm = document.getElementById('profile-form');
    if (profileForm) {
        profileForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('pref-user-name').value;
            try {
                const res = await apiFetch("/settings/api/save", {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name })
                });
                if (res.ok) {
                    alert("Profile updated successfully!");
                    document.querySelectorAll('.user-name').forEach(el => el.textContent = name);
                }
            } catch (err) { alert("Failed to save profile."); }
        });
    }

    // Save Bot Preferences
    const preferencesForm = document.getElementById('settings-preferences-form');
    if (preferencesForm) {
        preferencesForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const bot_name = document.getElementById('pref-bot-name').value;
            const auto_join = document.getElementById('pref-auto-join').checked;
            const recording = document.getElementById('pref-recording').checked;

            try {
                const res = await apiFetch("/settings/api/save", {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bot_name, auto_join, recording })
                });
                if (res.ok) {
                    alert("Preferences saved successfully!");
                }
            } catch (err) { alert("Failed to save preferences."); }
        });
    }

    // Initial Load & Polling
    checkServerStatus();
    setInterval(checkServerStatus, 15000);
    setInterval(loadLiveStatus, 3000); // Polling for bot status updates

    // Modal Interaction
    const joinBtn = document.getElementById('join-btn');
    const modal = document.getElementById('join-modal');
    const confirmJoin = document.getElementById('confirm-join');

    joinBtn.addEventListener('click', () => modal.classList.add('active'));

    window.closeModal = () => modal.classList.remove('active');

    const manualJoin = document.getElementById('manual-join');
    if (manualJoin) {
        manualJoin.addEventListener('click', () => {
            const url = document.getElementById('manual-url').value;
            dispatchRenata(url);
        });
    }

    if (confirmJoin) {
        confirmJoin.addEventListener('click', () => {
            const url = document.getElementById('meeting-url').value;
            dispatchRenata(url);
        });
    }

    // AI Chat Assistant
    const chatInput = document.getElementById('chat-input');
    const sendChat = document.getElementById('send-chat');
    const chatBox = document.getElementById('chat-box');

    async function handleChat() {
        const question = chatInput.value;
        if (!question) return;

        // Add user message
        const userMsg = document.createElement('div');
        userMsg.className = 'message user';
        userMsg.innerHTML = `<p>${question}</p>`;
        chatBox.appendChild(userMsg);
        chatInput.value = '';
        chatBox.scrollTop = chatBox.scrollHeight;

        try {
            const formData = new FormData();
            formData.append('question', question);

            const response = await apiFetch("/search/ask", {
                method: 'POST',
                body: formData
            });

            const data = await response.json();
            const answer = data.answer || "Renata could not generate an answer at this time.";

            // Add assistant message
            const assistantMsg = document.createElement('div');
            assistantMsg.className = 'message assistant';
            assistantMsg.innerHTML = `<p>${answer}</p>`;
            chatBox.appendChild(assistantMsg);
            chatBox.scrollTop = chatBox.scrollHeight;
        } catch (err) {
            const errorMsg = document.createElement('div');
            errorMsg.className = 'message assistant';
            errorMsg.innerHTML = `<p>Error connecting to Renata's intelligence.</p>`;
            chatBox.appendChild(errorMsg);
        }
    }

    sendChat.addEventListener('click', handleChat);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleChat();
    });

    // Initialize Engagement Chart
    const ctx = document.getElementById('engagementChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            datasets: [{
                label: 'Meeting Productivity',
                data: [65, 78, 82, 75, 90, 85, 92],
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
            scales: {
                y: { display: false },
                x: { grid: { display: false }, ticks: { color: '#94a3b8' } }
            }
        }
    });
});
