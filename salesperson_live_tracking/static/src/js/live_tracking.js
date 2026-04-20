/* ══════════════════════════════════════════════
   live_tracking.js
   Salesperson Live Tracking — GPS + Camera logic
══════════════════════════════════════════════ */

(function () {
    'use strict';

    /* ── Guard: only run on the live tracking page ── */
    if (!document.getElementById('startButton')) return;

    /* ══════════════════════════════════════════════
       READ SERVER DATA  (injected via data-* attrs)
    ══════════════════════════════════════════════ */
    const root        = document.getElementById('trackingRoot');
    const initialDist = root ? parseFloat(root.dataset.distance || '0') : 0;

    /* ══════════════════════════════════════════════
       STATE
    ══════════════════════════════════════════════ */
    const state = {
        tracking:      false,
        watchId:       null,
        heartbeatId:   null,
        timerId:       null,
        lastPayload:   null,
        trackingStart: null,
    };

    /* ══════════════════════════════════════════════
       DOM REFS
    ══════════════════════════════════════════════ */
    const $ = (id) => document.getElementById(id);

    const el = {
        startButton:       $('startButton'),
        stopButton:        $('stopButton'),
        statusBadge:       $('statusBadge'),
        statusDot:         $('statusDot'),
        statusLabel:       $('statusLabel'),
        noticeBox:         $('noticeBox'),
        lastSeenValue:     $('lastSeenValue'),
        latitudeValue:     $('latitudeValue'),
        longitudeValue:    $('longitudeValue'),
        locationNameValue: $('locationNameValue'),
        accuracyValue:     $('accuracyValue'),
        takingTimeValue:   $('takingTimeValue'),
        mapButton:         $('mapButton'),
        kpiDistance:       $('kpiDistance'),
    };

    /* ══════════════════════════════════════════════
       HELPERS
    ══════════════════════════════════════════════ */

    /**
     * Update the status badge in the header.
     * @param {string} status  - 'live' | 'idle' | 'offline'
     * @param {string} label   - Human-readable label
     */
    const updateStatus = (status, label) => {
        const s = status || 'offline';
        el.statusBadge.className   = `status-badge badge-${s}`;
        el.statusDot.className     = `status-dot dot-${s}`;
        el.statusLabel.textContent = label || 'Offline';
    };

    /**
     * Set the notice banner below the action bar.
     * @param {string} type    - '' | 'success' | 'warning' | 'danger'
     * @param {string} title
     * @param {string} message
     */
    const setNotice = (type, title, message) => {
        el.noticeBox.className = `notice${type ? ' notice-' + type : ''}`;
        el.noticeBox.innerHTML = `<strong>${title}</strong>${message}`;
    };

    /**
     * Format elapsed milliseconds as MM:SS or HH:MM:SS.
     */
    const formatDuration = (ms) => {
        const totalSec = Math.floor(ms / 1000);
        const h = Math.floor(totalSec / 3600);
        const m = Math.floor((totalSec % 3600) / 60);
        const s = totalSec % 60;
        const pad = (n) => String(n).padStart(2, '0');
        return h > 0
            ? `${pad(h)}:${pad(m)}:${pad(s)}`
            : `${pad(m)}:${pad(s)}`;
    };

    /** Update the "Taking Time" metric every second while tracking. */
    const tickTimer = () => {
        if (!state.trackingStart) return;
        el.takingTimeValue.textContent = formatDuration(Date.now() - state.trackingStart);
    };

    /**
     * POST JSON payload to a backend endpoint.
     * @param {string} url
     * @param {object} payload
     * @returns {Promise<object>}
     */
    const postJson = async (url, payload) => {
        const res = await fetch(url, {
            method:      'POST',
            headers:     { 'Content-Type': 'application/json' },
            body:        JSON.stringify(payload || {}),
            credentials: 'same-origin',
            keepalive:   true,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    };

    /* ══════════════════════════════════════════════
       METRICS REFRESH
       Called after every successful location push.
    ══════════════════════════════════════════════ */
    const refreshMetrics = (payload, resp) => {
        const lat = payload.latitude?.toFixed  ? payload.latitude.toFixed(6)  : payload.latitude;
        const lng = payload.longitude?.toFixed ? payload.longitude.toFixed(6) : payload.longitude;
        const acc = payload.accuracy ? Number(payload.accuracy).toFixed(1) : '—';

        el.latitudeValue.textContent     = lat || '—';
        el.longitudeValue.textContent    = lng || '—';
        el.locationNameValue.textContent = resp.location_name || '—';
        el.accuracyValue.textContent     = acc !== '—' ? `${acc} m` : '—';
        el.lastSeenValue.textContent     = resp.last_seen || new Date().toLocaleTimeString();

        if (resp.map_url) el.mapButton.href = resp.map_url;
        updateStatus(resp.status, resp.status_label);

        /* Live KM distance from backend */
        if (el.kpiDistance && resp.total_distance_km != null) {
            el.kpiDistance.textContent = parseFloat(resp.total_distance_km).toFixed(1);
        }

        /* Warn when GPS accuracy is poor */
        if (payload.accuracy && Number(payload.accuracy) > 200) {
            setNotice('warning', 'Low GPS accuracy',
                ' Move outdoors or enable high-accuracy mode for a precise location name.');
        }
    };

    
    const sendLocation = async (position) => {
        const payload = {
            latitude:  position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy:  position.coords.accuracy,
            speed:     position.coords.speed,
            heading:   position.coords.heading,
            source:    'browser',
        };
        state.lastPayload = payload;
        const result = await postJson('/salesperson_tracking/update', payload);
        refreshMetrics(payload, result);

        if (!payload.accuracy || Number(payload.accuracy) <= 200) {
            setNotice('success', 'Tracking active',
                ' Odoo is receiving fresh GPS points from this device.');
        }
    };

    /** Start GPS watch + heartbeat interval. */
    const startTracking = async () => {
        if (!navigator.geolocation) {
            setNotice('danger', 'Not supported', ' This browser does not support geolocation.');
            return;
        }
        if (state.tracking) return;

        state.tracking          = true;
        el.startButton.disabled = true;
        updateStatus('live', 'Starting…');
        state.trackingStart                = Date.now();
        el.takingTimeValue.textContent     = '00:00';
        state.timerId                      = setInterval(tickTimer, 1000);

        const opts = { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 };

        /* One-shot first fix */
        navigator.geolocation.getCurrentPosition(
            (pos) => sendLocation(pos).catch((e) => setNotice('danger', 'Update failed', ' ' + e.message)),
            (err) => {
                state.tracking          = false;
                el.startButton.disabled = false;
                if (state.timerId !== null) { clearInterval(state.timerId); state.timerId = null; }
                state.trackingStart            = null;
                el.takingTimeValue.textContent = '—';
                updateStatus('offline', 'Offline');
                setNotice('danger', 'Permission needed', ' ' + (err.message || 'GPS access was denied.'));
            },
            opts
        );

        /* Continuous watch */
        state.watchId = navigator.geolocation.watchPosition(
            (pos) => sendLocation(pos).catch((e) => setNotice('warning', 'Update failed', ' ' + e.message)),
            (err) => setNotice('warning', 'Tracking error', ' ' + (err.message || 'Could not read device location.')),
            opts
        );

        /* Heartbeat every 20 s — keeps the record alive even when device is stationary */
        state.heartbeatId = setInterval(() => {
            if (!state.lastPayload) return;
            postJson('/salesperson_tracking/update', state.lastPayload)
                .then((r)  => refreshMetrics(state.lastPayload, r))
                .catch((e) => setNotice('warning', 'Heartbeat failed', ' ' + e.message));
        }, 20000);
    };

    /** Stop GPS watch, heartbeat, and notify backend. */
    const stopTracking = async () => {
        state.tracking = false;

        if (state.watchId    !== null) { navigator.geolocation.clearWatch(state.watchId); state.watchId    = null; }
        if (state.heartbeatId !== null) { clearInterval(state.heartbeatId);               state.heartbeatId = null; }
        if (state.timerId     !== null) { clearInterval(state.timerId);                   state.timerId     = null; }

        const durationSeconds = state.trackingStart
            ? Math.floor((Date.now() - state.trackingStart) / 1000)
            : 0;

        state.trackingStart            = null;
        el.takingTimeValue.textContent = '—';
        el.startButton.disabled        = false;

        try {
            await postJson('/salesperson_tracking/stop', { duration_seconds: durationSeconds });
        } catch (e) {
            setNotice('warning', 'Stop warning', ' ' + e.message);
        }

        updateStatus('offline', 'Offline');
        setNotice('', 'Tracking stopped', ' This device is no longer sending live position updates.');
    };

    /* ── Button listeners ── */
    el.startButton.addEventListener('click', () =>
        startTracking().catch((e) => setNotice('danger', 'Start failed', ' ' + e.message)));

    el.stopButton.addEventListener('click', () =>
        stopTracking().catch((e) => setNotice('danger', 'Stop failed', ' ' + e.message)));

    /* ── Send beacon on page hide (tab close / navigation) ── */
    window.addEventListener('pagehide', () => {
        if (state.tracking) {
            navigator.sendBeacon('/salesperson_tracking/stop',
                new Blob(['{}'], { type: 'application/json' }));
        }
    });

    /* ══════════════════════════════════════════════
       CAMERA WIDGET
    ══════════════════════════════════════════════ */
    const openBtn      = $('openCameraBtn');
    const video        = $('selfieVideo');
    const canvas       = $('selfieCanvas');
    const previewBox   = $('previewBox');
    const snapRow      = $('snapRow');
    const camLabel     = $('camLabel');
    const stopBtn      = $('stopBtn');
    const captureBtn   = $('captureBtn');
    const flipBtn      = $('flipBtn');
    const flashEl      = $('flashEl');
    const downloadLink = $('downloadLink');
    const camGallery   = $('camGallery');
    const galleryGrid  = $('galleryGrid');
    const galleryCount = $('galleryCount');
    const clearAllBtn  = $('clearAllBtn');
    const photoViewer  = $('photoViewer');
    const viewerImg    = $('viewerImg');
    const pvBack       = $('pvBack');
    const pvDownload   = $('pvDownload');
    const pvDelete     = $('pvDelete');

    let stream       = null;
    let facingMode   = 'environment';
    let photos       = [];
    let viewingIndex = -1;

    /**
     * Start the device camera with the given facing mode.
     * @param {string} facing - 'user' | 'environment'
     */
    async function startCamera(facing) {
        if (stream) stream.getTracks().forEach((t) => t.stop());
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: facing },
                    width:      { ideal: 1280 },
                    height:     { ideal: 960 },
                },
            });
            video.srcObject        = stream;
            video.style.display    = 'block';
            previewBox.style.display  = 'block';
            openBtn.style.display     = 'none';
            snapRow.style.display     = 'none';
            camGallery.style.display  = 'none';
            photoViewer.style.display = 'none';
            camLabel.textContent      = 'Tap the shutter button to take a photo';
        } catch (e) {
            camLabel.textContent = 'Camera access denied or unavailable.';
            console.error('Camera error:', e);
        }
    }

    /** Stop camera stream and restore the open-camera button. */
    function closeCamera() {
        if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
        video.style.display       = 'none';
        video.srcObject           = null;
        previewBox.style.display  = 'none';
        openBtn.style.display     = 'inline-flex';
        camLabel.textContent      = 'Click to access your camera';
        snapRow.style.display     = 'none';
        if (photos.length > 0) renderGallery();
    }

    /** Re-render the photo gallery grid. */
    function renderGallery() {
        camGallery.style.display = 'flex';
        galleryCount.textContent = `Saved photos (${photos.length})`;
        galleryGrid.innerHTML    = '';

        if (photos.length === 0) {
            galleryGrid.innerHTML = '<div class="gallery-empty">No photos yet</div>';
            return;
        }

        photos.forEach(function (p, i) {
            const img   = document.createElement('img');
            img.src     = p.dataUrl;
            img.title   = p.ts;
            img.addEventListener('click', () => openViewer(i));
            galleryGrid.appendChild(img);
        });
    }

    /** Open a single-photo viewer at the given index. */
    function openViewer(idx) {
        viewingIndex              = idx;
        viewerImg.src             = photos[idx].dataUrl;
        camGallery.style.display  = 'none';
        photoViewer.style.display = 'flex';
        openBtn.style.display     = 'none';
    }

    /* ── Camera button listeners ── */
    openBtn.addEventListener('click', () => startCamera(facingMode));

    stopBtn.addEventListener('click', closeCamera);

    flipBtn.addEventListener('click', () => {
        facingMode = facingMode === 'user' ? 'environment' : 'user';
        startCamera(facingMode);
    });

    captureBtn.addEventListener('click', () => {
        if (!stream) return;

        /* Flash effect */
        flashEl.classList.add('go');
        setTimeout(() => flashEl.classList.remove('go'), 160);

        /* Draw frame to canvas */
        canvas.width  = video.videoWidth  || 640;
        canvas.height = video.videoHeight || 480;
        const ctx = canvas.getContext('2d');
        if (facingMode === 'user') { ctx.translate(canvas.width, 0); ctx.scale(-1, 1); }
        ctx.drawImage(video, 0, 0);

        const dataUrl  = canvas.toDataURL('image/jpeg', 0.92);
        const filename = `photo_${Date.now()}.jpg`;

        photos.push({ dataUrl, ts: new Date().toLocaleTimeString() });
        downloadLink.href     = dataUrl;
        downloadLink.download = filename;

        /* Upload to Odoo backend */
        fetch('/salesperson_tracking/save_photo', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method:  'call',
                id:      Date.now(),
                params:  { image_data: dataUrl, filename },
            }),
        })
        .then((res) => res.json())
        .then((data) => {
            const result = data.result;
            camLabel.textContent = result?.success
                ? '✓ Photo saved in Odoo!'
                : (result?.message || 'Upload failed');
            if (result?.success) snapRow.style.display = 'flex';
        })
        .catch((err) => {
            console.error(err);
            camLabel.textContent = 'Upload failed — network error';
        });

        snapRow.style.display = 'flex';
        setTimeout(() => { if (stream) snapRow.style.display = 'none'; }, 2000);

        renderGallery();
        camGallery.style.display = 'none';
    });

    /* Save / download link */
    downloadLink.addEventListener('click', (e) => {
        e.preventDefault();
        const a      = document.createElement('a');
        a.href       = downloadLink.href;
        a.download   = downloadLink.download;
        a.click();
    });

    /* Viewer — back */
    pvBack.addEventListener('click', () => {
        photoViewer.style.display = 'none';
        renderGallery();
        if (!stream) openBtn.style.display = 'inline-flex';
    });

    /* Viewer — download */
    pvDownload.addEventListener('click', () => {
        const a      = document.createElement('a');
        a.href       = photos[viewingIndex].dataUrl;
        a.download   = `photo_${Date.now()}.jpg`;
        a.click();
    });

    /* Viewer — delete */
    pvDelete.addEventListener('click', () => {
        photos.splice(viewingIndex, 1);
        photoViewer.style.display = 'none';
        if (photos.length > 0) renderGallery();
        else camGallery.style.display = 'none';
        if (!stream) openBtn.style.display = 'inline-flex';
    });

    /* Clear all photos */
    clearAllBtn.addEventListener('click', () => {
        photos = [];
        renderGallery();
    });

})();