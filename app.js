/* ═══════════════════════════════════════════════════════════════
   ASSMS – Frontend Utilities
   ═══════════════════════════════════════════════════════════════ */

const fetchWithCsrf = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
    init = init || {};
    const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
        const token = document.querySelector('meta[name="csrf-token"]')?.content;
        const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
        if (token) headers.set('X-CSRFToken', token);
        init = { ...init, headers };
    }
    return fetchWithCsrf(input, init);
};

function escapeHtml(value) {
    const element = document.createElement('span');
    element.textContent = value == null ? '' : String(value);
    return element.innerHTML;
}

// ── Toast notifications ─────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) { alert(message); return; }

    const id = 'toast-' + Date.now();
    const bgClass = {
        success: 'text-bg-success',
        danger:  'text-bg-danger',
        error:   'text-bg-danger',
        warning: 'text-bg-warning',
        info:    'text-bg-info',
    }[type] || 'text-bg-secondary';

    const html = `
        <div id="${id}" class="toast align-items-center ${bgClass} border-0" role="alert">
            <div class="d-flex">
                <div class="toast-body">${escapeHtml(message)}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto"
                        data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
    const el = document.getElementById(id);
    const toast = new bootstrap.Toast(el, { delay: 3000 });
    toast.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
}

// ── Sidebar toggle (mobile) ─────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    if (toggle && sidebar) {
        toggle.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
        // Close when clicking outside on mobile
        document.addEventListener('click', (e) => {
            if (window.innerWidth <= 992 &&
                sidebar.classList.contains('open') &&
                !sidebar.contains(e.target) &&
                !toggle.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        });
    }
});

// ── Theme toggle ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('themeToggle');
    const preference = document.getElementById('darkThemePreference');
    const html = document.documentElement;

    const setTheme = (theme) => {
        const isDark = theme === 'dark';
        if (isDark) html.setAttribute('data-theme', 'dark');
        else html.removeAttribute('data-theme');

        if (btn) {
            btn.innerHTML = `<i class="fas fa-${isDark ? 'sun' : 'moon'}" aria-hidden="true"></i>`;
            btn.setAttribute('aria-label', `Switch to ${isDark ? 'light' : 'dark'} theme`);
            btn.title = `Switch to ${isDark ? 'light' : 'dark'} theme`;
        }
        if (preference) preference.checked = isDark;
        localStorage.setItem('assms-theme', isDark ? 'dark' : 'light');
    };

    setTheme(localStorage.getItem('assms-theme') || 'light');

    if (btn) {
        btn.addEventListener('click', () => {
            setTheme(html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
        });
    }

    if (preference) {
        preference.addEventListener('change', () => {
            setTheme(preference.checked ? 'dark' : 'light');
        });
    }
});

// ── API wrapper ─────────────────────────────────────────────
async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    let data;
    try {
        data = await response.json();
    } catch {
        if (!response.ok) {
            throw new Error(`The request failed (HTTP ${response.status}). Please try again.`);
        }
        throw new Error('The server returned an unreadable response. Please try again.');
    }
    if (!response.ok) {
        throw new Error(
            data.message || data.error || `The request failed (HTTP ${response.status}).`
        );
    }
    return data;
}

function showRequestError(error, action = 'Request failed') {
    const detail = error instanceof TypeError
        ? 'Unable to connect to the server. Check your connection and try again.'
        : error.message || 'Please try again.';
    showToast(`${action}: ${detail}`, 'danger');
}

async function apiCall(url, method = 'GET', body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);

    try {
        return await fetchJson(url, opts);
    } catch (err) {
        showRequestError(err);
        throw err;
    }
}

// ── Auto-dismiss flash alerts after 5s ──────────────────────
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        document.querySelectorAll('.alert-dismissible').forEach(a => {
            try { bootstrap.Alert.getOrCreateInstance(a).close(); } catch (e) {}
        });
    }, 5000);
});

// ── Confirm helper ──────────────────────────────────────────
function confirmAction(msg = 'Are you sure?') {
    return window.confirm(msg);
}

window.showToast = showToast;
window.apiCall = apiCall;
window.fetchJson = fetchJson;
window.showRequestError = showRequestError;
window.confirmAction = confirmAction;
window.escapeHtml = escapeHtml;