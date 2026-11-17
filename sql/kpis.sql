-- Requêtes KPI du dashboard de performance opérationnelle.
-- Portables SQLite / PostgreSQL. Paramètres : :start, :end (dates).

-- name: kpi_global
SELECT
    COUNT(*)                                                         AS flights,
    AVG(CASE WHEN arr_delay < 15 THEN 1.0 ELSE 0.0 END)              AS otp15,
    AVG(CASE WHEN dep_delay < 15 THEN 1.0 ELSE 0.0 END)              AS dep_otp15,
    AVG(dep_delay)                                                   AS avg_dep_delay,
    AVG(CASE WHEN arr_delay > 0 THEN arr_delay ELSE 0 END)           AS avg_arr_delay_pos,
    SUM(CASE WHEN arr_delay > 0 THEN arr_delay ELSE 0 END)           AS total_delay_min,
    SUM(CASE WHEN arr_delay >= 180 THEN 1 ELSE 0 END)                AS flights_over_3h,
    SUM(delay_late_aircraft) * 1.0
        / NULLIF(SUM(delay_carrier + delay_weather + delay_nas + delay_late_aircraft), 0) AS reactionary_share
FROM flights
WHERE flight_date BETWEEN :start AND :end AND cancelled = 0;

-- name: kpi_daily
SELECT
    flight_date,
    COUNT(*)                                                AS flights,
    AVG(CASE WHEN arr_delay < 15 THEN 1.0 ELSE 0.0 END)     AS otp15,
    AVG(dep_delay)                                          AS avg_dep_delay,
    SUM(delay_late_aircraft)                                AS late_aircraft_min,
    SUM(delay_weather)                                      AS weather_min,
    SUM(delay_nas)                                          AS nas_min,
    SUM(delay_carrier)                                      AS carrier_min
FROM flights
WHERE flight_date BETWEEN :start AND :end AND cancelled = 0
GROUP BY flight_date
ORDER BY flight_date;

-- name: kpi_causes
SELECT
    SUM(delay_late_aircraft) AS late_aircraft,
    SUM(delay_nas)           AS nas,
    SUM(delay_weather)       AS weather,
    SUM(delay_carrier)       AS carrier
FROM flights
WHERE flight_date BETWEEN :start AND :end AND cancelled = 0;

-- name: kpi_by_airport
SELECT
    origin                                                  AS airport,
    COUNT(*)                                                AS departures,
    AVG(CASE WHEN dep_delay < 15 THEN 1.0 ELSE 0.0 END)     AS dep_otp15,
    AVG(dep_delay)                                          AS avg_dep_delay,
    SUM(delay_weather) * 1.0 / NULLIF(COUNT(*), 0)          AS weather_min_per_flight,
    SUM(delay_nas) * 1.0 / NULLIF(COUNT(*), 0)              AS nas_min_per_flight
FROM flights
WHERE flight_date BETWEEN :start AND :end AND cancelled = 0
GROUP BY origin
ORDER BY avg_dep_delay DESC;

-- name: kpi_worst_routes
SELECT
    origin, dest,
    COUNT(*)                                                AS flights,
    AVG(arr_delay)                                          AS avg_arr_delay,
    AVG(CASE WHEN arr_delay >= 15 THEN 1.0 ELSE 0.0 END)    AS delay15_rate
FROM flights
WHERE flight_date BETWEEN :start AND :end AND cancelled = 0
GROUP BY origin, dest
HAVING COUNT(*) >= 10
ORDER BY avg_arr_delay DESC
LIMIT 10;

-- name: kpi_tails
SELECT
    tail_number,
    COUNT(*)                                                AS legs,
    SUM(delay_late_aircraft)                                AS reactionary_min,
    AVG(CASE WHEN arr_delay >= 15 THEN 1.0 ELSE 0.0 END)    AS delay15_rate
FROM flights
WHERE flight_date BETWEEN :start AND :end AND cancelled = 0
GROUP BY tail_number
ORDER BY reactionary_min DESC
LIMIT 10;
