import { useState } from "react";
import { postControl } from "../api/client";
import type { ControlAction } from "../api/types";
import { SPEED_FACTORS } from "../config";
import { es } from "../i18n/es";

interface ControlPanelProps {
  paused: boolean;
  speedFactor: number;
  onApplied: () => void;
}

/** Manual field conditions. Each button queues one condition; none of them moves a valve. */
export function ControlPanel({ paused, speedFactor, onApplied }: ControlPanelProps) {
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const send = (action: ControlAction, factor?: number): void => {
    const body = factor === undefined ? { action } : { action, factor };
    postControl(body)
      .then(() => {
        setFailed(false);
        setMessage(es.controlsApplied);
        onApplied();
      })
      .catch(() => {
        setFailed(true);
        setMessage(es.controlsFailed);
      });
  };

  return (
    <div>
      <p className="muted">{es.controlsDetail}</p>
      <div className="controls">
        <button type="button" onClick={() => send("LEAK")}>{es.controlLeak}</button>
        <button type="button" onClick={() => send("HEAVY_RAIN")}>{es.controlHeavyRain}</button>
        <button type="button" onClick={() => send("SENSOR_STUCK")}>{es.controlSensorStuck}</button>
        <button type="button" onClick={() => send("SENSOR_SILENT")}>{es.controlSensorSilent}</button>
        <button type="button" onClick={() => send("NETWORK_DOWN")}>{es.controlNetworkDown}</button>
        <button type="button" onClick={() => send("NETWORK_UP")}>{es.controlNetworkUp}</button>
        <button type="button" onClick={() => send(paused ? "RESUME" : "PAUSE")}>
          {paused ? es.controlResume : es.controlPause}
        </button>
        <label className="speed">
          {es.controlSpeed}
          <select
            value={speedFactor}
            onChange={(event) => send("SET_SPEED", Number(event.target.value))}
          >
            {SPEED_FACTORS.map((factor) => (
              <option key={factor} value={factor}>
                {factor} {es.controlSpeedOption}
              </option>
            ))}
          </select>
        </label>
      </div>
      {message !== null ? (
        <p className={failed ? "alert" : "muted"} role="status">
          {message}
        </p>
      ) : null}
    </div>
  );
}
