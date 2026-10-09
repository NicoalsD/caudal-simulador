import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { es } from "../i18n/es";
import { SimulatedBanner } from "./SimulatedBanner";

describe("SimulatedBanner", () => {
  afterEach(() => {
    cleanup();
  });

  it("always shows the simulated-data notice in Spanish", () => {
    render(<SimulatedBanner />);

    expect(screen.getByRole("note", { name: "Datos simulados" })).toBeTruthy();
    expect(screen.getByText(es.simulatedBannerDetail)).toBeTruthy();
  });
});
