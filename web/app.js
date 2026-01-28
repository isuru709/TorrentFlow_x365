// Configuration
const API_BASE = window.location.origin;
let ws = null;
let reconnectTimeout = null;
let lastTorrentsHash = '';
let pollInterval = null; // fallback polling when WebSocket unavailable

// Connect to WebSocket for real-time updates
function connectWebSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);
    
    ws.onopen = () => {
        console.log('WebSocket connected');
        clearTimeout(reconnectTimeout);
        // Force immediate data load to sync state
        lastTorrentsHash = ''; // Reset hash to force render
        loadTorrents();
        stopPolling(); // stop fallback polling once WS is live
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'update') {
            console.log('WebSocket update received:', data.torrents.length, 'torrents');
            updateTorrentsList(data.torrents);
        }
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        reconnectTimeout = setTimeout(connectWebSocket, 3000);
        startPolling(); // use polling while WS is down
    };
}

function startPolling() {
    if (pollInterval) return;
    console.log('Starting fallback polling for torrent updates');
    pollInterval = setInterval(loadTorrents, 1500); // 1.5s to reduce load but stay snappy
}

function stopPolling() {
    if (!pollInterval) return;
    clearInterval(pollInterval);
    pollInterval = null;
    console.log('Stopped fallback polling');
}

// Add magnet link
async function addMagnet() {
    const input = document.getElementById('magnet-input');
    const url = input.value.trim();
    const sequential = document.getElementById('sequential-download').checked;
    
    if (!url) {
        showNotification('Please enter a magnet link, torrent URL, or info hash', 'error');
        return;
    }
    
    const button = event.target || document.querySelector('button');
    const originalText = button.textContent;
    button.textContent = 'Adding...';
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
            // Immediately refresh torrent list via API and WebSocket
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
                
                if (confirm('🚫 The site is blocking downloads.\n\n✅ But we found the magnet link!\n\nClick OK to use it automatically, or Cancel to copy it manually.')) {
                    input.value = magnetLink;
                    showNotification('🔄 Trying with magnet link...', 'info');
                    button.textContent = originalText;
                    button.disabled = false;
                    setTimeout(() => addMagnet(), 500);
                    return;
                } else {
                    navigator.clipboard.writeText(magnetLink).then(() => {
                        showNotification('📋 Magnet link copied to clipboard!', 'success');
                    }).catch(() => {
                        showNotification(`📋 Copy this magnet link:\n\n${magnetLink.substring(0, 60)}...`, 'info');
                    });
                }
                return;
            }
        }
        
        if (errorMessage.includes('403') || errorMessage.includes('Forbidden') || errorMessage.includes('blocking')) {
            errorMessage = '🚫 Site is blocking automated downloads.\n\n✅ SOLUTIONS:\n1. Find the magnet link on the torrent page\n2. Upload the .torrent file manually\n3. Use a different torrent site';
        } else if (errorMessage.includes('404')) {
            errorMessage = '❌ Torrent not found. The link may be expired or invalid.';
        } else if (errorMessage.includes('timeout')) {
            errorMessage = '⏱️ Request timed out. Please try again.';
        }
        
        showNotification(errorMessage, 'error');
    } finally {
        button.textContent = originalText;
        button.disabled = false;
    }
}

// Upload torrent file
async function uploadTorrent() {
    const fileInput = document.getElementById('torrent-file');
    const file = fileInput.files[0];
    const sequential = document.getElementById('sequential-download').checked;
    
    if (!file) return;
    
    const formData = new FormData();
    formData.append('file', file);
    
    showNotification('📤 Uploading torrent file...', 'info');
    
    try {
        const response = await fetch(`${API_BASE}/api/upload-torrent?sequential=${sequential}`, {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            fileInput.value = '';
            showNotification('✓ Torrent file uploaded successfully!', 'success');
            // Immediately refresh torrent list via API and WebSocket
            setTimeout(() => loadTorrents(), 100);
        } else {
            throw new Error(result.message || 'Failed to upload torrent');
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

// Load torrents list
async function loadTorrents() {
    try {
        const now = new Date();
        const response = await fetch(`${API_BASE}/api/torrents?ts=${Date.now()}` , {
            cache: 'no-store',
            headers: {
                'Cache-Control': 'no-cache'
            }
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const torrents = await response.json();
        console.log(`[poll] ${now.toLocaleTimeString()} fetched ${torrents.length} torrents`);
        updateTorrentsList(torrents);
    } catch (error) {
        console.error('Error loading torrents:', error);
        const container = document.getElementById('torrents-container');
        if (container) {
            container.innerHTML = '<p class="empty-state error">⚠️ Failed to load torrents. Retrying...</p>';
        }
    }
}

// Update torrents list - OPTIMIZED for real-time updates
function updateTorrentsList(torrents) {
    const container = document.getElementById('torrents-container');
    
    if (!container) {
        console.error('Torrents container not found');
        return;
    }

    console.log('Updating torrents list:', torrents ? torrents.length : 0, 'torrents');
    
    // Handle empty state
    if (!torrents || torrents.length === 0) {
        container.innerHTML = '<p class="empty-state">📥 No active torrents. Add one above!</p>';
        updateStats(0, 0, 0);
        return;
    }

    // Remove any previous empty-state placeholder before rendering torrents
    container.querySelectorAll('.empty-state').forEach(el => el.remove());
    
    // Get existing torrent elements
    const existingTorrents = {};
    container.querySelectorAll('.torrent-item').forEach(item => {
        const id = item.dataset.torrentId;
        if (id) existingTorrents[id] = item;
    });
    
    // Calculate totals
    let totalDownloadRate = 0;
    let totalUploadRate = 0;
    
    // Process each torrent
    torrents.forEach((torrent, index) => {
        // Safely extract values with defaults
        const id = torrent.id || '';
        const name = torrent.name || 'Loading metadata...';
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
        
        // Debug: log progress for first torrent
        if (index === 0 && progress > 0) {
            console.log('Torrent progress:', name, progress.toFixed(2) + '%', 'DL:', formatSpeed(downloadRate));
        }
        
        totalDownloadRate += downloadRate;
        totalUploadRate += uploadRate;
        
        // Check if torrent element already exists
        if (existingTorrents[id]) {
            // Update existing element (faster, no flicker)
            updateTorrentElement(existingTorrents[id], torrent);
            delete existingTorrents[id]; // Mark as processed
        } else {
            // Create new torrent element
            const torrentHTML = createTorrentHTML(torrent);
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = torrentHTML;
            container.appendChild(tempDiv.firstElementChild);
        }
    });
    
    // Remove torrents that no longer exist
    Object.values(existingTorrents).forEach(element => {
        element.remove();
    });
    
    // Ensure listeners stay attached
    if (!window.__torrentListenersAttached) {
        setupTorrentEventListeners();
    }

    // Update header stats
    updateStats(torrents.length, totalDownloadRate, totalUploadRate);

    // Show last update time for visibility/debugging
    const containerTime = document.getElementById('last-update');
    if (containerTime) {
        const now = new Date();
        containerTime.textContent = `Last update: ${now.toLocaleTimeString()}`;
    }
}

// Update existing torrent element (efficient, no rebuild)
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
    
    // Update state attribute for CSS
    element.dataset.state = state;
    
    // Update progress bar
    const progressFill = element.querySelector('.progress-fill');
    if (progressFill) {
        progressFill.style.width = `${progress.toFixed(1)}%`;
    }
    
    // Update stats
    const stats = {
        'Progress': `${progress.toFixed(1)}%`,
        'State': `<span class="state-${state}">${state}</span>`,
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
        if (label && value) {
            const labelText = label.textContent;
            if (stats[labelText]) {
                value.innerHTML = stats[labelText];
            }
        }
    });
}

// Create HTML for new torrent
function createTorrentHTML(torrent) {
    const id = torrent.id || '';
    const name = torrent.name || 'Loading metadata...';
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
        ? '<span class="done-badge">✅ COMPLETED</span>'
        : (isSeeding ? '<span class="seed-badge">🌱 SEEDING</span>' : '');

    // Determine button state
    const isPaused = stateLower.includes('pause') || stateLower.includes('stop');
    const pauseDisabled = (isPaused || isCompleted) ? 'disabled' : '';
    const resumeDisabled = (!isPaused || isCompleted) ? 'disabled' : '';
    const actionButtons = `
        <button type="button" class="btn-pause" data-id="${id}" title="Pause torrent" ${pauseDisabled}>⏸ Pause</button>
        <button type="button" class="btn-download" data-id="${id}" title="Download files">⬇ Download</button>
        <button type="button" class="btn-resume" data-id="${id}" title="Resume torrent" ${resumeDisabled}>▶ Resume</button>
    `;
    
    return `
        <div class="torrent-item ${isSeeding ? 'seeding-torrent' : ''}" data-torrent-id="${id}" data-state="${state}">
            <div class="torrent-header">
                <div class="torrent-name" title="${escapeHtml(name)}">
                    ${escapeHtml(name)} ${badge}
                </div>
                <div class="torrent-actions">
                    ${actionButtons}
                    <button type="button" class="btn-delete" data-id="${id}" title="Delete torrent">🗑 Delete</button>
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
                    <span class="stat-value state-${state}">${state}</span>
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

// Setup event listeners for torrent action buttons (called once on init)
function setupTorrentEventListeners() {
    const container = document.getElementById('torrents-container');
    if (!container) {
        console.warn('Torrents container not found during setup');
        return;
    }
    
    // Add event delegation - works for all current and future buttons
    container.addEventListener('click', (e) => {
        const target = e.target.closest('button');
        if (!target) return;
        
        const torrentId = target.dataset.id;
        if (!torrentId) return;
        
        e.preventDefault();
        e.stopPropagation();
        
        if (target.classList.contains('btn-pause')) {
            pauseTorrent(torrentId);
        } else if (target.classList.contains('btn-resume')) {
            resumeTorrent(torrentId);
        } else if (target.classList.contains('btn-download')) {
            downloadTorrent(torrentId);
        } else if (target.classList.contains('btn-delete')) {
            deleteTorrent(torrentId);
        }
    });
    
    window.__torrentListenersAttached = true;
    console.log('✓ Torrent event listeners attached');
}

// Pause torrent
async function pauseTorrent(id) {
    if (!id) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/torrents/${id}/pause`, { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to pause: ${response.statusText}`);
        }
        
        showNotification('✓ Torrent paused', 'success');
        setTimeout(loadTorrents, 500);
    } catch (error) {
        console.error('Pause error:', error);
        showNotification(`❌ Error pausing torrent: ${error.message}`, 'error');
    }
}

// Resume torrent
async function resumeTorrent(id) {
    if (!id) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/torrents/${id}/resume`, { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to resume: ${response.statusText}`);
        }
        
        showNotification('✓ Torrent resumed', 'success');
        setTimeout(loadTorrents, 500);
    } catch (error) {
        console.error('Resume error:', error);
        showNotification(`❌ Error resuming torrent: ${error.message}`, 'error');
    }
}

// Download torrent contents (single file or zip)
async function downloadTorrent(id) {
    if (!id) return;

    try {
        const response = await fetch(`${API_BASE}/api/torrents/${id}/files`);
        const files = await response.json();

        if (!response.ok) {
            const detail = (files && files.detail) ? files.detail : response.statusText;
            throw new Error(detail || 'Files not available yet');
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
        console.error('Download error:', error);
        showNotification(`❌ Unable to download yet: ${error.message}`, 'error');
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
            <button type="button" class="file-picker-download" aria-label="Download file">⬇</button>
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
        if (e.target === backdrop) {
            closeModal();
        }
    });

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
}

// Delete torrent
async function deleteTorrent(id) {
    if (!id) return;
    
    if (!confirm('⚠️ Remove this torrent and delete all data?')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/torrents/${id}?delete_files=true`, { 
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }
        
        showNotification('✓ Torrent removed successfully', 'success');
        
        // Remove from UI immediately for better UX
        const torrentElement = document.querySelector(`[data-torrent-id="${id}"]`);
        if (torrentElement) {
            torrentElement.style.opacity = '0';
            torrentElement.style.transform = 'scale(0.95)';
            setTimeout(() => {
                loadTorrents();
            }, 300);
        } else {
            loadTorrents();
        }
    } catch (error) {
        console.error('Delete error:', error);
        showNotification(`❌ Error deleting torrent: ${error.message}`, 'error');
        loadTorrents(); // Refresh to ensure consistency
    }
}

// Update stats in header
function updateStats(count, downloadSpeed, uploadSpeed) {
    const torrentsEl = document.getElementById('total-torrents');
    const speedEl = document.getElementById('total-speed');
    
    if (torrentsEl) {
        torrentsEl.textContent = `${count} Torrent${count !== 1 ? 's' : ''}`;
    }
    
    if (speedEl) {
        if (uploadSpeed > 0) {
            speedEl.textContent = `↓ ${formatSpeed(downloadSpeed)} | ↑ ${formatSpeed(uploadSpeed)}`;
        } else {
            speedEl.textContent = `↓ ${formatSpeed(downloadSpeed)}`;
        }
    }
}

// Utility functions
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
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
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
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
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// Fetch storage info
async function updateStorageInfo() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        const data = await response.json();
        
        if (data.storage) {
            const { free_gb, total_gb, used_percent } = data.storage;
            const storageElement = document.getElementById('storage-info');
            storageElement.textContent = `💾 ${free_gb} GB free / ${total_gb} GB (${used_percent}% used)`;
            
            // Color code based on usage
            if (used_percent > 90) {
                storageElement.style.color = '#dc3545';
            } else if (used_percent > 75) {
                storageElement.style.color = '#ffc107';
            } else {
                storageElement.style.color = 'rgba(255, 255, 255, 0.9)';
            }
        }
    } catch (error) {
        console.error('Failed to fetch storage info:', error);
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Setup magnet input enter key
    document.getElementById('magnet-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            addMagnet();
        }
    });
    
    // Setup event delegation for torrent buttons (once)
    setupTorrentEventListeners();
    
    // Load initial data
    loadTorrents();
    startPolling(); // start immediately; will stop once WebSocket connects
    connectWebSocket();
    updateStorageInfo();
    
    // Update storage info every 30 seconds
    setInterval(updateStorageInfo, 30000);
});
