# CLAUDE.md

Este archivo guía a Claude Code en este repositorio. Las reglas del proyecto están en `AGENTS.md`, que es la fuente única:

@AGENTS.md

## Notas específicas para Claude Code

- **Idioma:** código en inglés; documentación, commits y PR en español.
- **Commits:** `tipo: descripción` en español. **Nunca** agregues `Co-Authored-By` de Claude ni "Generated with Claude Code"; el hook lo rechaza.
- **Cuentas:** el dueño de este repo es `nicomora70`. Antes de commitear, cambia a la cuenta del integrante dueño de la tarea y verifica con `gh api user --jq .login`. Si su cuenta no está disponible, detente y pregunta.
- **Especificación:** antes de implementar, lee los documentos canónicos del backend enlazados en la sección 1 de `AGENTS.md`.
- **Subagentes:** se puede delegar a Claude Haiku o a OpenCode Go, pero solo Claude hace los commits después de revisar el diff.
