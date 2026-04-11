# MarsOps Web Frontend

A single-page React app that renders the Mars terrain in 3D, loads the Curiosity
rover model, draws the planned path, and animates the rover along the path as
WebSocket telemetry events stream in from the backend.

## Dev Setup

```bash
cd web
npm install
npm run dev
```

The backend must be running on `http://localhost:8000` before using the terrain
loader or mission controls. Start it from the repo root with:

```bash
uv run marsops-web
```

Then open `http://localhost:5173` in your browser.

### Smoke-test the current UI

Use the mission controls in the top-right corner:

- Pick one of the presets: **Delta Survey**, **Crater Dip**, or **Rim Patrol**.
- Optionally inject an anomaly and choose which step it fires on.
- Click **Run Mission** to load terrain, plan, and execute with live telemetry.
- Use the minimap in the bottom-left to choose a custom start cell; dim cells
  are discouraged as mission starts.

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server (HMR) |
| `npm run build` | Type-check + production build |
| `npm run lint` | TypeScript type-check only |
| `npm run preview` | Preview production build locally |

## Built With

- [Vite](https://vitejs.dev/) — build tool & dev server
- [React 19](https://react.dev/) — UI framework
- [TypeScript](https://www.typescriptlang.org/) — strict typing
- [React Three Fiber](https://docs.pmnd.rs/react-three-fiber) — React renderer for Three.js
- [@react-three/drei](https://github.com/pmndrs/drei) — R3F helpers (OrbitControls, Stars, Line, useGLTF)
- [Zustand](https://zustand-demo.pmnd.rs/) — lightweight global state
- [Tailwind CSS v3](https://tailwindcss.com/) — utility-first styling
