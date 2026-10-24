import { API_STATE_PATH, CONTROLS_PATH } from "../config";
import type { ControlBody, StateView } from "./types";

export async function fetchState(): Promise<StateView> {
  const response = await fetch(API_STATE_PATH, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`La API respondió ${response.status}`);
  }
  return (await response.json()) as StateView;
}

export async function postControl(body: ControlBody): Promise<void> {
  const response = await fetch(CONTROLS_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`La API respondió ${response.status}`);
  }
}
