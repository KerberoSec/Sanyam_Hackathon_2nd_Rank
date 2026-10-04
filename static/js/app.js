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
const pendingHabitActions = new Set();

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

        const currentLvl = (user.level !== undefined && user.level !== null) ? user.level : 1;
        const currentXP = (user.xp_points !== undefined && user.xp_points !== null) ? user.xp_points : 0;

        const levelEl = document.getElementById('navUserLevel');
        if (levelEl) levelEl.textContent = currentLvl;

        const xpEl = document.getElementById('navUserXP');
        if (xpEl) xpEl.textContent = currentXP;

        const dashLvlEl = document.getElementById('dashUserLevel');
        if (dashLvlEl) dashLvlEl.textContent = currentLvl;

        const dashXpEl = document.getElementById('dashUserXP');
        if (dashXpEl) dashXpEl.textContent = currentXP;
    } else {
        authOnlyElements.forEach(el => el.style.display = 'none');
        guestOnlyElements.forEach(el => el.style.display = '');
    }
}

/**
 * Loads current user profile and displays profile edit modal.
 */
async function openProfileModal() {
    const cachedUser = getUser();
    const emailEl = document.getElementById('profileEmail');
    const nameEl = document.getElementById('profileName');
    const oldPassEl = document.getElementById('profileOldPassword');
    const newPassEl = document.getElementById('profileNewPassword');
    if (emailEl) emailEl.value = cachedUser.email || '';
    if (nameEl) nameEl.value = cachedUser.name || '';
    if (oldPassEl) oldPassEl.value = '';
    if (newPassEl) newPassEl.value = '';

    const modalEl = document.getElementById('profileModal');
    if (modalEl && typeof bootstrap !== 'undefined') {
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
    }

    try {
        const res = await apiCall('/api/auth/profile');
        if (res && res.user) {
            const user = res.user;
            if (emailEl) emailEl.value = user.email || '';
            if (nameEl) nameEl.value = user.name || '';
            localStorage.setItem('user', JSON.stringify(user));
        }
    } catch (e) {
        console.warn('Could not refresh profile from server:', e);
    }
}

/**
 * Submits updated user profile changes.
 */
async function saveUserProfile(event) {
    if (event) event.preventDefault();
    const nameInput = document.getElementById('profileName');
    const oldPassInput = document.getElementById('profileOldPassword');
    const newPassInput = document.getElementById('profileNewPassword');

    const name = nameInput ? nameInput.value.trim() : '';
    const oldPassword = oldPassInput ? oldPassInput.value : '';
    const newPassword = newPassInput ? newPassInput.value : '';

    if (!name) {
        showToast('Name cannot be empty.', 'warning');
        return;
    }

    const payload = { name };
    if (newPassword) {
        if (!oldPassword) {
            showToast('Current password is required to set a new password.', 'warning');
            return;
        }
        if (newPassword.length < 8) {
            showToast('New password must be at least 8 characters.', 'warning');
            return;
        }
        payload.old_password = oldPassword;
        payload.new_password = newPassword;
    }

    const saveBtn = document.getElementById('profileSaveBtn');
    let originalBtnHtml = '';
    if (saveBtn) {
        originalBtnHtml = saveBtn.innerHTML;
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Saving...';
    }

    try {
        const res = await apiCall('/api/auth/profile', 'PUT', payload);

        if (res && res.user) {
            showToast('Profile updated successfully!', 'success');
            localStorage.setItem('user', JSON.stringify(res.user));
            if (res.token) {
                localStorage.setItem('token', res.token);
            }
            updateNavbarState();
            const userNameHeader = document.getElementById('userName');
            if (userNameHeader) userNameHeader.textContent = res.user.name;

            const modalEl = document.getElementById('profileModal');
            if (modalEl && typeof bootstrap !== 'undefined') {
                const modal = bootstrap.Modal.getInstance(modalEl) || bootstrap.Modal.getOrCreateInstance(modalEl);
                modal.hide();
            }
        }
    } catch (err) {
        console.error('Error saving profile:', err);
        showToast('Failed to update profile. Please try again.', 'danger');
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalBtnHtml || '<i class="fas fa-save me-1"></i> Save Changes';
        }
    }
}

window.openProfileModal = openProfileModal;
window.saveUserProfile = saveUserProfile;

// ============================================================================
// 2. Dark Mode & UI Feedback
// ============================================================================

/**
 * Updates UI labels and icons based on dark mode state.
 */
function updateThemeUI() {
    const isDark = document.body.classList.contains('dark-mode');

    const dropdownIcon = document.getElementById('themeDropdownIcon');
    const dropdownText = document.getElementById('themeDropdownText');
    if (dropdownIcon) {
        dropdownIcon.className = isDark ? 'fas fa-sun text-warning me-2' : 'fas fa-moon text-warning me-2';
    }
    if (dropdownText) {
        dropdownText.textContent = isDark ? 'Light Mode' : 'Dark Mode';
    }

    const toggleIcons = document.querySelectorAll('.theme-toggle-icon');
    toggleIcons.forEach(icon => {
        icon.className = isDark ? 'fas fa-sun text-warning theme-toggle-icon' : 'fas fa-moon theme-toggle-icon';
    });
}

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
    updateThemeUI();
}

/**
 * Toggles dark mode and persists preference.
 */
function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    const isDark = document.body.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDark);
    updateThemeUI();
    updateChartTheme();
}

function updateChartTheme() {
    const textColor = document.body.classList.contains('dark-mode') ? '#cbd5e1' : '#475569';
    const gridColor = document.body.classList.contains('dark-mode')
        ? 'rgba(148, 163, 184, 0.16)'
        : 'rgba(71, 85, 105, 0.14)';
    [completionChartInstance, moodChartInstance, window.habitCompletionChartInstance, window.habitTrendChartInstance].forEach((chart) => {
        if (!chart) return;
        const legend = chart.options.plugins?.legend;
        if (legend) {
            legend.labels = { ...legend.labels, color: textColor };
        }
        Object.values(chart.options.scales || {}).forEach((scale) => {
            if (scale.ticks) scale.ticks.color = textColor;
            if (scale.grid) scale.grid.color = gridColor;
        });
        chart.update('none');
    });
}

function setHabitActionPending(habitId, pending) {
    const normalizedId = Number(habitId);
    if (!Number.isInteger(normalizedId)) return;
    if (pending) pendingHabitActions.add(normalizedId);
    else pendingHabitActions.delete(normalizedId);
    document.querySelectorAll(`.js-habit-action[data-habit-action-id="${normalizedId}"]`)
        .forEach(button => { button.disabled = pending; });
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
        const options = { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' };
        todayEl.textContent = now.toLocaleDateString('en-US', options);
    }

    // Hook recommendation modal to populate proposals automatically if empty
    const recModalEl = document.getElementById('aiRecommendationsModal');
    if (recModalEl) {
        recModalEl.addEventListener('show.bs.modal', () => {
            const container = document.getElementById('aiRecommendationsResult');
            const goalInput = document.getElementById('aiGoalInput');
            if (container && (!container._recommendations || container._recommendations.length === 0)) {
                if (goalInput && !goalInput.value) {
                    goalInput.value = 'productivity and wellness';
                }
                generateAIHabits();
            }
        });
    }

    // Share the analytics payload between summary cards and the chart loader.
    const analyticsPromise = apiCall('/api/analytics');
    await Promise.all([
        loadUserStats(analyticsPromise),
        loadHabits(),
        loadMood(),
        loadAICoachMessage(),
        loadWeeklySummary(),
        loadMoodInsights(),
        loadBadges(),
        loadAnalytics(analyticsPromise)
    ]);
}

// ============================================================================
// 4. Statistics & Gamification
// ============================================================================

/**
 * Fetches and populates top summary statistics cards.
 */
async function loadUserStats(analyticsPromise = null) {
    const res = await (analyticsPromise || apiCall('/api/analytics'));
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
 * Maps habit category and icon to a professional Font Awesome vector icon.
 */
function getHabitVectorIconHtml(habit) {
    const cat = (habit.category || '').toLowerCase();
    const icon = (habit.icon || '').toLowerCase();
    if (cat.includes('fit') || icon.includes('fit') || icon.includes('run') || icon.includes('gym') || icon.includes('mobility') || icon.includes('walk') || cat.includes('health')) {
        return '<i class="fas fa-dumbbell text-primary"></i>';
    }
    if (cat.includes('mind') || cat.includes('meditat') || icon.includes('mind') || icon.includes('zen') || icon.includes('peace') || icon.includes('wellness')) {
        return '<i class="fas fa-spa" style="color: #0d9488;"></i>';
    }
    if (cat.includes('productiv') || cat.includes('work') || icon.includes('work') || icon.includes('task') || icon.includes('timer') || icon.includes('plan')) {
        return '<i class="fas fa-briefcase text-primary"></i>';
    }
    if (cat.includes('learn') || cat.includes('read') || cat.includes('study') || icon.includes('book')) {
        return '<i class="fas fa-book-open text-primary"></i>';
    }
    if (cat.includes('sleep') || cat.includes('rest') || icon.includes('sleep') || icon.includes('moon')) {
        return '<i class="fas fa-moon text-warning"></i>';
    }
    if (cat.includes('water') || cat.includes('hydrat') || icon.includes('water') || icon.includes('drop')) {
        return '<i class="fas fa-tint text-info"></i>';
    }
    if (cat.includes('finance') || cat.includes('money') || icon.includes('wallet')) {
        return '<i class="fas fa-wallet text-success"></i>';
    }
    return '<i class="fas fa-check-circle text-primary"></i>';
}

/**
 * Maps badge icon names to clean vector icons.
 */
function getBadgeIconHtml(iconName) {
    const icon = (iconName || '').toLowerCase();
    if (icon.includes('streak') || icon.includes('fire')) return '<i class="fas fa-fire text-warning"></i>';
    if (icon.includes('strength')) return '<i class="fas fa-dumbbell text-primary"></i>';
    if (icon.includes('master') || icon.includes('crown')) return '<i class="fas fa-crown text-warning"></i>';
    if (icon.includes('starter') || icon.includes('launch') || icon.includes('rocket')) return '<i class="fas fa-rocket text-info"></i>';
    if (icon.includes('builder')) return '<i class="fas fa-hammer text-secondary"></i>';
    if (icon.includes('century') || icon.includes('centennial')) return '<i class="fas fa-medal text-warning"></i>';
    if (icon.includes('consistency')) return '<i class="fas fa-check-double text-success"></i>';
    if (icon.includes('champion') || icon.includes('trophy')) return '<i class="fas fa-trophy text-warning"></i>';
    if (icon.includes('target')) return '<i class="fas fa-bullseye text-danger"></i>';
    return '<i class="fas fa-award text-primary"></i>';
}

/**
 * Maps insight icon names to clean vector icons.
 */
function getInsightIconHtml(iconName) {
    const icon = (iconName || '').toLowerCase();
    if (icon.includes('growth') || icon.includes('seed')) return '<i class="fas fa-seedling text-success"></i>';
    if (icon.includes('insight') || icon.includes('light') || icon.includes('tip')) return '<i class="fas fa-lightbulb text-warning"></i>';
    if (icon.includes('shield')) return '<i class="fas fa-shield-alt text-primary"></i>';
    if (icon.includes('alert') || icon.includes('warn')) return '<i class="fas fa-exclamation-triangle text-danger"></i>';
    if (icon.includes('star')) return '<i class="fas fa-star text-warning"></i>';
    if (icon.includes('trophy') || icon.includes('award')) return '<i class="fas fa-trophy text-warning"></i>';
    return '<i class="fas fa-info-circle text-info"></i>';
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
            <div class="badge-icon display-6">${getBadgeIconHtml(b.icon)}</div>
            <div class="badge-name mt-1">${escapeHtml(b.name)}</div>
            <small class="badge-desc text-muted">${b.unlocked ? 'Unlocked' : 'Locked'}</small>
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
        let emptyTitle = 'No habits found';
        let emptySubtitle = 'Click "New Habit" or use "Habit Recommendations" to get started!';
        if (habitSearchQuery) {
            emptyTitle = 'No matching habits';
            emptySubtitle = `No habits found matching "${escapeHtml(habitSearchQuery)}". Try clearing your search term.`;
        } else if (activeHabitFilter === 'pending') {
            emptyTitle = 'All caught up!';
            emptySubtitle = 'No pending habits remaining for today. Great work!';
        } else if (activeHabitFilter === 'completed') {
            emptyTitle = 'No completed habits yet';
            emptySubtitle = 'Complete habits from your pending list to build your daily streak.';
        }

        listEl.innerHTML = `
            <div class="text-center py-5 text-muted">
                <i class="fas fa-clipboard-list fa-3x mb-3 text-secondary opacity-50"></i>
                <p class="mb-2 fw-semibold fs-5">${emptyTitle}</p>
                <small class="d-block mb-3">${emptySubtitle}</small>
                ${!habitSearchQuery && activeHabitFilter === 'all' ? `
                    <div class="d-flex justify-content-center gap-2 mt-2">
                        <button type="button" class="btn btn-primary btn-sm rounded-pill px-3 shadow-sm" data-bs-toggle="modal" data-bs-target="#newHabitModal">
                            <i class="fas fa-plus me-1"></i> Add New Habit
                        </button>
                        <button type="button" class="btn btn-outline-primary btn-sm rounded-pill px-3 shadow-sm" data-bs-toggle="modal" data-bs-target="#aiRecommendationsModal">
                            <i class="fas fa-magic me-1"></i> Habit Recommendations
                        </button>
                    </div>
                ` : ''}
                ${(habitSearchQuery || activeHabitFilter !== 'all') ? `
                    <button type="button" class="btn btn-outline-secondary btn-sm rounded-pill px-3 mt-1 fw-semibold" onclick="clearHabitSearchAndFilters()">
                        Clear Filters & Search
                    </button>
                ` : ''}
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
                <div class="habit-icon p-2 rounded-3 bg-light text-center fs-3">${getHabitVectorIconHtml(habit)}</div>
                <div class="habit-content">
                    <div class="d-flex align-items-center gap-2 mb-1 flex-wrap">
                        <a href="/habit/${habit.id}" class="habit-title text-decoration-none fw-bold">${escapeHtml(habit.title)}</a>
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
                    ${!habit.is_scheduled_today ? '' : !isCompleted ? `
                        <button class="js-habit-action btn btn-sm btn-success rounded-pill px-3 shadow-sm" data-habit-action-id="${habit.id}" ${pendingHabitActions.has(Number(habit.id)) ? 'disabled' : ''} onclick="completeHabit(${habit.id})" aria-label="Mark ${escapeHtml(habit.title)} complete">
                            <i class="fas fa-check me-1"></i> Done
                        </button>
                    ` : `
                        <span class="badge bg-success-subtle text-success px-3 py-2 rounded-pill fw-semibold border border-success-subtle">
                            <i class="fas fa-check-circle me-1"></i> Completed
                        </span>
                    `}
                    ${habit.is_scheduled_today && !isSkipped && !isCompleted ? `
                        <button class="js-habit-action btn btn-sm btn-outline-secondary rounded-pill px-2" data-habit-action-id="${habit.id}" ${pendingHabitActions.has(Number(habit.id)) ? 'disabled' : ''} onclick="skipHabit(${habit.id})" aria-label="Skip ${escapeHtml(habit.title)}">
                            Skip
                        </button>
                    ` : ''}
                    ${habit.is_scheduled_today && !isMissed && !isSkipped && !isCompleted ? `
                        <button class="js-habit-action btn btn-sm btn-outline-danger rounded-pill px-2" data-habit-action-id="${habit.id}" ${pendingHabitActions.has(Number(habit.id)) ? 'disabled' : ''} onclick="missHabit(${habit.id})" aria-label="Mark ${escapeHtml(habit.title)} missed">
                            Miss
                        </button>
                    ` : ''}
                    <a href="/habit/${habit.id}" class="btn btn-sm btn-outline-primary rounded-circle p-2" aria-label="View analytics and history for ${escapeHtml(habit.title)}">
                        <i class="fas fa-chart-bar"></i>
                    </a>
                    <button class="btn btn-sm btn-outline-danger rounded-circle p-2" onclick="deleteHabit(${habit.id})" aria-label="Delete ${escapeHtml(habit.title)}">
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
function filterHabits(filterType) {
    activeHabitFilter = filterType;
    document.querySelectorAll('#habitFilterGroup button').forEach(button => {
        const selected = button.dataset.filter === filterType;
        button.classList.toggle('active', selected);
        button.setAttribute('aria-pressed', String(selected));
    });
    renderHabitsList();
}

window.handleHabitSearch = handleHabitSearch;
window.filterHabits = filterHabits;

/**
 * Clears habit search input and re-renders full list.
 */
function clearHabitSearch() {
    const searchInput = document.getElementById('habitSearchInput');
    if (searchInput) searchInput.value = '';
    habitSearchQuery = '';
    renderHabitsList();
}

/**
 * Resets search input and resets active filter to 'all'.
 */
function clearHabitSearchAndFilters() {
    const searchInput = document.getElementById('habitSearchInput');
    if (searchInput) searchInput.value = '';
    habitSearchQuery = '';
    filterHabits('all');
}

window.clearHabitSearch = clearHabitSearch;
window.clearHabitSearchAndFilters = clearHabitSearchAndFilters;

/**
 * Returns the app's UTC calendar date in YYYY-MM-DD format.
 */
function getCurrentAppDateString() {
    return new Date().toISOString().slice(0, 10);
}

/**
 * Marks habit completed today using the app's UTC calendar date.
 */
async function completeHabit(habitId) {
    if (pendingHabitActions.has(Number(habitId))) return;
    setHabitActionPending(habitId, true);
    try {
        const dateStr = getCurrentAppDateString();
        const res = await apiCall(`/api/habits/${habitId}/complete`, 'POST', { date: dateStr });
        if (!res) return;

        confetti({ particleCount: 80, spread: 60, origin: { y: 0.7 } });

        showToast(`+${res.xp_earned} XP earned!`, 'success');

        if (res.streak_message) showToast(res.streak_message, 'info');

        if (res.badges_unlocked && res.badges_unlocked.length > 0) {
            res.badges_unlocked.forEach(b => {
                showToast(`Achievement Unlocked: ${b.name}`, 'success', 5000);
            });
            await loadBadges();
        }

        await loadHabits();
        await loadUserStats();
    } finally {
        setHabitActionPending(habitId, false);
    }
}

/**
 * Excuses habit for today.
 */
async function skipHabit(habitId) {
    if (pendingHabitActions.has(Number(habitId))) return;
    setHabitActionPending(habitId, true);
    try {
        const dateStr = getCurrentAppDateString();
        const res = await apiCall(`/api/habits/${habitId}/skip`, 'POST', { date: dateStr });
        if (!res) return;
        showToast(`Habit excused for today. +${res.xp_earned || 0} XP earned.`, 'info');
        await loadHabits();
        await loadUserStats();
    } finally {
        setHabitActionPending(habitId, false);
    }
}

/**
 * Marks habit missed today.
 */
async function missHabit(habitId) {
    if (pendingHabitActions.has(Number(habitId))) return;
    setHabitActionPending(habitId, true);
    try {
        const dateStr = getCurrentAppDateString();
        const res = await apiCall(`/api/habits/${habitId}/miss`, 'POST', { date: dateStr });
        if (!res) return;
        showToast('Marked as missed. Rebuild momentum tomorrow!', 'warning');
        await loadHabits();
        await loadUserStats();
    } finally {
        setHabitActionPending(habitId, false);
    }
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
    const titleEl = document.getElementById('habitTitle');
    const title = titleEl ? titleEl.value.trim() : '';
    const category = document.getElementById('habitCategory') ? document.getElementById('habitCategory').value : 'productivity';
    const icon = document.getElementById('habitIcon') ? document.getElementById('habitIcon').value.trim() || 'habit' : 'habit';
    const reminderTime = document.getElementById('habitReminderTime') ? document.getElementById('habitReminderTime').value || null : null;

    const checkedBoxes = document.querySelectorAll('#frequencyOptions input:checked');
    const frequency = Array.from(checkedBoxes).map(cb => cb.value);

    if (!title) {
        showToast('Please specify a habit title', 'warning');
        if (titleEl) titleEl.focus();
        return;
    }
    if (frequency.length === 0) {
        showToast('Please select at least one scheduled day', 'warning');
        return;
    }

    const submitBtn = document.getElementById('createHabitSubmitBtn');
    let originalBtnHtml = '';
    if (submitBtn) {
        originalBtnHtml = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Creating...';
    }

    const payload = {
        title,
        category,
        icon,
        frequency,
        reminder_time: reminderTime
    };

    try {
        const res = await apiCall('/api/habits', 'POST', payload);
        if (res && (res.habit || res.id)) {
            showToast('Habit created successfully!', 'success');
            const form = document.getElementById('newHabitForm');
            if (form) form.reset();

            const modalEl = document.getElementById('newHabitModal');
            if (modalEl && typeof bootstrap !== 'undefined') {
                const modalInstance = bootstrap.Modal.getInstance(modalEl) || bootstrap.Modal.getOrCreateInstance(modalEl);
                modalInstance.hide();
            }

            await loadHabits();
            await loadUserStats();
        } else if (res && res.error) {
            showToast(res.error, 'danger');
        }
    } catch (err) {
        console.error('Error creating habit:', err);
        showToast('Failed to create habit. Please try again.', 'danger');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnHtml || '<i class="fas fa-plus me-1"></i> Create Habit';
        }
    }
}

// ============================================================================
// 6. Mood Tracking
// ============================================================================
// 6. Mood Tracking
// ============================================================================

let currentSelectedMood = 'neutral';
let todayMoodRecorded = false;

function updateMoodCharCount() {
    const input = document.getElementById('moodNoteInput');
    const counter = document.getElementById('moodCharCount');
    if (input && counter) {
        counter.textContent = `${input.value.length}/1000`;
    }
}

function selectMoodOption(mood) {
    document.querySelectorAll('.mood-option').forEach((element) => {
        const selected = element.dataset.mood === mood;
        element.classList.toggle('selected', selected);
        element.setAttribute('aria-pressed', String(selected));
    });
}

/**
 * Fetches and highlights today's logged mood if already recorded.
 */
async function loadMood() {
    const noteInput = document.getElementById('moodNoteInput');
    if (noteInput && !noteInput._hasCharListener) {
        noteInput._hasCharListener = true;
        noteInput.addEventListener('input', updateMoodCharCount);
    }

    const res = await apiCall('/api/mood/today');
    const feedbackEl = document.getElementById('moodFeedback');

    if (!res || !res.mood) {
        todayMoodRecorded = false;
        if (feedbackEl) {
            feedbackEl.innerHTML = '<span class="text-muted"><i class="fas fa-clock me-1"></i>No check-in yet today. Tap an emotion above to log.</span>';
        }
        return;
    }

    todayMoodRecorded = true;
    currentSelectedMood = res.mood.mood || 'neutral';
    selectMoodOption(currentSelectedMood);

    if (noteInput) {
        noteInput.value = res.mood.note || '';
        updateMoodCharCount();
    }

    if (feedbackEl) {
        feedbackEl.innerHTML = `<span class="badge bg-success-subtle text-success border border-success-subtle me-1"><i class="fas fa-check-circle me-1"></i>Logged for Today</span> Recorded as <strong class="text-capitalize">${res.mood.mood}</strong>${res.mood.note ? ' • Note attached' : ''}`;
    }
}

/**
 * Logs or updates mood for today.
 */
async function logMood(mood) {
    currentSelectedMood = mood;
    selectMoodOption(mood);

    const note = document.getElementById('moodNoteInput')?.value.trim() || null;
    const dateStr = getCurrentAppDateString();
    const res = await apiCall('/api/mood', 'POST', { mood, note, date: dateStr });
    if (!res) return;

    todayMoodRecorded = true;
    const feedbackEl = document.getElementById('moodFeedback');
    const messages = {
        happy: "Feeling good! Channel this positive momentum into your daily habits.",
        neutral: "Balanced and centered. Consistent small steps create great results.",
        sad: "Be gentle with yourself today. Even completing one micro-habit is a victory."
    };
    if (feedbackEl) {
        feedbackEl.innerHTML = `<span class="badge bg-success-subtle text-success border border-success-subtle me-1"><i class="fas fa-check-circle me-1"></i>Recorded</span> Logged as <strong class="text-capitalize">${mood}</strong>: ${messages[mood] || "Check-in saved."}`;
    }

    await loadMoodInsights();
    await loadAnalytics();
}

/**
 * Saves note attached to selected mood.
 */
async function saveMoodWithNote() {
    const selectedOption = document.querySelector('.mood-option.selected');
    const mood = selectedOption?.dataset?.mood || currentSelectedMood || 'neutral';
    selectMoodOption(mood);

    const noteInput = document.getElementById('moodNoteInput');
    const note = noteInput ? noteInput.value.trim() : '';
    const dateStr = getCurrentAppDateString();

    const saveBtn = document.getElementById('saveMoodNoteBtn');
    let originalHtml = '';
    if (saveBtn) {
        originalHtml = saveBtn.innerHTML;
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Saving...';
    }

    try {
        const res = await apiCall('/api/mood', 'POST', { mood, note: note || null, date: dateStr });
        if (res) {
            todayMoodRecorded = true;
            if (noteInput) {
                noteInput.value = res.note !== undefined && res.note !== null ? res.note : note;
                updateMoodCharCount();
            }
            showToast('Check-in and reflection note saved to local database!', 'success');
            const feedbackEl = document.getElementById('moodFeedback');
            if (feedbackEl) {
                feedbackEl.innerHTML = `<span class="badge bg-success-subtle text-success border border-success-subtle me-1"><i class="fas fa-save me-1"></i>Saved</span> Reflection note stored with your mood in the database.`;
            }
            if (saveBtn) {
                saveBtn.innerHTML = '<i class="fas fa-check me-1"></i> Saved';
                setTimeout(() => {
                    if (saveBtn) {
                        saveBtn.innerHTML = originalHtml || '<i class="fas fa-save me-1"></i>Save';
                        saveBtn.disabled = false;
                    }
                }, 1400);
            }
            await loadMoodInsights();
            await loadAnalytics();
        }
    } catch (err) {
        console.error('Error saving mood note:', err);
        showToast('Failed to save reflection note.', 'danger');
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalHtml || '<i class="fas fa-save me-1"></i>Save';
        }
    }
}

/**
 * Clears the reflection note from input and resets it in today's check-in.
 */
async function clearMoodNote() {
    const noteInput = document.getElementById('moodNoteInput');
    const feedbackEl = document.getElementById('moodFeedback');

    if (!todayMoodRecorded) {
        if (noteInput) {
            noteInput.value = '';
            updateMoodCharCount();
        }
        if (feedbackEl) {
            feedbackEl.innerHTML = '<span class="text-muted"><i class="fas fa-info-circle me-1"></i>Reflection note field cleared.</span>';
        }
        showToast('Note field cleared.', 'info');
        return;
    }

    const selectedOption = document.querySelector('.mood-option.selected');
    const mood = selectedOption?.dataset?.mood || currentSelectedMood || 'neutral';
    const dateStr = getCurrentAppDateString();

    const clearBtn = document.getElementById('clearMoodBtn');
    let originalHtml = '';
    if (clearBtn) {
        originalHtml = clearBtn.innerHTML;
        clearBtn.disabled = true;
        clearBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Clearing...';
    }

    try {
        const res = await apiCall('/api/mood', 'POST', { mood, note: null, date: dateStr });
        if (res) {
            if (noteInput) {
                noteInput.value = '';
                updateMoodCharCount();
            }
            showToast('Reflection note cleared from database.', 'info');
            if (feedbackEl) {
                feedbackEl.innerHTML = `<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle me-1"><i class="fas fa-eraser me-1"></i>Cleared</span> Reflection note removed from today's check-in.`;
            }
            await loadMoodInsights();
            await loadAnalytics();
        }
    } catch (err) {
        console.error('Error clearing mood note:', err);
        showToast('Failed to clear reflection note from database.', 'danger');
    } finally {
        if (clearBtn) {
            clearBtn.disabled = false;
            clearBtn.innerHTML = originalHtml || 'Clear';
        }
    }
}

window.saveMoodWithNote = saveMoodWithNote;
window.clearMoodNote = clearMoodNote;
window.logMood = logMood;

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
        badgeEl.textContent = 'Behavioral Coach';
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
    const badgeEl = document.getElementById('moodInsightStatusBadge');
    if (!container || !textEl) return;

    const res = await apiCall('/api/ai/mood-insights');
    if (!res || !res.insight || res.error) {
        container.style.display = 'none';
        return;
    }

    textEl.textContent = res.insight;
    if (badgeEl) {
        if (res.insight.includes('at least 3 days') || res.insight.includes('not enough')) {
            badgeEl.className = 'badge bg-secondary-subtle text-secondary rounded-pill small';
            badgeEl.textContent = 'Gathering Data';
        } else {
            badgeEl.className = 'badge bg-success-subtle text-success border border-success-subtle rounded-pill small';
            badgeEl.textContent = 'Pattern Detected';
        }
    }
    container.style.display = 'block';
}

/**
 * Sets goal text input and triggers micro-habit generation.
 */
window.setGoalAndGenerate = function(goal) {
    const goalInput = document.getElementById('aiGoalInput');
    if (goalInput) {
        goalInput.value = goal;
    }
    generateAIHabits();
};

/**
 * Generates AI-recommended micro-habits based on user's stated goal.
 */
async function generateAIHabits() {
    const goalInput = document.getElementById('aiGoalInput');
    const container = document.getElementById('aiRecommendationsResult');
    const generateBtn = document.getElementById('generateHabitsBtn');
    if (!container) return;

    let goal = goalInput ? goalInput.value.trim() : '';
    if (!goal) {
        goal = 'productivity and wellness';
        if (goalInput) goalInput.value = goal;
    }

    let originalBtnHtml = '';
    if (generateBtn) {
        originalBtnHtml = generateBtn.innerHTML;
        generateBtn.disabled = true;
        generateBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Generating...';
    }

    container.innerHTML = `
        <div class="text-center py-4 text-muted">
            <div class="spinner-border text-primary mb-2" role="status"></div>
            <p class="mb-0 small">Synthesizing tailored micro-habits...</p>
        </div>
    `;

    try {
        const res = await apiCall('/api/ai/habit-recommendations', 'POST', { goal });
        if (!res || !res.recommendations || res.recommendations.length === 0) {
            container.innerHTML = '<div class="text-danger small text-center py-3">Could not generate recommendations. Please try again.</div>';
            return;
        }

        container._recommendations = res.recommendations;
        if (container.dataset.recommendationListener !== 'true') {
            container.dataset.recommendationListener = 'true';
            container.addEventListener('click', (event) => {
                const button = event.target.closest('.js-add-recommendation');
                if (!button || !container.contains(button)) return;
                const recommendation = container._recommendations?.[Number(button.dataset.index)];
                if (!recommendation) return;
                addRecommendedHabit(
                    recommendation.title,
                    recommendation.category || 'general',
                    recommendation.icon || '',
                    JSON.stringify(recommendation.frequency || ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']),
                    button
                );
            });
        }

        container.innerHTML = res.recommendations.map((rec, index) => {
            return `
                <div class="card border p-3 rounded-3 shadow-sm recommendation-card">
                    <div class="d-flex justify-content-between align-items-start gap-2">
                        <div class="d-flex align-items-center gap-3">
                            <span class="fs-2 text-primary d-inline-flex align-items-center justify-content-center p-2 rounded-3 bg-light" style="width: 48px; height: 48px;">${getHabitVectorIconHtml(rec)}</span>
                            <div>
                                <h6 class="fw-bold mb-1">${escapeHtml(rec.title)}</h6>
                                <p class="text-muted small mb-1">${escapeHtml(rec.why || '')}</p>
                                <span class="badge bg-light text-secondary border small">${escapeHtml(rec.category || 'general')}</span>
                                <span class="badge bg-light text-secondary border small">${escapeHtml(rec.duration || '<5 mins')}</span>
                            </div>
                        </div>
                        <button type="button" class="btn btn-sm btn-outline-primary text-nowrap rounded-pill px-3 js-add-recommendation" data-index="${index}">
                            <i class="fas fa-plus me-1"></i> Add
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Error generating recommendations:', err);
        container.innerHTML = '<div class="text-danger small text-center py-3">Failed to load recommendations. Please check your network and try again.</div>';
    } finally {
        if (generateBtn) {
            generateBtn.disabled = false;
            generateBtn.innerHTML = originalBtnHtml || '<i class="fas fa-magic me-1"></i> Generate';
        }
    }
}

/**
 * Adds an AI recommended habit directly into user's habits list.
 */
async function addRecommendedHabit(title, category, icon, frequencyStr, triggerBtn = null) {
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

    if (triggerBtn) {
        triggerBtn.disabled = true;
        triggerBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Adding...';
    }

    try {
        const res = await apiCall('/api/habits', 'POST', payload);
        if (res && (res.habit || res.id)) {
            showToast(`Added "${title}" to your habits!`, 'success');
            if (triggerBtn) {
                triggerBtn.classList.remove('btn-outline-primary');
                triggerBtn.classList.add('btn-success');
                triggerBtn.innerHTML = '<i class="fas fa-check me-1"></i> Added';
            }
            const modalEl = document.getElementById('aiRecommendationsModal');
            if (modalEl && typeof bootstrap !== 'undefined') {
                const modalInstance = bootstrap.Modal.getInstance(modalEl) || bootstrap.Modal.getOrCreateInstance(modalEl);
                setTimeout(() => modalInstance.hide(), 350);
            }
            await loadHabits();
            await loadUserStats();
        } else if (res && res.error) {
            showToast(res.error, 'danger');
            if (triggerBtn) {
                triggerBtn.disabled = false;
                triggerBtn.innerHTML = '<i class="fas fa-plus me-1"></i> Add';
            }
        }
    } catch (err) {
        console.error('Error adding recommended habit:', err);
        showToast('Failed to add habit.', 'danger');
        if (triggerBtn) {
            triggerBtn.disabled = false;
            triggerBtn.innerHTML = '<i class="fas fa-plus me-1"></i> Add';
        }
    }
}

// ============================================================================
// 8. Analytics & Charts
// ============================================================================

/**
 * Renders weekly bar chart, mood doughnut chart, and behavioral pattern insights.
 */
async function loadAnalytics(analyticsPromise = null) {
    const res = await (analyticsPromise || apiCall('/api/analytics'));
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
                        backgroundColor: '#0ea5e9',
                        borderRadius: 6
                    },
                    {
                        label: 'Skipped',
                        data: res.weekly_chart.map(d => d.skipped),
                        backgroundColor: '#cbd5e1',
                        borderRadius: 6
                    },
                    {
                        label: 'Missed or unlogged',
                        data: res.weekly_chart.map(d => d.missed),
                        backgroundColor: '#f87171',
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
        updateChartTheme();
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
                    labels: ['Happy', 'Neutral', 'Sad'],
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
            updateChartTheme();
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
                        <span class="fs-5">${getInsightIconHtml(ins.icon)}</span>
                        <span class="fw-semibold small text-primary">${escapeHtml(ins.title || 'Insight')}</span>
                    </div>
                    <p class="mb-0 small text-muted">${escapeHtml(ins.message || '')}</p>
                </div>
            `).join('');
        }
    }
}

// ============================================================================
// 9. 3D Dynamic Card Tilt & Physics Engine
// ============================================================================

/**
 * Attaches real-time 3D interactive cursor parallax tilt to UI cards.
 */
function init3DPhysics() {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const hasFinePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    if (reducedMotion || !hasFinePointer) return;

    const cardSelectors = '.stat-card, .feature-card, .ai-banner-card, .auth-card, .testimonial-card, .recommendation-card';

    document.addEventListener('mousemove', (e) => {
        const target = e.target.closest(cardSelectors);
        if (!target) return;

        const rect = target.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;

        const rotateX = ((y - centerY) / centerY) * -7;
        const rotateY = ((x - centerX) / centerX) * 7;

        target.style.transform = `perspective(1000px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) translateZ(12px)`;
    });

    document.addEventListener('mouseout', (e) => {
        const target = e.target.closest(cardSelectors);
        if (target && !target.contains(e.relatedTarget)) {
            target.style.transform = '';
        }
    });
}

// ============================================================================
// 10. Page Lifecycle Bindings
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadDarkMode();
    updateNavbarState();
    init3DPhysics();

    // If on dashboard view, run full dashboard initialization
    if (document.getElementById('habitsList')) {
        initDashboard();
    }
});
