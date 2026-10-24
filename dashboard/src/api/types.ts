// Shapes of the local dashboard API (caudal-sim tablero). Field names follow the API, in English.

export interface ValveView {
  id: string;
  label: string;
  status: string;
}

export interface StateView {
  scenario: string;
  simulated: boolean;
  notice: string;
  updated_at: string | null;
  tank_level_m: number | null;
  sensor_level_m: number | null;
  gauge_min_m: number | null;
  gauge_max_m: number | null;
  paused: boolean;
  speed_factor: number;
  valves: ValveView[];
}

export const SIMULATION_EVENT_KINDS = [
  "VALVE_STATE_CHANGED",
  "COMMAND_DELIVERED",
  "COMMAND_CONFIRMED",
] as const;

export const DROPPED_EVENT = "DROPPED";

export interface SimulationEventView {
  id: string;
  occurred_at: string | null;
  kind: string;
  subject_id: string;
  detail: string;
}

/** Manual conditions the dashboard can inject. There is no valve action on purpose. */
export type ControlAction =
  | "LEAK"
  | "HEAVY_RAIN"
  | "SENSOR_STUCK"
  | "SENSOR_SILENT"
  | "NETWORK_DOWN"
  | "NETWORK_UP"
  | "PAUSE"
  | "RESUME"
  | "SET_SPEED";

export interface ControlBody {
  action: ControlAction;
  factor?: number;
}
