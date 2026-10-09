// Texts for the person using the dashboard, in Spanish. Codes from the API map to these labels.

export const es = {
  title: "Tablero del simulador CAUDAL",
  simulatedBanner: "Datos simulados",
  simulatedBannerDetail:
    "Ningún dato de este tablero proviene del acueducto real. Todo es generado por el simulador.",
  tankTitle: "Nivel del tanque",
  tankLevel: "Nivel real simulado",
  tankNoData: "Sin datos del tanque todavía.",
  valvesTitle: "Válvulas",
  valvesNone: "No hay válvulas en la simulación.",
  sensorTitle: "Sensor de nivel",
  sensorReading: "Lectura del sensor",
  sensorNoData: "El sensor todavía no reporta.",
  eventsTitle: "Eventos en vivo",
  eventsNone: "Todavía no hay eventos.",
  eventsDropped: "Se perdieron eventos porque el tablero iba atrasado:",
  connectionLive: "En vivo",
  connectionOffline: "Sin conexión con la API del simulador",
  stateError: "No se pudo leer el estado del simulador. Se volverá a intentar.",
  scenario: "Escenario",
  updatedAt: "Última actualización (simulada)",
  meters: "m",
  valveStatus: {
    CLOSED: "Cerrada",
    OPENING: "Abriendo",
    OPEN: "Abierta",
    CLOSING: "Cerrando",
    FAULT: "Falla",
  } as Record<string, string>,
  eventKind: {
    VALVE_STATE_CHANGED: "Cambio de válvula",
    COMMAND_DELIVERED: "Comando entregado",
    COMMAND_CONFIRMED: "Comando confirmado",
    DROPPED: "Eventos perdidos",
  } as Record<string, string>,
};
