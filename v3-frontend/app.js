// RENATA Frontend Logic
const API_BASE = "https://inimitably-cytotropic-fatimah.ngrok-free.dev";

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
        });
    });

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

            const response = await fetch(`${API_BASE}/live/join`, {
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

            const response = await fetch(`${API_BASE}/search/ask`, {
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
