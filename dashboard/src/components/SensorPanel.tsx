import { LEVEL_DECIMALS } from "../config";
import { es } from "../i18n/es";

interface SensorPanelProps {
  reading: number | null;
}

/** Last reading of the level sensor, which can be stuck, drifting or silent. */
export function SensorPanel({ reading }: SensorPanelProps) {
  if (reading === null) {
    return <p className="muted">{es.sensorNoData}</p>;
  }
  return (
    <p className="metric">
      {es.sensorReading}: <strong>{reading.toFixed(LEVEL_DECIMALS)} {es.meters}</strong>
    </p>
  );
}
