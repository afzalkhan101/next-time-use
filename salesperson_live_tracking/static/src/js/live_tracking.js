(function () {
    'use strict';

    if (!document.getElementById('startButton')) return;

    const root        = document.getElementById('trackingRoot');
    const initialDist = root ? parseFloat(root.dataset.distance || '0') : 0;
    const state = {
        tracking:      false,
        intervalId:    null,
        lastPayload:   null,
        trackingStart: null,
        timerId:       null, 
    };

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

    const updateStatus = (status, label) => {
        const s = status || 'offline';
        el.statusBadge.className   = `status-badge badge-${s}`;
        el.statusDot.className     = `status-dot dot-${s}`;
        el.statusLabel.textContent = label || 'Offline';
    };

    const setNotice = (type, title, message) => {
        el.noticeBox.className = `notice${type ? ' notice-' + type : ''}`;
        el.noticeBox.innerHTML = `<strong>${title}</strong>${message}`;
    };

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

    const tickTimer = () => {
        if (!state.trackingStart) return;
        el.takingTimeValue.textContent = formatDuration(Date.now() - state.trackingStart);
    };

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

        if (el.kpiDistance && resp.total_distance_km != null) {
            el.kpiDistance.textContent = parseFloat(resp.total_distance_km).toFixed(1);
        }

        if (payload.accuracy && Number(payload.accuracy) > 200) {
            setNotice('warning', 'Low GPS accuracy',
                ' Move outdoors or enable high-accuracy mode for a precise location name.');
        }
    };

    const GPS_OPTS = { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 };
    const INTERVAL_MS = 3 * 60 * 1000;

    const fetchAndSend = () => {
        navigator.geolocation.getCurrentPosition(
            async (position) => {
                const payload = {
                    latitude:  position.coords.latitude,
                    longitude: position.coords.longitude,
                    accuracy:  position.coords.accuracy,
                    speed:     position.coords.speed,
                    heading:   position.coords.heading,
                    source:    'browser',
                };
                state.lastPayload = payload;

                try {
                    const result = await postJson('/salesperson_tracking/update', payload);
                    refreshMetrics(payload, result);

                    if (!payload.accuracy || Number(payload.accuracy) <= 200) {
                        setNotice('success', 'Tracking active',
                            ' Odoo is receiving fresh GPS points from this device.');
                    }
                } catch (e) {
                    setNotice('warning', 'Update failed', ' ' + e.message);
                }
            },
            (err) => {
                setNotice('warning', 'GPS error', ' ' + (err.message || 'Could not read device location.'));
            },
            GPS_OPTS
        );
    };

    const startTracking = async () => {
        if (!navigator.geolocation) {
            setNotice('danger', 'Not supported', ' This browser does not support geolocation.');
            return;
        }
        if (state.tracking) return;

        state.tracking          = true;
        el.startButton.disabled = true;
        updateStatus('live', 'Starting…');
        state.trackingStart            = Date.now();
        el.takingTimeValue.textContent = '00:00';
        state.timerId                  = setInterval(tickTimer, 1000);

   
        localStorage.setItem('isTracking', 'true');
        localStorage.setItem('trackingStart', state.trackingStart);

        navigator.geolocation.getCurrentPosition(
            async (position) => {
                const payload = {
                    latitude:  position.coords.latitude,
                    longitude: position.coords.longitude,
                    accuracy:  position.coords.accuracy,
                    speed:     position.coords.speed,
                    heading:   position.coords.heading,
                    source:    'browser',
                };
                state.lastPayload = payload;

                try {
                    const result = await postJson('/salesperson_tracking/update', payload);
                    refreshMetrics(payload, result);
                    setNotice('success', 'Tracking active',
                        ' Odoo is receiving fresh GPS points from this device.');
                } catch (e) {
                    setNotice('danger', 'Update failed', ' ' + e.message);
                }
            },
            (err) => {
                state.tracking          = false;
                el.startButton.disabled = false;
                if (state.timerId !== null) { clearInterval(state.timerId); state.timerId = null; }
                state.trackingStart            = null;
                el.takingTimeValue.textContent = '—';
                updateStatus('offline', 'Offline');
                setNotice('danger', 'Permission needed', ' ' + (err.message || 'GPS access was denied.'));
            },
            GPS_OPTS
        );

        state.intervalId = setInterval(fetchAndSend, INTERVAL_MS);
    };

    const stopTracking = async () => {
        state.tracking = false;

        if (state.intervalId !== null) { clearInterval(state.intervalId); state.intervalId = null; }
        if (state.timerId    !== null) { clearInterval(state.timerId);    state.timerId    = null; }

        const durationSeconds = state.trackingStart
            ? Math.floor((Date.now() - state.trackingStart) / 1000)
            : 0;

        localStorage.removeItem('isTracking');
        localStorage.removeItem('trackingStart');

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


    const autoResumeTracking = () => {
        const isTracking = localStorage.getItem('isTracking');

        if (isTracking === 'true') {
            state.tracking = true;
            state.trackingStart = parseInt(localStorage.getItem('trackingStart'));

            el.startButton.disabled = true;
            updateStatus('live', 'Live');

            state.timerId = setInterval(tickTimer, 1000);
            state.intervalId = setInterval(fetchAndSend, INTERVAL_MS);

            fetchAndSend();
        }
    };

    el.startButton.addEventListener('click', () =>
        startTracking().catch((e) => setNotice('danger', 'Start failed', ' ' + e.message)));

    el.stopButton.addEventListener('click', () =>
        stopTracking().catch((e) => setNotice('danger', 'Stop failed', ' ' + e.message)));

  

    window.addEventListener('load', autoResumeTracking);

})();