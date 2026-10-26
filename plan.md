# Plan — mettre à jour ton fork `eSMART_homekit_rea`

> But : transformer tes fixes ad-hoc (faits à la main sur la Pi au fil des
> semaines) en un fork propre, documenté, installable en une commande.
> Quelqu'un qui arrive avec le même symptôme ("le switch HA ne bouge plus
> après une semaine") doit trouver la réponse en < 2 minutes.

---

## 0. TL;DR — ce qu'on livre

| Livrable | Rôle |
|---|---|
| `bootstrap.sh` (racine) | install fraîche en une commande, idempotent |
| `docs/HARDENING.md` | les 7 changements vs upstream + pourquoi |
| `docs/TROUBLESHOOTING.md` | l'arbre de décision Test 1 / Test 2 / Test 3 |
| `deploy/esmart-bridge.service` (patché) | `Type=simple`, `Restart=always` |
| `deploy/esmart-bridge-watchdog.{service,timer}` | health check 30s |
| `deploy/esmart-homekit.service` | unit séparée, optionnelle |
| `lib/keepalive-wrapper.py` | monkey-patch TCP keepalive, sans toucher upstream |
| `lib/watchdog.sh` | script du timer |
| `README.md` réécrit | pointe vers `docs/`, dit clairement "fork hardened" |
| `CHANGELOG.md` | 1.0.0-hardened : les 7 fixes |

Ne PAS modifier les fichiers Python upstream (`esmart-bridge.py`,
`esmart_core.py`, `esmart.py`). On veut pouvoir faire `git pull upstream
main` sans conflit. Tous les fixes vivent dans `lib/`, `deploy/`,
`bootstrap.sh` et `docs/`.

---

## 1. État actuel vs cible

### Ce qui existe sur la Pi (après les interventions manuelles)

```

/opt/esmart/                        # clone upstream
esmart_core.py                    # ← PATCHÉ à la main (TCP_KEEPIDLE)
esmart-bridge.py                  # ← PATCHÉ à la main (IDLE_SECS=180)
/etc/systemd/system/
esmart-bridge.service             # ← réécrit (Type=simple)
esmart-homekit.service            # ← créé à la main
/mnt/dietpi_userdata/homeassistant/packages/
esmart_bridge.yaml                # ← scan_interval: 3

```

Problème : **tout ça est invisible dans git**. Si la SD card meurt, c'est
perdu. Si quelqu'un te demande "comment t'as réparé ?", tu n'as pas de lien
à envoyer.

### Cible — structure du fork

```

esmart-hardened/                    # ← ton fork (renommé pour clarté)
├── README.md                       # réécrit, pointe vers docs/
├── CHANGELOG.md                    # nouveau, 1.0.0-hardened
├── plan.md                         # ← ce fichier (optionnel, peut rester)
├── bootstrap.sh                    # nouveau, install 1-ligne
├── lib/
│   ├── keepalive-wrapper.py        # nouveau
│   └── watchdog.sh                 # nouveau
├── deploy/
│   ├── esmart-bridge.service       # remplacé
│   ├── esmart-bridge-watchdog.service   # nouveau
│   ├── esmart-bridge-watchdog.timer     # nouveau
│   └── esmart-homekit.service      # nouveau
├── docs/
│   ├── HARDENING.md                # nouveau
│   ├── TROUBLESHOOTING.md          # nouveau
│   └── ARCHITECTURE.md             # nouveau (facultatif)
└── (tout le reste de upstream, intact : esmart.py, esmart_core.py, ...)

```

---

## 2. Séquence de commits

Faire **cinq commits séparés**, chacun testable indépendamment. C'est
important : si on te dit "le watchdog casse un truc", tu peux le revert
sans perdre le keepalive.

### Commit 1 — `chore: rename fork + add CHANGELOG`

- Renomme le repo GitHub `eSMART_homekit_rea` → `esmart-hardened` (optionnel,
  Settings → Rename ; GitHub redirige l'ancien nom).
- Ajoute `CHANGELOG.md` (squelette ci-dessous).
- Dans `README.md`, ajoute un encart en haut :

```markdown
> **This is a hardened fork.** It adds TCP keepalive, a health watchdog,
> and `Restart=always` systemd units on top of
> [swiss-vsdev/eSMART_homekit_rea](https://github.com/swiss-vsdev/eSMART_homekit_rea).
> See [`docs/HARDENING.md`](docs/HARDENING.md) for what changed and why.
> For a vanilla setup, use the upstream repo instead.
```

### Commit 2 — `feat(deploy): split bridge/HomeKit units, add Restart=always`

- Remplace `deploy/esmart-bridge.service` par la version `Type=simple`.
- Ajoute `deploy/esmart-homekit.service`.
- Met à jour `deploy/README` (ou l'entête du fichier) avec les nouvelles
instructions `systemctl enable --now`.

### Commit 3 — `feat(lib): TCP keepalive wrapper + bridge watchdog timer`

- Ajoute `lib/keepalive-wrapper.py`.
- Ajoute `lib/watchdog.sh` + `deploy/esmart-bridge-watchdog.{service,timer}`.
- Documente dans `docs/HARDENING.md` §1 et §2.

### Commit 4 — `feat(ha): patch esmart_bridge.yaml scan_interval 10→3`

- Ajoute `homeassistant-migration/patches/esmart_bridge.scan_interval.patch`
(un vrai `.patch` unifié, pas un sed dans un script).
- Modifie `homeassistant-migration/bootstrap.sh` pour l'appliquer après le
déploiement du package.
- Documente dans `docs/HARDENING.md` §6.

### Commit 5 — `feat: bootstrap.sh one-command installer + docs`

- Ajoute `bootstrap.sh` à la racine (celui déjà écrit).
- Ajoute `docs/TROUBLESHOOTING.md`.
- Réécrit `README.md` §Quick Start pour pointer vers `bootstrap.sh`.
- Ajoute un badge "hardened" en haut du README.

> **Ne pas squash.** Chaque commit doit builder/test indépendamment. Tag
> `v1.0.0-hardened` après le commit 5.

---

## 3. Contenu des fichiers clés

### 3.1 `CHANGELOG.md` (nouveau)

```
# Changelog

## [1.0.0-hardened] — 2026-10-26

Hardened fork of `swiss-vsdev/eSMART_homekit_rea` @ 2026-10-17.

### Added
- `bootstrap.sh` — one-command installer for DietPi / Raspberry Pi.
- `lib/keepalive-wrapper.py` — enables `TCP_KEEPIDLE=45s`,
  `TCP_KEEPINTVL=15s`, `TCP_KEEPCNT=4` on the XMPP socket, without
  patching upstream Python files.
- `lib/watchdog.sh` + `esmart-bridge-watchdog.timer` — restarts the
  bridge after 3 consecutive unhealthy `/api/status` checks (90s).
- `deploy/esmart-homekit.service` — HomeKit helper as an independent unit.
- `docs/HARDENING.md`, `docs/TROUBLESHOOTING.md`.

### Changed
- `deploy/esmart-bridge.service`: `Type=oneshot` → `Type=simple` with
  `Restart=always`, `RestartSec=10`. Fixes a bug where a crashed bridge
  was never restarted because systemd reported `active (exited)` forever.
- `homeassistant-migration/bootstrap.sh`: applies
  `scan_interval: 10` → `3` patch and restarts the HA container.

### Fixed
- **Zombie XMPP socket**: bridge wrote commands to a half-open TCP
  connection, never received state updates. Fixes: TCP keepalive (§1) +
  watchdog (§2). Symptom: switch in HA stays frozen while physical light
  changes.

### Not changed
- All upstream Python sources (`esmart.py`, `esmart-bridge.py`,
  `esmart_core.py`, `esmart-pair.py`) are **untouched** so `git pull
  upstream main` stays conflict-free.
```

### 3.2 `docs/HARDENING.md` (nouveau — le cœur)

Plan de la page, section par section :

1. **Le symptôme** — copier la description du bug : "switch affiché
correctement mais ne reflète pas la vraie lumière". Trois tests pour
identifier la cause (avant/après toggle physique, `curl /api/status`).
2. **Les trois modes de panne** — table :

- Socket zombie (bridge écrit, ne reçoit plus)
- Crash du process (systemd `oneshot` ne relance pas)
- Lag perçu (`scan_interval: 10`)
3. **Les sept fixes** — reprendre la table du `CHANGES.md` que je t'ai
donné dans le zip précédent. Chaque ligne : `#`, fichier, changement,
panne évitée.
4. **Pourquoi un wrapper plutôt qu'un patch upstream** — le point clé.
Explique que `lib/keepalive-wrapper.py` monkey-patche `socket.socket`
*avant* `runpy.run_path("esmart-bridge.py")`, donc `git pull` reste
clean. Si un jour tu veux PR upstream, tu peux convertir le wrapper en
patch `.diff`.
5. **Vérification** — les 4 commandes du README (status, watchdog, socket
keepalive, HA package).
6. **Désinstaller** — bloque `uninstall` du README.

### 3.3 `docs/TROUBLESHOOTING.md` (nouveau)

Reprendre exactement l'arbre de décision de ta conversation, condensé en
un document lisible par un inconnu :

```
## Symptom: the switch in HA shows the right position but does not
##          reflect the actual light

### Step 1 — Does the bridge see the state? (30 seconds)

    curl -s http://127.0.0.1:8090/api/nodes | jq '.[] | select(.id==386)'
    # then: physically toggle the light, wait 5s, rerun

    │
    ├── onoff changes off → on ......... Problem is on the HA side → Step 2
    └── onoff stays at off ............. Bridge is blind → Step 3

### Step 2 — What does HA read?
    ...
### Step 3 — Bridge blind: which kind?
    ...
```

Condenser les trois scénarios A/B/C en un tableau. **Ne pas** copier les
blocs de commandes complets de la conversation — juste les commandes de
diagnostic, puis pointer vers `bootstrap.sh` pour le fix.

### 3.4 `README.md` — nouvelle structure

Voici le plan de page (dans cet ordre, sections courtes, chaque section
fait <= 15 lignes) :

```
# eSMART HomeKit + Home Assistant — hardened fork

> Fork of swiss-vsdev/eSMART_homekit_rea with three production-hardening
> fixes: TCP keepalive, bridge watchdog, systemd supervision.
> Vanilla upstream users don't need this. Users who had "the switch
> froze after a week" do.

[badge: fork-upstream]

## The problem this fork solves

(3 phrases max — décrire le symptôme "switch figé" et pointer vers
docs/HARDENING.md.)

## Install (fresh DietPi / Raspberry Pi)

    curl -sL https://raw.githubusercontent.com/<you>/esmart-hardened/main/bootstrap.sh \
      | sudo bash -s -- --with-homekit

Flags:
| flag | effect |
|---|---|
| --with-homekit | HomeKit helper OR wire into existing Homebridge |
| --pin 03145154 | HomeKit PIN |
| --skip-ha | skip HA migration |
| --port 8090 | bridge port |

## Already installed?

    cd /opt/esmart && git pull && sudo bash bootstrap.sh

(Idempotent — patches scan_interval, rewrites systemd units, restarts.)

## Verify the hardening is active

(bloc de 4 commandes : is-active, watchdog timer, ss keepalive,
grep scan_interval)

## What changed vs upstream

See docs/HARDENING.md. Summary:
- lib/keepalive-wrapper.py  (TCP keepalive on XMPP socket)
- lib/watchdog.sh           (restart bridge if unhealthy 3×30s)
- deploy/esmart-bridge.service  (Type=simple, Restart=always)
- deploy/esmart-homekit.service (independent unit)
- homeassistant-migration/patch scan_interval 10→3

## Troubleshooting

See docs/TROUBLESHOOTING.md.

## Uninstall

(bloc systemctl disable + rm, comme dans le README précédent)

## License / credits

Fork of swiss-vsdev/eSMART_homekit_rea. Protocol work by the upstream
author. Hardening patches in lib/ and deploy/ are MIT.
```

---

## 4. Patches HA en `.patch` propre

Dans `homeassistant-migration/patches/esmart_bridge.scan_interval.patch` :

```
--- a/packages/esmart_bridge.yaml
+++ b/packages/esmart_bridge.yaml
@@ -1,3 +1,3 @@
 rest:
   - resource: http://127.0.0.1:8090/api/nodes
-    scan_interval: 10
+    scan_interval: 3
     sensor:
```

Et dans `bootstrap.sh`, remplacer le `sed` par :

```
if patch --dry-run -p1 -d "$HA_CONFIG" \
     < "$INSTALL_DIR/homeassistant-migration/patches/esmart_bridge.scan_interval.patch"; then
    patch -p1 -d "$HA_CONFIG" \
        < "$INSTALL_DIR/homeassistant-migration/patches/esmart_bridge.scan_interval.patch"
    docker restart homeassistant
fi
```

Avantage : si upstream change le contexte autour de `scan_interval`, `patch
--dry-run` échoue proprement au lieu de réécrire silencieusement n'importe
quelle ligne contenant `scan_interval:`.

---

## 5. Checklist de test avant de push

Sur une Pi vierge (ou une VM DietPi) :

- □  
`curl -sL bootstrap.sh | sudo bash -s -- --skip-ha` → bridge
`active (running)` + `/api/status` répond `online: true`
- □  
`sudo reboot` → après 90s : `systemctl is-active
    esmart-bridge esmart-bridge-watchdog.timer` → deux fois `active`
- □  
`sudo ss -tnoe state established '( dport = :5222 )' | grep
    keepalive` → `timer:(keepalive,45sec,0)`
- □  
Re-lancer `bootstrap.sh` sur une install existante → pas d'erreur,
`git log -1` inchangé, services toujours actifs
- □  
Avec Homebridge présent : `bootstrap.sh --with-homekit` → plugin
copié dans `/var/lib/homebridge/node_modules`, pas de service
`esmart-homekit` créé, Homebridge redémarre
- □  
HA container présent : `bootstrap.sh` → `esmart_bridge.yaml`
contient `scan_interval: 3`, container redémarre (vérifier avec
`docker ps --filter name=homeassistant --format '{{.Status}}'`)
- □  
`git diff upstream/main -- '*.py'` → **vide** (aucun fichier Python
modifié)

---

## 6. Stratégie upstream (optionnelle)

Deux choix :

### A. Rester fork (recommandé pour l'instant)

Le fork est autonome, personne n'a à merger quoi que ce soit. Dans 6 mois
tu peux ouvrir une issue sur `swiss-vsdev/eSMART_homekit_rea` :

> "I've been running a hardened fork for months — the two failure modes
> below are real and I have a fix. Want a PR for the systemd units, or a
> section in the README?"

Cette approche a deux avantages :

- Tu ne bloques pas sur le mainteneur upstream.
- Le fork devient une référence "si vous tombez sur ce bug, appliquez ces
patches".

### B. PR direct upstream

Uniquement si upstream accepte `deploy/` et `lib/`. Le wrapper keepalive
est le morceau le plus délicat à faire accepter (ils voudront probablement
plutôt un patch direct dans `esmart_core.py`). C'est faisable, mais ça
demande une conversation d'abord — ne pas coder le PR avant d'avoir un
"oui" en commentaire d'issue.

---

## 7. Ce que ce plan ne fait PAS

- **Pas de refactor Python.** Le wrapper keepalive est volontairement
isolé dans `lib/`, pas injecté dans `esmart-bridge.py`.
- **Pas de changement de port par défaut.** 8090 reste 8090.
- **Pas de Home Assistant supervisord config.** HA reste en container
Docker (dietpi_userdata), on ne migre pas vers HA OS.
- **Pas de config réseau / mDNS.** HomeKit reste sur 51826 comme
upstream, HA reste sur 8123.

Si un de ces points devient nécessaire, ouvrir une issue distincte dans le
fork plutôt que de l'entasser dans `bootstrap.sh`.

---

## 8. Ordre d'exécution

1. Sur la Pi, `cd /opt/esmart`, `git remote -v` doit pointer vers ton fork
(pas upstream). Si c'est encore upstream :

```
git remote rename origin upstream
git remote add origin git@github.com:<you>/esmart-hardened.git
git push -u origin main
```
2. Commits 1→5 sur une branche `hardened`, pas sur `main`.
3. Tester la checklist §5 sur une Pi vierge (la tienne ne suffit pas : elle
est déjà dans l'état cible).
4. `git push origin hardened`, merger dans `main`, taguer
`v1.0.0-hardened`.
5. Mettre à jour le README de la Pi elle-même : `sudo bash /opt/esmart/bootstrap.sh --skip-ha`
pour que l'install locale devienne *reproductible depuis le fork* et pas
un état manuel.
6. (Optionnel) ouvrir l'issue upstream §6A.

