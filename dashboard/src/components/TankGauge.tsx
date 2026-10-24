import { LEVEL_DECIMALS } from "../config";
import { es } from "../i18n/es";
import { tankPercent } from "../state/events";

interface TankGaugeProps {
  level: number | null;
  gaugeMin: number | null;
  gaugeMax: number | null;
}

/** Level of the simulated tank against the painted gauge of the aqueduct. */
export function TankGauge({ level, gaugeMin, gaugeMax }: TankGaugeProps) {
  if (level === null) {
    return <p className="muted">{es.tankNoData}</p>;
  }
  const hasRule = gaugeMin !== null && gaugeMax !== null && gaugeMin < gaugeMax;
  const width = hasRule ? tankPercent(level, gaugeMin, gaugeMax) : 0;
  return (
    <div>
      <p className="metric">
        {es.tankLevel}: <strong>{level.toFixed(LEVEL_DECIMALS)} {es.meters}</strong>
      </p>
      {hasRule ? (
        <div
          className="gauge"
          role="meter"
          aria-label={es.tankLevel}
          aria-valuemin={gaugeMin}
          aria-valuemax={gaugeMax}
          aria-valuenow={level}
        >
          <div className="gauge-fill" style={{ width: `${width}%` }} />
        </div>
      ) : null}
    </div>
  );
}
