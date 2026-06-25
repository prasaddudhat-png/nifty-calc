(function() {
    // Only run the auto-refresh timer if we are in the top-level window (not inside an iframe)
    if (window !== window.top) {
        console.log('[Auto-Refresh] Running inside an iframe. Timer deferred to parent window.');
        return;
    }

    const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes
    const WARNING_LEAD_TIME_MS = 15 * 1000;    // 15 seconds warning time

    let refreshTimer = null;
    let timeRemaining = REFRESH_INTERVAL_MS;
    let isPaused = false;
    let toastElement = null;

    // Selective storage and cache cleanup to solve storage and fetching delays
    async function cleanBrowserStorage() {
        console.log('[Auto-Refresh] Initiating browser cache and storage cleanup...');
        
        // 1. Clear Service Worker Cache Storage (forces fresh fetch of assets/APIs and resolves delay issues)
        if (window.caches) {
            try {
                const names = await caches.keys();
                await Promise.all(names.map(function(name) {
                    return caches.delete(name).then(function(success) {
                        if (success) {
                            console.log(`[Auto-Refresh] Deleted cache storage: ${name}`);
                        }
                    });
                }));
            } catch (err) {
                console.warn('[Auto-Refresh] Error listing/deleting caches:', err);
            }
        }

        // 2. Clear Session Storage
        try {
            sessionStorage.clear();
            console.log('[Auto-Refresh] Session storage cleared.');
        } catch (e) {
            console.warn('[Auto-Refresh] Session storage clear failed:', e);
        }

        // 3. Selective LocalStorage Cleanup
        // Critical settings and user data are strictly preserved to prevent loss of state or trade books!
        try {
            const preservedKeys = [
                'nifty_calc_backend_url',
                'nifty_calc_scanner_url',
                'autocalc_current_user',
                'autocalc_box_config',
                'autocalc_live_tracker_state'
            ];
            
            const keysToRemove = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key) {
                    // Keep essential settings, all user trade books, and scanner search histories
                    const isPreserved = preservedKeys.includes(key) || 
                                       key.startsWith('autocalc_tradebook_') || 
                                       key.startsWith('scanner_history') || 
                                       key === 'scanner_search_history';
                    
                    if (!isPreserved) {
                        keysToRemove.push(key);
                    }
                }
            }
            
            keysToRemove.forEach(function(key) {
                localStorage.removeItem(key);
            });
            console.log(`[Auto-Refresh] Cleared ${keysToRemove.length} non-essential localStorage keys.`);
        } catch (e) {
            console.warn('[Auto-Refresh] Error cleaning localStorage:', e);
        }
    }

    // Force reload bypassing browser caches
    async function triggerHardRefresh() {
        console.log('[Auto-Refresh] Initiating state save before refresh...');
        
        // 1. Save state on main window if save functions are defined
        if (typeof window.saveBoxConfig === 'function') {
            try {
                await window.saveBoxConfig();
                console.log('[Auto-Refresh] Main window box config saved.');
            } catch (e) {
                console.error('[Auto-Refresh] Failed to save main window box config:', e);
            }
        }
        if (typeof window.saveLiveTrackerState === 'function') {
            try {
                window.saveLiveTrackerState();
                console.log('[Auto-Refresh] Main window live tracker state saved.');
            } catch (e) {
                console.error('[Auto-Refresh] Failed to save main window live tracker state:', e);
            }
        }

        // 2. Save state inside loaded iframes (critical for app dashboard mode containing frames)
        const iframes = document.querySelectorAll('iframe');
        for (let i = 0; i < iframes.length; i++) {
            try {
                const iframeWin = iframes[i].contentWindow;
                if (iframeWin) {
                    if (typeof iframeWin.saveBoxConfig === 'function') {
                        await iframeWin.saveBoxConfig();
                        console.log(`[Auto-Refresh] Iframe ${i} box config saved.`);
                    }
                    if (typeof iframeWin.saveLiveTrackerState === 'function') {
                        iframeWin.saveLiveTrackerState();
                        console.log(`[Auto-Refresh] Iframe ${i} live tracker state saved.`);
                    }
                }
            } catch (e) {
                // Ignore cross-origin errors if iframe is loaded from different domain
                console.warn(`[Auto-Refresh] Could not save state for iframe ${i}:`, e);
            }
        }

        // 3. Clean storage and reload
        await cleanBrowserStorage();
        console.log('[Auto-Refresh] Performing hard refresh...');
        
        // Append unique timestamp to bypass network / proxy caching
        const url = new URL(window.location.href);
        url.searchParams.set('t_refresh', Date.now().toString());
        window.location.replace(url.toString());
    }

    // Render warning toast UI dynamically
    function showToast(secondsLeft) {
        if (toastElement) {
            updateToast(secondsLeft);
            return;
        }

        const styleId = 'auto-refresh-toast-styles';
        if (!document.getElementById(styleId)) {
            const style = document.createElement('style');
            style.id = styleId;
            style.innerHTML = `
                .refresh-toast {
                    position: fixed;
                    bottom: 20px;
                    right: 20px;
                    background: rgba(23, 18, 33, 0.95);
                    backdrop-filter: blur(12px);
                    -webkit-backdrop-filter: blur(12px);
                    border: 1px solid rgba(167, 139, 250, 0.4);
                    border-radius: 12px;
                    padding: 16px;
                    box-shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.7), 0 8px 15px -6px rgba(0, 0, 0, 0.7);
                    z-index: 999999;
                    font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
                    color: #ffffff;
                    width: 320px;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                    animation: slideIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                }
                .refresh-toast-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .refresh-toast-title {
                    font-size: 14px;
                    font-weight: 600;
                    color: #a78bfa;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .refresh-toast-title svg {
                    animation: spin 3s linear infinite;
                }
                .refresh-toast-desc {
                    font-size: 12px;
                    color: #8b85a1;
                    line-height: 1.45;
                }
                .refresh-toast-progress-container {
                    width: 100%;
                    height: 4px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 2px;
                    overflow: hidden;
                }
                .refresh-toast-progress {
                    height: 100%;
                    background: #a78bfa;
                    width: 100%;
                    transition: width 1s linear;
                }
                .refresh-toast-actions {
                    display: flex;
                    justify-content: flex-end;
                    gap: 8px;
                    margin-top: 4px;
                }
                .refresh-btn {
                    padding: 6px 14px;
                    font-size: 12px;
                    border-radius: 6px;
                    cursor: pointer;
                    font-weight: 600;
                    transition: all 0.2s ease;
                }
                .refresh-btn-primary {
                    background: #a78bfa;
                    color: #0f0b15;
                    border: none;
                }
                .refresh-btn-primary:hover {
                    background: #c084fc;
                }
                .refresh-btn-secondary {
                    background: transparent;
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    color: #ffffff;
                }
                .refresh-btn-secondary:hover {
                    background: rgba(255, 255, 255, 0.05);
                    border-color: rgba(255, 255, 255, 0.25);
                }
                @keyframes slideIn {
                    from { transform: translateY(100px) scale(0.9); opacity: 0; }
                    to { transform: translateY(0) scale(1); opacity: 1; }
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `;
            document.head.appendChild(style);
        }

        toastElement = document.createElement('div');
        toastElement.className = 'refresh-toast';
        toastElement.innerHTML = `
            <div class="refresh-toast-header">
                <div class="refresh-toast-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                    <span>Cache Storage Cleanup</span>
                </div>
            </div>
            <div class="refresh-toast-desc" id="refreshToastDesc">
                Refreshing in ${secondsLeft} seconds to optimize data fetching...
            </div>
            <div class="refresh-toast-progress-container">
                <div class="refresh-toast-progress" id="refreshToastProgress"></div>
            </div>
            <div class="refresh-toast-actions">
                <button class="refresh-btn refresh-btn-secondary" id="refreshPauseBtn">Pause</button>
                <button class="refresh-btn refresh-btn-primary" id="refreshNowBtn">Refresh Now</button>
            </div>
        `;
        document.body.appendChild(toastElement);

        document.getElementById('refreshNowBtn').addEventListener('click', triggerHardRefresh);
        document.getElementById('refreshPauseBtn').addEventListener('click', togglePause);
    }

    function updateToast(secondsLeft) {
        const desc = document.getElementById('refreshToastDesc');
        const progress = document.getElementById('refreshToastProgress');
        if (desc) {
            desc.textContent = `Refreshing in ${secondsLeft} seconds to clean cache and optimize data fetching...`;
        }
        if (progress) {
            const pct = (secondsLeft / (WARNING_LEAD_TIME_MS / 1000)) * 100;
            progress.style.width = `${pct}%`;
        }
    }

    function removeToast() {
        if (toastElement) {
            toastElement.remove();
            toastElement = null;
        }
    }

    function togglePause() {
        isPaused = !isPaused;
        const pauseBtn = document.getElementById('refreshPauseBtn');
        const desc = document.getElementById('refreshToastDesc');
        if (pauseBtn) {
            pauseBtn.textContent = isPaused ? 'Resume' : 'Pause';
            pauseBtn.className = isPaused ? 'refresh-btn refresh-btn-primary' : 'refresh-btn refresh-btn-secondary';
        }
        if (desc) {
            if (isPaused) {
                desc.textContent = 'Auto-refresh paused. Browser storage and cache will not be auto-cleaned.';
                const progress = document.getElementById('refreshToastProgress');
                if (progress) progress.style.width = '100%';
            } else {
                desc.textContent = 'Auto-refresh resumed.';
            }
        }
    }

    function startTimer() {
        const checkInterval = 1000; // 1 second tick
        console.log('[Auto-Refresh] Registered 5-minute auto-refresh and cache cleanup timer.');
        
        refreshTimer = setInterval(function() {
            if (isPaused) return;

            timeRemaining -= checkInterval;
            
            if (timeRemaining <= WARNING_LEAD_TIME_MS) {
                const secondsLeft = Math.ceil(timeRemaining / 1000);
                if (secondsLeft > 0) {
                    showToast(secondsLeft);
                } else {
                    removeToast();
                    clearInterval(refreshTimer);
                    triggerHardRefresh();
                }
            }
        }, checkInterval);
    }

    startTimer();
})();
