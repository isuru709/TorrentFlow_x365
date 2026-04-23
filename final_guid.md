# FINAL GUIDE: YAML, GitOps, Kubernetes, Argo CD - Full Learning Path (Sinhala)

මෙම guide එකේ අරමුණ:

1. ඔබගේ repo එකේ YAML files සියල්ල part-by-part තේරුම් ගන්න.
2. එක් app එකක් වෙනත් Docker app එකකට adapt කරන විදිහ ඉගෙන ගන්න.
3. apps 2ක් (docker images 2ක්) එකම cluster එකේ deploy කරන pattern ඉගෙන ගන්න.
4. ඔබ මුහුණ දුන් real issues + fixes එක mental model එකක් ලෙස දැනගන්න.

---

## 1) දැනට ඔබගේ setup එක එකට වැඩ කරන විදිහ

Flow (GitOps loop):

1. ඔබ `main` branch එකට push කරනවා.
2. GitHub Actions workflow image build/push කරනවා.
3. workflow එක `k8s/overlays/prod/kustomization.yaml` හි image tag update කර commit කරනවා.
4. Argo CD ඒ commit එක detect කර sync කරනවා.
5. Kubernetes deployment rollout වෙලා app update වෙනවා.

මෙය CI + CD + GitOps chain එක complete කරන pattern එකයි.

---

## 2) Repo YAML Map (File එකෙන් File එකට අරමුණ)

1. `docker-compose.yml`
   - Local development / single-VM run සඳහා.
2. `.github/workflows/build-and-deploy.yml`
   - CI pipeline: build/push image + kustomization tag update.
3. `k8s/kustomization.yaml`
   - Top-level entrypoint (Argo CD build root path).
4. `k8s/base/kustomization.yaml`
   - Base resources bundle (namespace/deployment/service/pvc).
5. `k8s/base/namespace.yaml`
   - Namespace create කිරීම.
6. `k8s/base/deployment.yaml`
   - Pod template + container config + probes + volumes.
7. `k8s/base/service.yaml`
   - Network exposure (LoadBalancer, port mapping).
8. `k8s/base/pvc.yaml`
   - Persistent storage claim.
9. `k8s/overlays/prod/kustomization.yaml`
   - Environment-specific image/tag/labels overrides.
10. `k8s/argocd/application.yaml`
    - Argo CD app definition (repo path, sync policy, destination).

---

## 3) YAML එකක් කියවන්න correct order එක

YAML එකේ beginner-to-advanced reading order:

1. `k8s/argocd/application.yaml` -> Argo repo එකෙන් මොන path එක build කරනවද?
2. `k8s/kustomization.yaml` -> top-level resources list.
3. `k8s/overlays/prod/kustomization.yaml` -> image/tag/labels override.
4. `k8s/base/kustomization.yaml` -> base resources මොනවද?
5. `k8s/base/deployment.yaml` -> main app runtime behavior.
6. `k8s/base/service.yaml` -> app external/internal exposure.
7. `k8s/base/pvc.yaml` -> storage semantics.
8. workflow file -> image automation path.

මේ order එකෙන් බලනකොට confuse වෙන්නෙ නෑ.

---

## 4) Part-by-part: docker-compose.yml

`services.torrent-downloader`

1. `build: .`
   - local Docker image repo root Dockerfile එකෙන් build කරනවා.
2. `ports`
   - host:container mapping.
   - `8080:8080` main app.
   - torrent ports TCP/UDP expose.
3. `volumes`
   - local folders -> container paths.
   - app state persist වෙයි.
4. `environment`
   - app behavior tune කරන env vars.
5. `restart: unless-stopped`
   - crash হলে auto restart.

කවදා compose use කරන්න?

- local test, single server deployments.
- GitOps/K8s production නම් k8s manifests use කරන්න.

---

## 5) Part-by-part: GitHub Actions workflow

File: `.github/workflows/build-and-deploy.yml`

Top keys:

1. `on.push.branches: main`
   - main push වලදී run වෙනවා.
2. `permissions.contents: write`
   - manifest update commit/push කිරීමට අවශ්‍ය.
3. `concurrency`
   - parallel deploy runs clash වීම වැළැක්වීම.

Job flow:

1. `Validate required secrets`
   - `DOCR_TOKEN` must exist.
2. `Set image variables`
   - registry/repo defaults fallback + sanitize.
3. `Build and push image`
   - DOCR වෙත tag push.
4. `Update kustomization image reference`
   - `newName` සහ `newTag` rewrite.
5. `Commit manifest update`
   - GitOps trigger commit.

Learning point:

- workflow fail point 80% secrets/formatting issues.
- image tag = commit SHA pattern deploy tracking සඳහා super useful.

---

## 6) Part-by-part: Kustomize files

### 6.1 `k8s/kustomization.yaml`

- top-level bundle.
- Argo `path: k8s` කරනකොට මේ file entrypoint.

### 6.2 `k8s/base/kustomization.yaml`

- base resources list.
- reusable, environment-neutral.

### 6.3 `k8s/overlays/prod/kustomization.yaml`

- environment-specific settings.
- `images` block CI pipeline update කරන point එක.
- `labels` block prod-specific metadata add කරනවා.

Kustomize mental model:

- base = default blueprint
- overlay = environment patch/override

---

## 7) Part-by-part: Kubernetes resources

### 7.1 Namespace (`k8s/base/namespace.yaml`)

- logical isolation boundary.
- resources එකට clean scope දෙනවා.

### 7.2 Deployment (`k8s/base/deployment.yaml`)

Important fields:

1. `replicas: 1`
   - one pod instance.
2. `strategy.type: Recreate`
   - RWO PVC app සඳහා safe update.
3. `containers[].image`
   - placeholder; overlay replaces tag/name.
4. `ports.containerPort: 8080`
   - app listens internally.
5. `env`
   - app runtime settings.
6. `readinessProbe/livenessProbe`
   - health checks.
7. `resources.requests/limits`
   - CPU/Mem boundaries.
8. `volumeMounts` + `volumes.persistentVolumeClaim`
   - storage attach.

### 7.3 Service (`k8s/base/service.yaml`)

1. `type: LoadBalancer`
   - DigitalOcean public LB IP create කරයි.
2. `port: 80 -> targetPort: http(8080)`
   - external 80, internal container 8080.

### 7.4 PVC (`k8s/base/pvc.yaml`)

1. `ReadWriteOnce`
   - එක node එකකට exclusive attach.
2. `storageClassName: do-block-storage`
   - DO block volume class.
3. `storage: 30Gi`
   - requested size.

---

## 8) Part-by-part: Argo CD Application

File: `k8s/argocd/application.yaml`

1. `source.repoURL/targetRevision/path`
   - Git source details.
2. `destination.namespace`
   - where resources apply වෙයි.
3. `syncPolicy.automated`
   - auto deploy enabled.
4. `prune/selfHeal`
   - drift correction + stale cleanup.
5. `syncOptions.CreateNamespace=true`
   - namespace create assist.

---

## 9) Single app -> වෙනත් Docker app එකකට adapt කරන 12-step checklist

Suppose app name = `my-api`, image = `registry.digitalocean.com/my-reg/my-api`, container port = `5000`.

1. `k8s/base/deployment.yaml`
   - `metadata.name`, labels change.
   - `containers[].name`, `image` placeholder change.
   - `containerPort` change (5000).
   - probes path/port update.
2. `k8s/base/service.yaml`
   - service name/selector change.
   - targetPort mapping update.
3. `k8s/base/pvc.yaml`
   - app storage need නැත්තම් remove.
4. `k8s/base/kustomization.yaml`
   - resource list align.
5. `k8s/base/namespace.yaml`
   - namespace rename (optional).
6. `k8s/overlays/prod/kustomization.yaml`
   - `images.name/newName/newTag` update.
7. `k8s/argocd/application.yaml`
   - app name/namespace/path review.
8. `.github/workflows/build-and-deploy.yml`
   - defaults `DEFAULT_DOCR_REGISTRY`, `DEFAULT_DOCR_REPOSITORY` update.
9. GitHub secrets verify (`DOCR_TOKEN`).
10. Argo app sync policy/destination verify.
11. Push change -> Actions green check.
12. Argo Health=Healthy, Sync=Synced verify.

---

## 10) Apps 2ක් (Docker images 2ක්) තිබුණොත් මොකද කරන්න

Best practice: apps දෙක separate deployments/services ලෙස හදන්න.

### Option A: same repo, same cluster, same Argo app (simple)

Recommended folder pattern:

```text
k8s/
  apps/
    app1/
      base/
        deployment.yaml
        service.yaml
        kustomization.yaml
    app2/
      base/
        deployment.yaml
        service.yaml
        kustomization.yaml
  overlays/
    prod/
      kustomization.yaml
```

`k8s/overlays/prod/kustomization.yaml` resources example:

```yaml
resources:
  - ../../apps/app1/base
  - ../../apps/app2/base
```

`images` block example:

```yaml
images:
  - name: app1
    newName: registry.digitalocean.com/xxx/app1
    newTag: latest
  - name: app2
    newName: registry.digitalocean.com/xxx/app2
    newTag: latest
```

Workflow adaptation:

1. either one workflow with matrix build for app1/app2,
2. or two workflow files (one per app),
3. then overlay image tags දෙකම update කර commit කරන්න.

### Option B: same repo, separate Argo applications (cleaner at scale)

- `argocd/app1-application.yaml`
- `argocd/app2-application.yaml`

Benefits:

- app-level independent sync/rollback.
- one app fail වෙලා වෙන app unaffected.

### Option C: one pod තුළ containers 2ක් (sidecar pattern)

Use only when tightly coupled (e.g., log sidecar, proxy sidecar).
Unrelated apps සඳහා avoid කරන්න.

---

## 11) Change matrix: මොන field මොකට වෙනස් කරන්නද

1. App name change -> deployment/service/labels/selectors/namespace.
2. Port change -> deployment containerPort + service targetPort.
3. Image change -> overlay images newName/newTag.
4. Storage remove -> pvc.yaml remove + deployment volumeMounts/volumes remove.
5. Storage shared requirement -> access mode reconsider (`RWO` vs `RWX`).
6. Scaling >1 with RWO -> architecture redesign or strategy/storage change required.

---

## 12) ඔබ මුහුණ දුන් Issues -> transferable lessons

1. `kustomization.yaml is empty`
   - Lesson: overlay file always valid + non-empty रखें.
2. Argo security path restriction
   - Lesson: Argo source path සහ kustomize relative paths align කරන්න.
3. `commonLabels` deprecation
   - Lesson: current schema (`labels`) use කරන්න.
4. namespace missing
   - Lesson: namespace resource explicit include කරන්න.
5. workflow syntax/sed errors
   - Lesson: brittle text replace avoid; safer rewrite logic use කරන්න.
6. image pull auth mismatch
   - Lesson: secret name + serviceaccount mapping check first.
7. multi-attach PVC
   - Lesson: single replica + RWO = `Recreate` strategy.

---

## 13) VPC console access (ඔබ අහපු practical point)

`VPC` itself shell එකක් නොවේ. Access points:

1. Nginx Droplet console
   - DO Dashboard -> Droplets -> Access -> Launch Console.
2. App pod console
   - `kubectl exec -it -n torrent-downloader <POD_NAME> -- /bin/sh`
3. Logs
   - `kubectl logs -f deploy/torrent-downloader -n torrent-downloader`

Managed node console (advanced) possible, but pod-level debug best practice.

---

## 14) Validation playbook (adapt any situation)

Before push:

1. `kubectl kustomize ./k8s` local render check.
2. YAML syntax lint/no errors.
3. image path + secret strategy verify.

After push:

1. GitHub Actions green.
2. Argo Synced + Healthy.
3. Pod Ready + logs clean.
4. Service endpoint reachable.

If fail:

1. first check: `kubectl get events -n <ns> --sort-by=.metadata.creationTimestamp`
2. second: `kubectl describe pod ...`
3. third: Argo app conditions + sync error details.

---

## 15) Final mental model

ඔබ මතක තබාගන්න core principle එක:

1. Git = source of truth.
2. CI builds image + writes desired image tag back to Git.
3. Argo CD reconciles Git desired state -> cluster real state.
4. Kubernetes actually runs workload.

මේ model එක තේරුම් ගත්තොත්, app එක වෙනස් උනත්, apps 2ක් උනත්, cloud එක වෙනස් උනත් adaptation කරන්න පුළුවන්.
