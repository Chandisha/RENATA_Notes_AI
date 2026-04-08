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
    loadUserProfile();

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

    // --- MOBILE SIDEBAR TOGGLE ---
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const sidebar = document.querySelector('.sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');

    if (mobileMenuBtn && sidebar && sidebarOverlay) {
        const toggleSidebar = () => {
            sidebar.classList.toggle('active');
            sidebarOverlay.classList.toggle('active');
        };

        mobileMenuBtn.addEventListener('click', toggleSidebar);
        sidebarOverlay.addEventListener('click', toggleSidebar);

        // Close sidebar when a nav item is clicked on mobile
        navItems.forEach(item => {
            item.addEventListener('click', () => {
                if (window.innerWidth <= 1024) {
                    sidebar.classList.remove('active');
                    sidebarOverlay.classList.remove('active');
                }
            });
        });
    }

    // --- GLOBAL NOTEBOOK DELEGATED LISTENERS ---
    document.addEventListener('click', (e) => {
        // Plus Button
        if (e.target.closest('#new-note-btn')) {
            e.preventDefault();
            console.log("Global: New Note Clicked");
            if (window.createNewNote) window.createNewNote();
        }
        // Save Button
        if (e.target.closest('#save-notebook-btn')) {
            e.preventDefault();
            console.log("Global: Save Note Clicked");
            if (window.saveCurrentNote) {
                window.updateNotebookSaveStatus('SAVING...');
                window.saveCurrentNote();
            }
        }
        // Delete Button
        if (e.target.closest('#delete-note-btn')) {
            e.preventDefault();
            if (window.deleteCurrentNote) window.deleteCurrentNote();
        }
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
            case 'notes':
                await loadNotesData();
                break;
            case 'gmail':
                await loadGmailData();
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
            case 'help':
                await loadHelpData();
                break;
        }
    }

    async function loadUserProfile() {
        try {
            const res = await apiFetch("/api/me");
            const data = await res.json();
            if (data.user) {
                const userNameEl = document.querySelector('.user-name');
                const userAvatarEl = document.querySelector('.avatar');
                const userAccountEl = document.querySelector('.user-account');

                if (userNameEl) userNameEl.textContent = data.user.name;
                if (userAvatarEl && data.user.picture) {
                    userAvatarEl.src = data.user.picture;
                    userAvatarEl.style.display = 'block';
                }

                if (userAccountEl && data.user.plan) {
                    const plan = data.user.plan.toUpperCase();
                    userAccountEl.textContent = `ACCOUNT: ${plan}`;
                    userAccountEl.style.color = plan === 'PRO' ? 'var(--accent-green)' : 'var(--accent-purple)';
                    window.currentUserPlan = data.user.plan;
                }

                const pName = document.getElementById('pref-user-name');
                const pEmail = document.getElementById('pref-user-email');
                if (pName) pName.value = data.user.name;
                if (pEmail) pEmail.value = data.user.email;
            }
            return data;
        } catch (err) {
            console.error("Failed to load user profile:", err);
            return null;
        }
    }

    async function loadDashboardData() {
        try {
            // 1. Fast Profile Load
            await loadUserProfile();

            // 2. Heavier Dashboard Data (Calendar, Stats, Recent)
            const res = await apiFetch("/dashboard_data");
            const data = await res.json();
            if (!data) return;

            // Preferences Initialization
            if (data.preferences) {
                const autoJoinCheck = document.getElementById('pref-auto-join');
                if (autoJoinCheck) {
                    autoJoinCheck.checked = (data.preferences.auto_join === true || data.preferences.auto_join === 1 || data.preferences.auto_join === "1" || data.preferences.auto_join === null || data.preferences.auto_join === undefined);
                }

                // Sync Global Switch in Top Bar
                const globalSwitch = document.getElementById('global-bot-switch');
                if (globalSwitch) {
                    globalSwitch.checked = (data.preferences.auto_join === true || data.preferences.auto_join === 1 || data.preferences.auto_join === "1" || data.preferences.auto_join === null || data.preferences.auto_join === undefined);
                }
                
                const bName = document.getElementById('pref-bot-name');
                const rec = document.getElementById('pref-recording');
                if (bName) bName.value = data.preferences.bot_name || '';
                if (rec) rec.checked = !!data.preferences.recording;
            }

            // Dashboard Stats
            const statsArr = document.querySelectorAll('#dashboard-page .stat-value');
            if (data.stats && statsArr.length >= 4) {
                statsArr[0].textContent = data.stats.total_meetings || 0;
                statsArr[1].textContent = (data.stats.total_duration_hours || 0).toFixed(1) + 'h';
                statsArr[2].textContent = data.stats.action_items_count || 0;
                statsArr[3].textContent = (data.stats.participant_count || 0).toFixed(1);
            }

            // Recent Reports List (PDF and processing)
            const recentList = document.getElementById('recent-list');
            if (recentList) {
                recentList.innerHTML = '';
                const recentAll = (data.recent_meetings || []).slice(0, 5);

                if (recentAll.length === 0) {
                    recentList.innerHTML = '<p class="muted" style="padding:10px;">No meetings yet.</p>';
                } else {
                    recentAll.forEach(m => {
                        const isProcessing = m.status === 'processing' || m.bot_status === 'PROCESSING';
                        const item = document.createElement('div');
                        item.className = 'list-item';
                        item.innerHTML = `
                            <div class="item-icon"><i data-feather="${isProcessing ? 'loader' : 'file-text'}" class="${isProcessing ? 'spin' : ''}"></i></div>
                            <div class="item-details">
                                <span class="item-title">${m.title || 'Meeting'}</span>
                                <span class="item-meta">${isProcessing ? 'AI Processing...' : 'Generated ' + timeAgo(m.updated_at || m.created_at)}</span>
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
                        
                        const isEnabled = ev.is_enabled !== false; // Default to true

                        card.innerHTML = `
                            <div class="meeting-card-top">
                                <span class="status-badge">Calendar Event</span>
                                <span class="meeting-time">${ev.start_time}</span>
                            </div>
                            <div class="meeting-title">${ev.summary}</div>
                            <div class="meeting-actions" style="display: flex; align-items: center; justify-content: space-between; border-top: 1px solid var(--border-color); padding-top: 15px; margin-top: 15px;">
                                <div class="bot-join-label" style="display: flex; align-items: center; gap: 8px;">
                                    <i data-feather="user-plus" style="width: 14px; color: var(--accent-orange);"></i>
                                    <span style="font-size: 0.85rem; font-weight: 500; color: var(--text-secondary);">Auto-Join Bot</span>
                                </div>
                                <div class="toggle-container" style="display: flex; align-items: center; gap: 10px;">
                                    <span style="font-size: 0.75rem; font-weight: 700; color: ${isEnabled ? 'var(--accent-green)' : 'var(--text-secondary)'}; text-transform: uppercase;">${isEnabled ? 'Active' : 'Skipped'}</span>
                                    <label class="switch" style="width: 40px; height: 20px;">
                                        <input type="checkbox" ${isEnabled ? 'checked' : ''} onchange="window.toggleMeetingBot('${ev.id}', this.checked, this)">
                                        <span class="slider round"></span>
                                    </label>
                                </div>
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

    // --- NOTE TAKING & NOTEBOOK LOGIC ---
    let currentNoteId = null;
    let notebookAutoSaveTimeout = null;

    async function loadNotesData() {
        try {
            // 1. Load Personal Notes List
            const pNotesRes = await apiFetch("/api/notes/list");
            if (pNotesRes) {
                const pNotesData = await pNotesRes.json();
                renderPersonalNotesList(pNotesData.notes || []);
            }

            // 2. Load AI Meetings List
            const aiNotesRes = await apiFetch("/api/notes/ai/list");
            if (aiNotesRes) {
                const aiNotesData = await aiNotesRes.json();
                renderAiMeetingsSelector(aiNotesData.meetings || []);
            }
            
            bindNotebookInputs();
        } catch (err) { console.error("Notebook Load Error:", err); }
    }

    function renderPersonalNotesList(notes) {
        const listContainer = document.getElementById('personal-notes-list');
        if (!listContainer) return;
        listContainer.innerHTML = '';
        
        if (notes.length === 0) {
            listContainer.innerHTML = '<div class="muted" style="font-size: 0.8rem; text-align: center; margin-top: 20px;">No notes yet. Click + to start.</div>';
            return;
        }

        notes.forEach(n => {
            const item = document.createElement('div');
            item.className = `note-item ${currentNoteId == n.id ? 'active' : ''}`;
            item.style.padding = '10px 12px';
            item.style.borderRadius = '8px';
            item.style.cursor = 'pointer';
            item.style.fontSize = '0.85rem';
            item.style.fontWeight = '600';
            item.style.overflow = 'hidden';
            item.style.whiteSpace = 'nowrap';
            item.style.textOverflow = 'ellipsis';
            item.style.marginBottom = '4px';
            item.style.transition = 'all 0.2s';
            
            if (currentNoteId == n.id) {
                item.style.background = 'rgba(242,113,33,0.1)';
                item.style.color = 'var(--accent-orange)';
            } else {
                item.style.background = 'transparent';
                item.style.color = 'var(--text-secondary)';
            }

            item.textContent = n.title || 'Untitled Note';
            item.onclick = (e) => {
                e.preventDefault();
                selectPersonalNote(n.id);
            };
            listContainer.appendChild(item);
        });
    }

    function renderAiMeetingsSelector(meetings) {
        const selector = document.getElementById('ai-insight-selector');
        if (!selector) return;
        selector.innerHTML = '<option value="" disabled selected>AI Insights from Meeting...</option>';
        meetings.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.meeting_id;
            const dateStr = new Date(m.start_time).toLocaleDateString(undefined, {month:'short', day:'numeric'});
            opt.textContent = `${m.title} (${dateStr})`;
            selector.appendChild(opt);
        });
        
        if (!selector.dataset.bound) {
            selector.addEventListener('change', () => loadAiInsight(selector.value));
            selector.dataset.bound = "true";
        }
    }
    // Notebook Inputs still need direct binding because they are 'input' events
    function bindNotebookInputs() {
        const subjectInput = document.getElementById('note-subject');
        const contentArea = document.getElementById('notebook-textarea');
        if (subjectInput && !subjectInput.dataset.bound) {
            subjectInput.addEventListener('input', triggerAutoSave);
            subjectInput.dataset.bound = "true";
        }
        if (contentArea && !contentArea.dataset.bound) {
            contentArea.addEventListener('input', triggerAutoSave);
            contentArea.dataset.bound = "true";
        }
    }

    window.selectPersonalNote = async function(id) {
        if (!id) return;
        currentNoteId = id;
        try {
            const res = await apiFetch(`/api/notes/personal/${id}`);
            if (res) {
                const data = await res.json();
                document.getElementById('note-subject').value = data.title || '';
                document.getElementById('notebook-textarea').value = data.content || '';
                document.getElementById('delete-note-btn').style.opacity = '1';
                window.updateNotebookSaveStatus('SAVED');
                
                // Re-render list to show active state
                const listRes = await apiFetch("/api/notes/list");
                if (listRes) {
                    const listData = await listRes.json();
                    renderPersonalNotesList(listData.notes);
                }
            }
        } catch (err) { console.error(err); }
    }

    window.createNewNote = function() {
        currentNoteId = null;
        const sub = document.getElementById('note-subject');
        const count = document.getElementById('notebook-textarea');
        if (sub) sub.value = '';
        if (count) count.value = '';
        
        const delBtn = document.getElementById('delete-note-btn');
        if (delBtn) delBtn.style.opacity = '0.5';
        
        // Remove active state from list items
        document.querySelectorAll('.note-item').forEach(item => {
            item.style.background = 'transparent';
            item.style.color = 'var(--text-secondary)';
        });

        window.updateNotebookSaveStatus('NEW DRAFT');
        if (sub) sub.focus();
    }

    function triggerAutoSave() {
        if (window.updateNotebookSaveStatus) window.updateNotebookSaveStatus('SAVING...');
        clearTimeout(notebookAutoSaveTimeout);
        notebookAutoSaveTimeout = setTimeout(() => {
            if (window.saveCurrentNote) window.saveCurrentNote();
        }, 1500);
    }

    window.updateNotebookSaveStatus = function(state) {
        const msgEl = document.getElementById('save-status-msg');
        if (!msgEl) return;
        msgEl.textContent = state;
        msgEl.style.opacity = (state === 'SAVED') ? '0.5' : '1';
        if (state === 'SAVING...') msgEl.style.color = 'var(--accent-orange)';
        else if (state === 'SAVED') msgEl.style.color = 'var(--text-secondary)';
        else msgEl.style.color = 'var(--accent-purple)';
    }

    window.saveCurrentNote = async function() {
        const title = document.getElementById('note-subject').value || 'Untitled Note';
        const content = document.getElementById('notebook-textarea').value;
        if (!content && title === 'Untitled Note') return;

        try {
            const res = await apiFetch("/api/notes/personal/save", {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: currentNoteId, title, content })
            });
            const data = await res.json();
            if (data.success) {
                if (!currentNoteId) currentNoteId = data.id;
                document.getElementById('delete-note-btn').style.opacity = '1';
                window.updateNotebookSaveStatus('SAVED');
                // Refresh list only if needed
                const listRes = await apiFetch("/api/notes/list");
                const listData = await listRes.json();
                renderPersonalNotesList(listData.notes);
            }
        } catch (err) { window.updateNotebookSaveStatus('STILL SAVING...'); }
    }

    async function deleteCurrentNote() {
        if (!currentNoteId) return;
        if (!confirm("Are you sure you want to delete this notepad file?")) return;
        try {
            await apiFetch(`/api/notes/personal/delete/${currentNoteId}`, { method: 'POST' });
            if (window.createNewNote) window.createNewNote();
            loadNotesData();
        } catch (err) { console.error(err); }
    }

    async function loadAiInsight(meetingId) {
        const display = document.getElementById('ai-insight-display');
        const footer = document.getElementById('ai-insight-footer');
        const pdfBtn = document.getElementById('view-full-pdf-btn');

        if (!meetingId) return;
        display.innerHTML = '<p class="muted">Loading Intelligence...</p>';
        footer.style.display = 'none';

        try {
            const res = await apiFetch(`/api/notes/ai/${meetingId}`);
            const data = await res.json();
            display.innerHTML = formatMarkdownToHTML(data.ai_notes);
            
            if (data.pdf_link) {
                footer.style.display = 'block';
                pdfBtn.onclick = (e) => {
                    e.preventDefault();
                    handleViewPdf(data.pdf_link, meetingId, data.is_paid);
                };
            }
        } catch (err) { display.innerHTML = '<p style="color:#ef4444;">Error loading AI insights.</p>'; }
    }

    function updateNotebookSaveStatus(text) {
        const el = document.getElementById('save-status-msg');
        if (el) {
            el.textContent = text;
            el.style.opacity = text === 'SAVED' ? '0.6' : '1';
            el.style.color = text === 'SAVING...' ? 'var(--accent-orange)' : 'var(--text-secondary)';
        }
    }

    function formatMarkdownToHTML(text) {
        if (!text) return '';
        let html = text
            .replace(/^### (.*$)/gim, '<h3 style="margin: 15px 0 10px; color: var(--accent-orange); font-size: 1.1rem; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 5px;">$1</h3>')
            .replace(/^## (.*$)/gim, '<h2 style="margin: 20px 0 10px; color: var(--accent-orange);">$1</h2>')
            .replace(/^# (.*$)/gim, '<h1 style="margin: 20px 0 10px;">$1</h1>')
            .replace(/^\- (.*$)/gim, '<li style="margin-left: 15px; margin-bottom: 8px; list-style-type: disc;">$1</li>')
            .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
        
        return `<div class="ai-md-content">${html}</div>`;
    }

    function timeAgo(date) {
        if (!date) return "recently";
        let parsedStr = typeof date === 'string' ? date.replace(' ', 'T') : date;
        // SQLite/Postgres TIMESTAMP CURRENT_TIMESTAMP is UTC. Ensure browser parses it as UTC.
        if (typeof parsedStr === 'string' && !parsedStr.endsWith('Z') && !parsedStr.includes('+')) {
            parsedStr += 'Z';
        }
        const d = new Date(parsedStr);
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

            // Show all meetings (completed and processing)
            const allMeetings = (data.meetings || []);
            const totalReports = data.total_count || allMeetings.length;

            if (allMeetings.length === 0) {
                grid.innerHTML = '<div class="card" style="grid-column: 1/-1; padding:40px; text-align:center;"><p class="muted">No meetings yet. Reports will appear here once meeting processing is complete.</p></div>';
                if (refreshIcon) refreshIcon.classList.remove('spin');
                return;
            }

            allMeetings.forEach((m, index) => {
                const pdfPath = m.pdf_path;
                const isProcessing = !pdfPath || m.bot_status === 'PROCESSING';
                const pdfName = pdfPath ? pdfPath.split(/[\\/]/).pop() : null;
                const pdfLink = pdfName ? `${API_BASE}/download/pdf/${pdfName}` : null;

                let transcriptsName = null;
                if (m.transcripts_pdf_path) {
                    transcriptsName = m.transcripts_pdf_path.split(/[\\/]/).pop();
                } else if (pdfName) {
                    transcriptsName = pdfName.replace("Report_", "Transcripts_");
                }

                const generatedTime = timeAgo(m.updated_at || m.created_at);

                const card = document.createElement('div');
                card.className = 'report-card';
                card.style.display = 'flex';
                card.style.alignItems = 'center';
                card.style.justifyContent = 'space-between';
                card.style.padding = '20px';

                card.innerHTML = `
                    <div style="display:flex; align-items:center; gap:20px;">
                        <div class="report-number" style="font-size: 1.2rem; font-weight: 800; color: var(--accent-purple); opacity: 0.5;">#${totalReports - index}</div>
                        <div>
                            <h3 class="report-title" style="margin:0; font-size:1.1rem;">${m.title || 'Meeting Report'}</h3>
                            <span class="muted" style="font-size:0.85rem;">${isProcessing ? '🔄 AI Processing in progress...' : 'Generated ' + generatedTime}</span>
                        </div>
                    </div>
                    <div style="display:flex; gap:12px; align-items:center;">
                        ${isProcessing ? `
                            <div class="processing-tag" style="padding: 8px 16px; background: rgba(139, 92, 246, 0.1); border: 1px solid var(--accent-purple); color: var(--accent-purple); border-radius: 8px; font-size: 0.85rem;">
                                <i data-feather="loader" class="spin" style="width:14px; height:14px; vertical-align:middle; margin-right:6px;"></i> Processing Intelligence...
                            </div>
                        ` : `
                            <a href="javascript:void(0);" onclick="handleViewPdf('${pdfLink}', '${m.meeting_id}', ${m.is_summarized_paid})" class="primary-btn" style="text-decoration:none; padding: 10px 20px;">
                                <i data-feather="file-text" style="width:16px; margin-right:8px;"></i> View PDF
                            </a>
                            ${transcriptsName ? `<a href="${API_BASE}/download/transcripts_pdf/${transcriptsName}" target="_blank" class="secondary-btn" style="text-decoration:none; padding: 10px 20px;">
                                <i data-feather="align-left" style="width:16px; margin-right:8px;"></i> View Transcripts
                            </a>` : ''}
                        `}
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

    window.deleteReport = async function (mId) {
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

    // Payment & Upgrade Logic
    let currentMeetingToUnlock = null;
    let currentPdfToOpen = null;

    window.handleViewPdf = function (pdfUrl, meetingId, isPaid) {
        if (window.currentUserPlan === 'Pro' || isPaid) {
            window.open(pdfUrl, '_blank');
        } else {
            currentMeetingToUnlock = meetingId;
            currentPdfToOpen = pdfUrl;
            const modal = document.getElementById('payment-modal');
            if (modal) modal.classList.add('active');
        }
    };

    window.closePaymentModal = function () {
        const modal = document.getElementById('payment-modal');
        if (modal) modal.classList.remove('active');
    };

    window.processUpgrade = async function () {
        const btn = document.getElementById('confirm-upgrade-btn');
        const origHTML = btn.innerHTML;
        btn.innerHTML = '<i data-feather="loader" class="spin" style="width:16px; margin-right:8px;"></i> Initializing Gateway...';
        try {
            // Check if Razorpay script is loaded
            if (typeof Razorpay === 'undefined') {
                console.log("Razorpay script not found, attempting to load...");
                const script = document.createElement('script');
                script.src = "https://checkout.razorpay.com/v1/checkout.js";
                script.async = true;
                const scriptLoaded = new Promise((resolve, reject) => {
                    script.onload = resolve;
                    script.onerror = () => reject(new Error("Failed to load Razorpay script. Please check your internet connection or disable AdBlockers."));
                });
                document.head.appendChild(script);
                await scriptLoaded;
            }

            // 1. Create Order on Backend
            const res = await apiFetch("/payments/create_order", {
                method: 'POST',
                body: JSON.stringify({ item_type: 'pro_monthly' })
            });
            const orderData = await res.json();

            if (!orderData || orderData.status !== 'success') {
                throw new Error(orderData ? orderData.message : 'Server error');
            }

            // 2. Open Razorpay Checkout
            const options = {
                "key": orderData.key,
                "amount": orderData.amount,
                "currency": "INR",
                "name": "RENATA AI",
                "description": "Upgrade to Pro Plan",
                "order_id": orderData.order_id,
                "handler": async function (response) {
                    // 3. Verify Payment
                    btn.innerHTML = '<i data-feather="loader" class="spin" style="width:16px; margin-right:8px;"></i> Verifying...';
                    feather.replace();

                    const verifyRes = await apiFetch("/payments/verify", {
                        method: 'POST',
                        body: JSON.stringify({
                            razorpay_order_id: response.razorpay_order_id,
                            razorpay_payment_id: response.razorpay_payment_id,
                            razorpay_signature: response.razorpay_signature,
                            item_type: 'pro_monthly'
                        })
                    });
                    const verifyData = await verifyRes.json();

                    if (verifyData.status === 'success') {
                        alert("Upgrade Successful! Welcome to RENATA Pro.");
                        await loadUserProfile(); // This updates window.currentUserPlan and Sidebar
                        closePaymentModal();
                        loadReportsData();
                    } else {
                        alert("Verification Failed: " + verifyData.message);
                    }

                    btn.innerHTML = origHTML;
                    btn.disabled = false;
                    feather.replace();
                },
                "modal": {
                    "ondismiss": function () {
                        btn.innerHTML = origHTML;
                        btn.disabled = false;
                        feather.replace();
                    }
                },
                "prefill": {
                    "email": document.querySelector('.user-account')?.textContent || ""
                },
                "theme": { "color": "#8b5cf6" }
            };
            const rzp = new Razorpay(options);
            rzp.on('payment.failed', function (response) {
                alert("Payment Failed: " + response.error.description);
                btn.innerHTML = origHTML;
                btn.disabled = false;
                feather.replace();
            });
            rzp.open();

        } catch (err) {
            console.error("Payment Error:", err);
            alert("Payment Error: " + err.message + "\n\nTry refreshing the page or checking if an AdBlocker is blocking Razorpay.");
            btn.innerHTML = origHTML;
            btn.disabled = false;
            feather.replace();
        }
    };

    async function loadAnalyticsData() {
        try {
            const res = await apiFetch("/analytics/data");
            const stats = await res.json();

            const mVal = document.getElementById('ana-total-meetings');
            const rVal = document.getElementById('ana-total-reports');
            const uVal = document.getElementById('ana-upcoming');

            if (mVal) mVal.textContent = stats.total_meetings || 0;
            if (rVal) rVal.textContent = stats.total_reports || 0;
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
        // Refresh every 10 seconds for real-time feel
        analyticsInterval = setInterval(() => {
            if (window.location.hash === '#analytics') {
                loadAnalyticsData();
            } else {
                clearInterval(analyticsInterval);
                analyticsInterval = null;
            }
        }, 10000);
    }

    async function loadSearchStats() {
        try {
            const res = await apiFetch("/search/status");
            const data = await res.json();
            const pc = document.getElementById("report-count");
            if (pc) pc.textContent = (data.pdf_count || 0);
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
                
                item.innerHTML = `
                    <div class="history-item-content" onclick="app.selectSession('${s.session_id}')">
                        <i data-feather="message-square"></i>
                        <span>${s.title || 'Conversation'}</span>
                    </div>
                    <button class="delete-chat-btn" onclick="app.deleteSession(event, '${s.session_id}')" title="Delete Chat">
                        <i data-feather="trash-2" style="width:14px;height:14px;"></i>
                    </button>
                `;
                list.appendChild(item);
            });

            feather.replace();
        } catch (err) { console.error(err); }
    }

    async function deleteSession(event, sessionId) {
        event.stopPropagation();
        if (!confirm("Are you sure you want to delete this chat?")) return;
        
        try {
            const res = await apiFetch(`/chat/sessions/${sessionId}`, { method: 'DELETE' });
            if (res.ok) {
                if (currentSessionId === sessionId) {
                    currentSessionId = null;
                    localStorage.removeItem('renata_chat_session');
                    const box = document.getElementById('chat-box');
                    if (box) box.innerHTML = '<div class="message assistant"><p>How can I help you today?</p></div>';
                }
                loadChatSessions();
            }
        } catch (err) { console.error("Delete failed:", err); }
    }

    // Expose to global for onclick
    window.app = window.app || {};
    window.app.selectSession = selectSession;
    window.app.deleteSession = deleteSession;

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

    // ─── Bot session state ───
    let _botActive = false;          // True while a bot session is in-flight
    let _botPollingInterval = null;  // Dedicated polling loop after dispatch

    function _startBotPolling() {
        if (_botPollingInterval) return; // already running
        _botPollingInterval = setInterval(async () => {
            try {
                const res = await apiFetch('/live/status');
                const data = await res.json();
                if (data.active && data.status && data.status !== 'IDLE') {
                    _botActive = true;
                    showBotActive(data.status, data.note);
                    if (data.status === 'COMPLETED' || data.status === 'FAILED') {
                        _stopBotPolling();
                        // After a finished session, show idle after 6 seconds
                        setTimeout(() => {
                            _botActive = false;
                            showBotIdle();
                        }, 6000);
                    }
                } else if (!_botActive) {
                    // Server says idle and we never started — stop polling quietly
                    _stopBotPolling();
                }
                // If _botActive but server says idle: keep showing last state
                // (transient — server may lag a bit on first write)
            } catch (e) { console.warn('Bot poll error:', e); }
        }, 2000);
    }

    function _stopBotPolling() {
        if (_botPollingInterval) { clearInterval(_botPollingInterval); _botPollingInterval = null; }
    }

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

    // ─── Simplified Status Helpers ───
    function _setLog(msg) {
        const el = document.getElementById('bot-log-text');
        if (el) el.innerHTML = '» ' + msg;
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

        let logMsg = note || status;
        let badgeText = status;
        let badgeColor = '#f27121';
        let animated = true;

        if (status === 'JOIN_PENDING' || status === 'DISPATCHING') {
            badgeText = 'Dispatching...';
            badgeColor = '#f27121';
            logMsg = logMsg !== status ? logMsg : 'Sending request to bot pilot...';
            _stopLiveTimer();
        } else if (status === 'JOINING' || status === 'FETCHING' || status === 'CONNECTING' || status.includes('LOBBY') || status.includes('LOGIN')) {
            badgeText = 'Connecting...';
            badgeColor = '#f59e0b';
            _stopLiveTimer();
        } else if (status === 'CONNECTED' || status.includes('LIVE')) {
            badgeText = 'Joined Successfully';
            badgeColor = '#10b981';
            logMsg = logMsg !== status ? logMsg : 'Bot is LIVE in the meeting and capturing intelligence.';
            _startLiveTimer();
        } else if (status === 'PROCESSING') {
            badgeText = 'Processing...';
            badgeColor = '#8b5cf6';
            logMsg = logMsg !== status ? logMsg : 'Meeting ended. Generating your intelligence report...';
            _stopLiveTimer();
        } else if (status === 'COMPLETED') {
            badgeText = 'Completed';
            badgeColor = '#10b981';
            animated = false;
            logMsg = logMsg !== status ? logMsg : 'Report ready! Your meeting report is now available in the Reports tab.';
            _stopLiveTimer();
            if (window.location.hash === '#reports') loadReportsData();
            if (window.location.hash === '#dashboard') loadDashboardData();
        } else if (status === 'FAILED' || status === 'ERROR') {
            badgeText = 'Failed';
            badgeColor = '#ef4444';
            animated = false;
            _stopLiveTimer();
        }

        if (pulse) {
            pulse.style.background = badgeColor;
            pulse.style.animation = animated ? 'pulse 1.5s infinite' : 'none';
        }

        _setBadge(badgeText, badgeColor);
        _setLog(logMsg);

        // Handle Live Notes (Option B)
        if (note && (note.includes('LIVE_INSIGHTS:') || status === 'LIVE' || status === 'CONNECTED')) {
            const notesCard = document.getElementById('live-notes-card');
            const notesArea = document.getElementById('live-notes-area');
            if (notesCard && notesArea) {
                notesCard.style.display = 'block';
                if (note.includes('LIVE_INSIGHTS:')) {
                    const insights = note.replace('LIVE_INSIGHTS:', '').trim();
                    // Basic formatting for the live feed
                    notesArea.innerHTML = insights.split('\n')
                        .map(line => `<div style="margin-bottom:8px;">${line}</div>`)
                        .join('');
                    const syncBadge = document.getElementById('notes-sync-status');
                    if (syncBadge) syncBadge.textContent = 'UPDATED ' + new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
                }
            }
        }
    }

    function showBotIdle() {
        const idle = document.getElementById('bot-idle-msg');
        const tracker = document.getElementById('bot-tracker');
        const pulse = document.getElementById('bot-pulse');
        const notesCard = document.getElementById('live-notes-card');

        if (idle) idle.style.display = 'block';
        if (tracker) tracker.style.display = 'none';
        if (notesCard) notesCard.style.display = 'none';
        
        if (pulse) { pulse.style.background = '#64748b'; pulse.style.animation = 'none'; }
        _setBadge('Idle', 'var(--text-secondary)');
        _stopLiveTimer();
    }

    async function loadLiveStatus() {
        if (window.location.hash !== '#live') return;
        try {
            const res = await apiFetch("/live/status");
            const data = await res.json();
            if (data.active && data.status && data.status !== 'IDLE') {
                _botActive = true;
                showBotActive(data.status, data.note);
                // Ensure polling is running whenever we detect an active bot
                _startBotPolling();
            } else if (!_botActive) {
                // Only reset to idle if we are NOT in the middle of a local dispatch
                showBotIdle();
            }
        } catch (err) { }
    }

    let currentDispatchMeetingId = null;

    window.dispatchRenata = async (url) => {
        if (!url) return alert('Please enter a meeting link.');
        const btn = document.getElementById('manual-join');

        if (btn && btn.getAttribute('data-mode') === 'cancel') {
            btn.innerHTML = '<i data-feather="loader" style="width:15px;height:15px;margin-right:6px;display:inline;"></i> Canceling...';
            btn.disabled = true;
            feather.replace();
            try {
                const fd = new FormData();
                fd.append('meeting_id', currentDispatchMeetingId);
                const res = await apiFetch('/live/cancel', { method: 'POST', body: fd });
                const data = await res.json();
                if (data.success) {
                    btn.removeAttribute('data-mode');
                    btn.style.background = '';
                    btn.style.color = '';
                    btn.innerHTML = '<i data-feather="send" style="width:15px;height:15px;margin-right:6px;display:inline;"></i> Dispatch Renata';
                    feather.replace();
                    currentDispatchMeetingId = null;
                    showBotIdle();
                } else {
                    alert('Error canceling: ' + (data.message || 'Failed'));
                    btn.innerHTML = '<i data-feather="x-circle" style="width:15px;height:15px;margin-right:6px;display:inline;"></i> Cancel Dispatch';
                    feather.replace();
                }
            } catch (err) {
                alert('Server error.');
                btn.innerHTML = '<i data-feather="x-circle" style="width:15px;height:15px;margin-right:6px;display:inline;"></i> Cancel Dispatch';
                feather.replace();
            }
            finally { if (btn) btn.disabled = false; }
            return;
        }

        if (btn) { btn.disabled = true; btn.innerHTML = '<i data-feather="loader" style="width:15px;height:15px;margin-right:6px;display:inline;"></i> Dispatching...'; feather.replace(); }
        const fd = new FormData();
        fd.append('meeting_url', url);
        try {
            const res = await apiFetch('/live/join', { method: 'POST', body: fd });
            const data = await res.json();
            if (data.success) {
                currentDispatchMeetingId = data.meeting_id;
                _botActive = true;          // Mark session as active immediately
                showBotActive('JOIN_PENDING', data.message);
                _stopBotPolling();          // Reset any old poll
                _startBotPolling();         // Start fresh dedicated polling loop

                if (window.closeModal) window.closeModal();

                if (btn) {
                    btn.setAttribute('data-mode', 'cancel');
                    btn.style.background = '#ef4444';
                    btn.style.color = 'white';
                    btn.innerHTML = '<i data-feather="x-circle" style="width:15px;height:15px;margin-right:6px;display:inline;"></i> Cancel Dispatch';
                    feather.replace();
                }
            } else {
                alert('Error: ' + (data.message || 'Failed to dispatch.'));
                if (btn) { btn.innerHTML = '<i data-feather="send" style="width:15px;height:15px;margin-right:6px;display:inline;"></i> Dispatch Renata'; feather.replace(); }
            }
        } catch (err) {
            alert('Server error. Is your pilot script running?');
            if (btn) { btn.innerHTML = '<i data-feather="send" style="width:15px;height:15px;margin-right:6px;display:inline;"></i> Dispatch Renata'; feather.replace(); }
        }
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

    const syncBtn = document.getElementById('sync-pdf-btn');
    if (syncBtn) {
        syncBtn.addEventListener('click', async () => {
            const origHTML = syncBtn.innerHTML;
            syncBtn.innerHTML = '<i data-feather="loader" style="width:14px;height:14px;"></i> Syncing...';
            syncBtn.disabled = true;
            feather.replace();

            try {
                const res = await apiFetch("/search/index", { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    syncBtn.innerHTML = '<i data-feather="check" style="width:14px;height:14px;"></i> Synced!';
                    const rc = document.getElementById('report-count');
                    if (rc) rc.textContent = data.indexed_segments || 0;
                } else {
                    syncBtn.innerHTML = origHTML;
                    alert('Sync error: ' + (data.message || 'Failed'));
                }
            } catch (e) {
                syncBtn.innerHTML = origHTML;
                alert('Sync action failed: ' + e.message);
            }
            feather.replace();
            setTimeout(() => {
                syncBtn.innerHTML = origHTML;
                syncBtn.disabled = false;
                feather.replace();
            }, 3000);
        });
    }

    const refNotesBtn = document.getElementById('refresh-notes-btn');
    if (refNotesBtn) refNotesBtn.onclick = () => loadNotesData();

    async function loadNotesData() {
        const grid = document.getElementById('notes-list');
        if (!grid) return;
        
        const refreshIcon = document.getElementById('refresh-notes-btn')?.querySelector('i');
        if (refreshIcon) refreshIcon.classList.add('spin');

        try {
            const res = await apiFetch("/reports_data");
            const data = await res.json();
            grid.innerHTML = '';

            const allMeetings = (data.meetings || []);
            if (allMeetings.length === 0) {
                grid.innerHTML = '<div class="card" style="padding:40px; text-align:center;"><p class="muted">No meeting notes captured yet. They will appear here once you join a live meeting.</p></div>';
                return;
            }

            allMeetings.forEach((m) => {
                const note = m.bot_status_note || '';
                const hasInsights = note.includes('LIVE_INSIGHTS:');
                const insights = hasInsights ? note.replace('LIVE_INSIGHTS:', '').trim() : 'No live insights were captured for this session.';
                const timeStr = m.start_time;

                const card = document.createElement('div');
                card.className = 'card';
                card.style.marginBottom = '16px';
                card.style.padding = '20px';
                card.style.borderLeft = hasInsights ? '4px solid var(--accent-orange)' : '4px solid var(--border-color)';
                
                card.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
                        <div>
                            <h3 style="margin:0; font-size:1.1rem; color:var(--text-main);">${m.title || 'Untitled Meeting'}</h3>
                            <span class="muted" style="font-size:0.85rem;">${timeStr}</span>
                        </div>
                        <span class="badge ${hasInsights ? 'orange' : 'gray'}" style="font-size:0.7rem;">
                            ${hasInsights ? 'AI CAPTURED' : 'EMPTY'}
                        </span>
                    </div>
                    <div style="background:rgba(242,113,33,0.03); padding:15px; border-radius:8px; font-size:0.92rem; line-height:1.6; color:#334155; border:1px dashed rgba(242,113,33,0.15);">
                        ${insights.split('\n').map(line => `<div style="margin-bottom:4px;">${line}</div>`).join('')}
                    </div>
                `;
                grid.appendChild(card);
            });
            feather.replace();
        } catch (err) {
            console.error("Notes Error:", err);
        } finally {
            if (refreshIcon) setTimeout(() => refreshIcon.classList.remove('spin'), 500);
        }
    }

    const refGmailBtn = document.getElementById('refresh-gmail-btn');
    if (refGmailBtn) refGmailBtn.onclick = () => loadGmailData();

    // Tab Switching Logic
    let currentGmailTab = "briefs";
    document.querySelectorAll('.gmail-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.gmail-tab').forEach(t => {
                t.classList.remove('active');
                t.style.borderBottom = "none";
                t.style.color = "#64748b";
            });
            tab.classList.add('active');
            tab.style.borderBottom = "2px solid var(--accent-purple)";
            tab.style.color = "var(--accent-purple)";
            currentGmailTab = tab.dataset.tab;
            loadGmailData();
        });
    });

    async function loadGmailData() {
        const grid = document.getElementById('gmail-briefs-list');
        if (!grid) return;
        
        const refreshIcon = document.getElementById('refresh-gmail-btn')?.querySelector('i');
        if (refreshIcon) refreshIcon.classList.add('spin');

        try {
            const res = await apiFetch("/api/gmail_intelligence");
            const data = await res.json();
            grid.innerHTML = '';

            const briefs = data.briefs || [];
            const inbox = data.recent_emails || [];

            if (currentGmailTab === "briefs") {
                // 1. SECTION: Meeting Briefs
                if (briefs.length > 0) {
                    briefs.forEach((b) => {
                        const card = document.createElement('div');
                        card.className = 'card';
                        card.style.marginBottom = '20px';
                        card.style.padding = '24px';
                        card.style.borderLeft = '4px solid var(--accent-purple)';
                        card.style.background = 'linear-gradient(to right, rgba(139, 92, 246, 0.03), transparent)';
                        
                        card.innerHTML = `
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px;">
                                <div>
                                    <h3 style="margin:0; font-size:1.2rem; color:var(--text-main);">${b.meeting_title}</h3>
                                    <span class="muted" style="font-size:0.85rem; display:block; margin-top:4px;">
                                        Starts ${b.start_time}
                                    </span>
                                </div>
                                <span class="badge purple">AI REPORT READY</span>
                            </div>
                            <div style="background:white; padding:18px; border-radius:12px; font-size:0.95rem; line-height:1.7; color:#1e293b; border:1px solid rgba(139, 92, 246, 0.1);">
                                ${b.insights.split('\n').map(line => `<div style="margin-bottom:6px;">${line}</div>`).join('')}
                            </div>
                        `;
                        grid.appendChild(card);
                    });
                } else {
                    grid.innerHTML = `
                        <div class="card" style="padding:60px; text-align:center;">
                            <i data-feather="smile" style="width:48px; height:48px; color:var(--accent-purple); opacity:0.3; margin-bottom:16px;"></i>
                            <h3>All Clear!</h3>
                            <p class="muted">No complex context reports found for upcoming meetings today.</p>
                        </div>
                    `;
                }
            } else {
                // 2. SECTION: Recent Inbox
                if (inbox.length > 0) {
                    inbox.forEach((em) => {
                        const card = document.createElement('div');
                        card.className = 'card';
                        card.style.marginBottom = '12px';
                        card.style.padding = '15px';
                        card.style.display = 'flex';
                        card.style.gap = '15px';
                        card.style.alignItems = 'center';
                        
                        card.innerHTML = `
                            <div style="width:40px; height:40px; border-radius:50%; background:rgba(0,0,0,0.03); display:flex; align-items:center; justify-content:center; flex-shrink:0;">
                                <i data-feather="mail" style="width:18px; color:#64748b;"></i>
                            </div>
                            <div style="flex:1; overflow:hidden;">
                                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                                    <strong style="font-size:0.95rem; color:var(--text-main); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${em.subject}</strong>
                                    <span class="muted" style="font-size:0.75rem;">${em.from.split('<')[0].trim()}</span>
                                </div>
                                <p class="muted" style="font-size:0.85rem; margin:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${em.snippet}</p>
                            </div>
                        `;
                        grid.appendChild(card);
                    });
                } else {
                    grid.innerHTML = '<div class="card" style="padding:40px; text-align:center;"><p class="muted">Your inbox is empty or restricted.</p></div>';
                }
            }

            feather.replace();
        } catch (err) {
            console.error("Gmail Intel Error:", err);
            grid.innerHTML = '<div class="card" style="padding:40px; text-align:center; color: #ef4444;"><p>Error loading intelligence: ' + err.message + '</p></div>';
        } finally {
            if (refreshIcon) setTimeout(() => refreshIcon.classList.remove('spin'), 500);
        }
    }

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

    // SETTINGS FORMS
    const profileForm = document.getElementById('profile-form');
    if (profileForm) {
        profileForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = profileForm.querySelector('button[type="submit"]');
            const originalText = btn.textContent;
            btn.textContent = 'Saving...';
            btn.disabled = true;

            const newName = document.getElementById('pref-user-name').value;
            try {
                const res = await apiFetch('/api/profile/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newName })
                });
                if (!res.ok) {
                    const errText = await res.text();
                    throw new Error(`Server returned status ${res.status}: ${errText.substring(0, 100)}`);
                }
                const data = await res.json();
                if (data.success) {
                    btn.textContent = 'Saved!';
                    setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
                    // Update ALL Sidebar/Profile Name elements
                    document.querySelectorAll('.user-name').forEach(el => el.textContent = newName);
                } else {
                    throw new Error(data.error || 'Failed to save');
                }
            } catch (err) {
                alert('Error updating profile: ' + err.message);
                btn.textContent = originalText;
                btn.disabled = false;
            }
        });
    }

    const prefForm = document.getElementById('settings-preferences-form');
    if (prefForm) {
        prefForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = prefForm.querySelector('button[type="submit"]');
            const originalText = btn.textContent;
            btn.textContent = 'Saving...';
            btn.disabled = true;

            const autoJoin = document.getElementById('pref-auto-join').checked;

            try {
                const res = await apiFetch('/api/profile/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        auto_join: autoJoin
                    })
                });
                if (!res.ok) {
                    const errText = await res.text();
                    throw new Error(`Server returned status ${res.status}: ${errText.substring(0, 100)}`);
                }
                const data = await res.json();
                if (data.success) {
                    btn.textContent = 'Saved!';
                    setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
                } else {
                    throw new Error(data.error || 'Failed to save');
                }
            } catch (err) {
                alert('Error submitting preferences: ' + err.message);
                btn.textContent = originalText;
                btn.disabled = false;
            }
        });
    }

    // AUTO-REFRESH DATA
    // Live status is handled by _startBotPolling() for active sessions.
    // The global interval here only does a gentle background probe on
    // page load / navigation (does NOT override an active dispatch).
    setInterval(() => {
        const currentHash = window.location.hash.replace('#', '');
        if (currentHash === 'analytics') {
            loadAnalyticsData();
            startAnalyticsAutoRefresh();
        }
        // Only probe live status if no dedicated polling loop is already running
        if ((currentHash === 'live' || currentHash === 'dashboard') && !_botPollingInterval) {
            loadLiveStatus();
        }
    }, 5000);

    // Initial load priorities
    loadUserProfile();
    loadDashboardData();
    loadAnalyticsData(); // Load analytics fast on startup
    loadLiveStatus();

    // --- HELP & SUPPORT TICKETS ---

    async function loadHelpData() {
        const list = document.getElementById('active-tickets-list');
        if (!list) return;

        try {
            const res = await apiFetch("/help/tickets");
            const data = await res.json();
            
            if (data.success && data.tickets && data.tickets.length > 0) {
                list.innerHTML = '';
                data.tickets.forEach(ticket => {
                    // Try to parse the date nicely
                    let dateStr = "Recently";
                    try {
                        dateStr = new Date(ticket.created_at).toLocaleDateString(undefined, {
                            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                        });
                    } catch(e) {}

                    const item = document.createElement('div');
                    item.className = 'card';
                    item.style.padding = '16px';
                    item.style.marginBottom = '12px';
                    item.style.borderLeft = '4px solid var(--accent-purple)';
                    item.style.background = 'rgba(139, 92, 246, 0.05)';
                    item.innerHTML = `
                        <div style="display:flex; justify-content:space-between; margin-bottom:8px; align-items: flex-start;">
                            <strong style="color:var(--text-main); font-size: 1rem;">${ticket.subject}</strong>
                            <span class="muted" style="font-size:0.75rem;">${dateStr}</span>
                        </div>
                        <p class="muted" style="font-size:0.9rem; margin:0; line-height: 1.5;">${ticket.query}</p>
                        <div style="margin-top:12px; font-size:0.8rem; font-weight:600; color:#f59e0b; display: flex; align-items: center; gap: 8px;">
                            <span class="status-dot pulse" style="background:#f59e0b; width: 8px; height: 8px;"></span> Open Ticket (Pending)
                        </div>
                    `;
                    list.appendChild(item);
                });
            } else {
                list.innerHTML = `
                    <div class="muted" style="text-align: center; padding: 40px;">
                        <i data-feather="check-circle" style="width: 32px; height: 32px; margin-bottom: 12px; opacity: 0.5;"></i>
                        <p>No active issues. You're all set!</p>
                    </div>
                `;
            }
            feather.replace();
        } catch (e) {
            console.error("Failed to load tickets:", e);
        }
    }

    const helpForm = document.getElementById('help-ticket-form');
    if (helpForm) {
        helpForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('submit-ticket-btn');
            const subject = document.getElementById('ticket-subject').value;
            const query = document.getElementById('ticket-query').value;

            if (!subject || !query) return;

            const origHTML = btn.innerHTML;
            btn.innerHTML = '<i data-feather="loader" class="spin" style="width:16px; margin-right:8px;"></i> Submitting...';
            btn.disabled = true;
            feather.replace();

            const formData = new FormData();
            formData.append('subject', subject);
            formData.append('query', query);

            try {
                const res = await apiFetch("/help/tickets", {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (data.success) {
                    alert("Ticket raised successfully! Confirmation sent to team.");
                    helpForm.reset();
                    await loadHelpData();
                } else {
                    alert("Failed to raise ticket: " + (data.message || "Unknown error"));
                }
            } catch (err) {
                alert("Network error submitting ticket: " + err.message);
            } finally {
                btn.innerHTML = origHTML;
                btn.disabled = false;
                feather.replace();
            }
        });
    }
});

// --- NEW TOGGLE HANDLERS (Anil Sir Feedback) ---

window.toggleGlobalBot = async function(el) {
    const enabled = el.checked;
    console.log("Setting global bot auto-join:", enabled);
    
    // UI Update for all meeting toggles if turning OFF
    if (!enabled) {
        document.querySelectorAll('#calendar-grid .switch input').forEach(inp => {
            if (inp.checked) {
                inp.checked = false;
                // Trigger label update for consistency
                const container = inp.closest('.toggle-container');
                const label = container.querySelector('span');
                if (label) {
                    label.textContent = 'Skipped';
                    label.style.color = 'var(--text-secondary)';
                }
            }
        });
    }

    try {
        const res = await apiFetch("/settings/toggle_global_bot", {
            method: 'POST',
            body: JSON.stringify({ enabled })
        });
        const data = await res.json();
        if (data.success) {
            const settingsCheck = document.getElementById('pref-auto-join');
            if (settingsCheck) settingsCheck.checked = enabled;
        } else {
            alert("Failed to update global switch");
            el.checked = !enabled;
        }
    } catch (err) {
        console.error(err);
        el.checked = !enabled;
    }
};

window.toggleMeetingBot = async function(meetingId, enabled, el) {
    console.log(`Setting bot for meeting ${meetingId}:`, enabled);
    
    // UI Update immediately
    const parent = el.closest('.toggle-container');
    const label = parent.querySelector('span');
    if (label) {
        label.textContent = enabled ? 'Active' : 'Skipped';
        label.style.color = enabled ? 'var(--accent-green)' : 'var(--text-secondary)';
    }
    
    try {
        const card = el.closest('.meeting-card');
        const summary = card.querySelector('.meeting-title').textContent;
        const startTime = card.querySelector('.meeting-time').textContent;

        const res = await apiFetch("/meetings/toggle_bot", {
            method: 'POST',
            body: JSON.stringify({ 
                meeting_id: meetingId, 
                enabled,
                summary,
                start_time: startTime
            })
        });
        const data = await res.json();
        if (!data.success) {
            alert("Failed to update meeting preference");
        }
    } catch (err) {
        console.error(err);
    }
};


});
