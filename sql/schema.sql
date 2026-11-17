-- AeroOps Intelligence - schéma relationnel
-- Compatible SQLite (mode local) et PostgreSQL (docker-compose).
-- Les colonnes de retard suivent la nomenclature BTS (US DOT) pour que
-- les données réelles et les données de démonstration partagent le même schéma.

CREATE TABLE IF NOT EXISTS airports (
    iata          VARCHAR(3) PRIMARY KEY,
    icao          VARCHAR(4) NOT NULL,
    name          VARCHAR(80) NOT NULL,
    lat           REAL NOT NULL,
    lon           REAL NOT NULL,
    is_hub        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS aircraft (
    tail_number   VARCHAR(10) PRIMARY KEY,
    ac_type       VARCHAR(8) NOT NULL,
    seats         INTEGER NOT NULL,
    base          VARCHAR(3) NOT NULL,
    is_spare      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS flights (
    flight_id            VARCHAR(32) PRIMARY KEY,
    flight_date          DATE NOT NULL,
    carrier              VARCHAR(3) NOT NULL,
    flight_number        VARCHAR(8) NOT NULL,
    tail_number          VARCHAR(10),
    origin               VARCHAR(3) NOT NULL,
    dest                 VARCHAR(3) NOT NULL,
    sched_dep            TIMESTAMP NOT NULL,
    sched_arr            TIMESTAMP NOT NULL,
    actual_dep           TIMESTAMP,
    actual_arr           TIMESTAMP,
    dep_delay            REAL,
    arr_delay            REAL,
    distance_km          REAL NOT NULL,
    seats                INTEGER,
    cancelled            INTEGER NOT NULL DEFAULT 0,
    delay_carrier        REAL DEFAULT 0,
    delay_weather        REAL DEFAULT 0,
    delay_nas            REAL DEFAULT 0,   -- ATC / contrôle aérien / capacité aéroport
    delay_late_aircraft  REAL DEFAULT 0    -- retard réactionnaire (avion en retard sur le leg précédent)
);
CREATE INDEX IF NOT EXISTS ix_flights_date ON flights (flight_date);
CREATE INDEX IF NOT EXISTS ix_flights_tail ON flights (tail_number, sched_dep);

CREATE TABLE IF NOT EXISTS weather_hourly (
    airport        VARCHAR(3) NOT NULL,
    ts             TIMESTAMP NOT NULL,      -- heure pleine
    temp_c         REAL,
    wind_kt        REAL,
    gust_kt        REAL,
    visibility_km  REAL,
    precip_mm      REAL,
    ceiling_ft     REAL,
    thunderstorm   INTEGER DEFAULT 0,
    snow           INTEGER DEFAULT 0,
    PRIMARY KEY (airport, ts)
);

CREATE TABLE IF NOT EXISTS predictions (
    flight_id          VARCHAR(32) NOT NULL,
    model_name         VARCHAR(20) NOT NULL,   -- 'tactical' ou 'strategic'
    pred_delay_min     REAL NOT NULL,
    prob_delay15       REAL NOT NULL,
    top_factor         VARCHAR(40),
    scored_at          TIMESTAMP NOT NULL,
    PRIMARY KEY (flight_id, model_name)
);
