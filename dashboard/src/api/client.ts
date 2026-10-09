import { API_STATE_PATH } from "../config";
import type { StateView } from "./types";

export async function fetchState(): Promise<StateView> {
  const response = await fetch(API_STATE_PATH, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`La API respondió ${response.status}`);
  }
  return (await response.json()) as StateView;
}
