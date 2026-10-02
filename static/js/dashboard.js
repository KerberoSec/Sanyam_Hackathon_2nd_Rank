/**
 * HabitFlow Dashboard Script Adapter
 * ===================================
 * Backwards compatibility adapter forwarding calls to app.js.
 * All dashboard features (AI coaching, habit filters, analytics, mood)
 * are managed centrally in static/js/app.js.
 */

// If app.js functions are in scope, this file simply confirms initialization
if (typeof initDashboard === 'function' && document.getElementById('habitsList')) {
    // Already handled by app.js on DOMContentLoaded
    console.debug('Dashboard script initialized via app.js');
}
