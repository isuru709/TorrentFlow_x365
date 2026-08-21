// =========================================================
// TorrentFlow x365 — Frontend Controller
// =========================================================

const API_BASE = window.location.origin;
let ws = null;
let reconnectTimeout = null;
let pollInterval = null;

// ---------------------------------------------------------
// WebSocket
// ---------------------------------------------------------
function setWsStatus(state) {
    const dot = document.querySelector('.ws-dot');
    const label = document.querySelector('.ws-label');
    if (!dot || !label) return;
    dot.classList.remove('connected', 'disconnected');
    if (state === 'connected') {
        dot.classList.add('connected');
        label.textContent = 'Live';
    } else if (state === 'disconnected') {
        dot.classList.add('disconnected');
        label.textContent = 'Offline';
    } else {
        label.textContent = 'Connecting';
    }
}

function connectWebSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        console.log('WebSocket connected');
        clearTimeout(reconnectTimeout);
        setWsStatus('connected');
        loadTorrents();
        stopPolling();
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'update') {
                updateTorrentsList(data.torrents);
            }
        } catch (e) {
            console.error('WS parse error:', e);
        }
    };

    ws.onerror = () => {
        console.error('WebSocket error');
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting…');
        setWsStatus('disconnected');
        reconnectTimeout = setTimeout(connectWebSocket, 3000);
        startPolling();
    };
}

function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(loadTorrents, 2000);
}

function stopPolling() {
    if (!pollInterval) return;
    clearInterval(pollInterval);
    pollInterval = null;
}

// ---------------------------------------------------------
// Add Torrent
// ---------------------------------------------------------
async function addMagnet() {
    const input = document.getElementById('magnet-input');
    const url = input.value.trim();
    const sequential = document.getElementById('sequential-download').checked;

    if (!url) {
        showNotification('Please enter a magnet link, torrent URL, or info hash', 'error');
        return;
    }

    const button = document.getElementById('add-btn');
    const originalHTML = button.innerHTML;
    button.innerHTML = '<span class="btn-icon">⏳</span> Adding…';
    button.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/api/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, sequential })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            input.value = '';
            showNotification('✓ Torrent added successfully!', 'success');
            setTimeout(() => loadTorrents(), 100);
        } else {
            const errorMsg = result.detail || result.message || 'Failed to add torrent';
            throw new Error(errorMsg);
        }
    } catch (error) {
        let errorMessage = error.message;

        if (errorMessage.includes('magnet:?xt=')) {
            const magnetMatch = errorMessage.match(/magnet:\?[^\n]+/);
            if (magnetMatch) {
                const magnetLink = magnetMatch[0];
                if (confirm('🚫 The site is blocking downloads.\n\n✅ But we found the magnet link!\n\nClick OK to use it automatically.')) {
                    input.value = magnetLink;
                    showNotification('🔄 Trying with magnet link…', 'info');
                    button.innerHTML = originalHTML;
                    button.disabled = false;
                    setTimeout(() => addMagnet(), 500);
                    return;
                } else {
                    navigator.clipboard.writeText(magnetLink).then(() => {
                        showNotification('📋 Magnet link copied to clipboard!', 'success');
                    }).catch(() => {
                        showNotification(`📋 Copy this magnet link:\n\n${magnetLink.substring(0, 60)}…`, 'info');
                    });
                }
                return;
            }
        }

        if (errorMessage.includes('403') || errorMessage.includes('Forbidden') || errorMessage.includes('blocking')) {
            errorMessage = '🚫 Site is blocking automated downloads.\n\n✅ Try using a magnet link or uploading the .torrent file.';
        } else if (errorMessage.includes('404')) {
            errorMessage = '❌ Torrent not found. The link may be expired.';
        } else if (errorMessage.includes('timeout')) {
            errorMessage = '⏱️ Request timed out. Please try again.';
        }

        showNotification(errorMessage, 'error');
    } finally {
        button.innerHTML = originalHTML;
        button.disabled = false;
    }
}

// ---------------------------------------------------------
// Upload Torrent
// ---------------------------------------------------------
async function uploadTorrent() {
    const fileInput = document.getElementById('torrent-file');
    const file = fileInput.files[0];
    const sequential = document.getElementById('sequential-download').checked;

    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    showNotification('📤 Uploading torrent file…', 'info');

    try {
        const response = await fetch(`${API_BASE}/api/upload-torrent?sequential=${sequential}`, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (result.success) {
            fileInput.value = '';
            showNotification('✓ Torrent file uploaded successfully!', 'success');
            setTimeout(() => loadTorrents(), 100);
        } else {
            throw new Error(result.message || 'Failed to upload torrent');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

// ---------------------------------------------------------
// Load / Update Torrents
// ---------------------------------------------------------
async function loadTorrents() {
    try {
        const response = await fetch(`${API_BASE}/api/torrents?ts=${Date.now()}`, {
            cache: 'no-store',
            headers: { 'Cache-Control': 'no-cache' }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const torrents = await response.json();
        updateTorrentsList(torrents);
    } catch (error) {
        console.error('Error loading torrents:', error);
        const container = document.getElementById('torrents-container');
        if (container && !container.querySelector('.torrent-item')) {
            container.innerHTML = '<div class="empty-state error"><div class="empty-icon">⚠️</div><p>Failed to load torrents</p><span>Retrying…</span></div>';
        }
    }
}

function updateTorrentsList(torrents) {
    const container = document.getElementById('torrents-container');
    if (!container) return;

    if (!torrents || torrents.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📥</div><p>No active torrents</p><span>Add a magnet link or upload a .torrent file to get started</span></div>';
        updateStats(0, 0, 0);
        return;
    }

    container.querySelectorAll('.empty-state').forEach(el => el.remove());

    const existingTorrents = {};
    container.querySelectorAll('.torrent-item').forEach(item => {
        const id = item.dataset.torrentId;
        if (id) existingTorrents[id] = item;
    });

    let totalDownloadRate = 0;
    let totalUploadRate = 0;

    torrents.forEach((torrent) => {
        const id = torrent.id || '';
        const downloadRate = torrent.download_rate || 0;
        const uploadRate = torrent.upload_rate || 0;

        totalDownloadRate += downloadRate;
        totalUploadRate += uploadRate;

        if (existingTorrents[id]) {
            updateTorrentElement(existingTorrents[id], torrent);
            delete existingTorrents[id];
        } else {
            const torrentHTML = createTorrentHTML(torrent);
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = torrentHTML;
            container.appendChild(tempDiv.firstElementChild);
        }
    });

    // Remove torrents that no longer exist with fade out
    Object.values(existingTorrents).forEach(element => {
        element.style.opacity = '0';
        element.style.transform = 'scale(0.96)';
        setTimeout(() => element.remove(), 300);
    });

    if (!window.__torrentListenersAttached) {
        setupTorrentEventListeners();
    }

    updateStats(torrents.length, totalDownloadRate, totalUploadRate);

    const timeEl = document.getElementById('last-update');
    if (timeEl) {
        timeEl.textContent = `Last update: ${new Date().toLocaleTimeString()}`;
    }
}

function updateTorrentElement(element, torrent) {
    const progress = torrent.progress || 0;
    const downloadRate = torrent.download_rate || 0;
    const uploadRate = torrent.upload_rate || 0;
    const state = torrent.state || 'unknown';
    const numPeers = torrent.num_peers || 0;
    const numSeeds = torrent.num_seeds || 0;
    const downloaded = torrent.downloaded || 0;
    const ratio = torrent.ratio || 0;
    const eta = torrent.eta || -1;

    element.dataset.state = state;

    const progressFill = element.querySelector('.progress-fill');
    if (progressFill) {
        progressFill.style.width = `${progress.toFixed(1)}%`;
    }

    const stats = {
        'Progress': `${progress.toFixed(1)}%`,
        'State': `<span class="state-${state}">${formatState(state)}</span>`,
        'Download': `↓ ${formatSpeed(downloadRate)}`,
        'Upload': `↑ ${formatSpeed(uploadRate)}`,
        'Peers': `${numPeers} (${numSeeds} seeds)`,
        'Downloaded': formatBytes(downloaded),
        'Ratio': ratio.toFixed(2),
        'ETA': formatETA(eta)
    };

    element.querySelectorAll('.stat-item').forEach(statItem => {
        const label = statItem.querySelector('.stat-label');
        const value = statItem.querySelector('.stat-value');
        if (label && value && stats[label.textContent]) {
            value.innerHTML = stats[label.textContent];
        }
    });
}

function createTorrentHTML(torrent) {
    const id = torrent.id || '';
    const name = torrent.name || 'Loading metadata…';
    const progress = torrent.progress || 0;
    const downloadRate = torrent.download_rate || 0;
    const uploadRate = torrent.upload_rate || 0;
    const state = torrent.state || 'unknown';
    const numPeers = torrent.num_peers || 0;
    const numSeeds = torrent.num_seeds || 0;
    const totalSize = torrent.total_size || 0;
    const downloaded = torrent.downloaded || 0;
    const ratio = torrent.ratio || 0;
    const eta = torrent.eta || -1;

    const stateLower = (state || '').toLowerCase();
    const isCompleted = progress >= 100 || stateLower.includes('complete');
    const isSeeding = !isCompleted && (stateLower.includes('seeding') || stateLower.includes('seed'));
    const badge = isCompleted
        ? '<span class="done-badge">✅ Completed</span>'
        : (isSeeding ? '<span class="seed-badge">🌱 Seeding</span>' : '');

    const isPaused = stateLower.includes('pause') || stateLower.includes('stop');
    const pauseDisabled = (isPaused || isCompleted) ? 'disabled' : '';
    const resumeDisabled = (!isPaused || isCompleted) ? 'disabled' : '';

    return `
        <div class="torrent-item" data-torrent-id="${id}" data-state="${state}">
            <div class="torrent-header">
                <div class="torrent-name" title="${escapeHtml(name)}">
                    ${escapeHtml(name)} ${badge}
                </div>
                <div class="torrent-actions">
                    <button type="button" class="btn-pause" data-id="${id}" title="Pause" ${pauseDisabled}>⏸ Pause</button>
                    <button type="button" class="btn-resume" data-id="${id}" title="Resume" ${resumeDisabled}>▶ Resume</button>
                    <button type="button" class="btn-download" data-id="${id}" title="Download files">⬇ Files</button>
                    <button type="button" class="btn-delete" data-id="${id}" title="Delete">🗑 Delete</button>
                </div>
            </div>

            <div class="progress-bar">
                <div class="progress-fill" style="width: ${progress.toFixed(1)}%"></div>
            </div>

            <div class="torrent-stats">
                <div class="stat-item">
                    <span class="stat-label">Progress</span>
                    <span class="stat-value">${progress.toFixed(1)}%</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">State</span>
                    <span class="stat-value state-${state}">${formatState(state)}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Download</span>
                    <span class="stat-value">↓ ${formatSpeed(downloadRate)}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Upload</span>
                    <span class="stat-value">↑ ${formatSpeed(uploadRate)}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Peers</span>
                    <span class="stat-value">${numPeers} (${numSeeds} seeds)</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Size</span>
                    <span class="stat-value">${formatBytes(totalSize)}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Downloaded</span>
                    <span class="stat-value">${formatBytes(downloaded)}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Ratio</span>
                    <span class="stat-value">${ratio.toFixed(2)}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">ETA</span>
                    <span class="stat-value">${formatETA(eta)}</span>
                </div>
            </div>
        </div>
    `;
}

// ---------------------------------------------------------
// Event Listeners (Delegation)
// ---------------------------------------------------------
function setupTorrentEventListeners() {
    const container = document.getElementById('torrents-container');
    if (!container) return;

    container.addEventListener('click', (e) => {
        const target = e.target.closest('button');
        if (!target) return;

        const torrentId = target.dataset.id;
        if (!torrentId) return;

        e.preventDefault();
        e.stopPropagation();

        if (target.classList.contains('btn-pause'))         pauseTorrent(torrentId);
        else if (target.classList.contains('btn-resume'))   resumeTorrent(torrentId);
        else if (target.classList.contains('btn-download')) downloadTorrent(torrentId);
        else if (target.classList.contains('btn-delete'))   deleteTorrent(torrentId);
    });

    window.__torrentListenersAttached = true;
}

// ---------------------------------------------------------
// Torrent Actions
// ---------------------------------------------------------
async function pauseTorrent(id) {
    if (!id) return;
    try {
        const response = await fetch(`${API_BASE}/api/torrents/${id}/pause`, { method: 'POST' });
        if (!response.ok) throw new Error(response.statusText);
        showNotification('✓ Torrent paused', 'success');
        setTimeout(loadTorrents, 500);
    } catch (error) {
        showNotification(`❌ Error pausing: ${error.message}`, 'error');
    }
}

async function resumeTorrent(id) {
    if (!id) return;
    try {
        const response = await fetch(`${API_BASE}/api/torrents/${id}/resume`, { method: 'POST' });
        if (!response.ok) throw new Error(response.statusText);
        showNotification('✓ Torrent resumed', 'success');
        setTimeout(loadTorrents, 500);
    } catch (error) {
        showNotification(`❌ Error resuming: ${error.message}`, 'error');
    }
}

async function downloadTorrent(id) {
    if (!id) return;
    try {
        const response = await fetch(`${API_BASE}/api/torrents/${id}/files`);
        const files = await response.json();

        if (!response.ok) {
            throw new Error((files && files.detail) ? files.detail : 'Files not available yet');
        }

        const availableFiles = Array.isArray(files) ? files : [];
        if (availableFiles.length === 0) {
            showNotification('⚠️ Files not ready yet. Please wait for the download to finish.', 'info');
            return;
        }

        if (availableFiles.length === 1) {
            triggerDownload(id, availableFiles[0].relative_path);
            return;
        }

        showFilePicker(id, availableFiles);
    } catch (error) {
        showNotification(`❌ ${error.message}`, 'error');
    }
}

function triggerDownload(torrentId, relativePath = null, asZip = false) {
    const link = document.createElement('a');
    if (asZip || !relativePath) {
        link.href = `${API_BASE}/api/torrents/${torrentId}/download`;
    } else {
        link.href = `${API_BASE}/api/torrents/${torrentId}/download?file=${encodeURIComponent(relativePath)}`;
    }
    link.target = '_blank';
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
}

function showFilePicker(torrentId, files) {
    const existing = document.querySelector('.file-picker-backdrop');
    if (existing) existing.remove();

    const backdrop = document.createElement('div');
    backdrop.className = 'file-picker-backdrop';

    const modal = document.createElement('div');
    modal.className = 'file-picker';

    modal.innerHTML = `
        <div class="file-picker-header">
            <div>
                <div class="file-picker-title">Choose what to download</div>
                <div class="file-picker-subtitle">${files.length} files available</div>
            </div>
            <button type="button" class="file-picker-close" aria-label="Close">✖</button>
        </div>
        <div class="file-picker-actions">
            <button type="button" class="download-all" data-action="zip">⬇ Download all (.zip)</button>
        </div>
        <div class="file-picker-list"></div>
    `;

    const listEl = modal.querySelector('.file-picker-list');
    files.forEach((file) => {
        const row = document.createElement('div');
        row.className = 'file-picker-row';
        row.innerHTML = `
            <div class="file-picker-name" title="${escapeHtml(file.relative_path || 'file')}">${escapeHtml(file.relative_path || 'file')}</div>
            <div class="file-picker-size">${formatBytes(file.size || 0)}</div>
            <button type="button" class="file-picker-download" aria-label="Download file">⬇ Get</button>
        `;

        row.querySelector('.file-picker-download').addEventListener('click', () => {
            triggerDownload(torrentId, file.relative_path);
            backdrop.remove();
        });

        listEl.appendChild(row);
    });

    modal.querySelector('.download-all').addEventListener('click', () => {
        triggerDownload(torrentId, null, true);
        backdrop.remove();
    });

    const closeModal = () => backdrop.remove();
    modal.querySelector('.file-picker-close').addEventListener('click', closeModal);
    backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) closeModal();
    });

    // Escape key closes modal
    const escHandler = (e) => {
        if (e.key === 'Escape') { closeModal(); document.removeEventListener('keydown', escHandler); }
    };
    document.addEventListener('keydown', escHandler);

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
}

async function deleteTorrent(id) {
    if (!id) return;
    if (!confirm('⚠️ Remove this torrent and delete all data?')) return;

    try {
        const response = await fetch(`${API_BASE}/api/torrents/${id}?delete_files=true`, { method: 'DELETE' });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        showNotification('✓ Torrent removed', 'success');

        const el = document.querySelector(`[data-torrent-id="${id}"]`);
        if (el) {
            el.style.opacity = '0';
            el.style.transform = 'scale(0.95)';
            setTimeout(() => loadTorrents(), 300);
        } else {
            loadTorrents();
        }
    } catch (error) {
        showNotification(`❌ Error: ${error.message}`, 'error');
        loadTorrents();
    }
}

// ---------------------------------------------------------
// Stats
// ---------------------------------------------------------
function updateStats(count, downloadSpeed, uploadSpeed) {
    const torrentsEl = document.getElementById('total-torrents');
    const speedEl = document.getElementById('total-speed');

    if (torrentsEl) {
        torrentsEl.innerHTML = `<span class="stat-pill-icon">📦</span> <span>${count} Torrent${count !== 1 ? 's' : ''}</span>`;
    }

    if (speedEl) {
        let text = `↓ ${formatSpeed(downloadSpeed)}`;
        if (uploadSpeed > 0) text += ` · ↑ ${formatSpeed(uploadSpeed)}`;
        speedEl.innerHTML = `<span class="stat-pill-icon">⚡</span> <span>${text}</span>`;
    }
}

async function updateStorageInfo() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        const data = await response.json();

        if (data.storage) {
            const { free_gb, total_gb, used_percent } = data.storage;
            const el = document.getElementById('storage-info');
            if (el) {
                el.innerHTML = `<span class="stat-pill-icon">💾</span> <span>${free_gb} GB free / ${total_gb} GB (${used_percent}%)</span>`;
                if (used_percent > 90)      el.style.borderColor = 'var(--danger)';
                else if (used_percent > 75)  el.style.borderColor = 'var(--warning)';
                else                         el.style.borderColor = 'var(--border-subtle)';
            }
        }
    } catch (error) {
        console.error('Failed to fetch storage info:', error);
    }
}

// ---------------------------------------------------------
// Utilities
// ---------------------------------------------------------
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatSpeed(bytesPerSec) {
    return formatBytes(bytesPerSec) + '/s';
}

function formatETA(seconds) {
    if (seconds < 0 || !isFinite(seconds)) return '∞';
    if (seconds === 0) return '—';
    if (seconds < 60)   return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

function formatState(state) {
    const stateMap = {
        '0': 'Queued',
        '1': 'Checking',
        '2': 'Metadata',
        '3': 'Downloading',
        '4': 'Downloading',
        '5': 'Seeding',
        'completed': 'Completed',
        'downloading': 'Downloading',
        'seeding': 'Seeding',
    };
    return stateMap[state] || state;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showNotification(message, type) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 350);
    }, 5000);
}

// ---------------------------------------------------------
// Keyboard Shortcuts
// ---------------------------------------------------------
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + V anywhere auto-focuses the input
        if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
            const input = document.getElementById('magnet-input');
            const active = document.activeElement;
            // Only auto-focus if not already in an input/textarea
            if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
            if (input) {
                e.preventDefault();
                input.focus();
                navigator.clipboard.readText().then(text => {
                    if (text && text.trim()) {
                        input.value = text.trim();
                        showNotification('📋 Pasted from clipboard', 'info');
                    }
                }).catch(() => {
                    // Clipboard access denied — just focus the input
                    input.focus();
                });
            }
        }
    });
}

// ---------------------------------------------------------
// Paste Button
// ---------------------------------------------------------
function setupPasteButton() {
    const btn = document.getElementById('paste-btn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        const input = document.getElementById('magnet-input');
        try {
            const text = await navigator.clipboard.readText();
            if (text && text.trim()) {
                input.value = text.trim();
                input.focus();
                showNotification('📋 Pasted from clipboard', 'info');
            }
        } catch {
            showNotification('⚠️ Clipboard access denied. Please paste manually.', 'error');
        }
    });
}

// ---------------------------------------------------------
// Initialize
// ---------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    // Enter key on input
    document.getElementById('magnet-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') addMagnet();
    });

    setupTorrentEventListeners();
    setupKeyboardShortcuts();
    setupPasteButton();

    loadTorrents();
    startPolling();
    connectWebSocket();
    updateStorageInfo();

    setInterval(updateStorageInfo, 30000);
});
