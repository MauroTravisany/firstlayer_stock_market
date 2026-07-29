# Dataform operational notes

## Problema recurrente: GitHub actualizado, Dataform no refleja cambios

Sintoma:
- El commit existe en GitHub.
- El release de Dataform sigue compilando sin tablas/columnas nuevas.
- BigQuery falla con tablas faltantes o columnas antiguas.

Causa usual:
- Dataform usa su repositorio/workspace interno.
- El workflow production puede apuntar a `main`, mientras el trabajo local se sube a `master`.
- Aunque se haga push a GitHub, el `releaseCompilationResult` puede seguir apuntando a una compilacion anterior.

Chequeos rapidos:
- Listar repo Dataform:
  `GET https://dataform.googleapis.com/v1beta1/projects/stocks-437902/locations/us-east1/repositories`
- Revisar release:
  `GET https://dataform.googleapis.com/v1beta1/projects/stocks-437902/locations/us-east1/repositories/portfolio-valuation/releaseConfigs`
- Revisar workflow:
  `GET https://dataform.googleapis.com/v1beta1/projects/stocks-437902/locations/us-east1/repositories/portfolio-valuation/workflowConfigs`
- Crear compilation result desde `main` y revisar `resolvedGitCommitSha`.
- Consultar acciones compiladas con:
  `GET https://dataform.googleapis.com/v1beta1/{compilationResult}:query`
- Buscar en esa respuesta la tabla/columna esperada.

Solucion pragmatica:
1. Subir cambios a `master`.
2. Si Dataform production usa `gitCommitish: main`, subir el mismo commit a `main`.
3. Crear compilation result desde `main`.
4. Si la compilacion no trae la tabla nueva, escribir los SQLX al workspace `main-workspace` con `workspaces.writeFile`.
5. Commit del workspace con `workspaces.commit`.
6. Crear compilation result nuevo.
7. Crear workflow invocation con ese compilation result o esperar el scheduler si no urge.

Notas de PowerShell:
- En URLs con `:query`, usar `${compilation}:query`; si se usa `$compilation:query`, PowerShell interpreta mal la variable.
- En URLs con query string, usar `${release}?updateMask=...`; si se usa `$release?`, PowerShell corta la variable.
- Para JSON en `curl.exe`, preferir archivo temporal con `--data-binary "@archivo.json"` para evitar problemas de comillas.

Regla operativa:
- Despues de cambios Dataform, no asumir que quedo en produccion por el push.
- Confirmar que el compilation result contiene la tabla/columna nueva antes de forzar workflow o scheduler.
