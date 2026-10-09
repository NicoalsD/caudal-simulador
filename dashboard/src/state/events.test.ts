import { describe, expect, it } from "vitest";
import type { SimulationEventView } from "../api/types";
import { MAX_EVENTS_SHOWN } from "../config";
import { appendEvent, parseEventFrame, tankPercent } from "./events";

const SAMPLE_ID = "7";
const OCCURRED_AT = "2026-01-01T06:00:00Z";
const VALVE_ID = "0190f3a2-7000-7000-8000-000000000001";
const HALF_PERCENT = 50;
const FULL_PERCENT = 100;
const GAUGE_MIN = 0;
const GAUGE_MAX = 5;

function eventNumbered(index: number): SimulationEventView {
  return { id: String(index), occurred_at: null, kind: "VALVE_STATE_CHANGED", subject_id: "", detail: "" };
}

describe("appendEvent", () => {
  it("keeps only the newest events that fit on the screen", () => {
    let events: SimulationEventView[] = [];
    for (let index = 0; index < MAX_EVENTS_SHOWN + 1; index += 1) {
      events = appendEvent(events, eventNumbered(index));
    }

    expect(events).toHaveLength(MAX_EVENTS_SHOWN);
    expect(events[0]?.id).toBe("1");
    expect(events.at(-1)?.id).toBe(String(MAX_EVENTS_SHOWN));
  });
});

describe("tankPercent", () => {
  it("maps the gauge range to 0 to 100 and clamps levels outside it", () => {
    expect(tankPercent(2.5, GAUGE_MIN, GAUGE_MAX)).toBe(HALF_PERCENT);
    expect(tankPercent(GAUGE_MAX + 1, GAUGE_MIN, GAUGE_MAX)).toBe(FULL_PERCENT);
    expect(tankPercent(-1, GAUGE_MIN, GAUGE_MAX)).toBe(0);
  });
});

describe("parseEventFrame", () => {
  it("reads a valve event with its time and detail", () => {
    const data = JSON.stringify({
      occurred_at: OCCURRED_AT,
      kind: "VALVE_STATE_CHANGED",
      subject_id: VALVE_ID,
      detail: "OPEN",
    });

    expect(parseEventFrame(SAMPLE_ID, "VALVE_STATE_CHANGED", data)).toEqual({
      id: SAMPLE_ID,
      occurred_at: OCCURRED_AT,
      kind: "VALVE_STATE_CHANGED",
      subject_id: VALVE_ID,
      detail: "OPEN",
    });
  });

  it("reads the dropped-events frame as its count", () => {
    expect(parseEventFrame(SAMPLE_ID, "DROPPED", '{"dropped":3}')?.detail).toBe("3");
  });

  it("ignores data that is not an event", () => {
    expect(parseEventFrame(SAMPLE_ID, "VALVE_STATE_CHANGED", "no es json")).toBeNull();
    expect(parseEventFrame(SAMPLE_ID, "VALVE_STATE_CHANGED", '{"detail": 3}')).toBeNull();
  });
});
