import pandas as pd
import hashlib
import os
from io import BytesIO
import zipfile
import streamlit as st

# ---------------- FUNCIÓN PRINCIPAL -----------------

def procesar_bonificaciones(archivo_existente, archivo_nuevo, archivo_mapeo):
    """
    Procesa y anonimiza nuevas bonificaciones, actualizando el consolidado existente y el diccionario global.
    Parámetros:
        archivo_existente: ruta al Excel consolidado existente
        archivo_nuevo: ruta al nuevo archivo de bonificaciones
        archivo_mapeo: ruta al diccionario global de IDs anonimizados
    Retorna:
        df_final (DataFrame): consolidado actualizado
        mapeos_globales (dict): diccionario con todos los mapeos actualizados
    """

    def anonimizar_id(valor):
        """Anonimiza determinísticamente un valor (hash truncado a 10 caracteres)."""
        return hashlib.sha256(str(valor).encode()).hexdigest()[:10]

    # Cargar mapeos globales
    mapeos_globales = {}
    if os.path.exists(archivo_mapeo):
        xls = pd.ExcelFile(archivo_mapeo)
        for hoja in xls.sheet_names:
            nombre_hoja = hoja.replace("Grupo_", "")
            df_mapeo = pd.read_excel(archivo_mapeo, sheet_name=hoja)
            if len(df_mapeo.columns) >= 2:
                col_real, col_anon = df_mapeo.columns[:2]
                if "Rut 1" in nombre_hoja or "Rut beneficiario" in nombre_hoja:
                    clave = "Rut 1"
                elif "Rut 2" in nombre_hoja or "RUT Trabajador" in nombre_hoja:
                    clave = "Rut 2"
                elif "ID SAP" in nombre_hoja or "No.Personal" in nombre_hoja:
                    clave = "ID SAP"
                else:
                    clave = nombre_hoja
                mapeos_globales[clave] = dict(zip(df_mapeo[col_real], df_mapeo[col_anon]))

    # Cargar consolidado y nuevo archivo
    df_existente = pd.read_excel(archivo_existente)
    df_nuevo = pd.read_excel(archivo_nuevo)

    # Eliminar columnas sensibles
    cols_eliminar = [
        "BE_AP_PAT_ASEG", "BE_AP_MAT_ASEG", "BE_NOMB_ASEG",
        "BE_AP_PAT_PACI", "BE_AP_MAT_PACI", "BE_NOMB_PACI"
    ]
    df_nuevo = df_nuevo.drop(columns=[c for c in cols_eliminar if c in df_nuevo.columns])

    # Grupos de columnas para anonimizar
    grupos_columnas = {
        "Rut 1": ["Rut 1", "Rut beneficiario"],
        "Rut 2": ["Rut 2", "RUT Trabajador"],
        "ID SAP": ["ID SAP", "No.Personal"]
    }

    # Aplicar anonimización consistente
    for col in df_nuevo.columns:
        for grupo_base, columnas_grupo in grupos_columnas.items():
            if col in columnas_grupo:
                mapeo = mapeos_globales.get(grupo_base, {})
                for valor in df_nuevo[col].dropna().unique():
                    if valor not in mapeo:
                        mapeo[valor] = anonimizar_id(valor)
                df_nuevo[col] = df_nuevo[col].map(mapeo)
                mapeos_globales[grupo_base] = mapeo
                break

    # Alinear columnas con el consolidado
    df_nuevo = df_nuevo[df_existente.columns]

    # Concatenar
    df_final = pd.concat([df_existente, df_nuevo], ignore_index=True)

    # Guardar resultados actualizados
    df_final.to_excel(archivo_existente, index=False)

    # Guardar mapeos actualizados
    with pd.ExcelWriter(archivo_mapeo, mode="w") as writer:
        for grupo, mapeo in mapeos_globales.items():
            df_mapeo = pd.DataFrame(list(mapeo.items()), columns=[f"{grupo}_real", f"{grupo}_anon"])
            df_mapeo.to_excel(writer, sheet_name=f"Grupo_{grupo}"[:31], index=False)

    return df_final, mapeos_globales


# ---------------- FUNCIÓN AUXILIAR -----------------

nombre_columnas = {
    "Rut 1": ["Rut 1_real","Rut 1_anon"],
    "Rut 2":["Rut 2_real","Rut 2_anon"],
    "ID SAP": ["ID SAP_real","ID SAP_anon"]
}

def guardar_diccionario_en_excel(diccionario, nombre_archivo, nombre_columnas):
    """Genera un Excel con los mapeos, con nombres de columnas personalizados."""
    with pd.ExcelWriter(nombre_archivo, engine='openpyxl') as writer:
        for hoja, subdic in diccionario.items():
            cols = nombre_columnas.get(hoja, ['Llave', 'Valor'])
            df = pd.DataFrame(list(subdic.items()), columns=cols)
            df.to_excel(writer, sheet_name=hoja, index=False)
    return nombre_archivo



# ---------------- APP STREAMLIT -----------------

st.title("Anonimización de Bonificaciones")

archivo_nuevo = st.file_uploader("📄 Suba el archivo del mes a agregar", type=["xls", "xlsx"])
archivo_existente = st.file_uploader("📄 Suba el archivo de bonificaciones del año actual", type=["xls", "xlsx"])
archivo_mapeo = st.file_uploader("📄 Suba el archivo de diccionario ID anonimizados", type=["xls", "xlsx"])

if archivo_nuevo and archivo_existente and archivo_mapeo and "df_procesado" not in st.session_state:
    try:
        with st.spinner("⏳ Procesando los archivos, por favor espere..."):
            # Guardar archivos temporales
            with open("tmp_existente.xlsx", "wb") as f:
                f.write(archivo_existente.getbuffer())
            with open("tmp_nuevo.xlsx", "wb") as f:
                f.write(archivo_nuevo.getbuffer())
            with open("tmp_mapeo.xlsx", "wb") as f:
                f.write(archivo_mapeo.getbuffer())

            # Ejecutar función principal
            df_procesado, mapeos_globales = procesar_bonificaciones(
                "tmp_existente.xlsx", "tmp_nuevo.xlsx", "tmp_mapeo.xlsx"
            )

            # Crear archivos Excel en memoria
            procesado_buffer = BytesIO()
            with pd.ExcelWriter(procesado_buffer, engine='openpyxl') as writer:
                df_procesado.to_excel(writer, index=False, sheet_name='Procesado')
            procesado_buffer.seek(0)

            # Crear Excel de mapeos usando la función auxiliar
            mapeo_buffer = BytesIO()
            with pd.ExcelWriter(mapeo_buffer, engine='openpyxl') as writer:
                for hoja, subdic in mapeos_globales.items():
                    cols = nombre_columnas.get(hoja, ['Llave', 'Valor'])
                    df_m = pd.DataFrame(list(subdic.items()), columns=cols)
                    df_m.to_excel(writer, sheet_name=hoja, index=False)
            mapeo_buffer.seek(0)

            # Empaquetar ambos en un ZIP
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr("Bonificaciones_Procesadas.xlsx", procesado_buffer.getvalue())
                zip_file.writestr("Diccionario_Anonimizacion.xlsx", mapeo_buffer.getvalue())
            zip_buffer.seek(0)

        st.session_state["df_procesado"] = df_procesado
        st.session_state["zip_output"] = zip_buffer

        st.success("✅ Archivos procesados con éxito")

        # Limpiar archivos temporales
        for f in ["tmp_existente.xlsx", "tmp_nuevo.xlsx", "tmp_mapeo.xlsx"]:
            if os.path.exists(f):
                os.remove(f)

    except Exception as e:
        st.error(f"❌ Ocurrió un error: {e}")

if "df_procesado" in st.session_state:
    st.download_button(
        label="📦 Descargar ZIP con archivos Excel",
        data=st.session_state["zip_output"],
        file_name="Anonimizacion_Bonificaciones.zip",
        mime="application/zip"
    )
    st.markdown("---")
    st.caption("Si desea usar nuevamente el programa, presione **Ctrl + R** para reiniciar.")
