# Dashboard en Grafana: paneles y consultas

> Nota: esta guía no se aplicó en el clúster físico (no se desplegaron Prometheus ni Grafana para no sobrecargar la RAM y la CPU de los nodos). Se conserva como referencia.

1. En la laptop: `cd monitoring && docker compose up -d`.
2. Abre http://localhost:3000 (usuario `admin`, contraseña `admin`).
3. Agrega la fuente de datos Prometheus con la URL `http://prometheus:9090`.
4. Crea un panel por cada fila de esta tabla (modo "Code" en el editor de consultas).

Antes, en cada nodo (ya queda instalado en el paso 2 del README): `sudo apt install -y prometheus-node-exporter`.

| Panel | Consulta PromQL | Qué muestra |
| --- | --- | --- |
| Nodos activos (uptime del servicio) | `up{job="nodos"}` | 1 = el nodo responde, 0 = caído |
| Tiempo encendido por nodo | `time() - node_boot_time_seconds` | Segundos desde el arranque |
| Peticiones por segundo por pod | `sum by (pod, node) (rate(edge_requests_total{endpoint="/predict",status="200"}[15s]))` | Se ve cómo un pod deja de recibir y el otro sube |
| Latencia de inferencia p95 | `histogram_quantile(0.95, sum by (le) (rate(edge_request_duration_seconds_bucket[30s])))` | Latencia del modelo, en segundos |
| Errores de validación | `sum(rate(edge_requests_total{endpoint="/predict",status="400"}[30s]))` | Peticiones rechazadas por datos inválidos |
| Alertas por clase | `sum by (label) (rate(edge_predictions_total[30s]))` | Cuántas lecturas se clasifican en cada clase |
| Temperatura de CPU | `node_thermal_zone_temp` | °C de cada nodo (verifica el nombre de la métrica en tu nodo) |
| Consumo | Medidor USB entre la fuente y el mini PC | Se anota a mano (W) en reposo y bajo carga; no sale de Prometheus |

Nota: el job `inferencia` consulta el NodePort, así que cada consulta cae en uno de los pods. Como las series llevan las etiquetas `pod` y `node`, el panel de peticiones por pod funciona, pero usen una ventana de `rate` de al menos 15 s.
