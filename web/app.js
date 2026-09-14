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

        // Keep connection alive for Heroku (prevents 55s timeout)
        window.wsPingInterval = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send('ping');
            }
        }, 30000);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'update') {
                if (data.torrents) updateTorrentsList(data.torrents);
                if (data.media_jobs) updateMediaList(data.media_jobs);
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
        clearInterval(window.wsPingInterval);
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
    const sequential = true;

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
    const sequential = true;

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
    const filesAvailable = torrent.files_available !== false;

    element.dataset.state = state;
    element.dataset.filesAvailable = String(filesAvailable);
    element.dataset.jobType = torrent.job_type || 'torrent';

    const progressFill = element.querySelector('.progress-fill');
    if (progressFill) {
        progressFill.style.width = `${progress.toFixed(1)}%`;
    }

    // Update badge for completed torrents with unavailable files
    const nameEl = element.querySelector('.torrent-name');
    if (nameEl) {
        const stateLower = (state || '').toLowerCase();
        const isCompleted = progress >= 100 || stateLower.includes('complete');
        
        // Remove existing badges
        const existingBadges = nameEl.querySelectorAll('.done-badge, .seed-badge, .unavailable-badge');
        existingBadges.forEach(b => b.remove());
        
        if (isCompleted && !filesAvailable) {
            const badge = document.createElement('span');
            badge.className = 'unavailable-badge';
            badge.textContent = '⚠️ Files Unavailable';
            nameEl.appendChild(badge);
        } else if (isCompleted) {
            const badge = document.createElement('span');
            badge.className = 'done-badge';
            badge.textContent = '✅ Completed';
            nameEl.appendChild(badge);
        }
    }

    // Update download button disabled state
    const downloadBtn = element.querySelector('.btn-download');
    if (downloadBtn) {
        downloadBtn.disabled = !filesAvailable;
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
    const filesAvailable = torrent.files_available !== false;

    const stateLower = (state || '').toLowerCase();
    const isCompleted = progress >= 100 || stateLower.includes('complete');
    const isSeeding = !isCompleted && (stateLower.includes('seeding') || stateLower.includes('seed'));
    
    let badge = '';
    if (isCompleted && !filesAvailable) {
        badge = '<span class="unavailable-badge">⚠️ Files Unavailable</span>';
    } else if (isCompleted) {
        badge = '<span class="done-badge">✅ Completed</span>';
    } else if (isSeeding) {
        badge = '<span class="seed-badge">🌱 Seeding</span>';
    }

    const isPaused = stateLower.includes('pause') || stateLower.includes('stop');
    const pauseDisabled = (isPaused || isCompleted) ? 'disabled' : '';
    const resumeDisabled = (!isPaused || isCompleted) ? 'disabled' : '';
    const downloadDisabled = !filesAvailable ? 'disabled' : '';
    const isMedia = torrent.job_type === 'media';

    return `
        <div class="torrent-item" data-torrent-id="${id}" data-state="${state}" data-files-available="${filesAvailable}" data-job-type="${torrent.job_type || 'torrent'}">
            <div class="torrent-header">
                <div class="torrent-name" title="${escapeHtml(name)}">
                    ${escapeHtml(name)} ${badge}
                </div>
                <div class="torrent-actions">
                    ${isMedia ? '' : `<button type="button" class="btn-copy-magnet" data-id="${id}" data-name="${escapeHtml(name)}" title="Copy Magnet Link">📋 Magnet</button>`}
                    ${isMedia ? '' : `<button type="button" class="btn-pause" data-id="${id}" title="Pause" ${pauseDisabled}>⏸ Pause</button>`}
                    ${isMedia ? '' : `<button type="button" class="btn-resume" data-id="${id}" title="Resume" ${resumeDisabled}>▶ Resume</button>`}
                    <button type="button" class="btn-download" data-id="${id}" title="Download files" ${downloadDisabled}>⬇ Files</button>
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
                ${isMedia ? '' : `
                <div class="stat-item">
                    <span class="stat-label">Peers</span>
                    <span class="stat-value">${numPeers} (${numSeeds} seeds)</span>
                </div>`}
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
    const handleActionClick = (e) => {
        const target = e.target.closest('button');
        if (!target) return;

        const torrentId = target.dataset.id;
        if (!torrentId) return;

        e.preventDefault();
        e.stopPropagation();
        const item = target.closest('.torrent-item');
        const jobType = item ? item.dataset.jobType : 'torrent';

        if (target.classList.contains('btn-pause'))         pauseTorrent(torrentId);
        else if (target.classList.contains('btn-resume'))   resumeTorrent(torrentId);
        else if (target.classList.contains('btn-download')) downloadTorrent(torrentId, jobType);
        else if (target.classList.contains('btn-delete'))   deleteTorrent(torrentId, jobType);
        else if (target.classList.contains('btn-copy-magnet')) {
            const name = target.dataset.name || torrentId;
            const magnetUri = `magnet:?xt=urn:btih:${torrentId}&dn=${encodeURIComponent(name)}`;
            navigator.clipboard.writeText(magnetUri).then(() => {
                const orig = target.innerHTML;
                target.innerHTML = '✅ Copied!';
                setTimeout(() => target.innerHTML = orig, 2000);
            }).catch(() => showNotification('Failed to copy', 'error'));
        }
    };

    const container = document.getElementById('torrents-container');
    if (container) container.addEventListener('click', handleActionClick);
    
    const mediaContainer = document.getElementById('media-jobs-container');
    if (mediaContainer) mediaContainer.addEventListener('click', handleActionClick);

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

async function downloadTorrent(id, jobType = 'torrent') {
    if (!id) return;
    window.currentModalJobType = jobType;
    try {
        const route = jobType === 'media' ? 'media' : 'torrents';
        const response = await fetch(`${API_BASE}/api/${route}/${id}/files`);
        const files = await response.json();

        if (!response.ok) {
            throw new Error((files && files.detail) ? files.detail : 'Files not available yet');
        }

        const availableFiles = Array.isArray(files) ? files : [];
        if (availableFiles.length === 0) {
            showNotification('⚠️ Files not ready yet. Please wait for the download to finish.', 'info');
            return;
        }

        showFilePicker(id, availableFiles);
    } catch (error) {
        showNotification(`❌ ${error.message}`, 'error');
    }
}

function triggerDownload(torrentId, relativePath = null, asZip = false) {
    const link = document.createElement('a');
    const route = window.currentModalJobType === 'media' ? 'media' : 'torrents';
    if (asZip || !relativePath) {
        link.href = `${API_BASE}/api/${route}/${torrentId}/download`;
    } else {
        link.href = `${API_BASE}/api/${route}/${torrentId}/download?file=${encodeURIComponent(relativePath)}`;
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
        
        let buttonsHTML = `
            <button type="button" class="file-picker-copy" aria-label="Copy direct link" title="Copy Direct Link" style="background: none; border: 1px solid #4a5568; color: #a0aec0; border-radius: 4px; cursor: pointer; padding: 4px 8px;">📋</button>
            <button type="button" class="file-picker-download" aria-label="Download file" title="Download">⬇ Get</button>
        `;
        
        if (file.media_type === 'video' || file.media_type === 'audio') {
            buttonsHTML = `<button type="button" class="file-picker-play" aria-label="Play media" title="Play Media" style="background: #e53e3e; border: none; color: white; border-radius: 4px; cursor: pointer; padding: 4px 8px; font-weight: 600;">▶ Play</button>` + buttonsHTML;
        }

        row.innerHTML = `
            <div class="file-picker-name" title="${escapeHtml(file.relative_path || 'file')}">${escapeHtml(file.relative_path || 'file')}</div>
            <div class="file-picker-size">${formatBytes(file.size || 0)}</div>
            <div class="file-picker-btn-group" style="display:flex; gap:6px; align-items:center;">
                ${buttonsHTML}
            </div>
        `;

        const dlBtn = row.querySelector('.file-picker-download');
        if (dlBtn) {
            dlBtn.addEventListener('click', () => {
                triggerDownload(torrentId, file.relative_path);
                backdrop.remove();
            });
        }
        
        const copyBtn = row.querySelector('.file-picker-copy');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                const fileExt = file.relative_path.split('.').pop().toLowerCase();
                const mediaType = file.media_type;
                const isPlayable = mediaType === 'video' || mediaType === 'audio' || ['mp4', 'mkv', 'webm', 'mp3', 'm4a'].includes(fileExt);

                const route = window.currentModalJobType === 'media' ? 'media' : 'torrents';
                const dlLink = `${API_BASE}/api/${route}/${torrentId}/download?file_index=${file.index}`;
                const directUrl = file.index !== undefined && file.index !== null
                    ? dlLink
                    : `${API_BASE}/api/${route}/${torrentId}/download?file=${encodeURIComponent(file.relative_path)}`;
                
                navigator.clipboard.writeText(directUrl).then(() => {
                    copyBtn.innerHTML = '✅';
                    setTimeout(() => copyBtn.innerHTML = '📋', 2000);
                });
            });
        }
        
        const playBtn = row.querySelector('.file-picker-play');
        if (playBtn) {
            playBtn.addEventListener('click', () => {
                playMedia(torrentId, file, files);
                backdrop.remove();
            });
        }

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

async function deleteTorrent(id, jobType = 'torrent') {
    if (!id) return;

    const route = jobType === 'media' ? 'media' : 'torrents';

    const deleteFiles = confirm('⚠️ Do you also want to delete the files from disk?\n\nClick OK to delete files & torrent, or Cancel to only remove from list.');

    try {
        if (deleteFiles) {
            const response = await fetch(`${API_BASE}/api/${route}/${id}?delete_files=true`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error(response.statusText);
            showNotification('🗑️ Item and files deleted', 'success');
        } else {
            const response = await fetch(`${API_BASE}/api/${route}/${id}?delete_files=false`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error(response.statusText);
            showNotification('🗑️ Item removed from list', 'success');
        }
        setTimeout(loadTorrents, 500);
    } catch (error) {
        showNotification(`❌ Error removing item: ${error.message}`, 'error');
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
                if (used_percent > 90)       el.style.borderColor = 'var(--danger)';
                else if (used_percent > 75)  el.style.borderColor = 'var(--warning)';
                else                         el.style.borderColor = 'var(--border-subtle)';
            }
        }
    } catch (error) {
        console.error('Failed to fetch storage info:', error);
    }
}

// ---------------------------------------------------------
// Media Player
// ---------------------------------------------------------
function playMedia(torrentId, mediaFile, allFiles) {
    const modal = document.getElementById('media-modal');
    const title = document.getElementById('media-title');
    const videoPlayer = document.getElementById('media-player');
    const audioPlayer = document.getElementById('audio-player');
    
    title.textContent = mediaFile.relative_path.split('/').pop();
    
    const route = window.currentModalJobType === 'media' ? 'media' : 'torrents';
    const streamUrl = `${API_BASE}/api/${route}/${torrentId}/stream/${mediaFile.index}`;
    
    videoPlayer.style.display = 'none';
    audioPlayer.style.display = 'none';
    
    let activePlayer = null;
    if (mediaFile.media_type === 'video') {
        activePlayer = videoPlayer;
        videoPlayer.style.display = 'block';
    } else if (mediaFile.media_type === 'audio') {
        activePlayer = audioPlayer;
        audioPlayer.style.display = 'block';
    }
    
    if (!activePlayer) return;
    
    // Clear existing tracks
    activePlayer.innerHTML = '';
    
    // Auto-detect subtitle in the same folder with the same name (or just any SRT/VTT in the torrent)
    const subFiles = allFiles.filter(f => f.media_type === 'subtitle');
    subFiles.forEach((sub, i) => {
        const track = document.createElement('track');
        track.kind = 'subtitles';
        track.label = sub.relative_path.split('/').pop();
        track.srclang = 'en';
        track.src = `${API_BASE}/api/torrents/${torrentId}/subtitle/${sub.index}`;
        if (i === 0) track.default = true;
        activePlayer.appendChild(track);
    });
    
    activePlayer.src = streamUrl;
    modal.style.display = 'flex';
    activePlayer.play().catch(e => console.log('Auto-play blocked:', e));
}

function closeMediaModal(event) {
    if (event.target.id === 'media-modal' || event.target.classList.contains('modal-close')) {
        const modal = document.getElementById('media-modal');
        const videoPlayer = document.getElementById('media-player');
        const audioPlayer = document.getElementById('audio-player');
        
        modal.style.display = 'none';
        videoPlayer.pause();
        videoPlayer.src = '';
        audioPlayer.pause();
        audioPlayer.src = '';
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
// =========================================================
// Media Engine Functions
// =========================================================

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('tab-' + tab).classList.add('active');
    
    if (tab === 'torrent') {
        document.getElementById('view-torrent').style.display = 'block';
        document.getElementById('view-media').style.display = 'none';
    } else {
        document.getElementById('view-torrent').style.display = 'none';
        document.getElementById('view-media').style.display = 'block';
    }
}

async function pasteMediaUrl() {
    try {
        const text = await navigator.clipboard.readText();
        document.getElementById('media-url-input').value = text;
    } catch (err) {
        showNotification('Failed to read clipboard', 'error');
    }
}

async function probeMedia() {
    const url = document.getElementById('media-url-input').value.trim();
    if (!url) return showNotification('Please enter a URL', 'error');
    
    const btn = document.getElementById('probe-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span> Probing...';
    
    try {
        const res = await fetch(`${API_BASE}/api/media/probe`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url})
        });
        const data = await res.json();
        
        if (!res.ok) throw new Error(data.detail || 'Probe failed');
        
        const resultDiv = document.getElementById('media-probe-result');
        resultDiv.style.display = 'block';
        
        let html = `<h4>${escapeHtml(data.title)}</h4>`;
        if (data.is_playlist) {
            html += `<p style="margin-bottom:10px;">Playlist with ${data.playlist_count} items</p>`;
            html += `<button class="btn btn-primary" onclick="startMediaDownload('${url}', null, true)">Download Playlist</button>`;
        } else {
            let options = '';
            data.formats.slice(-10).forEach(f => {
                let fmt = f.format_id;
                // If it's a video-only format, append +bestaudio to fix the "no sound" issue
                if (f.vcodec !== 'none' && f.acodec === 'none') {
                    fmt = `${f.format_id}+bestaudio/${f.format_id}/best`;
                }
                options += `<option value="${fmt}" ${f.is_default ? 'selected' : ''}>${f.resolution} (${f.ext})</option>`;
            });
            html += `
                <select id="media-format-select" class="file-picker-select" style="margin: 10px 0;">
                    ${options}
                </select>
                <br>
                <label style="display:flex; align-items:center; gap:8px; margin-bottom:10px;"><input type="checkbox" id="media-subs-check"> Embed Subtitles</label>
                <button class="btn btn-primary" onclick="startMediaDownload('${url}', document.getElementById('media-format-select').value, false, document.getElementById('media-subs-check').checked)">Download Media</button>
            `;
        }
        resultDiv.innerHTML = html;
    } catch (e) {
        showNotification(`Error: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">🔍</span> Probe';
    }
}

async function startMediaDownload(url, format_id, is_playlist, embed_subs = false) {
    const overridePlaylist = document.getElementById('media-playlist-check').checked;
    
    try {
        const res = await fetch(`${API_BASE}/api/media/download`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                url, 
                format_id, 
                embed_subtitles: embed_subs,
                is_playlist: overridePlaylist || is_playlist
            })
        });
        const data = await res.json();
        if (res.ok) {
            showNotification('Download started', 'success');
            document.getElementById('media-probe-result').style.display = 'none';
            document.getElementById('media-url-input').value = '';
        } else {
            throw new Error(data.detail || 'Failed to start download');
        }
    } catch (e) {
        showNotification(`Error: ${e.message}`, 'error');
    }
}

function updateMediaList(jobs) {
    const container = document.getElementById('media-jobs-container');
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📺</div><p>No media downloads</p><span>Paste a URL to download videos or playlists</span></div>';
        return;
    }

    container.querySelectorAll('.empty-state').forEach(el => el.remove());

    const existingJobs = {};
    container.querySelectorAll('.torrent-item').forEach(item => {
        const id = item.dataset.torrentId;
        if (id) existingJobs[id] = item;
    });

    jobs.forEach((job) => {
        const id = job.id || '';
        if (existingJobs[id]) {
            updateTorrentElement(existingJobs[id], job);
            delete existingJobs[id];
        } else {
            const html = createTorrentHTML(job);
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = html;
            container.appendChild(tempDiv.firstElementChild);
        }
    });

    Object.values(existingJobs).forEach(element => {
        element.style.opacity = '0';
        element.style.transform = 'scale(0.96)';
        setTimeout(() => element.remove(), 300);
    });
}
