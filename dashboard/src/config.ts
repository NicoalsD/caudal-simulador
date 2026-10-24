// Named constants of the dashboard. Business values never live here: they come from the API.

export const API_STATE_PATH = "/api/tablero/estado";
export const API_EVENTS_PATH = "/api/tablero/eventos";
export const STATE_REFRESH_MS = 2000;
export const MAX_EVENTS_SHOWN = 50;
export const PERCENT = 100;
export const LEVEL_DECIMALS = 2;
export const CONTROLS_PATH = "/api/tablero/controles";
export const SPEED_FACTORS = [1, 10, 60] as const;
export const DEFAULT_SPEED = 1;
