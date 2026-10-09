import { useEffect, useState } from "react";
import { fetchState } from "../api/client";
import { API_EVENTS_PATH, STATE_REFRESH_MS } from "../config";
import { DROPPED_EVENT, SIMULATION_EVENT_KINDS, type SimulationEventView, type StateView } from "../api/types";
import { appendEvent, parseEventFrame } from "../state/events";

export interface SimulationView {
  state: StateView | null;
  events: SimulationEventView[];
  connected: boolean;
  stateError: boolean;
}

/** Keeps the dashboard in sync: the state is polled, and the events arrive by SSE. */
export function useSimulation(): SimulationView {
  const [state, setState] = useState<StateView | null>(null);
  const [events, setEvents] = useState<SimulationEventView[]>([]);
  const [connected, setConnected] = useState(false);
  const [stateError, setStateError] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = (): void => {
      fetchState()
        .then((next) => {
          if (active) {
            setState(next);
            setStateError(false);
          }
        })
        .catch(() => {
          if (active) {
            setStateError(true);
          }
        });
    };
    refresh();
    const timer = window.setInterval(refresh, STATE_REFRESH_MS);

    const source = new EventSource(API_EVENTS_PATH);
    const onFrame = (message: MessageEvent<string>): void => {
      const view = parseEventFrame(message.lastEventId, message.type, message.data);
      if (view !== null && active) {
        setEvents((previous) => appendEvent(previous, view));
      }
    };
    source.onopen = () => {
      if (active) {
        setConnected(true);
      }
    };
    source.onerror = () => {
      if (active) {
        setConnected(false);
      }
    };
    for (const kind of [...SIMULATION_EVENT_KINDS, DROPPED_EVENT]) {
      source.addEventListener(kind, onFrame);
    }

    return () => {
      active = false;
      window.clearInterval(timer);
      source.close();
    };
  }, []);

  return { state, events, connected, stateError };
}
