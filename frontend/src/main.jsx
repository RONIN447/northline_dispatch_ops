import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  useMap,
} from 'react-leaflet';
import {
  ArrowUpRight,
  CloudRain,
  CloudSun,
  Clock3,
  LoaderCircle,
  MapPin,
  Route as RouteIcon,
  ShieldCheck,
  Truck,
  Wind,
} from 'lucide-react';
import 'leaflet/dist/leaflet.css';
import './style.css';

const RISK_COLORS = {
  Low: '#22a06b',
  Moderate: '#e7ad32',
  High: '#ed762b',
  Severe: '#d84f55',
  'No Travel': '#811d38',
};

function getLocalDepartureTime() {
  const departure = new Date(Date.now() + 30 * 60 * 1000);
  departure.setMinutes(departure.getMinutes() - departure.getTimezoneOffset());
  return departure.toISOString().slice(0, 16);
}

function FitMapToRoute({ route }) {
  const map = useMap();

  React.useEffect(() => {
    if (!route?.geometry?.length) return;
    const routeBounds = route.geometry.map(([longitude, latitude]) => [latitude, longitude]);
    map.fitBounds(routeBounds, { padding: [45, 45] });
  }, [map, route?.id]);

  return null;
}

function buildCorridorHeatmap(route) {
  if (!route?.checkpoints?.length) return [];

  return route.checkpoints.slice(0, -1).map((checkpoint, index) => {
    const nextCheckpoint = route.checkpoints[index + 1];
    const riskName = checkpoint.risk || nextCheckpoint.risk;
    const riskScore = {
      Low: 0,
      Moderate: 1,
      High: 2,
      Severe: 3,
      'No Travel': 4,
    }[riskName] ?? 0;

    return {
      id: `${route.id}-segment-${index}`,
      positions: [
        [checkpoint.lat, checkpoint.lon],
        [nextCheckpoint.lat, nextCheckpoint.lon],
      ],
      color: RISK_COLORS[riskName],
      opacity: 0.18 + (riskScore * 0.18),
      weight: 6 + riskScore * 3,
    };
  });
}

function RouteMap({ routePlan, selectedRoute, forecastOffset, onForecastOffsetChange, mapLayer, checkpointSpacing, onToggleLayer }) {
  const visibleCheckpoints = useMemo(() => {
    if (!selectedRoute) return [];

    return selectedRoute.checkpoints.map((checkpoint) => ({
      ...checkpoint,
      displayedArrival: new Date(
        new Date(checkpoint.eta).getTime() + forecastOffset * 60 * 60 * 1000,
      ),
    }));
  }, [selectedRoute, forecastOffset]);

  const corridorHeatmap = useMemo(() => buildCorridorHeatmap(selectedRoute), [selectedRoute]);

  return (
    <section className="map-panel">
      <div className="map-head">
        <div>
          <div className="eyebrow">Corridor view</div>
          <h2>
            {routePlan
              ? `${routePlan.origin.label} → ${routePlan.destination.label}`
              : 'Plan the next dispatch'}
          </h2>
        </div>
        <div className="map-actions">
          <button className="map-toggle" onClick={onToggleLayer}>
            {mapLayer === 'Risk' ? '◉ Risk layer' : '☁ Weather layer'}
          </button>
          <button className="icon-btn" aria-label="Map options">···</button>
        </div>
      </div>

      <div className="map-wrap">
        <MapContainer center={[37.8, -120]} zoom={6} scrollWheelZoom className="map">
          <TileLayer
            attribution="&copy; OpenStreetMap"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FitMapToRoute route={selectedRoute} />
          {routePlan?.routes.map((route) => (
            <Polyline
              key={route.id}
              positions={route.geometry.map(([longitude, latitude]) => [latitude, longitude])}
              pathOptions={{
                color: route.id === selectedRoute?.id ? '#155f50' : '#83918b',
                weight: route.id === selectedRoute?.id ? 5 : 3,
                opacity: route.id === selectedRoute?.id ? 0.95 : 0.48,
                dashArray: route.id === selectedRoute?.id ? undefined : '7 8',
              }}
            />
          ))}
          {mapLayer === 'Weather' && corridorHeatmap.map((segment) => (
            <Polyline
              key={segment.id}
              positions={segment.positions}
              pathOptions={{
                color: segment.color,
                weight: segment.weight,
                opacity: segment.opacity,
              }}
            />
          ))}
          {visibleCheckpoints.map((checkpoint) => (
            <CircleMarker
              key={`${checkpoint.mile}-${checkpoint.lat}`}
              center={[checkpoint.lat, checkpoint.lon]}
              radius={mapLayer === 'Risk' ? 7 : Math.max(6, Math.min(13, 6 + checkpoint.windMph / 10))}
              pathOptions={{
                color: '#fff',
                weight: 2,
                fillColor: mapLayer === 'Risk'
                  ? RISK_COLORS[checkpoint.risk]
                  : checkpoint.rainInHr > 0.1 ? '#4688cb' : '#22a06b',
                fillOpacity: 0.95,
              }}
            >
              <Popup>
                <div className="popup">
                  <b>{checkpoint.mile} mi · {checkpoint.risk}</b>
                  <br />Arrival {checkpoint.displayedArrival.toLocaleString()}
                  <br />Wind {Math.round(checkpoint.windMph)} mph · Rain {checkpoint.rainInHr.toFixed(2)} in/hr · Snow {checkpoint.snowInHr.toFixed(1)} in/hr
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>

        <div className="map-legend">
          <b>{mapLayer.toUpperCase()} LEVEL</b>
          {Object.entries(RISK_COLORS).map(([riskName, color]) => (
            <span key={riskName}><i style={{ background: color }} />{riskName}</span>
          ))}
        </div>
        <div className="map-attribution">Forecast checkpoints · {checkpointSpacing} mi</div>
      </div>

      <ForecastTimeline forecastOffset={forecastOffset} onChange={onForecastOffsetChange} />
    </section>
  );
}

function ForecastTimeline({ forecastOffset, onChange }) {
  const displayedTime = new Date(Date.now() + forecastOffset * 60 * 60 * 1000);

  return (
    <div className="forecast-bar">
      <div className="forecast-label">
        <div className="weather-icon"><CloudSun size={20} /></div>
        <div><b>Corridor forecast</b><span>Checkpoint arrival conditions</span></div>
      </div>
      <div className="slider-zone">
        <div className="slider-labels">
          <span>DEPARTURE</span><b>+{forecastOffset} HOURS</b><span>48 HOURS</span>
        </div>
        <input
          aria-label="Forecast hour"
          type="range"
          min="0"
          max="48"
          value={forecastOffset}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <div className="slider-ticks"><i /><i /><i /><i /><i /></div>
      </div>
      <div className="forecast-value">
        <span>{forecastOffset === 0 ? 'NOW' : 'FORECAST'}</span>
        <b>{displayedTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b>
      </div>
    </div>
  );
}

function RoutePlanner({ formValues, onFieldChange, onSubmit, isLoading, errorMessage }) {
  return (
    <aside className="sidebar">
      <div className="eyebrow">ROUTE PLANNER</div>
      <h1>Map the safest<br />route ahead.</h1>
      <p className="intro">Compare weather exposure and lead time before dispatching the load.</p>

      <form onSubmit={onSubmit} className="planner-form">
        <label>ORIGIN
          <div className="input-wrap"><MapPin size={16} />
            <input value={formValues.origin} onChange={(event) => onFieldChange('origin', event.target.value)} required />
          </div>
        </label>
        <div className="connector" />
        <label>DESTINATION
          <div className="input-wrap"><ArrowUpRight size={16} />
            <input value={formValues.destination} onChange={(event) => onFieldChange('destination', event.target.value)} required />
          </div>
        </label>
        <div className="field-row">
          <label>DEPARTURE
            <div className="input-wrap"><Clock3 size={16} />
              <input type="datetime-local" value={formValues.departure} onChange={(event) => onFieldChange('departure', event.target.value)} required />
            </div>
          </label>
        </div>
        <div className="field-row">
          <label>LOAD WEIGHT
            <div className="input-wrap"><Truck size={16} />
              <input type="number" min="0" value={formValues.loadWeight} onChange={(event) => onFieldChange('loadWeight', event.target.value)} required />
              <span className="unit">lb</span>
            </div>
          </label>
          <label>CHECKPOINTS
            <div className="select-wrap">
              <select value={formValues.intervalMiles} onChange={(event) => onFieldChange('intervalMiles', event.target.value)}>
                <option value="10">Every 10 mi</option>
                <option value="25">Every 25 mi</option>
                <option value="50">Every 50 mi</option>
              </select>
            </div>
          </label>
        </div>
        <button className="plan-button" disabled={isLoading}>
          {isLoading
            ? <><LoaderCircle className="spin" size={17} /> Analyzing corridor...</>
            : <><CloudSun size={17} /> Analyze routes <span>→</span></>}
        </button>
      </form>

      {errorMessage && <div className="error">{errorMessage}</div>}
      <div className="logic-note">
        <ShieldCheck size={16} />
        <span><b>Load-aware safety</b><br />Wind, rain, and snow thresholds are adjusted for cargo weight and route exposure.</span>
      </div>
      <div className="sidebar-foot">Route data by OSRM <span>·</span> weather by Open-Meteo</div>
    </aside>
  );
}

function RouteOptions({ routes, selectedRoute, onSelectRoute }) {
  return (
    <aside className="routes-panel">
      <div className="routes-header">
        <div className="eyebrow">Available routes</div>
        <h2>{routes ? `${routes.length} routes analyzed` : 'Routes will appear here'}</h2>
      </div>
      {selectedRoute && (
        <div className="recommendation">
          <span><ShieldCheck size={15} /> SAFEST BALANCE</span>
          <b>{selectedRoute.distanceMiles} mi <i>·</i> {selectedRoute.durationHours} hr</b>
          <small>{selectedRoute.severeMiles} severe mi · {selectedRoute.highMiles} high mi</small>
        </div>
      )}
      <div className="route-list">
        {routes?.map((route, index) => (
          <button
            className={`route-card ${route.id === selectedRoute?.id ? 'active' : ''}`}
            key={route.id}
            onClick={() => onSelectRoute(route.id)}
          >
            <div className="route-card-top">
              <span className="route-num">0{index + 1}</span>
              <span className="route-title">{index === 0 ? 'Recommended route' : `Alternative ${index}`}</span>
              {route.recommended && <span className="best-tag">BEST</span>}
            </div>
            <div className="route-metrics">
              <b>{route.distanceMiles}<small> mi</small></b>
              <b>{route.durationHours}<small> hr</small></b>
              <span className="risk-pill" style={getExposureStyle(route)}>{getExposureLabel(route)}</span>
            </div>
            <div className="route-meta">
              <span><Wind size={13} /> {route.checkpoints.length} checkpoints</span>
              <span>Arrive {new Date(route.arrival).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
            <div className="route-summary">{route.summary}</div>
          </button>
        ))}
      </div>

      {selectedRoute && <CheckpointList route={selectedRoute} />}
      <div className="ranking-note">
        <b>How routes are ranked</b>
        <span>1. Fewest severe miles · 2. Fewest high miles<br />3. Lowest average risk · 4. Shortest time</span>
      </div>
    </aside>
  );
}

function getExposureLabel(route) {
  if (route.severeMiles) return 'Severe risk';
  if (route.highMiles) return 'High risk';
  return 'Low exposure';
}

function getExposureStyle(route) {
  if (route.severeMiles) return { color: '#b33a44', background: '#fbecee' };
  if (route.highMiles) return { color: '#a36c08', background: '#fff5df' };
  return { color: '#19734f', background: '#e8f5ef' };
}

function CheckpointList({ route }) {
  return (
    <>
      <div className="checkpoint-heading">
        <div><div className="eyebrow">SELECTED ROUTE</div><b>Checkpoint conditions</b></div>
        <span>{route.distanceMiles} mi · {route.durationHours} hr</span>
      </div>
      <div className="checkpoint-list">
        {route.checkpoints.map((checkpoint) => (
          <div className="checkpoint" key={`${checkpoint.mile}-${checkpoint.lat}`}>
            <div className="cp-mile">
              <i style={{ background: RISK_COLORS[checkpoint.risk] }} />
              {checkpoint.mile}<small>mi</small>
            </div>
            <div className="cp-main">
              <b>{checkpoint.risk}</b>
              <span>{new Date(checkpoint.eta).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · {Math.round(checkpoint.windMph)} mph wind</span>
            </div>
            <div className="cp-weather"><CloudRain size={14} />{checkpoint.rainInHr.toFixed(2)}<small>in</small></div>
          </div>
        ))}
      </div>
    </>
  );
}

function App() {
  const [formValues, setFormValues] = useState({
    origin: 'San Francisco, CA',
    destination: 'Los Angeles, CA',
    departure: getLocalDepartureTime(),
    loadWeight: '28000',
    intervalMiles: '25',
  });
  const [routePlan, setRoutePlan] = useState(null);
  const [selectedRouteId, setSelectedRouteId] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [forecastOffset, setForecastOffset] = useState(0);
  const [mapLayer, setMapLayer] = useState('Risk');
  const selectedRoute = routePlan?.routes.find((route) => route.id === selectedRouteId)
    || routePlan?.routes[0];

  function updateFormField(fieldName, fieldValue) {
    setFormValues((currentValues) => ({ ...currentValues, [fieldName]: fieldValue }));
  }

  async function requestRoutePlan(departureValue = formValues.departure) {
    setIsLoading(true);
    setErrorMessage('');

    try {
      const requestBody = {
        ...formValues,
        departure: new Date(departureValue).toISOString(),
      };
      const response = await fetch('/api/plan/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });
      const responseBody = await response.json();
      if (!response.ok) throw new Error(responseBody.error || 'Route planning failed.');

      setRoutePlan(responseBody);
      setSelectedRouteId(responseBody.recommendedRouteId);
      return responseBody;
    } catch (error) {
      setErrorMessage(error.message);
      return null;
    } finally {
      setIsLoading(false);
    }
  }

  async function analyzeRoutes(event) {
    event.preventDefault();
    setForecastOffset(0);
    await requestRoutePlan(formValues.departure);
  }

  async function handleForecastOffsetChange(nextOffset) {
    setForecastOffset(nextOffset);
    const nextDeparture = new Date(new Date(formValues.departure).getTime() + nextOffset * 60 * 60 * 1000);
    await requestRoutePlan(nextDeparture.toISOString());
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon"><RouteIcon size={19} /></div>
          <div><strong>Northline</strong><span>Dispatch Ops</span></div>
        </div>
        <div className="top-status">
          <span className="status-dot" /> Route Weather Desk
          <span className="divider" /> <span className="utc">Live forecast</span>
        </div>
        <div className="profile">ND</div>
      </header>

      <div className="workspace">
        <RoutePlanner
          formValues={formValues}
          onFieldChange={updateFormField}
          onSubmit={analyzeRoutes}
          isLoading={isLoading}
          errorMessage={errorMessage}
        />
        <RouteMap
          routePlan={routePlan}
          selectedRoute={selectedRoute}
          forecastOffset={forecastOffset}
          onForecastOffsetChange={handleForecastOffsetChange}
          mapLayer={mapLayer}
          checkpointSpacing={formValues.intervalMiles}
          onToggleLayer={() => setMapLayer((currentLayer) => currentLayer === 'Risk' ? 'Weather' : 'Risk')}
        />
        <RouteOptions
          routes={routePlan?.routes}
          selectedRoute={selectedRoute}
          onSelectRoute={setSelectedRouteId}
        />
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
