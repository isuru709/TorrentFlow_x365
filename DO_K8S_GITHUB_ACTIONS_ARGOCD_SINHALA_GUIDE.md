# DigitalOcean + Kubernetes + GitHub Actions + Argo CD (Sinhala Step-by-Step)

මෙම guide එකේ ඉලක්කය:

- ඔබ `git push` කරන හැම වෙලාවේම Docker image auto build/push වෙනවා.
- image tag එක Kubernetes manifest වලට auto update වෙනවා.
- Argo CD ඒ commit එක detect කර cluster එක auto sync කර app එක update කරනවා.

---

## 1) මේ services එකට එකට වැඩ කරන විදිහ

Flow එක සරලව:

1. ඔබ `main` branch එකට push කරනවා.
2. GitHub Actions workflow (`.github/workflows/build-and-deploy.yml`) run වෙනවා.
3. workflow එක Docker image build කර DigitalOcean Container Registry (DOCR) ට push කරනවා.
4. workflow එක `k8s/overlays/prod/kustomization.yaml` file එකේ `newTag` (හා `newName`) update කර commit/push කරනවා.
5. Argo CD app (`k8s/argocd/application.yaml`) එම git වෙනස්කම detect කර auto sync කරනවා.
6. Kubernetes Deployment එක new image tag එකෙන් rolling update කරනවා.

Result: manual SSH deploy අවශ්‍ය නැහැ. `push -> auto deploy`.

---

## 2) Prerequisites

අවශ්‍ය දේවල්:

- DigitalOcean account (billing enabled)
- GitHub repo admin access
- Local machine හෝ DO Droplet VM එකක් (control/jumpbox)
- Cloudflare domain (optional - domain/HTTPS setup සඳහා)
- Cloudflare API token (optional - DNS automation සඳහා)
- Cloudflare origin cert files (`origin.pem`, `origin-key.pem`) (optional - Nginx HTTPS setup සඳහා)
- Installed tools:
  - `doctl`
  - `kubectl`
  - `argocd` (CLI optional, web UI තිබුනත් හරි)
  - `docker` (local testing සඳහා optional)

ඔබ VM එකක් use කරනවා නම් Ubuntu droplet එකක් create කර tools install කරගෙන මේ steps run කරන්න.

---

## 3) DigitalOcean Registry (DOCR) create කරන්න

```bash
doctl auth init --access-token <DIGITALOCEAN_PAT>
doctl registry create torrentflow-registry
```

Registry list check:

```bash
doctl registry get
```

---

## 4) Kubernetes Cluster + Nodes setup කරන්න

### 4.1 Cluster create

පළමුව available versions බලන්න:

```bash
doctl kubernetes options versions
```

ඊළඟට cluster create කරන්න (example):

```bash
doctl kubernetes cluster create torrentflow-cluster \
  --region sgp1 \
  --version <SUPPORTED_VERSION> \
  --size s-2vcpu-4gb \
  --count 2
```

### 4.2 kubeconfig save

```bash
doctl kubernetes cluster kubeconfig save torrentflow-cluster
```

### 4.3 Nodes register/ready verify

```bash
kubectl get nodes -o wide
```

`STATUS` column එකේ `Ready` නම් node registration හරි.

---

## 5) Namespace + registry pull secret configure කරන්න

දැනට deployment එක default service account imagePullSecret එක use කරන නිසා,
namespace එකට registry secret එක create කර service account එකට link කළ යුතුයි.

```bash
kubectl create namespace torrent-downloader --dry-run=client -o yaml | kubectl apply -f -

doctl registry login

kubectl create secret generic torrentflow-registry \
  --from-file=.dockerconfigjson=$HOME/.docker/config.json \
  --type=kubernetes.io/dockerconfigjson \
  -n torrent-downloader \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl patch serviceaccount default -n torrent-downloader \
  -p '{"imagePullSecrets":[{"name":"torrentflow-registry"}]}'
```

Verify:

```bash
kubectl get secret torrentflow-registry -n torrent-downloader
kubectl get serviceaccount default -n torrent-downloader -o yaml
```

---

## 6) Argo CD install කරන්න

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl rollout status deployment/argocd-server -n argocd
```

Initial admin password ගන්න:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d && echo
```

UI access (local port-forward):

```bash
kubectl port-forward svc/argocd-server -n argocd 8081:443
```

Browser: `https://localhost:8081`

---

## 7) Argo CD Application deploy කරන්න

ඔබගේ repo එක public නිසා repo credentials නැතුවත් වැඩ කරයි.

```bash
kubectl apply -f k8s/argocd/application.yaml
kubectl get applications -n argocd
```

Application status `Healthy/Synced` වීමට ටික වෙලාවක් යයි.

---

## 8) GitHub Secrets set කරන්න (Automation එකේ heart)

GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret

Required secret:

1. `DOCR_TOKEN` = DigitalOcean PAT (registry read/write permissions සමඟ)

Optional overrides (set කළොත් පමණක්):

1. `DOCR_REGISTRY` = `registry.digitalocean.com/torrentflow-registry`
2. `DOCR_REPOSITORY` = `torrent-downloader`

Note:

- `DOCR_TOKEN` (DigitalOcean Registry token) සහ Cloudflare API token දෙක වෙනස් දෙවල්.
- Cloudflare API token එක GitHub Actions Docker build workflow එකට අවශ්‍ය නොවේ.

ඔබගේ existing workflow file:

- `.github/workflows/build-and-deploy.yml`

මෙය already මෙහෙම කරනවා:

1. image build/push
2. `k8s/overlays/prod/kustomization.yaml` update (`newTag`)
3. git commit/push

---

## 9) First deployment test (End-to-End)

1. repo එකට small code change එකක් commit/push කරන්න.
2. GitHub Actions run status බලන්න.
3. workflow success වුණාම Argo CD app sync වෙනවා.

Cluster side verify commands:

```bash
kubectl get pods -n torrent-downloader
kubectl rollout status deploy/torrent-downloader -n torrent-downloader
kubectl get svc -n torrent-downloader
```

Running pod එක image tag check:

```bash
kubectl get pods -n torrent-downloader -o=jsonpath='{range .items[*]}{.metadata.name}{" => "}{.spec.containers[0].image}{"\n"}{end}'
```

---

## 10) Push එකකින් update වෙන actual cycle එක

ඔබ `main` branch push කරන හැම වෙලාවම:

1. GitHub Actions image tag = short commit SHA
2. DOCR ට image push
3. `kustomization.yaml` tag update + push
4. ArgoCD auto sync
5. Kubernetes rolling update

ඒකයි full GitOps + CI/CD loop එක.

---

## 11) Troubleshooting (සම්භාව්‍ය errors)

### A) `ImagePullBackOff`

- namespace secret/serviceaccount mapping වැරදි
- registry auth token scope වැරදි
- image path mismatch

Check:

```bash
kubectl describe pod <POD_NAME> -n torrent-downloader
kubectl get secret -n torrent-downloader
kubectl get serviceaccount default -n torrent-downloader -o yaml
```

### B) Argo CD sync නොවෙයි

- app path wrong (`k8s`)
- branch mismatch

Check:

```bash
kubectl get application torrent-downloader -n argocd -o yaml
```

### C) Workflow run වෙයි, deploy නොවේ

- workflow `kustomization.yaml` update commit එක fail වුනාද බලන්න
- Actions log වල `Commit manifest update` step check කරන්න

### D) `FailedAttachVolume` / `Multi-Attach`

- `ReadWriteOnce` PVC + `RollingUpdate` combo එකෙන් old/new pods එකවර run වීම නිසා එන්න පුළුවන්.
- Fix: `k8s/base/deployment.yaml` හි strategy `Recreate` ලෙස සකසන්න.

### E) `sed ... unterminated s command`

- secrets වල hidden newline/format issue නිසා image update step fail වුණා.
- Fix: workflow එක `sed` අයින් කර line-by-line rewrite method එකට මාරු කළා.

---

## 12) ඔබ මුහුණ දුන් Issues සහ Fixes (Summary)

1. Argo CD `kustomization.yaml is empty`:
Fix: `k8s/overlays/prod/kustomization.yaml` content restore කළා.
2. Argo CD security path error (`not in or below overlays/prod`):
Fix: app source path `k8s` කළා + `k8s/kustomization.yaml` add කළා.
3. `commonLabels` deprecated warning:
Fix: `labels` block භාවිතා කළා.
4. `namespace not found`:
Fix: `k8s/base/namespace.yaml` add කර base resources වලට include කළා.
5. GitHub workflow YAML syntax error:
Fix: malformed heredoc block remove කර stable generation logic භාවිතා කළා.
6. `DOCR_REGISTRY is missing` workflow fail:
Fix: `DOCR_TOKEN` only required කර registry/repository defaults දාලා robust කළා.
7. Registry image pull unauthorized:
Fix: hardcoded `imagePullSecrets` remove කර namespace serviceaccount pull secret flow align කළා.
8. `FailedAttachVolume` / multi-attach:
Fix: deployment strategy `Recreate` කළා.

---

## 13) Nodes scale up/down (Learning section)

### Node pool add (example)

```bash
doctl kubernetes cluster node-pool create torrentflow-cluster \
  --name extra-workers \
  --size s-2vcpu-4gb \
  --count 1
```

Verify:

```bash
kubectl get nodes
```

Managed Kubernetes (DOKS) වල nodes control plane එකට auto register වෙනවා.

---

## 14) ඉගෙනගන්න වැදගත් concept map එක

- VM/Droplet: ඔබ commands run කරන control machine (optional but practical)
- DOKS Cluster: app run වෙන Kubernetes cluster
- Nodes: pods run වෙන worker machines
- DOCR: private Docker image registry
- GitHub Actions: CI (build + push + manifest update)
- Argo CD: CD (Git state -> cluster state sync)

---

## 15) Quick checklist

- [ ] DOCR create කරලා තියෙනවා
- [ ] DOKS cluster + nodes `Ready`
- [ ] `torrentflow-registry` secret create + default serviceaccount mapping කරලා තියෙනවා
- [ ] ArgoCD install + application created
- [ ] GitHub `DOCR_TOKEN` secret set කරලා තියෙනවා
- [ ] (`DOCR_REGISTRY`/`DOCR_REPOSITORY`) optional override secrets අවශ්‍ය නම් set කරලා තියෙනවා
- [ ] push එකකින් image tag update + auto rollout වෙනවා

---

## 16) VPC තුළ run වෙන app console access කරන්නේ කොහොමද

වැදගත්:

- VPC එකට "single console" එකක් නැහැ.
- ඔබ access කරන්නේ Droplet console එක හෝ Kubernetes pod console එක.

### A) Kubernetes app console (recommended)

```bash
kubectl get pods -n torrent-downloader
kubectl logs -f deploy/torrent-downloader -n torrent-downloader
kubectl exec -it -n torrent-downloader <POD_NAME> -- /bin/sh
```

### B) Nginx VM (Droplet) console

Dashboard path:

1. DigitalOcean -> Droplets -> ඔබගේ Nginx Droplet
2. Access tab -> Launch Droplet Console

SSH method:

```bash
ssh root@<VM_PUBLIC_IP>
```

### C) Kubernetes node console (advanced only)

1. DigitalOcean -> Kubernetes -> Cluster -> Node Pools -> Node
2. Node linked Droplet -> Access -> Launch Console

Note:

- DOKS worker nodes managed resources වන නිසා manual node-level changes persistent නොවෙයි.
- app debugging සඳහා `kubectl logs` + `kubectl exec` path එක use කරන එක best practice.

---

ඔබට ඕන නම් ඊළඟ step එකට:

- HTTPS + domain + Ingress + cert-manager
- preview environments (feature branches)
- Slack/Discord deployment notifications
