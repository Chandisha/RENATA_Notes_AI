// RENATA Frontend Logic
const API_BASE = "https://inimitably-cytotropic-fatimah.ngrok-free.dev";

// Helper for Ngrok-skip-browser-warning
async function apiFetch(endpoint, options = {}) {
    const headers = {
        'ngrok-skip-browser-warning': 'true',
        ...options.headers
    };
    return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
}

document.addEventListener('DOMContentLoaded', () => {
    // Initialize Feather icons
    feather.replace();

    // Navigation Logic
    const navItems = document.querySelectorAll('.nav-item');
    const pages = document.querySelectorAll('.page');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetPage = item.getAttribute('data-page');

            // Update Active Nav
            navItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            // Show Target Page
            pages.forEach(p => p.classList.remove('active'));
            document.getElementById(`${targetPage}-page`).classList.add('active');

            // Trigger Data Load
            loadPageData(targetPage);
        });
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

            // Update Stats
            if (data.stats) {
                document.querySelector('.stat-card:nth-child(1) .stat-value').textContent = data.stats.total_meetings || 0;
                document.querySelector('.stat-card:nth-child(2) .stat-value').textContent = (data.stats.total_hours || 0).toFixed(1) + 'h';
                document.querySelector('.stat-card:nth-child(3) .stat-value').textContent = data.stats.action_items_count || 0;
                document.querySelector('.stat-card:nth-child(4) .stat-value').textContent = data.stats.participant_count || 0;
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

    window.dispatchRenata = async (url) => {
        const formData = new FormData();
        formData.append('meeting_url', url);
        await fetch(`${API_BASE}/live/join`, { method: 'POST', body: formData });
        alert("Renata Dispatched!");
    };

    // Initial Load
    loadDashboardData();

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

            // Add assistant message
            const assistantMsg = document.createElement('div');
            assistantMsg.className = 'message assistant';
            assistantMsg.innerHTML = `<p>${data.answer}</p>`;
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
