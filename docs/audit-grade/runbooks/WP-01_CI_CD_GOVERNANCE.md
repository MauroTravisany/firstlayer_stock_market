# WP-01 - Gobierno de ramas, CI, deploy y rollback

Este runbook describe configuraciones manuales. Escribirlas aqui no demuestra que esten aplicadas. Cada paso debe verificarse en GitHub y adjuntarse como evidencia antes de reactivar `Deploy Cloud Run service`.

## 1. Flujo versionado

```text
workflow syntax + invariants + secrets + unit tests + dependency gates
  -> security preflight gate
  -> build immutable images + Dataform/dashboard/Terraform validation
  -> CI gate for the exact git SHA
  -> production environment approval
  -> publish images once and resolve immutable digests
  -> sync the exact approved dataform/ tree and compile it
  -> deploy revision with zero traffic
  -> metadata and functional /readyz smoke
  -> promote traffic
  -> functional /healthz smoke
  -> promote the validated Dataform compilation
  -> exact traffic and Dataform release rollback on failure
```

`ci.yml` es el unico workflow que responde a `pull_request`, `push` y `workflow_dispatch`. `deploy.yml` no acepta ninguno de esos eventos: solo recibe `workflow_run` de `CI`, con resultado `success`, evento original `push`, rama `main` y repositorio de origen identico.

Las imagenes se construyen dentro del CI y se guardan como artefactos con `git_sha`, image ID y checksum. Deploy descarga artefactos del run exacto, verifica otra vez SHA/checksum, compara el image ID real inmediatamente despues de `docker load`, publica cada imagen una vez y usa exclusivamente una referencia `@sha256:`. No usa tags mutables para actualizar Cloud Run.

## 2. Cambiar la default branch a main

Pendiente manual:

1. Abrir `Settings -> General -> Default branch`.
2. Seleccionar `main`, confirmar `Update` y aceptar la advertencia.
3. Verificar en `Settings -> Branches` que `main` aparece como default branch.
4. Verificar por CLI read-only:

```bash
gh repo view MauroTravisany/firstlayer_stock_market --json defaultBranchRef --jq .defaultBranchRef.name
```

El resultado requerido es `main`.

## 3. Proteger main

En `Settings -> Rules -> Rulesets`, crear un ruleset activo llamado `protect-main` con target `main`. Configurar exactamente:

- `Require a pull request before merging`: habilitado.
- `Require approvals`: `1` como minimo.
- `Require review from Code Owners`: habilitado.
- `Dismiss stale pull request approvals when new commits are pushed`: habilitado.
- `Require conversation resolution before merging`: habilitado.
- `Require status checks to pass before merging`: habilitado.
- `Require branches to be up to date before merging`: habilitado.
- `Block force pushes`: habilitado.
- `Restrict deletions`: habilitado.

Required checks propuestos:

```text
CI / Workflow syntax and immutable actions
CI / Python, repository invariants and secrets
CI / Critical npm audit gate
CI / Security preflight gate
CI / Dataform compile
CI / Dashboard build
CI / Terraform validate
CI / Dependency review
CI / CI gate
```

`CI / CI gate` depende tambien de las ocho variantes `Build immutable image (...)`; por eso un fallo de build, test, scanner o compilacion impide que el gate termine en success.

No habilitar bypass para administradores o aplicaciones salvo una decision separada y auditada. Guardar captura/export del ruleset y fecha de aplicacion en la evidencia de WP-01.

## 4. Configurar el GitHub Environment production

En `Settings -> Environments`:

1. Crear o abrir el environment `production`.
2. En `Deployment protection rules`, agregar `required reviewers` y seleccionar un reviewer independiente que no sea el autor del cambio.
3. Habilitar `Prevent self-review` cuando el plan de GitHub lo permita.
4. En `Deployment branches and tags`, elegir `Selected branches and tags` y permitir solo `main`.
5. Limitar acceso a `GCP_SA_KEY` y `GCP_PROJECT_ID` al environment cuando GitHub permita environment secrets.
6. No agregar secrets a jobs de CI.

La aprobacion corresponde al job `Approve, deploy, smoke and promote`. El job no comienza, no autentica contra GCP y no publica imagenes hasta que el environment aprueba ese run y ese SHA.

## 5. Reconciliar master

No eliminar ni modificar la rama remota durante WP-01. Procedimiento posterior con aprobacion del owner:

1. Comparar historia:

```bash
git fetch origin main master
git log --left-right --cherry-pick --oneline origin/main...origin/master
```

2. Si existen commits unicos requeridos, migrarlos mediante PR hacia `main`; nunca fusionar `master` directamente sin CI.
3. Crear una referencia de archivo, por ejemplo `archive/master-pre-main-YYYYMMDD`, y verificar su SHA remoto.
4. Bloquear `master` contra push/force-push mientras se conserva.
5. Eliminarla solo mediante una decision manual posterior, cuando `main` sea default y no queden consumidores.

Ningun workflow productivo versionado contiene `master` como trigger.

## 6. Mantener deploy deshabilitado

Estado requerido durante implementación y revision: `disabled_manually`.

Verificacion read-only:

```bash
gh api repos/MauroTravisany/firstlayer_stock_market/actions/workflows/deploy.yml --jq .state
```

No ejecutar `gh workflow enable`, `workflow_dispatch` ni llamadas equivalentes durante el PR. Reactivar solo despues de:

1. fusionar WP-01 mediante PR protegida;
2. confirmar todos los required checks sobre el commit fusionado;
3. verificar default branch y ruleset de `main`;
4. verificar required reviewers del environment `production`;
5. obtener aprobacion humana explicita para reactivar;
6. registrar la evidencia y el SHA antes de `gh workflow enable deploy.yml`.

La reactivacion no forma parte de WP-01.

## 7. Transicion del workflow de dashboard

Antes de retirar cualquier workflow legacy de GitHub Pages:

1. identificar por API el ID, nombre, path y estado de todos los workflows que publiquen Pages;
2. comprobar que `deploy-dashboard.yml` fusionado usa el SHA actual de `main`, que el CI de ese SHA fue exitoso y que repite la comprobacion inmediatamente antes de `actions/deploy-pages`;
3. ejecutar una publicacion controlada y conservar run ID, SHA y URL;
4. deshabilitar el workflow legacy solo despues de verificar la publicacion nueva;
5. registrar la lectura final que demuestre que queda un unico camino autorizado.

Esta transicion es manual y permanece pendiente durante el PR.

## 8. Smoke test no destructivo

`scripts/ci/smoke_test_services.py` aplica dos capas. Primero ejecuta `gcloud run revisions describe`, exige una imagen `@sha256:`, valida `Ready=True`, confirma `observedGeneration` y compara el digest exacto. Luego obtiene un identity token con audience explicita y ejecuta solo `GET /readyz` sobre la revision sin trafico y `GET /healthz` despues de promoverla.

Cada respuesta debe incluir `status`, `service`, `git_sha`, `version`, `image_digest`, `operation=readiness_probe` y `mutation_performed=false`. Tiene timeout, limita el tamano de respuesta y falla ante HTTP distinto de 200, JSON malformado, SHA/digest incorrecto o cualquier indicio de orden, estrategia, escritura BigQuery, alerta o mutacion de recursos. Los handlers se ejecutan antes de cargar configuracion de negocio.

## 9. Rollback exacto

Antes de crear revisiones, `cloud_run_traffic.py` registra por servicio `spec.traffic`, `status.traffic`, revisiones, porcentajes, tags, `latestReadyRevision` y `latestCreatedRevision`.

Ante un fallo, restaura en orden inverso el reparto anterior con `--to-revisions`, limpia los tags nuevos y repone todos los tags previos. No usa `latestReadyRevision` como sustituto de la revision activa. Si el estado ya coincide, el rollback es idempotente y no ejecuta cambios. Un fallo parcial se informa como `ROLLBACK_INCOMPLETE` y mantiene el workflow fallando.

La retencion del artifact es parte del gate: si las promociones terminaron pero `actions/upload-artifact` falla, el paso `failure()` posterior restaura el release Dataform y los mapas de trafico. No se acepta una promocion activa sin evidencia descargable.

## 10. Promocion y rollback Dataform

Despues del approval, deploy vuelve a verificar que el SHA aprobado siga siendo el `main` remoto actual. Antes de mover la rama Dataform exige que el release no tenga una programacion automatica activa. Crea un commit de snapshot cuyo arbol es exactamente `APPROVED_SHA:dataform`, lo publica en `dataform-production` y verifica el SHA remoto.

La compilacion se crea desde el release `production`; debe resolver al commit de snapshot exacto y contener cero `compilationErrors`. El release no cambia hasta que las ocho revisiones Cloud Run superan smoke y promocion. Entonces se actualiza solo `releaseCompilationResult` y se genera `dataform-promotion-evidence.json` con el SHA Git, tree SHA, snapshot commit, compilation ID, release anterior, release nuevo y metadata de rollback.

Si falla cualquier paso posterior, se restaura el `releaseCompilationResult` anterior y se verifica la respuesta. La rama puede conservar el commit auditado, pero ningun workflow lo ejecuta mientras el release apunte a la compilacion anterior.

Despues de un rollback autorizado se debe:

1. comparar semanticamente `spec.traffic` y `status.traffic` con el snapshot;
2. verificar el `releaseCompilationResult` Dataform restaurado;
3. ejecutar los probes contra las revisiones nuevamente activas;
4. conservar todos los artifacts y logs del run;
5. abrir incidente con SHA, digest, revision, compilation ID, timestamps y motivo;
6. mantener bloqueada cualquier promocion nueva hasta cerrar el incidente.

Este PR prueba los algoritmos con fixtures y contratos. No ejecuta rollback live ni modifica GCP.

## 11. Dependencias y supply chain

Todas las entradas `uses:` deben estar fijadas a un commit SHA completo. Las acciones Docker, incluido actionlint, deben usar `@sha256:<digest>`. `verify_action_pinning.py` y los workflow contract tests bloquean tags mutables.

CI ejecuta audits separados para `dashboard/` y `dataform/`. El JSON se valida con `npm_audit_gate.py`; cualquier finding critical no autorizado falla. `.github/npm-audit-allowlist.json` no acepta excepciones globales: cada registro debe identificar GHSA/CVE, paquete, version exacta, superficie, razon, owner, issue y fecha de expiracion. Un cambio de paquete/version, registro incompleto o fecha vencida falla cerrado.

Para renovar una excepcion:

1. confirmar que no existe una actualizacion compatible;
2. abrir o actualizar el issue de remediacion;
3. limitar la entrada al advisory, paquete y version exactos;
4. asignar owner y expiracion corta;
5. obtener revision independiente mediante PR;
6. nunca reducir el umbral ni usar `--audit-level` como sustituto del gate.

Dependabot debe conservar entradas para Actions, npm de dashboard/Dataform, Terraform y pip en `/`.

## 12. Workload Identity Federation

La migracion desde `GCP_SA_KEY` hacia Workload Identity Federation pertenece a WP-10. Mientras tanto, el secret solo aparece en workflows de deploy y nunca en `ci.yml`. Esta limitacion debe permanecer visible como riesgo residual.
