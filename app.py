import streamlit as st
import asyncio
from calendar_agent import calendar_assistant, Runner

st.set_page_config(page_title="Calendar AI", page_icon="🗓️")
st.title("🗓️ Asistente de Google Calendar")

# Inicializamos el estado de los mensajes
if "messages" not in st.session_state:
    st.session_state.messages = []

# Dibujamos el historial en la interfaz
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("¿Qué agendamos hoy?"):
    
    # Mostramos el mensaje del usuario en la pantalla
    with st.chat_message("user"):
        st.markdown(prompt)
        
    # --- LA MAGIA DE LA MEMORIA EMPIEZA AQUÍ ---
    # 1. Recorremos los mensajes anteriores para armar un "resumen" de la charla
    historial_texto = "Historial de la conversación:\n"
    for msg in st.session_state.messages[-6:]: # Tomamos solo los últimos 6 mensajes para no saturar al modelo
        rol = "Usuario" if msg["role"] == "user" else "Asistente"
        historial_texto += f"{rol}: {msg['content']}\n"
        
    # 2. Unimos el historial con el mensaje actual para darle todo el contexto al agente
    prompt_con_memoria = f"{historial_texto}\nUsuario: {prompt}\n\n(Instrucción: Responde a la última petición del usuario teniendo en cuenta el contexto del historial)."
    # --- FIN DE LA MAGIA ---

    # Guardamos el mensaje en Streamlit
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Pensando y revisando el calendario..."):
            try:
                # Le enviamos al agente el prompt "dopado" con toda la memoria
                result = asyncio.run(Runner.run(calendar_assistant, input=prompt_con_memoria))
                respuesta = result.final_output
            except Exception as e:
                respuesta = f"Error: {e}"
            
        st.markdown(respuesta)
    
    # Guardamos la respuesta del agente
    st.session_state.messages.append({"role": "assistant", "content": respuesta})