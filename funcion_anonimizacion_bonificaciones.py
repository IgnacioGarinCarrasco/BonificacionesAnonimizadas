import pandas as pd
import hashlib
import os
import shutil
import streamlit as st
from io import BytesIO
import zipfile



def procesar_bonificaciones(archivo_existente, archivo_nuevo, archivo_mapeo):
    
    def anonimizar_id(valor):
        """Función interna para anonimizar valores determinísticamente"""
        return hashlib.sha256(str(valor).encode()).hexdigest()[:10]
    
    # Crear respaldos
    for ruta in [archivo_existente, archivo_mapeo]:
        if os.path.exists(ruta):
            shutil.copy(ruta, ruta.replace(".xlsx", "_respaldo.xlsx"))
    
    # Cargar mapeos globales existentes
    mapeos_globales = {}
    if os.path.exists(archivo_mapeo):
        xls = pd.ExcelFile(archivo_mapeo)
        for hoja in xls.sheet_names:
            df_mapeo = pd.read_excel(archivo_mapeo, sheet_name=hoja)
            if len(df_mapeo.columns) >= 2:
                col_real, col_anon = df_mapeo.columns[:2]
                clave = "Rut 1" if any(x in hoja for x in ["Rut 1", "Rut beneficiario"]) else \
                    "Rut 2" if any(x in hoja for x in ["Rut 2", "RUT Trabajador"]) else \
                    "ID SAP" if any(x in hoja for x in ["ID SAP", "No.Personal"]) else hoja
                mapeos_globales[clave] = dict(zip(df_mapeo[col_real], df_mapeo[col_anon]))
    
    # Cargar archivos de datos
    df_existente = pd.read_excel(archivo_existente)
    df_nuevo = pd.read_excel(archivo_nuevo)
    
    # Eliminar columnas sensibles si existen
    cols_eliminar = [
        "BE_AP_PAT_ASEG", "BE_AP_MAT_ASEG", "BE_NOMB_ASEG",
        "BE_AP_PAT_PACI", "BE_AP_MAT_PACI", "BE_NOMB_PACI"
    ]
    df_nuevo = df_nuevo.drop(columns=[c for c in cols_eliminar if c in df_nuevo.columns])
    
    # Mapeo de grupos de columnas
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
                nuevos_valores = {}
                
                for valor in df_nuevo[col].dropna().unique():
                    if pd.notna(valor) and valor not in mapeo:
                        anon = anonimizar_id(valor)
                        mapeo[valor] = anon
                        nuevos_valores[valor] = anon
                
                mapeos_globales[grupo_base] = mapeo
                df_nuevo[col] = df_nuevo[col].map(mapeo)
                break
    
    # Alinear columnas y concatenar
    columnas_comunes = [col for col in df_nuevo.columns if col in df_existente.columns]
    df_nuevo = df_nuevo[columnas_comunes]
    df_final = pd.concat([df_existente, df_nuevo], ignore_index=True)
    
    # Guardar resultados
    #df_final.to_excel(archivo_existente, index=False)
    
    # Actualizar mapeo global
    with pd.ExcelWriter(archivo_mapeo) as writer:
        for grupo, mapeo in mapeos_globales.items():
            df_mapeo = pd.DataFrame(list(mapeo.items()), columns=[f"{grupo}_real", f"{grupo}_anon"])
            nombre_hoja = f"Grupo_{grupo}"[:31]  # Limitar a 31 caracteres (límite de Excel)
            df_mapeo.to_excel(writer, sheet_name=nombre_hoja, index=False)

    return df_final, df_mapeo


# ---------------- Streamlit ----------------

st.title("Anonimización de Bonificaciones")

archivo_nuevo = st.file_uploader("📄 Suba el archivo de bonificaciones del año actual", type=["xls", "xlsx"])
archivo_existente = st.file_uploader("📄 Suba el archivo del mes a agregar", type=["xls", "xlsx"])
archivo_mapeo = st.file_uploader("📄 Suba el archivo de diccionario ID anonimizados", type=["xls", "xlsx"])


# Si los archivos fueron cargados y no hay resultados previos en session_state
if archivo_nuevo and archivo_existente and archivo_mapeo and "df_procesado" not in st.session_state:
    try:
        with st.spinner("⏳ Estamos procesando los archivos, por favor espere..."):
            # Guardar archivos temporales
            with open("tmp_existente.xlsx", "wb") as f:
                f.write(archivo_existente.getbuffer())
            with open("tmp_nuevo.xlsx", "wb") as f:
                f.write(archivo_nuevo.getbuffer())
            with open("tmp_mapeo.xlsx", "wb") as f:
                f.write(archivo_mapeo.getbuffer())

            # Ejecutar función principal
            df_procesado, df_mapeo = procesar_bonificaciones("tmp_existente.xlsx", "tmp_nuevo.xlsx", "tmp_mapeo.xlsx")

            # Crear un archivo ZIP en memoria
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                # Archivo procesado
                procesado_buffer = BytesIO()
                with pd.ExcelWriter(procesado_buffer, engine='openpyxl') as writer:
                    df_procesado.to_excel(writer, index=False, sheet_name='Procesado')
                procesado_buffer.seek(0)
                zip_file.writestr("Bonificaciones_Procesadas.xlsx", procesado_buffer.getvalue())

                # Archivo de mapeo
                mapeo_buffer = BytesIO()
                with pd.ExcelWriter(mapeo_buffer, engine='openpyxl') as writer:
                    df_mapeo.to_excel(writer, index=False, sheet_name='Diccionario')
                mapeo_buffer.seek(0)
                zip_file.writestr("Diccionario_Anonimizacion.xlsx", mapeo_buffer.getvalue())

            zip_buffer.seek(0)

        # Guardar en session_state
        st.session_state["df_procesado"] = df_procesado
        st.session_state["zip_output"] = zip_buffer

        st.success("✅ Archivos procesados con éxito")

        # Eliminar archivos temporales
        for f in ["tmp_existente.xlsx", "tmp_nuevo.xlsx", "tmp_mapeo.xlsx"]:
            if os.path.exists(f):
                os.remove(f)

    except Exception as e:
        st.error(f"❌ Ocurrió un error: {e}")

# Mostrar los resultados si ya están en memoria
if "df_procesado" in st.session_state:
    #st.dataframe(st.session_state["df_procesado"].head())

    st.download_button(
        label="📦 Descargar ZIP con archivos Excel",
        data=st.session_state["zip_output"],
        file_name="Anonimizacion_Bonificaciones.zip",
        mime="application/zip"
    )

    st.markdown("---")

    st.caption("Si desea usar nuevamente el programa, presiona las teclas: ctrl + r")
    st.caption("Puede cerrar la aplicación si ya terminó ✅")