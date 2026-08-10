# WP-01 - Gobierno de ramas, CI, deploy y rollback

Este runbook describe configuraciones manuales. Escribirlas aqui no demuestra que esten aplicadas. Cada paso debe verificarse en GitHub y adjuntarse como evidencia antes de reactivar `Deploy Cloud Run service`.

## 1. Flujo versionado

```text
build immutable images
  -> tests and scans in CI
  -> CI gate for the exact git SHA
  -> production environment approval
  -> publish image once and resolve immutable digest
  -> deploy revision with zero traffic
  -> read-only readiness smoke
  -> promote traffic
  -> post-promotion smoke
  -> rollback traffic on failure
```

`ci.yml` es el unico workflow que responde a `pull_request`, `push` y `workflow_dispatch`. `deploy.yml` no acepta ninguno de esos eventos: solo recibe `workflow_run` de `CI`, con resultado `success`, evento original `push`, rama `main` y repositorio de origen identico.

Las imagenes se construyen dentro del CI y se guardan como artefactos con `git_sha`, image ID y checksum. Deploy descarga artefactos del run exacto, verifica otra vez SHA/checksum, publica cada imagen una vez y usa exclusivamente una referencia `@sha256:`. No usa tags mutables para actualizar Cloud Run.

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
CI / CI gate
CI / Python and repository invariants
CI / Workflow syntax and contracts
CI / Dataform compile
CI / Dashboard build
CI / Terraform validate
CI / Dependency review
```

`CI / CI gate` depende tambien de las ocho variantes `Build immutable image (...)`; por eso un fallo de build, test, scanner o compilacion impide que el gate termine en success.

No habilitar bypass para administradores o aplicaciones salvo una decision separada y auditada. Guardar captura/export del ruleset y fecha de aplicacion en la evidencia de WP-01.

## 4. Configurar el GitHub Environment production

En `Settings -> Environments`:

1. Crear o abrir el environment `production`.
2. En `Deployment protection rules`, agregar `required reviewers` y seleccionar al owner operacional autorizado.
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

## 7. Smoke test no destructivo

`scripts/ci/smoke_test_services.py` solo ejecuta `gcloud run revisions describe`. Tiene timeout entre 1 y 120 segundos, exige una imagen `@sha256:`, valida `Ready=True`, confirma `observedGeneration` y compara el digest exacto. No llama URLs funcionales, no crea ordenes, no escribe tablas, no ejecuta estrategias y no envia alertas.

Una revision nueva se crea con `--no-traffic`. Si el smoke previo falla, la promocion se detiene y el trafico sigue en la revision anterior.

## 8. Rollback

Antes de crear cada revision, deploy registra:

```text
service
previous_revision
staged_revision
immutable_image_digest
git_sha
environment
```

Si falla el smoke posterior a la promocion, el trap `rollback` recorre `promoted-revisions.tsv` en orden inverso y ejecuta:

```bash
gcloud run services update-traffic SERVICE \
  --project PROJECT \
  --region us-east1 \
  --platform managed \
  --to-revisions "previous_revision=100" \
  --quiet
```

Despues de un rollback autorizado se debe:

1. verificar `status.traffic` y `status.latestReadyRevisionName` por lectura;
2. ejecutar el smoke read-only contra `previous_revision` y su digest conocido;
3. conservar `release-manifest.ndjson`, `staged-revisions.tsv`, `promoted-revisions.tsv` y logs del run;
4. abrir incidente con SHA, digest fallido, revision restaurada, timestamps y motivo;
5. mantener bloqueada cualquier promocion nueva hasta cerrar el incidente.

Este PR prueba el algoritmo con fixtures y contratos. No ejecuta un rollback real ni modifica Cloud Run.

## 9. Workload Identity Federation

La migracion desde `GCP_SA_KEY` hacia Workload Identity Federation pertenece a WP-10. Mientras tanto, el secret solo aparece en workflows de deploy y nunca en `ci.yml`. Esta limitacion debe permanecer visible como riesgo residual.
