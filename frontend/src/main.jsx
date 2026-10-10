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

const WEATHER_COLORS = {
  wind: '#e58b2d',
  rain: '#3182bd',
  snow: '#7b61b1',
};

function getLocalDepartureTime() {
  const departure = new Date(Date.now() + 30 * 60 * 1000);
  const pad = (value) => String(value).padStart(2, '0');
  // datetime-local values are wall-clock values, not UTC timestamps. Building the
  // value from local components avoids shifting the default by the user's timezone.
  return [departure.getFullYear(), pad(departure.getMonth() + 1), pad(departure.getDate())].join('-')
    + `T${pad(departure.getHours())}:${pad(departure.getMinutes())}`;
}

function formatEta(value) {
  return new Date(value).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
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

// This layer translates route checkpoints into a corridor-style visualization so the
// user can see weather exposure without needing a full GIS raster engine.
function buildCorridorHeatmap(route) {
  if (!route?.checkpoints?.length) return [];

  return route.checkpoints.slice(0, -1).map((checkpoint, index) => {
    const nextCheckpoint = route.checkpoints[index + 1];
    const windScore = Math.min(1, checkpoint.windMph / 55);
    const rainScore = Math.min(1, checkpoint.rainInHr / 1.01);
    const snowScore = Math.min(1, checkpoint.snowInHr / 3.01);
    const weatherType = snowScore >= rainScore && snowScore >= windScore
      ? 'snow'
      : rainScore >= windScore ? 'rain' : 'wind';
    const intensity = Math.max(windScore, rainScore, snowScore);

    return {
      id: `${route.id}-segment-${index}`,
      positions: [
        [checkpoint.lat, checkpoint.lon],
        [nextCheckpoint.lat, nextCheckpoint.lon],
      ],
      color: WEATHER_COLORS[weatherType],
      opacity: 0.3 + (intensity * 0.55),
      weight: 7 + intensity * 5,
      weatherType,
    };
  });
}

function RouteMap({ routePlan, selectedRoute, forecastOffset, departure, onForecastOffsetChange, onForecastCommit, mapLayer, checkpointSpacing, onToggleLayer }) {
  // The forecast slider replans only when released, so the checkpoint ETA and weather
  // values always come from the same requested departure time.
  const visibleCheckpoints = useMemo(() => {
    if (!routePlan?.routes) return [];
    return routePlan.routes
      .flatMap((route, routeIndex) => route.checkpoints.map((checkpoint) => ({
        ...checkpoint,
        routeId: route.id,
        routeLabel: route.recommended ? 'Recommended route' : `Alternative ${routeIndex}`,
        selected: route.id === selectedRoute?.id,
      })))
      .sort((left, right) => Number(left.selected) - Number(right.selected));
  }, [routePlan, selectedRoute?.id]);

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
          <button type="button" className="map-toggle" onClick={onToggleLayer}>
            {mapLayer === 'Risk' ? '◉ Risk layer' : '☁ Weather layer'}
          </button>
          <button type="button" className="icon-btn" aria-label="Map options">···</button>
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
              key={`${checkpoint.routeId}-${checkpoint.mile}-${checkpoint.lat}`}
              center={[checkpoint.lat, checkpoint.lon]}
              radius={checkpoint.selected
                ? mapLayer === 'Risk' ? 7 : Math.max(6, Math.min(13, 6 + checkpoint.windMph / 10))
                : 4}
              pathOptions={{
                color: '#fff',
                weight: checkpoint.selected ? 2 : 1,
                fillColor: mapLayer === 'Risk'
                  ? RISK_COLORS[checkpoint.risk]
                  : checkpoint.snowInHr > 0.1
                    ? WEATHER_COLORS.snow
                    : checkpoint.rainInHr > 0.1
                      ? WEATHER_COLORS.rain
                      : checkpoint.windMph >= 25
                        ? WEATHER_COLORS.wind
                        : '#22a06b',
                fillOpacity: checkpoint.selected ? 0.95 : 0.62,
              }}
            >
              <Popup>
                <div className="popup">
                  <b>{checkpoint.routeLabel} · {checkpoint.mile} mi · {checkpoint.risk}</b>
                  <br />Arrival {new Date(checkpoint.eta).toLocaleString()}
                  <br />Wind {Math.round(checkpoint.windMph)} mph · Rain {checkpoint.rainInHr.toFixed(2)} in/hr · Snow {checkpoint.snowInHr.toFixed(1)} in/hr
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>

        <div className="map-legend">
          <b>{mapLayer === 'Risk' ? 'RISK LEVEL' : 'WEATHER EXPOSURE'}</b>
          {mapLayer === 'Risk'
            ? Object.entries(RISK_COLORS).map(([riskName, color]) => (
              <span key={riskName}><i style={{ background: color }} />{riskName}</span>
            ))
            : Object.entries(WEATHER_COLORS).map(([weatherType, color]) => (
              <span key={weatherType}><i style={{ background: color }} />{weatherType}</span>
            ))}
        </div>
        <div className="map-attribution">Forecast checkpoints · {checkpointSpacing} mi</div>
      </div>

      <ForecastTimeline
        forecastOffset={forecastOffset}
        departure={departure}
        onChange={onForecastOffsetChange}
        onCommit={onForecastCommit}
      />
    </section>
  );
}

function ForecastTimeline({ forecastOffset, departure, onChange, onCommit }) {
  const displayedTime = new Date(new Date(departure).getTime() + forecastOffset * 60 * 60 * 1000);

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
          onChange={(event) => {
            const nextOffset = Number(event.target.value);
            onChange(nextOffset);
            onCommit(nextOffset);
          }}
        />
        <div className="slider-ticks"><i /><i /><i /><i /><i /></div>
      </div>
      <div className="forecast-value">
        <span>{forecastOffset === 0 ? 'DEPARTURE' : 'FORECAST'}</span>
        <b>{displayedTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b>
      </div>
    </div>
  );
}

function CityAutocomplete({ id, label, value, onChange, icon: Icon }) {
  const [suggestions, setSuggestions] = useState([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isFocused, setIsFocused] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [suggestionError, setSuggestionError] = useState('');

  React.useEffect(() => {
    const query = value.trim();
    if (query.length < 2) {
      setSuggestions([]);
      setSuggestionError('');
      setIsSearching(false);
      return undefined;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(async () => {
      setIsSearching(true);
      setSuggestionError('');
      try {
        const params = new URLSearchParams({
          name: query,
          count: '6',
          language: 'en',
          format: 'json',
        });
        const response = await fetch(
          `https://geocoding-api.open-meteo.com/v1/search?${params}`,
          { signal: controller.signal },
        );
        if (!response.ok) throw new Error(`City search failed (${response.status}).`);

        const body = await response.json();
        const seenLabels = new Set();
        const results = (body.results || []).map((result) => {
          const locationLabel = [result.name, result.admin1, result.country]
            .filter(Boolean)
            .join(', ');
          return {
            id: result.id || locationLabel,
            label: locationLabel,
            detail: [result.admin1, result.country].filter(Boolean).join(', '),
          };
        }).filter((result) => {
          if (!result.label || seenLabels.has(result.label)) return false;
          seenLabels.add(result.label);
          return true;
        });
        setSuggestions(results);
        setActiveIndex(-1);
      } catch (error) {
        if (error.name !== 'AbortError') {
          setSuggestions([]);
          setSuggestionError('City suggestions are unavailable right now.');
        }
      } finally {
        if (!controller.signal.aborted) setIsSearching(false);
      }
    }, 250);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [value]);

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown' && suggestions.length) {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % suggestions.length);
    } else if (event.key === 'ArrowUp' && suggestions.length) {
      event.preventDefault();
      setActiveIndex((current) => (current <= 0 ? suggestions.length - 1 : current - 1));
    } else if (event.key === 'Enter' && activeIndex >= 0 && suggestions[activeIndex]) {
      event.preventDefault();
      onChange(suggestions[activeIndex].label);
      setIsFocused(false);
    } else if (event.key === 'Escape') {
      setIsFocused(false);
    }
  }

  const showSuggestions = isFocused && value.trim().length >= 2;

  return (
    <div className="city-field">
      <label htmlFor={id}>{label}</label>
      <div className="city-autocomplete">
        <div className="input-wrap"><Icon size={16} />
          <input
            id={id}
            type="text"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            onKeyDown={handleKeyDown}
            autoComplete="off"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={showSuggestions}
            aria-controls={`${id}-suggestions`}
            aria-activedescendant={activeIndex >= 0 ? `${id}-suggestion-${activeIndex}` : undefined}
            aria-busy={isSearching}
            required
          />
        </div>
        {showSuggestions && (
          <div className="city-suggestions" id={`${id}-suggestions`} role="listbox">
            {isSearching && <div className="city-suggestion-message">Searching cities...</div>}
            {!isSearching && suggestionError && (
              <div className="city-suggestion-message city-suggestion-error" role="status">{suggestionError}</div>
            )}
            {!isSearching && !suggestionError && suggestions.map((suggestion, index) => (
              <button
                type="button"
                role="option"
                aria-selected={activeIndex === index}
                id={`${id}-suggestion-${index}`}
                className={`city-suggestion ${activeIndex === index ? 'active' : ''}`}
                key={`${suggestion.id}-${index}`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onChange(suggestion.label);
                  setIsFocused(false);
                }}
              >
                <MapPin size={14} />
                <span><b>{suggestion.label}</b><small>{suggestion.detail}</small></span>
              </button>
            ))}
            {!isSearching && !suggestionError && suggestions.length === 0 && (
              <div className="city-suggestion-message">No matching cities found.</div>
            )}
          </div>
        )}
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
        <CityAutocomplete
          id="origin"
          label="ORIGIN"
          value={formValues.origin}
          onChange={(value) => onFieldChange('origin', value)}
          icon={MapPin}
        />
        <div className="connector" />
        <CityAutocomplete
          id="destination"
          label="DESTINATION"
          value={formValues.destination}
          onChange={(value) => onFieldChange('destination', value)}
          icon={ArrowUpRight}
        />
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
        <button type="submit" className="plan-button" disabled={isLoading}>
          {isLoading
            ? <><LoaderCircle className="spin" size={17} /> Analyzing corridor...</>
            : <><CloudSun size={17} /> Analyze routes <span>→</span></>}
        </button>
      </form>

      {errorMessage && <div className="error" role="alert">{errorMessage}</div>}
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
        <h2>{routes ? `${routes.length} route${routes.length === 1 ? '' : 's'} analyzed` : 'Routes will appear here'}</h2>
        {routes && routes.length < 3 && (
          <div className="provider-note">The routing provider returned {routes.length} available option{routes.length === 1 ? '' : 's'} for this trip.</div>
        )}
      </div>
      {selectedRoute && (
        <div className="recommendation">
          <span><ShieldCheck size={15} /> SAFEST BALANCE</span>
          <b>{selectedRoute.distanceMiles} mi <i>·</i> {selectedRoute.durationHours} hr</b>
          <small>
            {selectedRoute.noTravelMiles ? `${selectedRoute.noTravelMiles} no-travel mi · ` : ''}
            {selectedRoute.severeMiles} severe mi · {selectedRoute.highMiles} high mi
          </small>
        </div>
      )}
      <div className="route-list">
        {routes?.map((route, index) => (
          <button
            type="button"
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
              <span>Arrive {formatEta(route.arrival)}</span>
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
  if (route.noTravelMiles) return 'No travel';
  if (route.severeMiles) return 'Severe risk';
  if (route.highMiles) return 'High risk';
  return 'Low exposure';
}

function getExposureStyle(route) {
  if (route.noTravelMiles) return { color: '#811d38', background: '#f7e8ee' };
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
              <span>{formatEta(checkpoint.eta)} · {Math.round(checkpoint.windMph)} mph wind</span>
            </div>
            <div className="cp-weather"><CloudRain size={14} />{checkpoint.rainInHr.toFixed(2)}<small>in</small></div>
          </div>
        ))}
      </div>
    </>
  );
}

const API_BASE_URL = import.meta.env.DEV
  ? ''
  : (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

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
  const forecastRequestTimer = React.useRef(null);
  React.useEffect(() => () => window.clearTimeout(forecastRequestTimer.current), []);
  const selectedRoute = routePlan?.routes.find((route) => route.id === selectedRouteId)
    || routePlan?.routes[0];

  function updateFormField(fieldName, fieldValue) {
    setFormValues((currentValues) => ({ ...currentValues, [fieldName]: fieldValue }));
  }

  // The planner submits a single payload to the backend, which handles the heavy work of
  // geocoding, route alternatives, weather lookup, scoring, and ranking.
  async function requestRoutePlan(departureValue = formValues.departure) {
    setIsLoading(true);
    setErrorMessage('');

    try {
      const requestBody = {
        ...formValues,
        departure: new Date(departureValue).toISOString(),
      };
      const response = await fetch(`${API_BASE_URL}/api/plan/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });
      const responseText = await response.text();
      let responseBody = {};
      if (responseText) {
        try {
          responseBody = JSON.parse(responseText);
        } catch {
          throw new Error(`Route service returned an invalid response (${response.status}).`);
        }
      }
      if (!response.ok && !responseText) {
        throw new Error(`Route service is unavailable (${response.status}).`);
      }
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
    window.clearTimeout(forecastRequestTimer.current);
    setForecastOffset(0);
    await requestRoutePlan(formValues.departure);
  }

  function handleForecastOffsetChange(nextOffset) {
    setForecastOffset(nextOffset);
  }

  function commitForecastOffset(nextOffset) {
    // Slider input fires repeatedly while dragging. Wait until the user pauses so
    // one gesture produces one route/weather refresh instead of many API calls.
    window.clearTimeout(forecastRequestTimer.current);
    forecastRequestTimer.current = window.setTimeout(() => {
      const nextDeparture = new Date(new Date(formValues.departure).getTime() + nextOffset * 60 * 60 * 1000);
      requestRoutePlan(nextDeparture.toISOString());
    }, 500);
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
          departure={formValues.departure}
          onForecastOffsetChange={handleForecastOffsetChange}
          onForecastCommit={commitForecastOffset}
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
