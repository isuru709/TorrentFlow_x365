# DigitalOcean Web Dashboard + GitHub UI + Argo CD UI (Sinhala Guide)

මෙම guide එක CLI commands නොමැතිව, Web dashboards හරහා setup කරන පියවර-පියවර ක්‍රමයයි.

ඉලක්කය:

- ඔබ main branch එකට push කරන හැම වෙලාවෙම Docker image auto rebuild වෙන්න
- image tag auto update වෙන්න
- Argo CD මගින් Kubernetes cluster එක auto sync වෙලා app එක update වෙන්න

---

## 1) Overall flow එක (සරල map එක)

1. ඔබ GitHub වෙත code push කරනවා
2. GitHub Actions workflow run වෙලා image එක DO Container Registry වෙත push කරනවා
3. workflow එක repo එකේ `k8s/overlays/prod/kustomization.yaml` update කර commit කරනවා
4. Argo CD එම change එක detect කර cluster එකට auto sync කරනවා
5. Kubernetes rolling update එකෙන් new pods run වෙනවා

---

## 2) DigitalOcean Dashboard එකෙන් Container Registry create කරන්න

1. DigitalOcean dashboard login කරන්න
2. වම් menu එකෙන් Container Registry තෝරන්න
3. Create Registry click කරන්න
4. Registry name ලෙස `torrentflow-registry` දාන්න
5. Create button click කරන්න

Note:

- ඔබගේ workflow එකේ image path එක registry name එකට match විය යුතුයි

---

## 3) DigitalOcean Dashboard එකෙන් Kubernetes Cluster + Nodes create කරන්න

1. වම් menu එකෙන් Kubernetes තෝරන්න
2. Create Cluster click කරන්න
3. Region තෝරන්න (latency අඩු region එක)
4. Kubernetes version stable/latest එකක් තෝරන්න
5. Node Pool configuration:
   - Plan: production load එකට ගැළපෙන size එක
   - Node count: අවම වශයෙන් 2 (high availability learning සඳහා හොඳයි)
6. Cluster name ලෙස `torrentflow-cluster` දාන්න
7. Create Cluster click කරන්න

Nodes register/ready check (Dashboard):

1. cluster details page එකට යන්න
2. Nodes tab එක open කරන්න
3. සියලු nodes Running/Healthy status තියෙනවාද බලන්න

---

## 4) Registry එක Cluster එකට connect කරන්න (Image pull සඳහා)

1. Kubernetes -> ඔබගේ cluster -> Settings (හෝ Integrations) tab වෙත යන්න
2. Container Registry integration option එකෙන් `torrentflow-registry` connect කරන්න
3. Namespace selection ඇත්නම් `torrent-downloader` namespace එක තෝරන්න
4. Save/Connect click කරන්න

වැදගත්:

- DO registry integration connect කළාම namespace එකට dockerconfigjson pull secret එක auto create වෙනවා
- deployment එකේ old hardcoded secret name තිබ්බොත් (උදා: `do-registry`) image pull fail වෙන්න පුළුවන්
- ඒ වෙලාවට `k8s/base/deployment.yaml` එකෙන් `imagePullSecrets` block ඉවත් කරන්න
  (default service account pull secret එක use කරන්න)

---

## 5) Argo CD install කරන්න (Dashboard path)

1. Kubernetes -> ඔබගේ cluster -> Marketplace tab වෙත යන්න
2. Argo CD app search කර Install click කරන්න
3. Namespace ලෙස `argocd` තෝරන්න
4. Argo CD server expose option එකේ LoadBalancer/Ingress option එක enable කරන්න (UI access සඳහා)
5. Install complete වෙනකම් ඉන්න

Install පසු:

1. cluster workloads/services list එකෙන් Argo CD server external URL එක ගන්න
2. browser එකෙන් Argo CD UI open කරන්න

Tip:

- Marketplace form එකේ admin credential values set කරන්න පුළුවන් නම් setup වෙලාවෙම set කරන්න

---

## 6) Argo CD UI එකෙන් Application create කරන්න

Argo CD UI > New App:

1. Application Name: `torrent-downloader`
2. Project: `default`
3. Sync Policy: Automatic
4. Prune Resources: Enable
5. Self Heal: Enable
6. Repository URL: `https://github.com/isuru709/TorrentFlow_x365.git`
7. Revision: `main`
8. Path: `k8s`
9. Destination Cluster: `https://kubernetes.default.svc`
10. Destination Namespace: `torrent-downloader`
11. Create App click කරන්න

Result:

- app එක Synced + Healthy status එකට යා යුතුයි

---

## 7) GitHub Web UI එකෙන් Actions Secrets set කරන්න

GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret

Required secret:

1. Name: `DOCR_TOKEN`
2. Value: DigitalOcean personal access token

Optional overrides (default values වෙනස් කරන්න ඕන නම් පමණක්):

1. Name: `DOCR_REGISTRY`
2. Default: `registry.digitalocean.com/torrentflow-registry`
3. Name: `DOCR_REPOSITORY`
4. Default: `torrent-downloader`

වැදගත්:

- `DOCR_TOKEN` (DigitalOcean registry සඳහා) සහ Cloudflare API token එක වෙනස්.
- Cloudflare API token + `origin.pem` + `origin-key.pem` domain/HTTPS hosting stage එකේ භාවිතා කරන්න.

DO token create කිරීම (Dashboard):

1. DigitalOcean -> API -> Tokens/Keys
2. Generate New Token click කරන්න
3. Registry write permissions ඇතුළත් token එකක් generate කරන්න
4. එම token value එක `DOCR_TOKEN` ලෙස GitHub secret එකට දාන්න

---

## 8) GitHub Actions workflow verify කරන්න (Web UI)

repo එකේ මේ file එක check කරන්න:

- `.github/workflows/build-and-deploy.yml`

මේ workflow එක main branch push වලදී:

1. Docker image build/push කරනවා
2. `k8s/overlays/prod/kustomization.yaml` file එකේ tag update කරනවා
3. updated manifest එක commit/push කරනවා

---

## 9) First test (CLI නැතුව end-to-end)

1. GitHub web editor එකෙන් `README.md` වගේ file එකකට small edit එකක් කරන්න
2. Commit directly to main branch
3. Actions tab එකේ workflow run එක watch කරන්න
4. Workflow success පසු, commit history එකේ bot commit එක (`ci: set image ...`) එනවාද බලන්න
5. Argo CD UI එකේ app status OutOfSync -> Synced/Healthy වෙනවාද බලන්න
6. DigitalOcean Kubernetes workloads view එකේ new pod rollout වෙනවාද බලන්න

---

## 10) Nodes scale/registration (Web UI)

1. Kubernetes -> cluster -> Node Pools tab
2. Scale option එකෙන් node count වැඩි/අඩු කරන්න
3. Save/Resize click කරන්න
4. Nodes section එකේ new nodes Running/Ready වීම verify කරන්න

ඒමෙන් ඔබට cluster, nodes, registration behavior practical විදිහට බලන්න පුළුවන්.

---

## 11) UI-based Troubleshooting

### A) Argo CD service එක LoadBalancer කරන්න ගියේ Windows CMD parse error එනවා

Issue:

- මේ command එක Linux shell වල වැඩ කළත් Windows CMD එකේ single quotes නිසා parse error (yaml/json parse) එන්න පුළුවන්:

```bash
kubectl patch svc argocd-server -n argocd -p '{"spec": {"type": "LoadBalancer"}}'
```

Fix (Windows CMD):

- Double quotes + escape use කරන්න:

```bash
kubectl patch svc argocd-server -n argocd -p "{\"spec\": {\"type\": \"LoadBalancer\"}}"
```

Alternative fix:

- Manual edit method එක use කරන්න:

```bash
kubectl edit svc argocd-server -n argocd
```

- open වෙන editor එකේ `spec.type` value `ClusterIP` සිට `LoadBalancer` ලෙස වෙනස් කර save කරන්න.

### B) Windows CMD එකෙන් Argo CD Admin Password decode කරගන්න බැරි වීම

Issue:

- Linux guide වල තියෙන `base64 -d` command එක Windows CMD එකේ direct ලෙස වැඩ නොකරන අවස්ථා තියෙනවා.

Fix (PowerShell method):

```powershell
$password = kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($password))
```

Alternative (CMD + online decode):

1. CMD එකෙන් encoded value එක ගන්න:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"
```

1. output එක `base64decode.org` වගේ trusted decoder site එකකට දාලා plain password එක decode කරන්න.

### C) Argo CD App create කරන වෙලාවේ `kustomization.yaml is empty` error එක

Issue:

- Error message:
  `InvalidSpecError: Unable to generate manifests ... kustomization.yaml is empty`
- මෙයින් අදහස් වෙන්නේ `k8s/overlays/prod/kustomization.yaml` file එක empty හෝ invalid බවයි.

- Error message එකේ
  `security; file ... is not in or below ... overlays/prod`
  වගේ part එකක් එනවා නම්, Argo CD app path එක `k8s` ලෙස set කරන්න.
  (Strict load restriction mode එකේ `overlays/prod` path එකෙන් `../../base` references block වෙන්න පුළුවන්.)

- `# Warning: 'commonLabels' is deprecated` warning එක එනවා නම්,
  `commonLabels:` block එක ඉවත් කර `labels:` block එක භාවිතා කරන්න.

Fix:

- `k8s/overlays/prod/kustomization.yaml` file එකට පහත content එක දාන්න:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: torrent-downloader

resources:
  - ../../base

images:
  - name: torrent-downloader
    newName: registry.digitalocean.com/torrentflow-registry/torrent-downloader
    newTag: latest

labels:
  - pairs:
      app.kubernetes.io/managed-by: argocd
      app.kubernetes.io/environment: prod
    includeSelectors: false
    includeTemplates: true
```

Important reminder:

- ඔබ `base` layer එක separate kustomize package එකක් ලෙස භාවිතා කරනවා නම්,
  `k8s/base/kustomization.yaml` file එකත් තිබිය යුතුයි.
- එහි `resources` list එක deployment/service/pvc files වලට point විය යුතුයි. Example:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - deployment.yaml
  - service.yaml
  - pvc.yaml
```

- `k8s/kustomization.yaml` file එකත් තිබිය යුතුයි. Example:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - overlays/prod
```

### D) Actions fail with missing secret

- GitHub Actions logs වල `DOCR_TOKEN is missing` message එනවා නම්,
  GitHub Secrets වල `DOCR_TOKEN` එක set කරලා නැවත run කරන්න.
- `DOCR_REGISTRY` සහ `DOCR_REPOSITORY` secrets optional වන නිසා,
  ඒවා නැතිවත් workflow default values සමඟ run වෙයි.

### E) Pod image pull fail

- registry integration secret name mismatch වුනොත් image pull fail වෙනවා.
- `k8s/base/deployment.yaml` හි old `imagePullSecrets` name එකක් (උදා: `do-registry`) තිබ්බොත්,
  එය ඉවත් කර default service account pull secret එක use කරන්න.
- Namespace එකේ secret list බලලා (`torrentflow-registry` වගේ) integration secret create වෙලාද confirm කරන්න.

### F) `FailedAttachVolume` / `Multi-Attach error` (RWO PVC)

- Error message උදාහරණය:
  `Multi-Attach error for volume ... Volume is already used by pod ...`
- මෙය සාමාන්‍යයෙන් replica එක 1ක් තියෙන app එකක් `RollingUpdate` strategy එකෙන් update කරනකොට,
  old pod එක සහ new pod එක එකම වෙලාවේ එකම `ReadWriteOnce` PVC එක mount කරන්න try කරන නිසා වෙනවා.

Fix:

- `k8s/base/deployment.yaml` හි strategy එක `Recreate` ලෙස set කරන්න.
- එවිට update වෙලාවේ old pod terminate වුණාට පස්සේ පමණක් new pod start වෙයි.

Example:

```yaml
spec:
  replicas: 1
  strategy:
    type: Recreate
```

---

## 12) ඔබ මුහුණ දුන් Issues සහ Fixes (Summary)

1. Argo CD `kustomization.yaml is empty`:
Fix: overlay `kustomization.yaml` content restore කළා.
2. Argo CD security path error (`not in or below overlays/prod`):
Fix: Argo app path `k8s` කළා + top-level `k8s/kustomization.yaml` add කළා.
3. `commonLabels` deprecation:
Fix: `labels` block වලට migrate කළා.
4. `namespace not found` sync failure:
Fix: namespace manifest add කර base resources වලට include කළා.
5. GitHub workflow YAML syntax issue:
Fix: malformed heredoc replace කර stable generation logic දාලා fix කළා.
6. `DOCR_REGISTRY is missing` fail:
Fix: `DOCR_TOKEN` only required කර defaults add කළා.
7. `sed ... unterminated s command`:
Fix: `sed` step remove කර safe line-by-line rewrite logic භාවිතා කළා.
8. `ImagePullBackOff` (secret mismatch):
Fix: hardcoded imagePullSecrets remove කර namespace/serviceaccount registry secret flow align කළා.
9. `FailedAttachVolume` / multi-attach:
Fix: deployment strategy `Recreate` කළා.

---

## 13) Learning checklist

- [ ] DigitalOcean Registry create කරලා තියෙනවා
- [ ] Kubernetes cluster + nodes dashboard හරහා create කරලා තියෙනවා
- [ ] Registry integration cluster එකට connect කරලා තියෙනවා
- [ ] Argo CD install + App create කරලා තියෙනවා
- [ ] GitHub Actions secrets set කරලා තියෙනවා
- [ ] main push එකකින් auto build + auto deploy වැඩ කරනවා

---

## 14) VPC තුළ run වෙන app console access කරන්නේ කොහොමද

වැදගත්:

- VPC එකක් කියන්නේ network boundary එකක්. ඒකට direct "VPC console" එකක් නැහැ.
- access method එක app run වෙන්නේ කොහේද කියන එක මත තීරණය වෙයි.

### A) App pod console (recommended)

```bash
kubectl get pods -n torrent-downloader
kubectl logs -f deploy/torrent-downloader -n torrent-downloader
kubectl exec -it -n torrent-downloader <POD_NAME> -- /bin/sh
```

### B) Nginx VM console

Dashboard path:

1. DigitalOcean -> Droplets -> Nginx Droplet
2. Access -> Launch Droplet Console

SSH method:

```bash
ssh root@<VM_PUBLIC_IP>
```

### C) Kubernetes node console (advanced)

1. DigitalOcean -> Kubernetes -> Cluster -> Node Pools -> Node
2. linked Droplet -> Access -> Launch Console

Note:

- Managed nodes වල manual edits පසුව replace වෙන්න පුළුවන්.
- troubleshooting සඳහා `kubectl` based pod-level access path එකම use කරන්න.

---

මෙය pure dashboard-first GitOps learning path එකකි. CLI එකකට යන්න අවශ්‍ය වෙන්නේ advanced debugging stage එකේ පමණයි.
