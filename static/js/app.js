/**
 * HabitFlow Core Frontend Application Logic
 * =========================================
 * Provides unified state management, API communications, authentication state,
 * gamification celebrations, AI coaching integrations, and interactive chart bindings.
 */

// Global State
let allHabitsCache = [];
let activeHabitFilter = 'all';
let habitSearchQuery = '';
let completionChartInstance = null;
let moodChartInstance = null;

/**
 * Sanitizes unsafe input strings to prevent Cross-Site Scripting (XSS).
 * @param {*} unsafe - Input string or value.
 * @returns {string} Escaped HTML string.
 */
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ============================================================================
// 1. Authentication & API Helpers
// ============================================================================

/**
 * Retrieves the stored JWT authentication token.
 * @returns {string|null} The active token or null if unauthenticated.
 */
function getToken() {
    return localStorage.getItem('token');
}

/**
 * Retrieves stored user metadata.
 * @returns {Object} User details object.
 */
function getUser() {
    try {
        return JSON.parse(localStorage.getItem('user') || '{}');
    } catch {
        return {};
    }
}

/**
 * Returns standard authorization headers for fetch requests.
 * @returns {Object} Headers dictionary.
 */
function getAuthHeaders() {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
}

/**
 * Centralized API request wrapper with authentication error handling.
 * @param {string} endpoint - The API route path (e.g. '/api/habits').
 * @param {string} [method='GET'] - HTTP verb ('GET', 'POST', 'PUT', 'DELETE').
 * @param {Object|null} [data=null] - Request JSON payload.
 * @returns {Promise<Object|null>} Parsed JSON response or null on error.
 */
async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method,
        headers: getAuthHeaders()
    };

    if (data && method !== 'GET') {
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(endpoint, options);

        if (response.status === 401) {
            // Token has expired or is invalid
            clearAuth();
            if (!window.location.pathname.includes('/login') && !window.location.pathname.includes('/register') && window.location.pathname !== '/') {
                window.location.href = '/login';
            }
            return null;
        }

        const json = await response.json();
        if (!response.ok) {
            console.warn(`API Error [${endpoint}]:`, json.message || response.statusText);
            showToast(json.message || 'Action failed', 'danger');
            return null;
        }

        return json;
    } catch (error) {
        console.error(`Network Failure [${endpoint}]:`, error);
        showToast('Network error. Please verify server connection.', 'danger');
        return null;
    }
}

/**
 * Enforces client-side authentication guard for protected views.
 */
function checkAuth() {
    if (!getToken()) {
        window.location.href = '/login';
    }
}

/**
 * Clears stored authentication credentials.
 */
function clearAuth() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
}

/**
 * Logs out the user, notifies backend, and redirects to login view.
 */
async function logout() {
    try {
        await apiCall('/api/auth/logout', 'POST');
    } catch (e) {
        // Ignore server error on logout
    }
    clearAuth();
    updateNavbarState();
    window.location.href = '/login';
}

/**
 * Synchronizes navbar elements based on whether a valid session token exists.
 */
function updateNavbarState() {
    const token = getToken();
    const user = getUser();

    const authOnlyElements = document.querySelectorAll('.auth-only');
    const guestOnlyElements = document.querySelectorAll('.guest-only');

    if (token) {
        authOnlyElements.forEach(el => el.style.display = '');
        guestOnlyElements.forEach(el => el.style.display = 'none');

        const nameEl = document.getElementById('navUserName');
        if (nameEl && user.name) nameEl.textContent = user.name;

        const levelEl = document.getElementById('navUserLevel');
        if (levelEl && user.level) levelEl.textContent = user.level;

        const xpEl = document.getElementById('navUserXP');
        if (xpEl && user.xp_points !== undefined) xpEl.textContent = user.xp_points;
    } else {
        authOnlyElements.forEach(el => el.style.display = 'none');
        guestOnlyElements.forEach(el => el.style.display = '');
    }
}

// ============================================================================
// 2. Dark Mode & UI Feedback
// ============================================================================

/**
 * Loads and applies dark mode preference from local storage.
 */
function loadDarkMode() {
    const isDark = localStorage.getItem('darkMode') === 'true';
    if (isDark) {
        document.body.classList.add('dark-mode');
    } else {
        document.body.classList.remove('dark-mode');
    }
}

/**
 * Toggles dark mode and persists preference.
 */
function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    const isDark = document.body.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDark);
}

/**
 * Displays a non-intrusive floating toast notification.
 * @param {string} message - Notification text.
 * @param {string} [type='info'] - 'success', 'info', 'warning', 'danger'.
 * @param {number} [duration=3500] - Lifespan in milliseconds.
 */
function showToast(message, type = 'info', duration = 3500) {
    let container = document.getElementById('toastNotificationContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastNotificationContainer';
        container.className = 'position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
    }

    const toastEl = document.createElement('div');
    toastEl.className = `alert alert-${type} alert-dismissible fade show shadow-lg mb-2`;
    toastEl.style.minWidth = '300px';
    toastEl.setAttribute('role', 'alert');
    toastEl.innerHTML = `
        <div class="d-flex align-items-center justify-content-between gap-2">
            <div>${escapeHtml(message)}</div>
            <button type="button" class="btn-close ms-2" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;

    container.appendChild(toastEl);

    setTimeout(() => {
        toastEl.classList.remove('show');
        setTimeout(() => toastEl.remove(), 300);
    }, duration);
}

// ============================================================================
// 3. Dashboard Initialization
// ============================================================================

/**
 * Initializes the main dashboard view.
 */
async function initDashboard() {
    checkAuth();
    updateNavbarState();

    const user = getUser();
    const userNameEl = document.getElementById('userName');
    if (userNameEl && user.name) {
        userNameEl.textContent = user.name;
    }

    // Set formatted human-readable date
    const todayEl = document.getElementById('todayDateDisplay');
    if (todayEl) {
        const now = new Date();
        const options = { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' };
        todayEl.textContent = now.toLocaleDateString('en-US', options);
    }

    // Load data in parallel
    await Promise.all([
        loadUserStats(),
        loadHabits(),
        loadMood(),
        loadAICoachMessage(),
        loadWeeklySummary(),
        loadMoodInsights(),
        loadBadges(),
        loadAnalytics()
    ]);
}

// ============================================================================
// 4. Statistics & Gamification
// ============================================================================

/**
 * Fetches and populates top summary statistics cards.
 */
async function loadUserStats() {
    const res = await apiCall('/api/analytics');
    if (!res) return;

    const summary = res.summary || {};
    const streakEl = document.getElementById('streakDays');
    if (streakEl) streakEl.textContent = summary.combined_streak || 0;

    const compEl = document.getElementById('totalCompletions');
    if (compEl) compEl.textContent = summary.total_completions || 0;

    const consEl = document.getElementById('consistency');
    if (consEl) consEl.textContent = (summary.consistency_score || 0) + '%';

    const habitsEl = document.getElementById('totalHabits');
    if (habitsEl) habitsEl.textContent = summary.total_habits || 0;

    // Update level and XP in localStorage and navbar
    const user = getUser();
    if (res.user_level) user.level = res.user_level;
    if (res.user_xp !== undefined) user.xp_points = res.user_xp;
    localStorage.setItem('user', JSON.stringify(user));
    updateNavbarState();
}

/**
 * Loads all achievement badges from backend and renders unlocked state.
 */
async function loadBadges() {
    const container = document.getElementById('badgesList');
    if (!container) return;

    const res = await apiCall('/api/auth/badges');
    if (!res || !res.badges) {
        container.innerHTML = '<div class="text-muted small text-center py-2">No badges available</div>';
        return;
    }

    const badges = res.badges;
    const earnedCount = badges.filter(b => b.unlocked).length;
    const badgeCounter = document.getElementById('badgesEarnedCount');
    if (badgeCounter) {
        badgeCounter.textContent = `${earnedCount} / ${badges.length} Unlocked`;
    }

    container.innerHTML = badges.map(b => `
        <div class="badge-item ${b.unlocked ? 'unlocked' : 'locked'}" title="${escapeHtml(b.name)}: ${escapeHtml(b.description)}${b.earned_at ? ' (Unlocked ' + escapeHtml(b.earned_at.split('T')[0]) + ')' : ' (Locked)'}">
            <div class="badge-icon display-6">${escapeHtml(b.icon)}</div>
            <div class="badge-name mt-1">${escapeHtml(b.name)}</div>
            <small class="badge-desc text-muted">${b.unlocked ? '✓ Unlocked' : '🔒 Locked'}</small>
        </div>
    `).join('');
}

// ============================================================================
// 5. Habits Management
// ============================================================================

/**
 * Loads and renders the list of habits for today.
 */
async function loadHabits() {
    const listEl = document.getElementById('habitsList');
    if (!listEl) return;

    const res = await apiCall('/api/habits');
    if (!res || !res.habits) {
        listEl.innerHTML = '<div class="text-center py-4 text-muted">Failed to load habits.</div>';
        return;
    }

    allHabitsCache = res.habits;
    renderHabitsList();
}

/**
 * Renders habits into DOM according to active filter ('all', 'pending', 'completed').
 */
function renderHabitsList() {
    const listEl = document.getElementById('habitsList');
    if (!listEl) return;

    let filtered = allHabitsCache;
    if (activeHabitFilter === 'pending') {
        filtered = allHabitsCache.filter(h => h.today_status !== 'completed');
    } else if (activeHabitFilter === 'completed') {
        filtered = allHabitsCache.filter(h => h.today_status === 'completed');
    }

    if (habitSearchQuery) {
        const query = habitSearchQuery.toLowerCase();
        filtered = filtered.filter(h => 
            (h.title && h.title.toLowerCase().includes(query)) ||
            (h.category && h.category.toLowerCase().includes(query))
        );
    }

    if (filtered.length === 0) {
        listEl.innerHTML = `
            <div class="text-center py-5 text-muted">
                <i class="fas fa-clipboard-list fa-3x mb-3 text-secondary opacity-50"></i>
                <p class="mb-2 fw-semibold">No habits found.</p>
                <small>${habitSearchQuery ? 'Try clearing your search term.' : 'Click "New Habit" or use "AI Recommendations" to add one!'}</small>
            </div>
        `;
        return;
    }

    listEl.innerHTML = filtered.map(habit => {
        const isCompleted = habit.today_status === 'completed';
        const isSkipped = habit.today_status === 'skipped';
        const isMissed = habit.today_status === 'missed';

        let statusClass = 'border-start-primary';
        if (isCompleted) statusClass = 'completed';
        else if (isSkipped) statusClass = 'skipped';
        else if (isMissed) statusClass = 'missed';

        return `
            <div class="habit-item ${statusClass} shadow-sm" id="habit-${habit.id}">
                <div class="habit-icon p-2 rounded-3 bg-light text-center fs-3">${escapeHtml(habit.icon || '✨')}</div>
                <div class="habit-content">
                    <div class="d-flex align-items-center gap-2 mb-1 flex-wrap">
                        <a href="/habit/${habit.id}" class="habit-title text-decoration-none text-dark fw-bold">${escapeHtml(habit.title)}</a>
                        <span class="badge bg-light text-secondary border rounded-pill small">${escapeHtml(habit.category)}</span>
                        ${!habit.is_scheduled_today ? '<span class="badge bg-secondary-subtle text-muted rounded-pill small">Not Scheduled Today</span>' : ''}
                    </div>
                    <div class="d-flex align-items-center gap-3 text-muted small flex-wrap">
                        <span>
                            ${habit.current_streak > 0 
                                ? `<span class="text-warning fw-semibold"><i class="fas fa-fire me-1"></i>${habit.current_streak}d streak</span>` 
                                : '<span class="text-muted"><i class="fas fa-seedling me-1"></i>Streak ready</span>'}
                        </span>
                        <span>•</span>
                        <span>${habit.total_completions || 0} completions</span>
                        <span>•</span>
                        <span>${habit.consistency_score || 0}% consistency</span>
                    </div>
                </div>
                <div class="habit-actions d-flex align-items-center gap-2">
                    ${!isCompleted ? `
                        <button class="btn btn-sm btn-success rounded-pill px-3 shadow-sm" onclick="completeHabit(${habit.id})" title="Mark Done">
                            <i class="fas fa-check me-1"></i> Done
                        </button>
                    ` : `
                        <span class="badge bg-success-subtle text-success px-3 py-2 rounded-pill fw-semibold border border-success-subtle">
                            <i class="fas fa-check-circle me-1"></i> Completed
                        </span>
                    `}
                    ${!isSkipped && !isCompleted ? `
                        <button class="btn btn-sm btn-outline-secondary rounded-pill px-2" onclick="skipHabit(${habit.id})" title="Excuse Habit">
                            Skip
                        </button>
                    ` : ''}
                    ${!isMissed && !isCompleted ? `
                        <button class="btn btn-sm btn-outline-danger rounded-pill px-2" onclick="missHabit(${habit.id})" title="Mark Missed">
                            Miss
                        </button>
                    ` : ''}
                    <a href="/habit/${habit.id}" class="btn btn-sm btn-outline-primary rounded-circle p-2" title="Analytics & History">
                        <i class="fas fa-chart-bar"></i>
                    </a>
                    <button class="btn btn-sm btn-outline-danger rounded-circle p-2" onclick="deleteHabit(${habit.id})" title="Delete Habit">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * Filters habits list in real-time as user types into search input.
 */
function handleHabitSearch(query) {
    habitSearchQuery = (query || '').trim();
    renderHabitsList();
}

/**
 * Filters habits list tabs.
 */
function filterHabits(filterType, btnEl) {
    activeHabitFilter = filterType;
    document.querySelectorAll('#habitFilterGroup button').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    renderHabitsList();
}

/**
 * Marks habit completed today.
 */
async function completeHabit(habitId) {
    const res = await apiCall(`/api/habits/${habitId}/complete`, 'POST');
    if (!res) return;

    confetti({
        particleCount: 80,
        spread: 60,
        origin: { y: 0.7 }
    });

    showToast(`+${res.xp_earned} XP earned! 🎉`, 'success');

    if (res.streak_message) {
        showToast(res.streak_message, 'info');
    }

    if (res.badges_unlocked && res.badges_unlocked.length > 0) {
        res.badges_unlocked.forEach(b => {
            showToast(`Achievement Unlocked: ${b.icon} ${b.name}!`, 'success', 5000);
        });
        await loadBadges();
    }

    await loadHabits();
    await loadUserStats();
}

/**
 * Excuses habit for today.
 */
async function skipHabit(habitId) {
    const res = await apiCall(`/api/habits/${habitId}/skip`, 'POST');
    if (!res) return;

    showToast('Habit excused for today. Streak preserved!', 'info');
    await loadHabits();
    await loadUserStats();
}

/**
 * Marks habit missed today.
 */
async function missHabit(habitId) {
    const res = await apiCall(`/api/habits/${habitId}/miss`, 'POST');
    if (!res) return;

    showToast('Marked as missed. Rebuild momentum tomorrow!', 'warning');
    await loadHabits();
    await loadUserStats();
}

/**
 * Deletes habit with confirmation.
 */
async function deleteHabit(habitId) {
    if (!confirm('Are you sure you want to remove this habit?')) return;
    const res = await apiCall(`/api/habits/${habitId}`, 'DELETE');
    if (res) {
        showToast('Habit removed', 'info');
        await loadHabits();
        await loadUserStats();
    }
}

/**
 * Submits new habit creation modal form.
 */
async function createHabit() {
    const title = document.getElementById('habitTitle').value.trim();
    const category = document.getElementById('habitCategory').value;
    const icon = document.getElementById('habitIcon').value.trim() || '✨';
    const reminderTime = document.getElementById('habitReminderTime').value || null;

    const checkedBoxes = document.querySelectorAll('#frequencyOptions input:checked');
    const frequency = Array.from(checkedBoxes).map(cb => cb.value);

    if (!title) {
        showToast('Please specify a habit title', 'warning');
        return;
    }
    if (frequency.length === 0) {
        showToast('Please select at least one scheduled day', 'warning');
        return;
    }

    const payload = {
        title,
        category,
        icon,
        frequency,
        reminder_time: reminderTime
    };

    const res = await apiCall('/api/habits', 'POST', payload);
    if (res) {
        showToast('Habit created successfully! 🔥', 'success');
        document.getElementById('newHabitForm').reset();

        const modalEl = document.getElementById('newHabitModal');
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) modalInstance.hide();

        await loadHabits();
        await loadUserStats();
    }
}

// ============================================================================
// 6. Mood Tracking
// ============================================================================

/**
 * Fetches and highlights today's logged mood if already recorded.
 */
async function loadMood() {
    const res = await apiCall('/api/mood/today');
    if (!res || !res.mood) return;

    const currentMood = res.mood.mood;
    document.querySelectorAll('.mood-option').forEach(el => el.classList.remove('selected'));
    const target = document.querySelector(`[onclick="logMood('${currentMood}')"]`);
    if (target) target.classList.add('selected');

    const noteInput = document.getElementById('moodNoteInput');
    if (noteInput && res.mood.note) {
        noteInput.value = res.mood.note;
    }
}

/**
 * Logs or updates mood for today.
 */
async function logMood(mood) {
    document.querySelectorAll('.mood-option').forEach(el => el.classList.remove('selected'));
    const target = document.querySelector(`[onclick="logMood('${mood}')"]`);
    if (target) target.classList.add('selected');

    const note = document.getElementById('moodNoteInput')?.value.trim() || null;
    const res = await apiCall('/api/mood', 'POST', { mood, note });
    if (!res) return;

    const feedbackEl = document.getElementById('moodFeedback');
    const messages = {
        happy: "Feeling good! Channel this positive momentum into your daily habits.",
        neutral: "Balanced and centered. Consistent small steps create great results.",
        sad: "Be gentle with yourself today. Even completing one micro-habit is a victory."
    };
    if (feedbackEl) {
        feedbackEl.textContent = messages[mood] || "Mood logged.";
    }

    await loadMoodInsights();
}

/**
 * Saves note attached to selected mood.
 */
async function saveMoodWithNote() {
    const selectedOption = document.querySelector('.mood-option.selected');
    let mood = 'neutral';
    if (selectedOption) {
        if (selectedOption.textContent.includes('Happy')) mood = 'happy';
        else if (selectedOption.textContent.includes('Sad')) mood = 'sad';
    }
    const note = document.getElementById('moodNoteInput')?.value.trim();
    const res = await apiCall('/api/mood', 'POST', { mood, note });
    if (res) {
        showToast('Mood note saved!', 'success');
    }
}

// ============================================================================
// 7. AI Coach Features
// ============================================================================

/**
 * Loads today's AI coaching message.
 */
async function loadAICoachMessage(forceRefresh = false) {
    const textEl = document.getElementById('aiCoachText');
    const badgeEl = document.getElementById('aiCoachSourceBadge');
    if (!textEl) return;

    if (forceRefresh) textEl.textContent = 'Generating fresh coaching insights...';

    const endpoint = forceRefresh ? '/api/ai/daily-message?refresh=true' : '/api/ai/daily-message';
    const res = await apiCall(endpoint);
    if (!res) return;

    textEl.textContent = res.message || "Consistency builds greatness.";
    if (badgeEl) {
        badgeEl.textContent = res.source === 'gemini' ? 'Gemini AI Coach' : 'Adaptive Guidance';
    }
}

/**
 * Loads AI weekly performance summary.
 */
async function loadWeeklySummary(forceRefresh = false) {
    const textEl = document.getElementById('weeklyAIText');
    if (!textEl) return;

    if (forceRefresh) textEl.textContent = 'Analyzing weekly patterns...';

    const endpoint = forceRefresh ? '/api/ai/weekly-summary?refresh=true' : '/api/ai/weekly-summary';
    const res = await apiCall(endpoint);
    if (!res) return;

    textEl.textContent = res.summary || "Keep tracking daily to unlock comprehensive reviews.";
}

/**
 * Loads AI mood-habit correlation insight.
 */
async function loadMoodInsights() {
    const container = document.getElementById('moodInsights');
    const textEl = document.getElementById('moodInsightText');
    if (!container || !textEl) return;

    const res = await apiCall('/api/ai/mood-insights');
    if (!res || !res.insight || res.error) {
        container.style.display = 'none';
        return;
    }

    textEl.textContent = res.insight;
    container.style.display = 'block';
}

/**
 * Generates AI-recommended micro-habits based on user's stated goal.
 */
async function generateAIHabits() {
    const goalInput = document.getElementById('aiGoalInput');
    const container = document.getElementById('aiRecommendationsResult');
    if (!goalInput || !container) return;

    const goal = goalInput.value.trim();
    if (!goal) {
        showToast('Please type a goal first (e.g. better sleep, focus, hydration)', 'warning');
        return;
    }

    container.innerHTML = `
        <div class="text-center py-4 text-muted">
            <div class="spinner-border text-primary mb-2" role="status"></div>
            <p class="mb-0 small">Crafting tailored micro-habits with AI...</p>
        </div>
    `;

    const res = await apiCall('/api/ai/habit-recommendations', 'POST', { goal });
    if (!res || !res.recommendations || res.recommendations.length === 0) {
        container.innerHTML = '<div class="text-danger small text-center py-3">Could not generate recommendations. Please try again.</div>';
        return;
    }

    container.innerHTML = res.recommendations.map(rec => {
        const freqString = JSON.stringify(rec.frequency || ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']).replace(/"/g, '&quot;');
        return `
            <div class="card border p-3 rounded-3 shadow-sm recommendation-card">
                <div class="d-flex justify-content-between align-items-start gap-2">
                    <div class="d-flex align-items-center gap-3">
                        <span class="display-6">${escapeHtml(rec.icon || '✨')}</span>
                        <div>
                            <h6 class="fw-bold mb-1">${escapeHtml(rec.title)}</h6>
                            <p class="text-muted small mb-1">${escapeHtml(rec.why || '')}</p>
                            <span class="badge bg-light text-secondary border small">${escapeHtml(rec.category || 'general')}</span>
                            <span class="badge bg-light text-secondary border small">${escapeHtml(rec.duration || '<5 mins')}</span>
                        </div>
                    </div>
                    <button class="btn btn-sm btn-outline-primary text-nowrap rounded-pill px-3"
                            onclick="addRecommendedHabit('${escapeHtml(rec.title).replace(/'/g, "\\'")}', '${escapeHtml(rec.category || 'general')}', '${escapeHtml(rec.icon || '✨')}', '${freqString}')">
                        <i class="fas fa-plus me-1"></i> Add
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * Adds an AI recommended habit directly into user's habits list.
 */
async function addRecommendedHabit(title, category, icon, frequencyStr) {
    let frequency = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
    try {
        frequency = JSON.parse(frequencyStr.replace(/&quot;/g, '"'));
    } catch {}

    const payload = {
        title,
        category,
        icon,
        frequency
    };

    const res = await apiCall('/api/habits', 'POST', payload);
    if (res) {
        showToast(`Added "${title}" to your habits! 🎉`, 'success');
        const modalEl = document.getElementById('aiRecommendationsModal');
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) modalInstance.hide();
        await loadHabits();
        await loadUserStats();
    }
}

// ============================================================================
// 8. Analytics & Charts
// ============================================================================

/**
 * Renders weekly bar chart, mood doughnut chart, and behavioral pattern insights.
 */
async function loadAnalytics() {
    const res = await apiCall('/api/analytics');
    if (!res) return;

    // Render Weekly Bar Chart
    const weeklyCanvas = document.getElementById('completionChart');
    if (weeklyCanvas && res.weekly_chart) {
        if (completionChartInstance) completionChartInstance.destroy();

        completionChartInstance = new Chart(weeklyCanvas, {
            type: 'bar',
            data: {
                labels: res.weekly_chart.map(d => d.day.substring(0, 3)),
                datasets: [
                    {
                        label: 'Completed',
                        data: res.weekly_chart.map(d => d.completed),
                        backgroundColor: '#667eea',
                        borderRadius: 6
                    },
                    {
                        label: 'Skipped',
                        data: res.weekly_chart.map(d => d.skipped),
                        backgroundColor: '#cbd5e1',
                        borderRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom' }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 }
                    }
                }
            }
        });
    }

    // Render Mood Doughnut Chart
    const moodCanvas = document.getElementById('moodChart');
    if (moodCanvas) {
        const moodRes = await apiCall('/api/mood/analytics');
        if (moodRes && moodRes.mood_distribution) {
            if (moodChartInstance) moodChartInstance.destroy();

            const dist = moodRes.mood_distribution;
            moodChartInstance = new Chart(moodCanvas, {
                type: 'doughnut',
                data: {
                    labels: ['Happy 😊', 'Neutral 😐', 'Sad 😢'],
                    datasets: [{
                        data: [dist.happy || 0, dist.neutral || 0, dist.sad || 0],
                        backgroundColor: ['#10b981', '#f59e0b', '#ef4444'],
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'bottom' }
                    }
                }
            });
        }
    }

    // Render Coach Pattern Insights
    const insightsContainer = document.getElementById('coachInsightsList');
    if (insightsContainer && res.insights) {
        if (res.insights.length === 0) {
            insightsContainer.innerHTML = '<div class="text-muted small text-center py-3">Log habits for a few days to unlock insights!</div>';
        } else {
            insightsContainer.innerHTML = res.insights.slice(0, 4).map(ins => `
                <div class="p-3 rounded-3 bg-light border shadow-sm">
                    <div class="d-flex align-items-center gap-2 mb-1">
                        <span class="fs-5">${escapeHtml(ins.icon || '💡')}</span>
                        <span class="fw-semibold small text-primary">${escapeHtml(ins.title || 'Insight')}</span>
                    </div>
                    <p class="mb-0 small text-muted">${escapeHtml(ins.message || '')}</p>
                </div>
            `).join('');
        }
    }
}

// ============================================================================
// 9. Page Lifecycle Bindings
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadDarkMode();
    updateNavbarState();

    // If on dashboard view, run full dashboard initialization
    if (document.getElementById('habitsList')) {
        initDashboard();
    }
});
