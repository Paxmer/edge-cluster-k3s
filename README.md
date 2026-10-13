# Clúster Edge con K3s para mantenimiento predictivo con IA local

Proyecto Final Integrador de Arquitectura de Computadoras 2 (Universidad Mariano Gálvez de Guatemala). Autores: Kleiver Jedidias García Guarcas, Ricardo Ismael Pérez Ajanel, Allan David Alessandro Racancoj Lopez y Pablo Javier Sandoval. El informe completo se entrega por separado; este repositorio contiene el código, los manifiestos y las evidencias de las pruebas.

Clúster de 3 mini PC Intel (Wintel W8 Pro, Atom x5-Z8350 de 64 bits): 1 master + 2 workers con K3s. Clasifica lecturas simuladas de temperatura y vibración de un motor: `normal`, `desgaste` o `falla_inminente`.

Si se usan Raspberry Pi, casi todo sirve igual: cambia la imagen a `--platform linux/arm64`, activa cgroups con `cgroup_memory=1 cgroup_enable=memory` en `/boot/firmware/cmdline.txt` y usa Raspberry Pi OS Lite de 64 bits.

## Qué trae el kit y qué está probado

| Parte | Archivos | Estado |
| --- | --- | --- |
| Simulador de señales y características | `edgekit/` | Probado (8 pruebas automáticas) |
| Entrenamiento y comparación de modelos | `train.py` | Probado; genera `artifacts/` |
| Servicio de inferencia (HTTP) | `service/app.py` | Probado en una computadora y desplegado por el equipo en el clúster |
| Simulador de sensores | `simulator.py` | Probado contra el clúster (ver `docs/resultados/`) |
| Prueba de caída de un worker | `failover_test.py` | Ejecutada por el equipo en los 3 mini PC, con un worker desconectado (ver `docs/resultados/`) |
| Imagen Docker | `service/Dockerfile` | Construida e importada en los workers por el equipo |
| Manifiestos de K3s | `k8s/` y `k8s/pruebas-v1/` | `pruebas-v1/` son los manifiestos usados en las pruebas del equipo; los de `k8s/` añaden mejoras: `externalTrafficPolicy: Local` se midió en la serie A/B (sin peticiones perdidas con Local frente a 11 a 13 por corrida con Cluster; ver `docs/resultados/`), y las sondas y las tolerancias de 15 s **aún no se midieron** |
| Prometheus y Grafana | `monitoring/`, `docs/dashboard.md` | No se desplegaron en el clúster físico, para no sobrecargar la RAM ni la CPU de los nodos; quedan como referencia |

Nota sobre las IP: este README usa 192.168.100.x como ejemplo; en las pruebas del equipo los nodos usaron 192.168.1.26 (master), .27 y .28 (workers) y la laptop la .50. Las latencias y tamaños de modelo de `artifacts/` cambian un poco entre ejecuciones de `train.py`, por lo que pueden diferir levemente de la tabla del informe.

Muy importante: los datos son **sintéticos**. Las métricas de `artifacts/metrics.json` describen el desempeño sobre datos simulados, no sobre una máquina real. Las latencias de `model_comparison.csv` se midieron en la computadora donde se entrenó, no en los mini PC.

## 1. Probar todo en la laptop (sin los mini PC)

Requiere Python 3.11 o superior.

```bash
python3 -m venv .venv && source .venv/bin/activate      # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
python train.py                                          # entrena y guarda artifacts/
python -m unittest discover -s tests -v                  # 8 pruebas
```

Levantar el servicio y probarlo:

```bash
# terminal 1
PYTHONPATH=. python -m service.app
# terminal 2
python simulator.py --endpoints http://127.0.0.1:8000 --duration 30
```

## 2. Preparar los mini PC

Antes de empezar, comprueben en cada equipo (en Windows, Administrador de tareas > Rendimiento) que tiene unos 2 GB de RAM y que trae el puerto de red RJ45. Para el master, 2 GB es el mínimo de K3s: no habiliten swap y no corran Prometheus ni Grafana ahí.

1. **Instalar Ubuntu Server 24.04 LTS de 64 bits** en cada equipo, con un pendrive. Esto **borra Windows** y todo lo que haya en la eMMC. En el instalador: nombre del equipo (`master`, `worker1`, `worker2`), usuario, clave e instalar el servidor OpenSSH.

   Si el pendrive no arranca, es probable que el firmware sea UEFI de 32 bits: hay que copiar un archivo `bootia32.efi` a la carpeta `EFI/BOOT/` del pendrive (formato FAT32). No está verificado para este modelo; si no lo logran, avisen y buscamos otra ruta.

2. **Red.** Mientras instalan, unan un puerto del switch al router para tener internet por DHCP. Cada nodo tendrá, en la misma interfaz, su IP del router y su IP estática del clúster. Primero evita que cloud-init reescriba la red:

   ```bash
   echo 'network: {config: disabled}' | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
   ip a                                   # anota el nombre de la interfaz cableada (eth0, enp1s0, ...)
   sudo nano /etc/netplan/50-cluster.yaml
   ```

   Contenido del archivo (cambia el nombre de la interfaz y la IP: `.10` master, `.11` worker1, `.12` worker2). Después borra o mueve el otro archivo de `/etc/netplan/` si hay uno que configure la misma interfaz:

   ```yaml
   network:
     version: 2
     ethernets:
       eth0:
         dhcp4: true
         addresses: [192.168.100.10/24]
   ```

   ```bash
   sudo chmod 600 /etc/netplan/50-cluster.yaml && sudo netplan apply
   ```

   Para la demo, desconecta el cable hacia el router: los nodos conservan su IP estática y trabajan aislados.

3. **Velocidad de red.** Comprueben el enlace de cada equipo con `sudo ethtool <interfaz> | grep Speed`. En la prueba del equipo, `ethtool` del master informó 1000 Mb/s. Si algún equipo negocia solo 10/100 Mbps y quieren Gigabit, hace falta un adaptador USB 3.0 a Gigabit (la IP estática va entonces en la interfaz del adaptador).

4. En cada nodo: `sudo apt update && sudo apt install -y curl prometheus-node-exporter`.

5. Desde la laptop (con IP 192.168.100.50/24 en su puerto Ethernet) comprueba `ping 192.168.100.10`, `.11` y `.12`.

## 3. Instalar K3s

En el **master** (se desactivan componentes que no hacen falta para ahorrar RAM; sin metrics-server no funciona `kubectl top`):

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--node-ip 192.168.100.10 --advertise-address 192.168.100.10 --flannel-iface eth0 --disable traefik --disable servicelb --disable metrics-server" sh -
sudo cat /var/lib/rancher/k3s/server/node-token          # copia el token
```

En cada **worker** (cambia la IP y pega el token; usa el nombre real de la interfaz en `--flannel-iface`):

```bash
curl -sfL https://get.k3s.io | K3S_URL=https://192.168.100.10:6443 K3S_TOKEN=<TOKEN> INSTALL_K3S_EXEC="--node-ip 192.168.100.11 --flannel-iface eth0" sh -
```

De vuelta en el master (para abreviar: `alias k='sudo k3s kubectl'`):

```bash
k get nodes -o wide                                      # los 3 deben estar Ready
free -m                                                  # revisa que al master le quede RAM libre
k label node worker1 role=worker
k label node worker2 role=worker
```

## 4. Construir la imagen e importarla en los workers

En la laptop, con Docker instalado y después de `python train.py`:

```bash
docker buildx build --platform linux/amd64 -f service/Dockerfile -t edge-infer:1.0 -o type=docker,dest=edge-infer.tar .
scp edge-infer.tar <usuario>@192.168.100.11:~ ; scp edge-infer.tar <usuario>@192.168.100.12:~
```

En **cada worker**:

```bash
sudo k3s ctr images import edge-infer.tar
sudo k3s ctr images ls | grep edge-infer
```

La versión de scikit-learn de `requirements.txt` y de la imagen deben ser la misma; si no, el servicio no podrá cargar el modelo.

## 5. Desplegar y probar

En el master (copia antes la carpeta `k8s/` con `scp -r k8s <usuario>@192.168.100.10:~`):

```bash
k apply -f k8s/
k -n edge get pods -o wide            # 2 pods Running, uno por worker
k -n edge get svc
```

En la laptop:

```bash
curl http://192.168.100.11:30080/info
python simulator.py --endpoints http://192.168.100.11:30080,http://192.168.100.12:30080 --duration 60
```

## 6. Prueba de caída de un worker (lo más importante de la demo)

1. En la laptop: `python failover_test.py --endpoints http://192.168.100.11:30080,http://192.168.100.12:30080 --rate 5 --duration 150 --csv caida1.csv --plot caida1.png`
2. En el master, en otra terminal: `k get nodes -w` y `k -n edge get pods -o wide -w`.
3. A los ~30 s apaga el worker1 (`sudo poweroff` o desconecta su alimentación o su cable de red). Anota la hora.
4. Observa: el nodo pasa a `NotReady` y su pod se reprograma en el worker2. Tiempos aproximados: unos 40 s hasta `NotReady` más 15 s de tolerancia; **midan y reporten los suyos**.
5. Al terminar revisa el resumen: éxito final, éxito al primer intento, ventana más larga sin servicio y reparto por nodo.
6. Repite 3 veces y pongan los resultados en una tabla.

Opcional para acelerar la detección (no probado): en el master, instala K3s con `--kube-controller-manager-arg=node-monitor-grace-period=10s`.

### Si la prueba muestra fallos que no se recuperan (resultado real del equipo)

En la primera prueba real (apagar un worker a los ~16 s, 60 s de duración) el éxito final fue de 89,83 % y el de primer intento ~77 %, y los fallos siguieron hasta el final de la corrida. Es lo esperado con la política por defecto (`externalTrafficPolicy: Cluster`): al pedir a un worker vivo, kube-proxy reparte ~50 % hacia el pod del worker caído hasta que Kubernetes lo marca `NotReady` y retira su endpoint (~40 s por defecto), y con 3 intentos por petición queda ~12,5 % (0,5³) de fallos, que coincide con lo medido.

Para comparar, hagan dos series de 3 repeticiones cada una (150 s, apagar el worker a ~30 s):

1. **Serie A**: `k8s/service.yaml` con `externalTrafficPolicy: Cluster` (quiten la línea o pongan `Cluster`) y `kubectl apply -f k8s/service.yaml`.
2. **Serie B**: con `externalTrafficPolicy: Local` (como viene ahora) y `kubectl apply -f k8s/service.yaml`.

Entre repeticiones: reconecten el worker, esperen a que esté `Ready` y reinicien el despliegue (`kubectl -n edge rollout restart deploy/edge-infer`) para que vuelva a haber un pod por worker. Usen solo las IP de los workers en `--endpoints`. Reporten el resumen de cada corrida tal cual salga; no promedien a ojo ni elijan la mejor.

## 7. Dashboard

Ver `docs/dashboard.md`. Levanta Prometheus y Grafana en la laptop con `monitoring/docker-compose.yml`.

## 8. Evidencias que conviene capturar para el informe

- Foto del montaje (mini PC, switch, cables) y diagrama de red.
- `k get nodes -o wide` con las tres IPs estáticas.
- Salida de `ip a` y del archivo de netplan de cada nodo.
- `k -n edge get pods -o wide` antes, durante y después de la caída.
- Salida de `train.py`, `metrics.json`, `model_comparison.csv` y la matriz de confusión.
- Resumen de `failover_test.py` y su gráfica, de las 3 repeticiones.
- Capturas del dashboard durante la caída.
- Lectura de un medidor USB de consumo en reposo y bajo carga (si lo consiguen).

## 9. Problemas frecuentes

| Síntoma | Causa probable |
| --- | --- |
| El pendrive de Ubuntu no arranca | Firmware UEFI de 32 bits: falta `bootia32.efi` en el pendrive |
| Pod en `ErrImageNeverPull` | La imagen no se importó en ese worker (`k3s ctr images import`) |
| Pod en `CrashLoopBackOff` y el log dice que no carga el modelo | Distinta versión de scikit-learn entre el entrenamiento y la imagen |
| El worker no se une | Token mal copiado, puerto 6443 bloqueado, IP del master incorrecta o `--flannel-iface` con un nombre que no existe |
| El master va muy lento o K3s se reinicia | Poca RAM: revisa con `free -m`, no corras nada más en el master |
| `exec format error` | La imagen se construyó para otra arquitectura; usa `--platform linux/amd64` |
| El cliente no llega al NodePort | Revisa que la laptop tenga IP en 192.168.100.0/24 y que el switch esté encendido |
