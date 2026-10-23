"""
EJERCICIO 5 - Calidad de datos en ventas
Carga 'ventas_con_problemas.csv', detecta y corrige problemas de calidad,
genera un informe, visualizaciones y guarda 'ventas_limpias.csv'.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# ----------------------------------------------------------------------
# CONFIGURACIÓN
# ----------------------------------------------------------------------
RUTA_ENTRADA = "ventas_con_problemas.csv"
RUTA_SALIDA = "ventas_limpias.csv"
RUTA_INFORME = "informe_calidad.txt"

CRITICOS = ["fecha", "producto", "cantidad", "precio_unitario", "total"]
NUMERICOS = ["cantidad", "precio_unitario", "total"]
K_IQR = 3.0   # 1.5 = outliers "normales", 3.0 = outliers extremos (más conservador)
TOL = 0.01    # tolerancia (en €) al comparar cantidad * precio con el total

sns.set_theme(style="whitegrid")

problemas = []   # una entrada por tipo de problema
embudo = []      # nº de filas tras cada etapa


def registrar(tipo, detectados, corregidos, eliminados):
    problemas.append({
        "tipo": tipo,
        "detectados": int(detectados),
        "corregidos": int(corregidos),
        "eliminados": int(eliminados),
    })


def etapa(nombre, df):
    embudo.append((nombre, len(df)))


# ----------------------------------------------------------------------
# 1. CARGA Y EXPLORACIÓN INICIAL
# ----------------------------------------------------------------------
# Leemos todo como texto para no perder información (fechas raras, etc.)
raw = pd.read_csv(RUTA_ENTRADA, dtype=str)
raw = raw.apply(lambda c: c.str.strip()).replace("", np.nan)

df = raw.copy()
for col in NUMERICOS:
    df[col] = pd.to_numeric(df[col], errors="coerce")
df_antes = df.copy()          # copia "sucia" para las gráficas
n_original = len(df)
etapa("Original", df)

print("=" * 60)
print("EXPLORACIÓN INICIAL")
print("=" * 60)
print(f"Dimensiones: {df.shape[0]} filas x {df.shape[1]} columnas\n")
print(df.head(), "\n")
print("Tipos de datos:\n", df.dtypes, "\n")
print("Nulos por columna:\n", df.isna().sum(), "\n")
print(f"Filas duplicadas exactas: {raw.duplicated().sum()}\n")
print("Estadísticas descriptivas (datos originales):\n", df[NUMERICOS].describe().round(2), "\n")

# ----------------------------------------------------------------------
# 2-3. DETECCIÓN Y LIMPIEZA
# Cada fila se cuenta en la etapa donde se elimina, así que los números
# del informe cuadran con el total de filas.
# ----------------------------------------------------------------------

# --- 3.1 Valores nulos --------------------------------------------------
nulos_por_columna = df[CRITICOS].isna().sum()
filas_con_nulos = df[CRITICOS].isna().any(axis=1)

# Fecha y producto no se pueden inventar -> se eliminan
sin_fecha_producto = df["fecha"].isna() | df["producto"].isna()
df = df[~sin_fecha_producto].copy()

# En los numéricos se puede recuperar el campo que falta con los otros dos
nulos_num_antes = df[NUMERICOS].isna().any(axis=1).sum()

cand = df["total"] / df["precio_unitario"]
m = (df["cantidad"].isna() & df["precio_unitario"].notna() & df["total"].notna()
     & (df["precio_unitario"] != 0) & ((cand - cand.round()).abs() < TOL))
df.loc[m, "cantidad"] = cand[m].round()

m = (df["precio_unitario"].isna() & df["cantidad"].notna() & df["total"].notna()
     & (df["cantidad"] != 0))
df.loc[m, "precio_unitario"] = (df["total"] / df["cantidad"])[m].round(2)

m = df["total"].isna() & df["cantidad"].notna() & df["precio_unitario"].notna()
df.loc[m, "total"] = (df["cantidad"] * df["precio_unitario"])[m].round(2)

recuperadas = nulos_num_antes - df[NUMERICOS].isna().any(axis=1).sum()
df = df.dropna(subset=NUMERICOS).copy()   # los que no se pueden recuperar

registrar("Valores nulos (filas)", filas_con_nulos.sum(), recuperadas,
          filas_con_nulos.sum() - recuperadas)
etapa("Tras nulos", df)

# --- 3.2 Fechas inválidas -----------------------------------------------
fecha_dt = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
invalidas = fecha_dt.isna()
registrar("Fechas inválidas", invalidas.sum(), 0, invalidas.sum())
df = df[~invalidas].copy()
df["fecha"] = fecha_dt[~invalidas]
etapa("Tras fechas", df)

# --- 3.3 Valores negativos ----------------------------------------------
# cantidad < 0     -> devoluciones: no son ventas, se eliminan
# precio < 0       -> error de signo: se corrige con el valor absoluto
# total < 0 (resto)-> se recalcula como cantidad * precio
neg_q = df["cantidad"] < 0
neg_p = df["precio_unitario"] < 0
neg_t = df["total"] < 0
for nombre, mascara in [("cantidad", neg_q), ("precio_unitario", neg_p), ("total", neg_t)]:
    registrar(f"Negativos en {nombre}", mascara.sum(),
              (mascara & ~neg_q).sum(), (mascara & neg_q).sum())

df = df[~neg_q].copy()
df["precio_unitario"] = df["precio_unitario"].abs()
mt = neg_t.loc[df.index]
df.loc[mt, "total"] = (df["cantidad"] * df["precio_unitario"]).round(2)[mt]
etapa("Tras negativos", df)

# --- 3.4 Inconsistencias en el total ------------------------------------
total_calc = (df["cantidad"] * df["precio_unitario"]).round(2)
incons = (df["total"] - total_calc).abs() > TOL
registrar("Total inconsistente", incons.sum(), incons.sum(), 0)
df.loc[incons, "total"] = total_calc[incons]
etapa("Tras inconsistencias", df)

# --- 3.5 Duplicados (antes que los outliers para no sesgar los cuartiles)
dup = df.duplicated(subset=CRITICOS, keep="first")
registrar("Duplicados", dup.sum(), 0, dup.sum())
df = df[~dup].copy()
etapa("Tras duplicados", df)


# --- 3.6 Outliers (método IQR) ------------------------------------------
def outliers_iqr(serie, grupos=None, k=K_IQR):
    """True donde el valor queda fuera de [Q1 - k*IQR, Q3 + k*IQR]."""
    if grupos is None:
        q1, q3 = serie.quantile(0.25), serie.quantile(0.75)
    else:
        q1 = serie.groupby(grupos).transform(lambda s: s.quantile(0.25))
        q3 = serie.groupby(grupos).transform(lambda s: s.quantile(0.75))
    iqr = q3 - q1
    return (serie < q1 - k * iqr) | (serie > q3 + k * iqr)


# cantidad: IQR global; precio y total: IQR por producto (cada producto tiene su rango)
out_q = outliers_iqr(df["cantidad"])
out_p = outliers_iqr(df["precio_unitario"], df["producto"])
out_t = outliers_iqr(df["total"], df["producto"])

registrar("Outliers en cantidad", out_q.sum(), 0, out_q.sum())
registrar("Outliers en precio_unitario", out_p.sum(), 0, (out_p & ~out_q).sum())
registrar("Outliers en total", out_t.sum(), 0, (out_t & ~out_q & ~out_p).sum())

df = df[~(out_q | out_p | out_t)].copy()
etapa("Tras outliers", df)

# ----------------------------------------------------------------------
# DATOS LIMPIOS
# ----------------------------------------------------------------------
df = df.sort_values("fecha").reset_index(drop=True)
df["cantidad"] = df["cantidad"].astype(int)
n_final = len(df)

# Comprobaciones finales
assert df[CRITICOS].notna().all().all()
assert (df[NUMERICOS] > 0).all().all()
assert ((df["cantidad"] * df["precio_unitario"] - df["total"]).abs() <= TOL).all()
assert not df.duplicated().any()

# ----------------------------------------------------------------------
# 4. INFORME
# ----------------------------------------------------------------------
tabla = pd.DataFrame(problemas)
stats = df[NUMERICOS].agg(["mean", "median", "std"]).round(2)

lineas = [
    "=" * 60,
    "INFORME DE CALIDAD DE DATOS",
    "=" * 60,
    f"Filas originales:          {n_original}",
    f"Filas tras la limpieza:    {n_final}",
    f"Filas eliminadas:          {n_original - n_final} "
    f"({(n_original - n_final) / n_original:.1%})",
    "",
    "Nulos por columna (datos originales):",
    nulos_por_columna.to_string(),
    "",
    "Problemas identificados y tratados:",
    tabla.to_string(index=False),
    "",
    "Nota: una fila con varios problemas se cuenta en la etapa en la que se elimina.",
    "",
    "Evolución del nº de filas:",
    "\n".join(f"  {n:<22}{f}" for n, f in embudo),
    "",
    "Estadísticas descriptivas de los datos limpios:",
    stats.to_string(),
]
informe = "\n".join(lineas)
print(informe)
with open(RUTA_INFORME, "w", encoding="utf-8") as f:
    f.write(informe)

# ----------------------------------------------------------------------
# 5. VISUALIZACIONES
# ----------------------------------------------------------------------
# Figura 1: filas por etapa y problemas por tipo
fig, ax = plt.subplots(1, 2, figsize=(15, 5))
nombres, filas = zip(*embudo)
sns.barplot(x=list(filas), y=list(nombres), color="steelblue", ax=ax[0])
ax[0].set_title("Filas tras cada etapa de limpieza")
ax[0].set_xlabel("Nº de filas")
largo = tabla.melt(id_vars="tipo", value_vars=["detectados", "corregidos", "eliminados"],
                   var_name="acción", value_name="n")
sns.barplot(data=largo, y="tipo", x="n", hue="acción", ax=ax[1])
ax[1].set_title("Problemas detectados, corregidos y eliminados")
ax[1].set_xlabel("Nº de filas")
ax[1].set_ylabel("")
plt.tight_layout()
plt.savefig("fig1_resumen_limpieza.png", dpi=150)

# Figura 2: distribuciones antes (escala log en Y) y después
fig, ax = plt.subplots(2, 3, figsize=(15, 8))
for i, col in enumerate(NUMERICOS):
    sns.histplot(df_antes[col].dropna(), bins=40, color="indianred", ax=ax[0, i])
    ax[0, i].set_yscale("log")
    ax[0, i].set_title(f"{col} - ANTES (eje Y log)")
    sns.histplot(df[col], bins=30, color="seagreen", ax=ax[1, i])
    ax[1, i].set_title(f"{col} - DESPUÉS")
plt.tight_layout()
plt.savefig("fig2_distribuciones_antes_despues.png", dpi=150)

# Figura 3: boxplots por producto y ventas diarias (datos limpios)
fig, ax = plt.subplots(1, 2, figsize=(16, 6))
sns.boxplot(data=df, x="precio_unitario", y="producto", ax=ax[0])
ax[0].set_title("Precio unitario por producto (datos limpios)")
ventas_dia = df.groupby("fecha")["total"].sum()
ax[1].plot(ventas_dia.index, ventas_dia.values, marker="o")
ax[1].set_title("Ventas totales por día (datos limpios)")
ax[1].set_ylabel("€")
ax[1].tick_params(axis="x", rotation=45)
plt.tight_layout()
plt.savefig("fig3_productos_y_ventas_diarias.png", dpi=150)

plt.show()

# ----------------------------------------------------------------------
# 6. GUARDAR DATOS LIMPIOS
# ----------------------------------------------------------------------
df_out = df.copy()
df_out["fecha"] = df_out["fecha"].dt.strftime("%Y-%m-%d")
df_out.to_csv(RUTA_SALIDA, index=False)
print(f"\nDatos limpios guardados en '{RUTA_SALIDA}' ({n_final} filas)")
