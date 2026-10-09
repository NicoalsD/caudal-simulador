import type { ValveView } from "../api/types";
import { es } from "../i18n/es";

interface ValveListProps {
  valves: ValveView[];
}

/** Position of each valve, as the simulation reports it. The dashboard never moves a valve. */
export function ValveList({ valves }: ValveListProps) {
  if (valves.length === 0) {
    return <p className="muted">{es.valvesNone}</p>;
  }
  return (
    <ul className="valves">
      {valves.map((valve) => (
        <li key={valve.id} className={`valve valve-${valve.status.toLowerCase()}`}>
          <span>{valve.label}</span>
          <span className="badge">{es.valveStatus[valve.status] ?? valve.status}</span>
        </li>
      ))}
    </ul>
  );
}
