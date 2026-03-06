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
                if (userNameEl) userNameEl.textContent = data.user.name;
                if (userAvatarEl && data.user.picture) userAvatarEl.src = data.user.picture;
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

    async function loadSearchStats() {
        try {
            const res = await apiFetch("/search/status");
            const data = await res.json();
            console.log("KB Stats:", data);
        } catch (err) { console.error(err); }
    }

    async function loadLiveStatus() {
        try {
            const res = await apiFetch("/live/status");
            const data = await res.json();
            console.log("Live Status:", data);
        } catch (err) { console.error(err); }
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
        const formData = new FormData();
        formData.append('meeting_url', url);
        await fetch(`${API_BASE}/live/join`, { method: 'POST', body: formData });
        alert("Renata Dispatched!");
    };

    // Initial Load
    checkServerStatus();
    setInterval(checkServerStatus, 10000); // Check every 10s

    // Modal Interaction
    const joinBtn = document.getElementById('join-btn');
    const modal = document.getElementById('join-modal');
    const confirmJoin = document.getElementById('confirm-join');

    joinBtn.addEventListener('click', () => modal.classList.add('active'));

    window.closeModal = () => modal.classList.remove('active');

    confirmJoin.addEventListener('click', async () => {
        const url = document.getElementById('meeting-url').value;
        if (!url) return alert("Please enter a meeting URL");

        try {
            const formData = new FormData();
            formData.append('meeting_url', url);

            const response = await apiFetch("/live/join", {
                method: 'POST',
                body: formData
            });

            const data = await response.json();
            if (data.success) {
                alert("Renata is joining the meeting!");
                closeModal();
            } else {
                alert("Error: " + data.message);
            }
        } catch (err) {
            console.error(err);
            alert("Could not connect to local server. Ensure it's running.");
        }
    });

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
            errorMsg.innerHTML = `<p>Error connecting to Renata's local intelligence.</p>`;
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
