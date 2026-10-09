import { es } from "../i18n/es";

/** The "Datos simulados" notice. It is always on screen: no page shows simulated data unlabeled. */
export function SimulatedBanner() {
  return (
    <div className="banner" role="note" aria-label={es.simulatedBanner}>
      <strong>{es.simulatedBanner}</strong>
      <span>{es.simulatedBannerDetail}</span>
    </div>
  );
}
