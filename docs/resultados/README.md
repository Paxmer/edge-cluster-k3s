# Resultados registrados por el equipo

Pruebas ejecutadas en el clúster real (3 mini PC, IP 192.168.1.26, .27 y .28), con `failover_test.py --rate 5 --duration 60`, desconectando el cable de red de un worker. Los datos del modelo son sintéticos.

| Corrida | Worker desconectado | Peticiones | Éxito final | Primer intento | Mediana / p95 | Mayor ventana sin servicio |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | worker1 | 118 | 106 (89,83 %) | 90 (76,27 %) | 28,0 / 833,6 ms | 2,6 s |
| 2 | worker2 | 118 | 106 (89,83 %) | 92 (77,97 %) | 28,8 / 843,9 ms | 5,1 s |

Es una sola corrida por condición, así que no permite estimar la variación entre repeticiones. Las capturas y gráficas de estas corridas están en el informe.

El informe completo (PDF) describe el método, la discusión y las limitaciones.

## Serie A/B (corte a ~30 s, 150 s por corrida)

- Corridas A1 a A3 con la política `Cluster` y B1 a B3 con `Local`, alternando el trabajador desconectado (worker1, worker2, worker1).
- Con `Cluster` hubo 11 a 13 peticiones sin respuesta por corrida, concentradas unos 40 s tras el corte; con `Local`, ninguna. Las cifras se leyeron de las gráficas; se pueden recalcular con `python analizar_csv.py archivo.csv --cut-at 30`.
- Con el trabajador caído, el pod de reemplazo queda `Pending` por la anti-afinidad estricta.
- Con el cable al router desconectado, el simulador completó 30 lecturas (operación sin Internet).
- Memoria usada: unos 580 MB de 1 571 MB por trabajador; el master, entre 982 y 1 003 MB.
