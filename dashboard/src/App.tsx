import { EventLog } from "./components/EventLog";
import { SensorPanel } from "./components/SensorPanel";
import { SimulatedBanner } from "./components/SimulatedBanner";
import { TankGauge } from "./components/TankGauge";
import { ValveList } from "./components/ValveList";
import { useSimulation } from "./hooks/useSimulation";
import { es } from "./i18n/es";

export function App() {
  const { state, events, connected, stateError } = useSimulation();

  return (
    <div className="page">
      <header className="header">
        <h1>{es.title}</h1>
        <span className={connected ? "badge live" : "badge offline"}>
          {connected ? es.connectionLive : es.connectionOffline}
        </span>
      </header>
      <SimulatedBanner />
      {stateError ? <p className="alert">{es.stateError}</p> : null}
      <main className="grid">
        <section className="card" aria-labelledby="tank-title">
          <h2 id="tank-title">{es.tankTitle}</h2>
          <TankGauge
            level={state?.tank_level_m ?? null}
            gaugeMin={state?.gauge_min_m ?? null}
            gaugeMax={state?.gauge_max_m ?? null}
          />
        </section>
        <section className="card" aria-labelledby="valves-title">
          <h2 id="valves-title">{es.valvesTitle}</h2>
          <ValveList valves={state?.valves ?? []} />
        </section>
        <section className="card" aria-labelledby="sensor-title">
          <h2 id="sensor-title">{es.sensorTitle}</h2>
          <SensorPanel reading={state?.sensor_level_m ?? null} />
        </section>
        <section className="card wide" aria-labelledby="events-title">
          <h2 id="events-title">{es.eventsTitle}</h2>
          <EventLog events={events} />
        </section>
      </main>
      {state !== null ? (
        <footer className="footer">
          {es.scenario}: {state.scenario}
          {state.updated_at !== null ? ` · ${es.updatedAt}: ${state.updated_at}` : ""}
        </footer>
      ) : null}
    </div>
  );
}
