import { DROPPED_EVENT, type SimulationEventView } from "../api/types";
import { MAX_EVENTS_SHOWN, PERCENT } from "../config";

/** Adds an event at the end and keeps only the newest ones that fit on the screen. */
export function appendEvent(
  events: readonly SimulationEventView[],
  next: SimulationEventView,
): SimulationEventView[] {
  const merged = [...events, next];
  return merged.length > MAX_EVENTS_SHOWN ? merged.slice(merged.length - MAX_EVENTS_SHOWN) : merged;
}

/** Share of the painted gauge that the level covers, from 0 to 100. Levels out of range are clamped. */
export function tankPercent(level: number, gaugeMin: number, gaugeMax: number): number {
  const clamped = Math.min(Math.max(level, gaugeMin), gaugeMax);
  return ((clamped - gaugeMin) / (gaugeMax - gaugeMin)) * PERCENT;
}

/** Reads one SSE frame. Returns null when the data is not a valid event (it is then ignored). */
export function parseEventFrame(id: string, kind: string, data: string): SimulationEventView | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) {
    return null;
  }
  if (kind === DROPPED_EVENT) {
    const dropped = "dropped" in parsed ? String(parsed.dropped) : "0";
    return { id, occurred_at: null, kind, subject_id: "", detail: dropped };
  }
  const record = parsed as Record<string, unknown>;
  const { occurred_at: occurredAt, subject_id: subjectId, detail } = record;
  if (typeof subjectId !== "string" || typeof detail !== "string") {
    return null;
  }
  return {
    id,
    occurred_at: typeof occurredAt === "string" ? occurredAt : null,
    kind,
    subject_id: subjectId,
    detail,
  };
}
