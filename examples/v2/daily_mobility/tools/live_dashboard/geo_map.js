/**
 * 北京地图视图（Leaflet + 高德/OSM 底图）
 */
(function initGeoMap(global) {
  const BEIJING_CENTER = [39.9042, 116.4074];
  const GEO_FAN_RADIUS_M = 22;
  const GEO_FAN_RADIUS_MAX_M = 48;
  const OVERLAP_THRESHOLD_M = 25;
  const COMMUTE_COLOR = "#2980b9";

  let map = null;
  let layerTrail = null;
  let layerMarkers = null;
  let layerClusters = null;
  let layerLandmarks = null;
  let layerTargets = null;
  let onSelectSlot = null;

  function gaodeTileLayer(style) {
    return L.tileLayer(
      "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style={style}&x={x}&y={y}&z={z}".replace(
        "{style}",
        String(style),
      ),
      {
        subdomains: ["1", "2", "3", "4"],
        maxZoom: 18,
        attribution: "© 高德地图",
      },
    );
  }

  function offsetLatLng(lat, lng, angleRad, distM) {
    const earth = 6378137;
    const dLat = ((distM * Math.cos(angleRad)) / earth) * (180 / Math.PI);
    const dLng =
      ((distM * Math.sin(angleRad)) / (earth * Math.cos((lat * Math.PI) / 180))) *
      (180 / Math.PI);
    return [lat + dLat, lng + dLng];
  }

  function isMovingPoint(p) {
    if (!p) return false;
    const status = String(p.status || "").toLowerCase();
    return (
      status === "moving" ||
      p.position_kind === "moving" ||
      p.intention === "commute"
    );
  }

  function locationKey(p) {
    if (isMovingPoint(p)) {
      return `moving:${p.slot}`;
    }
    return `ll:${Number(p.lng).toFixed(5)},${Number(p.lat).toFixed(5)}`;
  }

  function centroid(batch) {
    const lat = batch.reduce((s, p) => s + p.lat, 0) / batch.length;
    const lng = batch.reduce((s, p) => s + p.lng, 0) / batch.length;
    return { lat, lng };
  }

  function haversineM(a, b) {
    const R = 6378137;
    const dLat = ((b.lat - a.lat) * Math.PI) / 180;
    const dLng = ((b.lng - a.lng) * Math.PI) / 180;
    const x =
      Math.sin(dLat / 2) ** 2 +
      Math.cos((a.lat * Math.PI) / 180) *
      Math.cos((b.lat * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }

  function formatDistanceM(m) {
    if (m < 1000) return `${Math.round(m)} m`;
    return `${(m / 1000).toFixed(1)} km`;
  }

  function targetLabel(targetId, homeAoi, workAoi) {
    if (targetId == null) return null;
    if (homeAoi != null && targetId === homeAoi) return "家";
    if (workAoi != null && targetId === workAoi) return "单位";
    return `AOI ${targetId}`;
  }

  function spreadOverlappingGeoPoints(points) {
    if (points.length < 2) {
      points.forEach((p) => {
        p._baseLat = p.lat;
        p._baseLng = p.lng;
        p._clusterSize = 1;
        p.displayLat = p.lat;
        p.displayLng = p.lng;
      });
      return points;
    }

    const byKey = new Map();
    for (const p of points) {
      const key = locationKey(p);
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key).push(p);
    }

    const batches = [];
    const consumed = new Set();
    for (const [key, batch] of byKey) {
      if (consumed.has(key)) continue;
      let merged = [...batch];
      consumed.add(key);
      let c = centroid(merged);
      if (!key.startsWith("moving:")) {
        for (const [otherKey, other] of byKey) {
          if (consumed.has(otherKey) || otherKey.startsWith("moving:")) continue;
          const oc = centroid(other);
          if (haversineM(c, oc) <= OVERLAP_THRESHOLD_M) {
            merged = merged.concat(other);
            consumed.add(otherKey);
            c = centroid(merged);
          }
        }
      }
      batches.push(merged);
    }

    for (const batch of batches) {
      if (batch.length === 1) {
        const p = batch[0];
        p._baseLat = p.lat;
        p._baseLng = p.lng;
        p._clusterSize = 1;
        p.displayLat = p.lat;
        p.displayLng = p.lng;
        continue;
      }
      batch.sort((a, b) => a.slot - b.slot);
      const c = centroid(batch);
      const n = batch.length;
      const radiusM = Math.min(
        GEO_FAN_RADIUS_MAX_M,
        GEO_FAN_RADIUS_M + Math.max(0, n - 2) * 2.5,
      );
      const useFullCircle = n > 5;
      const angleStep = useFullCircle ? (2 * Math.PI) / n : Math.min(0.55, 0.12 * (n - 1));
      const startAngle = useFullCircle
        ? -Math.PI / 2
        : -Math.PI / 2 - (angleStep * (n - 1)) / 2;

      batch.forEach((p, i) => {
        p._baseLat = c.lat;
        p._baseLng = c.lng;
        p._clusterSize = n;
        p._clusterIndex = i;
        const angle = startAngle + i * angleStep;
        [p.displayLat, p.displayLng] = offsetLatLng(c.lat, c.lng, angle, radiusM);
      });
    }
    return points;
  }

  function buildGeoPoints(data, endSlot) {
    const slots = (data.slots || []).filter(
      (s) => s.filled && s.slot <= endSlot && s.lat != null && s.lng != null,
    );
    const pts = slots.map((s) => ({
      slot: s.slot,
      lat: Number(s.lat),
      lng: Number(s.lng),
      intention: s.intention,
      position_kind: s.position_kind,
      position_label: s.position_label,
      poi_name: s.poi_name,
      time_label: s.time_label,
      status: s.status,
      target_aoi_id: s.target_aoi_id,
      home_aoi: s.home_aoi,
      work_aoi: s.work_aoi,
    }));

    const live = data.live?.snapshot;
    if (live?.lat != null && live?.lng != null && pts.length) {
      const last = pts[pts.length - 1];
      if (last.slot === endSlot) {
        last.lat = Number(live.lat);
        last.lng = Number(live.lng);
        last.status = live.status || last.status;
        last.position_kind = live.position_kind || last.position_kind;
        last.target_aoi_id = live.target_aoi_id ?? last.target_aoi_id;
        last.live = true;
      }
    }
    return spreadOverlappingGeoPoints(pts);
  }

  function ensureMap() {
    if (map) return map;
    const el = document.getElementById("geo-map");
    if (!el || typeof L === "undefined") return null;

    map = L.map(el, { zoomControl: true, attributionControl: true }).setView(
      BEIJING_CENTER,
      12,
    );

    const gaodeStd = gaodeTileLayer(8);
    const gaodeSat = gaodeTileLayer(6);
    const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
    });

    gaodeStd.addTo(map);
    L.control
      .layers(
        { 高德标准: gaodeStd, 高德影像: gaodeSat, OpenStreetMap: osm },
        {},
        { position: "topright", collapsed: true },
      )
      .addTo(map);

    layerLandmarks = L.layerGroup().addTo(map);
    layerTargets = L.layerGroup().addTo(map);
    layerClusters = L.layerGroup().addTo(map);
    layerTrail = L.layerGroup().addTo(map);
    layerMarkers = L.layerGroup().addTo(map);

    return map;
  }

  function popupHtml(p, labels) {
    const intent = labels.intention[p.intention] || p.intention || "—";
    const pos = labels.position[p.position_kind] || p.position_kind || "—";
    const moving = isMovingPoint(p);
    const dest = targetLabel(p.target_aoi_id, p.home_aoi, p.work_aoi);
    const cluster =
      (p._clusterSize || 1) > 1
        ? `<br/><small>同地 ${p._clusterSize} 时段 · 展开 #${(p._clusterIndex ?? 0) + 1}</small>`
        : "";
    const moveLine = moving
      ? `<br/><small style="color:${COMMUTE_COLOR}">${dest ? `通勤 → ${dest}` : "通勤途中"} · status=${p.status || "moving"}</small>`
      : "";
    return `<strong>时段 ${p.slot + 1}</strong> · ${p.time_label || ""}<br/>
      意图：${intent}<br/>位置：${pos}${p.poi_name ? ` · ${p.poi_name}` : ""}${moveLine}${cluster}`;
  }

  function renderLandmarks(data) {
    layerLandmarks.clearLayers();
    const homeSlots = (data.slots || []).filter(
      (s) => s.position_kind === "home" && s.lat != null && s.lng != null,
    );
    const workSlots = (data.slots || []).filter(
      (s) => s.position_kind === "work" && s.lat != null && s.lng != null,
    );
    const addLm = (slots, label, kind) => {
      if (!slots.length) return;
      const c = centroid(
        slots.map((s) => ({ lat: Number(s.lat), lng: Number(s.lng) })),
      );
      L.marker([c.lat, c.lng], {
        icon: L.divIcon({
          className: "geo-landmark",
          html: `<span class="geo-landmark-inner geo-landmark-${kind}">${label}</span>`,
          iconSize: [36, 20],
          iconAnchor: [18, 10],
        }),
        interactive: false,
        zIndexOffset: -100,
      }).addTo(layerLandmarks);
    };
    addLm(homeSlots, "家", "home");
    addLm(workSlots, "单位", "work");
    return { homeSlots, workSlots };
  }

  function targetLatLng(data, targetAoiId) {
    if (targetAoiId == null) return null;
    const hit = (data.slots || []).find(
      (s) => s.aoi_id === targetAoiId && s.lat != null && s.lng != null,
    );
    if (hit) return [Number(hit.lat), Number(hit.lng)];
    const home = (data.slots || []).find((s) => s.home_aoi === targetAoiId && s.lat != null);
    if (home) return [Number(home.lat), Number(home.lng)];
    const work = (data.slots || []).find((s) => s.work_aoi === targetAoiId && s.lat != null);
    if (work) return [Number(work.lat), Number(work.lng)];
    return null;
  }

  function renderTargetHints(data, points, focusSlot) {
    layerTargets.clearLayers();
    const focus = points.find((p) => p.slot === focusSlot);
    if (!focus || !isMovingPoint(focus) || focus.target_aoi_id == null) return;
    const dest = targetLatLng(data, focus.target_aoi_id);
    if (!dest) return;
    const caption = targetLabel(focus.target_aoi_id, focus.home_aoi, focus.work_aoi);
    L.polyline(
      [
        [focus.displayLat, focus.displayLng],
        dest,
      ],
      { color: COMMUTE_COLOR, weight: 2, opacity: 0.55, dashArray: "6 6" },
    ).addTo(layerTargets);
    L.circleMarker(dest, {
      radius: 8,
      fillColor: "#fff",
      color: COMMUTE_COLOR,
      weight: 2,
      fillOpacity: 0.9,
    })
      .bindTooltip(caption ? `目的地：${caption}` : "目的地", { permanent: false })
      .addTo(layerTargets);
  }

  function renderClusterRings(points, posColor) {
    layerClusters.clearLayers();
    const seen = new Set();
    for (const p of points) {
      if ((p._clusterSize || 1) < 2 || isMovingPoint(p)) continue;
      const id = `${p._baseLat?.toFixed(5)},${p._baseLng?.toFixed(5)}`;
      if (seen.has(id)) continue;
      seen.add(id);
      const batch = points.filter(
        (q) =>
          q._baseLat === p._baseLat &&
          q._baseLng === p._baseLng &&
          (q._clusterSize || 1) > 1,
      );
      const n = batch.length;
      const radiusM =
        Math.min(GEO_FAN_RADIUS_MAX_M, GEO_FAN_RADIUS_M + Math.max(0, n - 2) * 2.5) + 8;
      L.circle([p._baseLat, p._baseLng], {
        radius: radiusM,
        color: posColor(batch[0].position_kind),
        weight: 1.5,
        fillColor: posColor(batch[0].position_kind),
        fillOpacity: 0.08,
        dashArray: "5 4",
        interactive: false,
      }).addTo(layerClusters);
    }
  }

  function render(ctx) {
    const m = ensureMap();
    if (!m) return { pointCount: 0, message: "地图库未加载" };

    const { data, endSlot, selectedSlot, latestSlot, intentionColor, positionColor, labels } =
      ctx;

    const points = buildGeoPoints(data, endSlot);
    layerTrail.clearLayers();
    layerMarkers.clearLayers();
    layerClusters.clearLayers();
    layerLandmarks.clearLayers();
    layerTargets.clearLayers();

    if (!points.length) {
      m.setView(BEIJING_CENTER, 11);
      return {
        pointCount: 0,
        message: "暂无经纬度数据（需问卷快照含坐标；无坐标时段仅在示意图显示）",
      };
    }

    renderLandmarks(data);
    renderClusterRings(points, positionColor);
    const focusSlot = selectedSlot != null ? selectedSlot : latestSlot;
    renderTargetHints(data, points, focusSlot);

    const latlngs = [];
    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      latlngs.push([p.displayLat, p.displayLng]);
      if (i > 0) {
        const prev = points[i - 1];
        const dist = haversineM(
          { lat: prev.displayLat, lng: prev.displayLng },
          { lat: p.displayLat, lng: p.displayLng },
        );
        if (dist < 3) continue;
        const commute = isMovingPoint(prev) || isMovingPoint(p);
        const color = commute ? COMMUTE_COLOR : positionColor(p.position_kind);
        const opts = {
          color,
          weight: commute ? 3 : 2.5,
          opacity: commute ? 0.8 : 0.65,
        };
        if (commute) opts.dashArray = "8 6";

        const sameCluster =
          prev._baseLat === p._baseLat &&
          prev._baseLng === p._baseLng &&
          (p._clusterSize || 1) > 1 &&
          !commute;
        if (sameCluster && dist < OVERLAP_THRESHOLD_M * 1.5) {
          L.polyline(
            [
              [prev.displayLat, prev.displayLng],
              [p._baseLat, p._baseLng],
              [p.displayLat, p.displayLng],
            ],
            { ...opts, weight: 2, opacity: 0.45, dashArray: "4 3" },
          ).addTo(layerTrail);
        } else {
          const line = L.polyline(
            [
              [prev.displayLat, prev.displayLng],
              [p.displayLat, p.displayLng],
            ],
            opts,
          ).addTo(layerTrail);
          if (dist >= 120) {
            const mid = line.getCenter();
            L.marker(mid, {
              icon: L.divIcon({
                className: "geo-dist-label",
                html: `<span>${formatDistanceM(dist)}</span>`,
                iconSize: [60, 18],
                iconAnchor: [30, 9],
              }),
              interactive: false,
            }).addTo(layerTrail);
          }
        }
      }
    }

    for (const p of points) {
      const isSelected = selectedSlot === p.slot;
      const isLatest = latestSlot === p.slot;
      const inCluster = (p._clusterSize || 1) > 1;
      const moving = isMovingPoint(p);
      let radius = 7;
      if (inCluster && !isSelected && !isLatest) radius = 5;
      if (isLatest) radius = 9;
      if (isSelected) radius = 11;

      if (moving) {
        const icon = L.divIcon({
          className: `geo-moving-marker${isLatest ? " geo-moving-latest" : ""}`,
          html: `<span class="geo-moving-inner">🚶<small>#${p.slot + 1}</small></span>`,
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        });
        const marker = L.marker([p.displayLat, p.displayLng], {
          icon,
          zIndexOffset: isLatest || isSelected ? 500 : 100,
        }).addTo(layerMarkers);
        marker.bindPopup(popupHtml(p, labels), { maxWidth: 280 });
        marker.on("click", () => {
          if (onSelectSlot) onSelectSlot(p.slot);
        });
        continue;
      }

      const marker = L.circleMarker([p.displayLat, p.displayLng], {
        radius,
        fillColor: positionColor(p.position_kind),
        color: intentionColor(p.intention),
        weight: isLatest || isSelected ? 3 : 2,
        fillOpacity: 0.92,
      }).addTo(layerMarkers);

      marker.bindPopup(popupHtml(p, labels), { maxWidth: 280 });
      marker.on("click", () => {
        if (onSelectSlot) onSelectSlot(p.slot);
      });
    }

    const bounds = L.latLngBounds(latlngs);
    if (latlngs.length === 1) {
      m.setView(latlngs[0], 15);
    } else {
      m.fitBounds(bounds.pad(0.15), { maxZoom: 15, animate: false });
    }

    return { pointCount: points.length, message: null };
  }

  function invalidateSize() {
    if (!map) return;
    setTimeout(() => map.invalidateSize(), 80);
  }

  function setSelectHandler(fn) {
    onSelectSlot = fn;
  }

  global.GeoMapView = {
    render,
    invalidateSize,
    setSelectHandler,
    buildGeoPoints,
  };
})(window);
