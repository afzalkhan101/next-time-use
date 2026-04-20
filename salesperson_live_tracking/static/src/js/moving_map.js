
(function () {
    'use strict';
    var mapEl = document.getElementById('map');
    if (!mapEl) return;
    var b64     = mapEl.getAttribute('data-points') || '';
    var planB64 = mapEl.getAttribute('data-plans')  || '';
    var points  = [];
    var plans   = [];

    try { points = JSON.parse(atob(b64));     } catch (e) { points = []; }
    try { plans  = JSON.parse(atob(planB64)); } catch (e) { plans  = []; }
    var DEFAULT_CENTER = [23.7701, 90.4254]; 
    var map = L.map('map', { zoomControl: true }).setView(DEFAULT_CENTER, 15);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '\u00a9 <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
    }).addTo(map);

    if (!points || points.length === 0) {
        document.getElementById('routeLoading').style.display = 'none';

        var nd = document.createElement('div');
        nd.className = 'no-data';
        nd.innerHTML = [
            '<div class="no-data-card">',
            '  <div class="no-data-icon">',
            '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
            '      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/>',
            '      <circle cx="12" cy="10" r="3"/>',
            '    </svg>',
            '  </div>',
            '  <div class="no-data-title">No location data</div>',
            '  <div class="no-data-sub">No GPS logs available for today.</div>',
            '</div>',
        ].join('');

        document.querySelector('.map-wrapper').appendChild(nd);
        return;
    }

    var valid = points.filter(function (p) {
        return typeof p.lat === 'number'
            && typeof p.lng === 'number'
            && (p.accuracy <= 200 || p.accuracy === 0);
    });
    if (valid.length === 0) valid = points;

    var latlngs = valid.map(function (p) { return [p.lat, p.lng]; });

    function downsample(arr, maxPts) {
        if (arr.length <= maxPts) return arr;
        var step = arr.length / maxPts;
        var out  = [];
        for (var i = 0; i < arr.length; i += step) {
            out.push(arr[Math.floor(i)]);
        }
        var last = arr[arr.length - 1];
        if (out[out.length - 1] !== last) out.push(last);
        return out;
    }

    function addStartMarker(p) {
        return L.marker([p.lat, p.lng], {
            icon: L.divIcon({
                html: '<div style="width:16px;height:16px;background:#3b6d11;border-radius:50%;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.3)"></div>',
                iconSize:   [16, 16],
                iconAnchor: [8, 8],
                className:  '',
            }),
        })
        .addTo(map)
        .bindPopup(
            '<b>Start point</b><br>' + (p.time || '') +
            (p.location_name ? '<br>' + p.location_name : '')
        );
    }

    /** Red teardrop — most recent / last GPS point. */
    function addEndMarker(p) {
        return L.marker([p.lat, p.lng], {
            icon: L.divIcon({
                html: '<div style="width:22px;height:22px;background:#dc2626;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:3px solid #fff;box-shadow:0 2px 10px rgba(0,0,0,.3)"></div>',
                iconSize:   [22, 22],
                iconAnchor: [11, 22],
                className:  '',
            }),
        })
        .addTo(map)
        .bindPopup(
            '<b>Current / last position</b><br>' + (p.time || '') +
            (p.location_name ? '<br>' + p.location_name : '') +
            '<br>Accuracy: ' + (p.accuracy ? p.accuracy.toFixed(1) + ' m' : '—')
        )
        .openPopup();
    }

    /** Blue dots with accuracy circle for intermediate waypoints. */
    function addIntermediateMarkers(pts) {
        pts.forEach(function (p, i) {
            if (i === 0 || i === pts.length - 1) return; /* skip start/end */

            /* Accuracy radius circle */
            if (p.accuracy > 0 && p.accuracy <= 500) {
                L.circle([p.lat, p.lng], {
                    radius:      p.accuracy,
                    color:       '#3b82f6',
                    fillColor:   '#3b82f6',
                    fillOpacity: 0.08,
                    weight:      1,
                    opacity:     0.3,
                }).addTo(map);
            }

            /* Dot marker */
            var dot = L.circleMarker([p.lat, p.lng], {
                radius:      4,
                color:       '#1a73e8',
                fillColor:   '#bfdbfe',
                fillOpacity: 1,
                weight:      2,
            });

            var timeStr  = p.time  ? p.time.replace('T', ' ') : '—';
            var speedStr = p.speed ? (p.speed * 3.6).toFixed(1) + ' km/h' : '0 km/h';
            var accStr   = p.accuracy ? p.accuracy.toFixed(1) + ' m' : '—';

            dot.bindPopup(
                '<b>Time:</b> '     + timeStr  + '<br>' +
                '<b>Speed:</b> '    + speedStr + '<br>' +
                '<b>Accuracy:</b> ' + accStr   +
                (p.location_name ? '<br><b>Location:</b> ' + p.location_name : '')
            );
            dot.addTo(map);
        });
    }

    /** Render planned visit markers — green if visited, red if not. */
    function addPlanMarkers(planList) {
        if (!planList || planList.length === 0) return;
        planList.forEach(function (pl) {
            if (typeof pl.lat !== 'number' || typeof pl.lng !== 'number') return;
            var visited = !!pl.visited;
            var color   = visited ? '#3b6d11' : '#dc2626';
            L.circleMarker([pl.lat, pl.lng], {
                radius:      7,
                color:       color,
                fillColor:   color,
                fillOpacity: visited ? 0.55 : 0.45,
                weight:      2,
            })
            .bindPopup(
                '<b>' + (pl.name || 'Planned location') + '</b><br>' +
                (visited ? '&#10003; Visited' : '&#8226; Not visited yet') +
                (pl.address ? '<br>' + pl.address : '')
            )
            .addTo(map);
        });
    }

    /* ══════════════════════════════════════════════
       MAP BOUNDS
    ══════════════════════════════════════════════ */

    /** Fit the viewport to cover all GPS + plan points. */
    function fitAll(routeBounds) {
        var allLatLngs = latlngs.slice();
        if (plans) {
            plans.forEach(function (pl) {
                if (typeof pl.lat === 'number') allLatLngs.push([pl.lat, pl.lng]);
            });
        }
        if (routeBounds) {
            map.fitBounds(routeBounds, { padding: [50, 50] });
        } else if (allLatLngs.length > 1) {
            map.fitBounds(L.latLngBounds(allLatLngs), { padding: [50, 50] });
        } else {
            map.setView(latlngs[0], 16);
        }
        setTimeout(function () { map.invalidateSize(); }, 300);
    }

    /* ══════════════════════════════════════════════
       ROUTE INFO CARD  (Google Maps–style overlay)
    ══════════════════════════════════════════════ */

    /**
     * Populate and show the route info card + top-bar pills.
     * @param {string} distKm  - e.g. "12.4"
     * @param {number} durMin  - integer minutes
     */
    function showRouteInfo(distKm, durMin) {
        var box  = document.getElementById('routeInfoBox');
        var dp   = document.getElementById('routeDistancePill');
        var tp   = document.getElementById('routeDurationPill');
        var dv   = document.getElementById('routeDistVal');
        var tv   = document.getElementById('routeDurVal');

        document.getElementById('ribDur').textContent  = durMin + ' min';
        document.getElementById('ribDist').textContent = distKm + ' km';
        box.style.display = 'block';

        if (dp) { dp.style.display = 'flex'; dv.textContent = distKm + ' km'; }
        if (tp) { tp.style.display = 'flex'; tv.textContent = durMin + ' min'; }
    }

    /* ══════════════════════════════════════════════
       GPS FALLBACK POLYLINE
       Shown when OSRM is unavailable.
    ══════════════════════════════════════════════ */
    function drawGpsFallback() {
        L.polyline(latlngs, {
            color:     '#6366f1',
            weight:    3,
            opacity:   0.85,
            dashArray: '7 5',
        }).addTo(map);
    }

    /* ══════════════════════════════════════════════
       OSRM ROAD ROUTE FETCH
    ══════════════════════════════════════════════ */

    /**
     * Request a road-snapped route from the public OSRM demo server.
     * Downsamples to 80 waypoints to stay within URL limits.
     * @param {function(Error|null, object|null)} callback
     */
    function fetchRoadRoute(callback) {
        var sampled  = downsample(valid, 80);
        var coordStr = sampled.map(function (p) { return p.lng + ',' + p.lat; }).join(';');
        var url      = 'https://router.project-osrm.org/route/v1/driving/' + coordStr
                       + '?overview=full&geometries=geojson&steps=false';

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.routes && data.routes.length > 0) {
                    callback(null, data.routes[0]);
                } else {
                    callback(new Error('No route returned'), null);
                }
            })
            .catch(function (e) { callback(e, null); });
    }

  
    fetchRoadRoute(function (err, route) {
        var loadingEl = document.getElementById('routeLoading');
        if (loadingEl) loadingEl.style.display = 'none';

        if (!err && route) {
            /* ── Road-snapped route from OSRM GeoJSON ── */
            var roadCoords = route.geometry.coordinates.map(function (c) {
                return [c[1], c[0]]; /* [lng, lat] → [lat, lng] */
            });

            /* White outline for road depth feel */
            L.polyline(roadCoords, {
                color:   '#ffffff',
                weight:  11,
                opacity: 0.55,
            }).addTo(map);

            /* Blue road polyline */
            var roadLine = L.polyline(roadCoords, {
                color:   '#1a73e8',
                weight:  6,
                opacity: 0.9,
            }).addTo(map);

            /* Distance & duration overlay */
            var distKm = (route.distance / 1000).toFixed(1);
            var durMin = Math.round(route.duration / 60);
            showRouteInfo(distKm, durMin);

            addIntermediateMarkers(valid);
            addStartMarker(valid[0]);
            addEndMarker(valid[valid.length - 1]);
            addPlanMarkers(plans);
            fitAll(roadLine.getBounds());

        } else {
            /* ── Fallback: dashed GPS path ── */
            console.warn('OSRM unavailable — using GPS fallback:', err);
            drawGpsFallback();
            addIntermediateMarkers(valid);
            addStartMarker(valid[0]);
            addEndMarker(valid[valid.length - 1]);
            addPlanMarkers(plans);
            fitAll(null);
        }
    });

})();