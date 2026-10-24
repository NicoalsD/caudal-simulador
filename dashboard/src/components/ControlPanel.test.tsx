import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { es } from "../i18n/es";
import { ControlPanel } from "./ControlPanel";

describe("ControlPanel", () => {
  afterEach(() => {
    cleanup();
  });

  it("offers field conditions and pause, but never a valve command", () => {
    render(<ControlPanel paused={false} speedFactor={1} onApplied={() => undefined} />);

    expect(screen.getByRole("button", { name: es.controlLeak })).toBeTruthy();
    expect(screen.getByRole("button", { name: es.controlPause })).toBeTruthy();
    const labels = screen.getAllByRole("button").map((button) => button.textContent ?? "");
    expect(labels.some((label) => /válvula|abrir|cerrar/i.test(label))).toBe(false);
  });

  it("shows resume while the clock is paused", () => {
    render(<ControlPanel paused speedFactor={10} onApplied={() => undefined} />);

    expect(screen.getByRole("button", { name: es.controlResume })).toBeTruthy();
  });
});
