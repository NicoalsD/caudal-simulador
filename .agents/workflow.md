# Flujo de trabajo: ramas, commits, cuentas y PR

> Este archivo es idéntico en los 4 repositorios de CAUDAL (`caudal-backend`, `caudal-frontend`, `caudal-ia`, `caudal-simulador`). Si lo cambias, cámbialo en todos.

## 1. Cuentas permitidas

Solo estas tres cuentas trabajan en CAUDAL. Ninguna otra, aunque esté abierta en la máquina.

| Integrante | Cuenta | Rol actual | Correo para commits |
|---|---|---|---|
| Nicolas Diaz | `NicoalsD` | Frontend, UX, publicación, documentación y DevOps | correo verificado en su cuenta |
| Drako Salazar | `Drako2305` | Backend Java, base de datos, seguridad y patrones | `203891767+Drako2305@users.noreply.github.com` |
| Nicolas Mora | `nicomora70` | IA, datos simulados y simulador (se une más adelante) | `167647383+nicomora70@users.noreply.github.com` |

Antes de cada bloque de trabajo:

```bash
gh auth switch --hostname github.com --user <cuenta>
git config user.name "<Nombre del integrante>"
git config user.email "<correo del integrante>"
gh api user --jq .login          # debe mostrar la cuenta del integrante
```

Reglas:

- El trabajo de un integrante se publica solo con su cuenta. Si su cuenta no está disponible, el trabajo espera; nunca se sube con otra.
- Al rehacer una rama ajena (rebase), primero se cambia a la cuenta y a la identidad de su dueño, para que autor y committer sean la misma persona.

## 2. Ramas (Git Flow)

| Rama | Sale de | Se fusiona en | Uso |
|---|---|---|---|
| `main` | | | Versiones publicadas con etiqueta (`v0.1.0`, `v1.0.0`) |
| `develop` | `main` | `main` (por release) | Integración; rama por defecto |
| `feature/<tema>` | `develop` | `develop` | Funcionalidad nueva |
| `bugfix/<tema>` | `develop` | `develop` | Corrección de un error en desarrollo |
| `hotfix/<tema>` | `main` | `main` y `develop` | Corrección urgente de una versión publicada |
| `release/<versión>` | `develop` | `main` y `develop` | Preparar una versión |
| `docs/<tema>` | `develop` | `develop` | Solo documentación o diagramas |
| `chore/<tema>` | `develop` | `develop` | Configuración, CI, dependencias |

Los nombres van en `kebab-case` y en español o inglés corto: `feature/registro-de-lecturas`, `bugfix/zona-horaria-cierre`.

`main` y `develop` están protegidas con rulesets: no se puede hacer push directo, force-push ni borrarlas; todo entra por PR con el check `commit-lint` en verde.

## 3. Commits

Formato obligatorio, en español:

```
tipo: descripción en minúscula y en presente
```

- Máximo 72 caracteres en la primera línea, sin punto final.
- Cuerpo opcional en español, separado por una línea en blanco, para explicar el porqué.
- Tipos permitidos:

| Tipo | Cuándo |
|---|---|
| `feat` | Funcionalidad nueva (feature) |
| `fix` | Corrección de un error (bugfix), con su prueba de regresión |
| `hotfix` | Corrección urgente sobre `main` |
| `docs` | Documentación o diagramas |
| `test` | Solo pruebas |
| `refactor` | Cambio interno sin cambiar el comportamiento |
| `style` | Formato o estilos sin cambiar la lógica |
| `perf` | Rendimiento |
| `build` | Sistema de construcción o dependencias |
| `ci` | Workflows de GitHub Actions |
| `chore` | Configuración y mantenimiento |
| `revert` | Revertir un commit anterior |

Ejemplos válidos:

```
feat: agrega la cadena de validación de lecturas
fix: corrige la zona horaria del cierre del día
docs: agrega el diagrama de secuencia del login
test: cubre la detección de reutilización del refresh
```

Un commit es una unidad lógica: un documento, un diagrama, una migración, una clase o patrón, un endpoint, una regla de validación, un control de seguridad, las pruebas de una unidad, una corrección con su prueba, un refactor o un cambio de configuración. Está prohibido:

- mensajes genéricos ("update", "cambios", "wip", "arreglos");
- commits vacíos o que dividen artificialmente un cambio de una línea;
- reescribir fechas;
- **atribuir el trabajo a una IA**: ningún `Co-Authored-By` de Claude u otra IA y ninguna línea "Generated with ..." en commits, PR ni releases.

### Hook local

```bash
git config core.hooksPath .githooks
```

El hook `.githooks/commit-msg` rechaza los mensajes que no cumplen el formato y los trailers de IA. El workflow `commit-lint` aplica las mismas reglas a cada PR (título y commits).

## 4. Pull requests

1. Actualiza tu rama base: `git checkout develop && git pull`.
2. Crea tu rama, haz commits pequeños y empuja con tu cuenta.
3. Abre el PR hacia `develop` con la plantilla en español. **El título también sigue `tipo: descripción`**, porque se convierte en el asunto del merge commit.
4. Espera el check `commit-lint` (y, desde la Fase 1, build, pruebas y lint).
5. Fusiona con **merge commit** (el repositorio no permite squash ni rebase), para conservar todos los commits:

```bash
gh pr merge <número> --merge --subject "<título del PR>" --delete-branch
```

Las aprobaciones, cuando se exijan, las dan personas. Un agente nunca aprueba con la cuenta de otro integrante.

## 5. Versiones

- Al cerrar una fase: rama `release/vX.Y.Z` o PR `develop → main`, etiqueta `vX.Y.Z` y release con notas en español.
- Fase 0 → `v0.1.0`; MVP (fases 1 a 8) → `v0.9.0`; entrega → `v1.0.0`.

## 6. Seguimiento de commits

Al cerrar cada fase se registra el avance:

```bash
git rev-list --count --no-merges develop
git shortlog -sn --no-merges develop
```

El plan completo de commits por repositorio, fase e integrante está en [`docs/Plan-de-commits.md`](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Plan-de-commits.md) del backend. Meta: `caudal-backend` con 150 commits o más.

Relacionados: [AGENTS.md](../AGENTS.md) · [Roles y planeación](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Roles-y-planeacion.md)
