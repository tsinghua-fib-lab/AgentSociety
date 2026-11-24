/**
 * AgentMap Component - Interactive map/random visualization using DeckGL and Mapbox
 */

import * as React from 'react';
import { useTranslation } from 'react-i18next';
import DeckGL from '@deck.gl/react';
import { OrthographicView } from '@deck.gl/core';
import { IconLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import MapGL from 'react-map-gl/mapbox';
import mapboxgl from 'mapbox-gl';
// @ts-ignore
import MapboxWorker from 'mapbox-gl/dist/mapbox-gl-csp-worker';
import { useReplay } from '../store';
import { getAgentIconUrl } from '../icons';
import 'mapbox-gl/dist/mapbox-gl.css';

// Public Mapbox token for client-side map rendering. This is a pk.* token
// (public token) designed for browser use and is safe to expose in the client.
// Override via the MAPBOX_ACCESS_TOKEN environment variable at build time.
const MAPBOX_ACCESS_TOKEN = (
  typeof process !== 'undefined' && process.env?.MAPBOX_ACCESS_TOKEN
) || 'pk.eyJ1IjoiZmh5ZHJhbGlzayIsImEiOiJja3VzMWc5NXkwb3RnMm5sbnVvd3IydGY0In0.FrwFkYIMpLbU83K9rHSe8w';
const MAP_STYLE = 'mapbox://styles/mapbox/standard';

const resolvedWorker = (MapboxWorker as any).default ?? MapboxWorker;
if (typeof resolvedWorker === 'string') {
  mapboxgl.workerUrl = resolvedWorker;
} else if (typeof resolvedWorker === 'function') {
  if (typeof (mapboxgl as any).setWorkerClass === 'function') {
    (mapboxgl as any).setWorkerClass(resolvedWorker);
  } else {
    mapboxgl.workerClass = resolvedWorker;
  }
}

const INITIAL_GEO_VIEW_STATE = {
  longitude: 116.4,
  latitude: 39.9,
  zoom: 10.5,
  pitch: 0,
  bearing: 0,
};

const INITIAL_ORTHO_VIEW_STATE = {
  target: [0, 0, 0] as [number, number, number],
  zoom: 1,
};

function getAgentColor(profile: Record<string, any> | undefined): [number, number, number, number] {
  if (!profile) return [22, 119, 255, 255];
  const gender = String(profile.gender ?? '').toLowerCase();
  if (gender === 'male') return [66, 165, 245, 255];
  if (gender === 'female') return [239, 154, 154, 255];
  return [22, 119, 255, 255];
}

const RANDOM_LAYOUT_ASPECT_RATIO = 1.6;
const RANDOM_LAYOUT_WIDTH = 240;
const RANDOM_LAYOUT_HEIGHT = RANDOM_LAYOUT_WIDTH / RANDOM_LAYOUT_ASPECT_RATIO;
const RANDOM_LAYOUT_PADDING = 16;
const RANDOM_LAYOUT_JITTER = 0.32;

function hashInt(value: number): number {
  let hashed = value | 0;
  hashed = Math.imul(hashed ^ 0x9e3779b9, 0x85ebca6b);
  hashed ^= hashed >>> 13;
  hashed = Math.imul(hashed, 0xc2b2ae35);
  hashed ^= hashed >>> 16;
  return hashed >>> 0;
}

function hashToUnit(value: number): number {
  return hashInt(value) / 0x100000000;
}

function getRandomLayout(ids: number[]): Map<number, [number, number]> {
  const positions = new Map<number, [number, number]>();
  if (ids.length === 0) {
    return positions;
  }

  // Use a deterministic jittered grid so agents are spread evenly without
  // collapsing into visible clusters when no geo positions are available.
  const shuffledIds = [...ids].sort((left, right) => {
    const leftHash = hashInt(left);
    const rightHash = hashInt(right);
    if (leftHash === rightHash) {
      return left - right;
    }
    return leftHash - rightHash;
  });

  const columns = Math.max(1, Math.ceil(Math.sqrt(ids.length * RANDOM_LAYOUT_ASPECT_RATIO)));
  const rows = Math.max(1, Math.ceil(ids.length / columns));
  const usableWidth = RANDOM_LAYOUT_WIDTH - RANDOM_LAYOUT_PADDING * 2;
  const usableHeight = RANDOM_LAYOUT_HEIGHT - RANDOM_LAYOUT_PADDING * 2;
  const cellWidth = usableWidth / columns;
  const cellHeight = usableHeight / rows;

  shuffledIds.forEach((id, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const centerX = -usableWidth / 2 + cellWidth * (column + 0.5);
    const centerY = usableHeight / 2 - cellHeight * (row + 0.5);
    const jitterX = (hashToUnit(id * 31 + 7) - 0.5) * cellWidth * RANDOM_LAYOUT_JITTER;
    const jitterY = (hashToUnit(id * 31 + 19) - 0.5) * cellHeight * RANDOM_LAYOUT_JITTER;
    positions.set(id, [centerX + jitterX, centerY + jitterY]);
  });

  return positions;
}

interface AgentMapProps {
  mapboxToken?: string;
}

export const AgentMap: React.FC<AgentMapProps> = ({ mapboxToken = MAPBOX_ACCESS_TOKEN }) => {
  const { t } = useTranslation();
  const { state, actions } = useReplay();
  const { agentProfiles, positionsAtStep, selectedAgentId, layoutMode } = state;
  const [geoViewState, setGeoViewState] = React.useState(INITIAL_GEO_VIEW_STATE);
  const [orthoViewState, setOrthoViewState] = React.useState(INITIAL_ORTHO_VIEW_STATE);
  const [hovering, setHovering] = React.useState(false);
  const [mapError, setMapError] = React.useState<string | null>(null);
  const [didFitGeoView, setDidFitGeoView] = React.useState(false);

  const visibleIds = React.useMemo(() => {
    if (positionsAtStep.length > 0) {
      return positionsAtStep.map((position) => position.agent_id);
    }
    return Array.from(agentProfiles.keys()).sort((a, b) => a - b);
  }, [agentProfiles, positionsAtStep]);

  const randomLayout = React.useMemo(() => getRandomLayout(visibleIds), [visibleIds]);

  const agentList = React.useMemo(() => {
    return visibleIds.map((agentId) => {
      const profile = agentProfiles.get(agentId);
      const point = positionsAtStep.find((position) => position.agent_id === agentId);
      const randomPoint = randomLayout.get(agentId) ?? [0, 0];
      const hasGeo = point?.lng != null && point?.lat != null;
      const coordinate = layoutMode === 'map' && hasGeo
        ? [point!.lng!, point!.lat!]
        : [randomPoint[0], randomPoint[1]];
      return {
        id: agentId,
        name: profile?.name || `Agent ${agentId}`,
        avatarUrl: getAgentIconUrl(profile?.profile),
        profile: profile?.profile,
        hasGeo,
        coordinate,
      };
    }).filter((agent) => layoutMode !== 'map' || agent.hasGeo);
  }, [agentProfiles, layoutMode, positionsAtStep, randomLayout, visibleIds]);

  React.useEffect(() => {
    if (layoutMode !== 'map' || didFitGeoView || agentList.length === 0) {
      return;
    }
    const lngs = agentList.map((agent) => Number(agent.coordinate[0]));
    const lats = agentList.map((agent) => Number(agent.coordinate[1]));
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    setGeoViewState((prev) => ({
      ...prev,
      longitude: (minLng + maxLng) / 2,
      latitude: (minLat + maxLat) / 2,
      zoom: 10.5,
    }));
    setDidFitGeoView(true);
  }, [agentList, didFitGeoView, layoutMode]);

  const viewState = layoutMode === 'map' ? geoViewState : orthoViewState;

  const handleViewStateChange = ({ viewState: nextViewState }: any) => {
    if (layoutMode === 'map') {
      setGeoViewState(nextViewState);
    } else {
      setOrthoViewState(nextViewState);
    }
  };

  const layers = React.useMemo(() => {
    const result: any[] = [];
    const isCartesian = layoutMode !== 'map';
    const currentZoom = isCartesian ? orthoViewState.zoom : geoViewState.zoom;
    const showIcons = isCartesian ? currentZoom > 0.5 : currentZoom > 10;

    if (showIcons) {
      result.push(new IconLayer({
        id: 'agent-icons',
        data: agentList.map((agent) => ({
          id: agent.id,
          coordinate: agent.coordinate,
          avatarUrl: agent.avatarUrl,
          isSelected: agent.id === selectedAgentId,
        })),
        pickable: true,
        billboard: true,
        getIcon: (item: any) => ({
          url: item.avatarUrl,
          width: 128,
          height: 128,
          anchorX: 64,
          anchorY: 64,
        }),
        getSize: (item: any) => item.isSelected ? 40 : 32,
        getPosition: (item: any) => item.coordinate,
        sizeScale: 1,
        sizeMinPixels: 24,
        sizeMaxPixels: 56,
        parameters: { depthTest: false },
      }));

      result.push(new TextLayer({
        id: 'agent-labels',
        data: agentList.map((agent) => ({
          id: agent.id,
          coordinate: agent.coordinate,
          text: agent.name,
        })),
        getText: (item: any) => item.text,
        getPosition: (item: any) => item.coordinate,
        getSize: 12,
        sizeUnits: 'pixels',
        background: true,
        backgroundPadding: [4, 4, 4, 4],
        getBackgroundColor: [0, 0, 0, 128],
        getColor: [255, 255, 255],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'bottom',
        getPixelOffset: [0, -20],
        parameters: { depthTest: false },
      }));
    } else {
      result.push(new ScatterplotLayer({
        id: 'agent-points',
        data: agentList.map((agent) => ({
          id: agent.id,
          coordinate: agent.coordinate,
          color: agent.id === selectedAgentId ? [255, 99, 132] : [22, 119, 255],
        })),
        pickable: true,
        radiusUnits: isCartesian ? 'pixels' : 'meters',
        radiusScale: isCartesian ? 1 : 20,
        radiusMinPixels: 6,
        radiusMaxPixels: 24,
        getPosition: (item: any) => item.coordinate,
        getRadius: 10,
        getFillColor: (item: any) => item.color,
      }));
    }

    return result;
  }, [agentList, geoViewState.zoom, layoutMode, orthoViewState.zoom, selectedAgentId]);

  const handleClick = React.useCallback((info: any) => {
    if (!info.object) {
      return;
    }
    const agentId = info.object.id;
    actions.selectAgent(agentId === selectedAgentId ? null : agentId);
  }, [actions, selectedAgentId]);

  if (visibleIds.length === 0) {
    return (
      <div className="map-placeholder">
        <div className="map-placeholder-icon">🗺️</div>
        <div>No agent replay data available</div>
        <div style={{ fontSize: '12px', marginTop: '8px' }}>
          Replay datasets need at least one agent state table to render the scene
        </div>
      </div>
    );
  }

  const isCartesian = layoutMode !== 'map';

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }} onContextMenu={(event) => event.preventDefault()}>
      <DeckGL
        viewState={viewState}
        onViewStateChange={handleViewStateChange}
        controller={true}
        layers={layers}
        onHover={(info) => setHovering(Boolean(info.object))}
        getCursor={() => hovering ? 'pointer' : 'grab'}
        onClick={handleClick}
        views={isCartesian ? new OrthographicView({ id: 'ortho', controller: true }) : undefined}
        getTooltip={({ object, layer }) => {
          if (!object || !layer) return null;
          const agent = agentList.find((item) => item.id === object.id);
          if (!agent) return null;
          const positionText = layoutMode === 'map'
            ? `Position: ${Number(agent.coordinate[0]).toFixed(4)}, ${Number(agent.coordinate[1]).toFixed(4)}`
            : 'Layout: Random';
          return {
            html: `
              <div style="padding: 8px; font-size: 12px;">
                <div style="font-weight: bold; margin-bottom: 4px;">${agent.name}</div>
                <div>ID: ${agent.id}</div>
                <div>${positionText}</div>
              </div>
            `,
            style: {
              backgroundColor: 'var(--as-tooltip-bg)',
              color: 'var(--as-tooltip-fg)',
              borderRadius: '4px',
            },
          };
        }}
      >
        {layoutMode === 'map' && (
          <MapGL
            mapboxAccessToken={mapboxToken}
            mapStyle={MAP_STYLE}
            reuseMaps
            style={{ width: '100%', height: '100%' }}
            onError={(event: { error?: { message?: string } }) => {
              const message = event?.error?.message ?? 'Mapbox load failed';
              setMapError(message);
            }}
          />
        )}
      </DeckGL>

      <div style={{
        position: 'absolute',
        bottom: 16,
        left: 16,
        padding: '12px',
        background: 'var(--as-tooltip-bg)',
        borderRadius: '8px',
        fontSize: '11px',
        color: 'var(--as-tooltip-fg)',
      }}>
        <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>
          {layoutMode === 'map' ? 'Agent Positions' : 'Random Agent Layout'}
        </div>
        <div>{agentList.length} agents visible</div>
        <div style={{ opacity: 0.7, marginTop: '4px' }}>
          Zoom: {Number(viewState.zoom).toFixed(1)}
        </div>
        {selectedAgentId !== null && (
          <div style={{ marginTop: '4px', color: 'var(--vscode-errorForeground)' }}>
            Selected: Agent {selectedAgentId}
          </div>
        )}
      </div>

      {layoutMode === 'map' && agentList.length === 0 && (
        <div style={{
          position: 'absolute',
          top: 16,
          right: 16,
          padding: '10px 12px',
          background: 'var(--as-panel-bg-strong)',
          borderRadius: '8px',
          fontSize: '12px',
          color: 'var(--as-strong-text)',
        }}>
          {t('replay.noData')}
        </div>
      )}

      {mapError && (
        <div style={{
          position: 'absolute',
          top: 16,
          left: 16,
          padding: '10px 12px',
          background: 'var(--as-panel-bg-strong)',
          borderRadius: '8px',
          fontSize: '12px',
          color: 'var(--vscode-errorForeground)',
          maxWidth: '360px',
          boxShadow: 'var(--as-shadow)',
        }}>
          {t('replay.map.loadFailed')}: {mapError}
        </div>
      )}
    </div>
  );
};
