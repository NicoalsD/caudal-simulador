import type { SimulationEventView } from "../api/types";
import { es } from "../i18n/es";

interface EventLogProps {
  events: SimulationEventView[];
}

const TIME_LOCALE = "es-CO";

function formatTime(value: string | null): string {
  if (value === null) {
    return "";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString(TIME_LOCALE);
}

/** Newest events last, as they arrive from the simulation. */
export function EventLog({ events }: EventLogProps) {
  if (events.length === 0) {
    return <p className="muted">{es.eventsNone}</p>;
  }
  return (
    <ol className="events">
      {events.map((event) => (
        <li key={event.id}>
          <time>{formatTime(event.occurred_at)}</time>{" "}
          <span className="badge">{es.eventKind[event.kind] ?? event.kind}</span>{" "}
          {event.kind === "DROPPED" ? (
            <span>
              {es.eventsDropped} {event.detail}
            </span>
          ) : (
            <span>{event.detail}</span>
          )}
        </li>
      ))}
    </ol>
  );
}
