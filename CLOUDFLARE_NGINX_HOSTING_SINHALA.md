# Cloudflare + Nginx හරහා TorrentFlow Host කරන Step-by-Step Guide (Sinhala)

ඔබගේ app එක දැන් Argo CD එකේ Healthy + Synced නිසා, මේ guide එකෙන් domain + HTTPS + Nginx reverse proxy සමඟ production hosting කරනවා.

---

## 1) දැන්ම Access කරන්න (current live endpoint)

ඔබගේ current Kubernetes LoadBalancer IP:

- App: <http://188.166.198.40>
- API Docs: <http://188.166.198.40/docs>

මෙය temporary access path එක. Domain + SSL සඳහා පහත steps follow කරන්න.

---

## 2) Recommended Architecture

Cloudflare (DNS + SSL edge) -> Nginx VM (reverse proxy) -> Kubernetes LoadBalancer Service (188.166.198.40:80)

මෙහෙම කරන එකේ වාසි:

- Domain control Cloudflare එකෙන් manage කරගන්න පුළුවන්
- HTTPS terminate කර security improve වෙනවා
- Nginx එකෙන් timeouts, headers, upload behavior fine-tune කරන්න පුළුවන්

---

## 3) Prerequisites

- Cloudflare account + domain add කරලා තිබිය යුතුයි
- Public IP එකක් ඇති Ubuntu VM එකක් (Nginx run කරන්න)
- VM firewall ports: 80, 443 open
- Kubernetes app already running (ඔබගේ case එකේ already ready)

---

## 4) Cloudflare DNS record create කරන්න

Cloudflare Dashboard -> DNS -> Add record:

1. Type: A
2. Name: app (හෝ ඔබට ඕන subdomain)
3. IPv4 address: Nginx VM public IP
4. Proxy status: Proxied (orange cloud)
5. Save

Example final URL:

- <https://app.yourdomain.com>

Note:

- Nginx VM එක නොභාවිතා කරන quick method එක direct LB IP (`188.166.198.40`) වෙත A record දාන එකයි.
- ඔබ Nginx use කරන නිසා A record එක VM IP එකට දාන්න.

---

## 5) Nginx VM එකේ setup

Ubuntu VM එකේ run කරන්න:

```bash
sudo apt update
sudo apt install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

Firewall (UFW) use කරනවා නම්:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
```

---

## 6) Cloudflare Origin Certificate create කරන්න

Cloudflare -> SSL/TLS -> Origin Server -> Create Certificate

1. Key type: RSA (default ok)
2. Hostnames:
   - app.yourdomain.com
   - (optional) *.yourdomain.com
3. Create
4. Certificate සහ Private key copy කර ගන්න

ඔබට දැනටමත් `origin.pem` සහ `origin-key.pem` files තියෙන නිසා,
ඒවා VM එකේ Nginx SSL path එකට copy කරන්න:

```bash
sudo mkdir -p /etc/nginx/ssl
sudo cp origin.pem /etc/nginx/ssl/origin.pem
sudo cp origin-key.pem /etc/nginx/ssl/origin-key.pem
sudo chmod 600 /etc/nginx/ssl/origin-key.pem
```

---

## 7) Nginx reverse proxy config create කරන්න

File create කරන්න:

```bash
sudo nano /etc/nginx/sites-available/torrentflow.conf
```

පහත config එක paste කරන්න (domain එක replace කරන්න):

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name app.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name app.yourdomain.com;

    ssl_certificate     /etc/nginx/ssl/origin.pem;
    ssl_certificate_key /etc/nginx/ssl/origin-key.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    client_max_body_size 2G;

    location / {
        proxy_pass http://188.166.198.40:80;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
        proxy_buffering off;
    }
}
```

Enable + test + reload:

```bash
sudo ln -sf /etc/nginx/sites-available/torrentflow.conf /etc/nginx/sites-enabled/torrentflow.conf
sudo nginx -t
sudo systemctl reload nginx
```

---

## 8) Cloudflare SSL settings

Cloudflare -> SSL/TLS:

1. SSL/TLS encryption mode: Full (strict)
2. Always Use HTTPS: On
3. WebSockets: On

Recommended:

- Cache Rules වල `/api/*` සහ `/ws*` paths bypass කරන්න (dynamic traffic සඳහා)

Cloudflare API token (optional automation):

- මෙම token එක DNS API automation සඳහා පාවිච්චි කරන්න පුළුවන්.
- මෙය DigitalOcean `DOCR_TOKEN` එක නොවේ.

Token verify example:

```bash
curl -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" \
    -H "Authorization: Bearer <CLOUDFLARE_API_TOKEN>" \
    -H "Content-Type: application/json"
```

---

## 9) Final verification

Browser:

- <https://app.yourdomain.com>
- <https://app.yourdomain.com/docs>

Terminal test:

```bash
curl -I https://app.yourdomain.com
```

Expected:

- `HTTP/2 200` (හෝ 307/308 -> then 200)

---

## 10) Troubleshooting quick fixes

### A) Cloudflare 525 SSL handshake failed

- Origin certificate paths හරිද බලන්න
- Cloudflare mode `Full (strict)` සමඟ cert valid ද බලන්න

### B) Cloudflare 502/504

- Nginx VM එකෙන් backend reachable ද බලන්න:

```bash
curl -I http://188.166.198.40
```

- Kubernetes service/pod health check කරන්න

### C) Cloudflare 521

- VM firewall 80/443 open ද බලන්න
- Nginx service running ද බලන්න:

```bash
sudo systemctl status nginx
```

### D) WebSocket real-time updates වැඩ නොකරයි

- Nginx config එකේ Upgrade/Connection headers තිබිය යුතුයි
- Cloudflare WebSockets On ද බලන්න

### E) PowerShell `curl` command error (`Cannot find drive. A drive with the name 'http' does not exist.`)

- Windows PowerShell වල `curl` කියන්නේ `Invoke-WebRequest` alias එකක්.
- ඉතින් Linux style `curl -I http://...` command එක direct run කළාම parameter prompt/error එන්න පුළුවන්.

Use this instead:

```powershell
Invoke-WebRequest -Uri "http://188.166.198.40/health" -Method Get -UseBasicParsing
```

හෝ native curl.exe use කරන්න:

```powershell
curl.exe -I "http://188.166.198.40/health"
```

---

## 11) Optional hardening

- Nginx VM එකට fail2ban enable කරන්න
- access/error logs centralized කර monitor කරන්න
- rate limit rules add කරන්න (abuse control)
- Cloudflare WAF rules enable කරන්න

---

## 12) ඔබ මුහුණ දුන් Issues සහ Fixes (Summary)

1. Argo CD manifest build error (`kustomization.yaml is empty`):
Fix: overlay/base/root kustomization files නිවැරදිව align කළා.
2. Argo CD path security restriction:
Fix: app source path `k8s` ලෙස update කළා.
3. Namespace missing sync error:
Fix: namespace manifest add කළා.
4. GitHub Actions YAML/sed errors:
Fix: workflow logic harden කර safer file update method භාවිතා කළා.
5. ImagePullBackOff (registry auth/secret mismatch):
Fix: serviceaccount registry secret mapping align කළා.
6. Multi-Attach PVC:
Fix: single replica RWO workload සඳහා deployment strategy `Recreate` කළා.

---

## 13) VPC තුළ run වෙන program console access කරන්නේ කොහොමද

`VPC` එකට separate shell එකක් නැති නිසා, real console access points දෙකක් තියෙනවා.

### A) Nginx VM (Droplet) console

Dashboard path:

1. DigitalOcean Dashboard login
2. Manage -> Droplets
3. Nginx VM එක select කරන්න
4. Access tab
5. Launch Droplet Console

SSH method:

```bash
ssh root@<VM_PUBLIC_IP>
```

### B) Kubernetes app pod console (program run වෙන තැන)

```bash
kubectl get pods -n torrent-downloader
kubectl logs -f deploy/torrent-downloader -n torrent-downloader
kubectl exec -it -n torrent-downloader <POD_NAME> -- /bin/sh
```

### C) Kubernetes node console (advanced)

1. DigitalOcean -> Kubernetes -> Cluster -> Node Pools -> Node
2. linked Droplet -> Access -> Launch Console

Note:

- node-level manual edits managed cluster එකේ long-term maintain නොවෙයි.
- app debugging වලදී pod-level console + logs එක best practice.
- console button නොපෙනේ නම් ඔබ account/project permission (owner/member scope) check කරන්න.

---

මෙම setup එකෙන් ඔබට stable domain + HTTPS hosting එකක් ලැබෙනවා, Kubernetes app updates Argo CD හරහා continue auto-sync වෙනවා.
