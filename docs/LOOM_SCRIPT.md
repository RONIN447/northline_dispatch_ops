# Loom walkthrough script (5-10 minutes)

## Opening (30 sec)

"Hi, I’m presenting a weather-aware truck routing dashboard that helps dispatchers compare route options based on wind, rain, snow, and load weight. The goal is to reduce route risk while keeping schedule efficiency in mind."

## Problem statement (45 sec)

"In freight operations, relying on a single route without weather awareness can create expensive delays, safety hazards, and route inefficiency. This app helps planners evaluate the safest route before dispatching a load."

## Product overview (1 min)

"The tool accepts origin, destination, departure time, load weight, and checkpoint spacing. It queries routing and weather providers, then scores each route using weather and risk thresholds."

## Demo flow (3-4 min)

1. Open the main dashboard.
2. Enter a route such as San Francisco to Los Angeles.
3. Set a departure time and load weight.
4. Click Analyze routes.
5. Show the recommended route card, route metrics, and checkpoint risk summary.
6. Toggle between Risk layer and Weather layer.
7. Adjust the forecast slider to preview changes over time.
8. Point out the route ranking logic: severe miles, high miles, average risk, then duration.

## Technical highlight (2 min)

"The backend performs geocoding, route alternatives, weather fetches, and risk classification. The frontend turns that into a live map and operational route summary without losing performance."

## Why this is strong (1 min)

"It combines practical logistics thinking with real API integration and an operational UI, which is exactly the kind of product thinking teams want from a top candidate."

## Closing (30 sec)

"I designed this to feel like a real dispatch tool, not just a demo. It is ready for repo handoff, local run, and extension into a production-grade deployment."
