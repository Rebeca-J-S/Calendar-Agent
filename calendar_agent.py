import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from rich.logging import RichHandler

import yfinance as yf
from openai import AsyncAzureOpenAI
from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    function_tool,
    set_tracing_disabled,
)

# ----- Logging bonito en consola -----
logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler()])

# Cargar variables del .env
load_dotenv()

# Desactivar tracing si no lo usas
set_tracing_disabled(True)

# ----- Azure OpenAI Configuration -----
endpoint = os.getenv("ENDPOINT_URL")
deployment = os.getenv("DEPLOYMENT_NAME")
subscription_key = os.getenv("AZURE_OPENAI_API_KEY")
api_version = os.getenv("OPENAI_API_VERSION", "2025-01-01-preview")

if not all([endpoint, deployment, subscription_key]):
    raise RuntimeError(
        "Faltan variables de entorno: ENDPOINT_URL, DEPLOYMENT_NAME o AZURE_OPENAI_API_KEY."
    )

client = AsyncAzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=subscription_key,
)

MODEL_NAME = deployment

from datetime import datetime, timezone, timedelta

@function_tool
def get_current_date() -> str:
    """Obtiene la fecha y hora actual exacta para que el agente tenga contexto temporal."""
    # Configuramos la zona horaria local (UTC-4)
    tz_local = timezone(timedelta(hours=-4))
    
    # Retornamos fecha y hora en un formato fácil de entender para la IA
    return datetime.now(tz_local).strftime("%Y-%m-%d %H:%M:%S")

import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Los permisos que el agente necesita (leer y escribir eventos)
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

def authenticate_google_calendar():
    creds = None
    
    # Verifica si ya existe el token.json de una sesión anterior
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Si no hay credenciales válidas o expiraron, te pedirá iniciar sesión
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # AQUÍ es donde el código lee el archivo credentials.json que se acaba de descargar
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            
            # Esto abrirá una pestaña en el navegador web
            creds = flow.run_local_server(port=0)
        
        # Guarda el token generado para que el agente lo use automáticamente después
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    print("¡Autenticación exitosa! El archivo token.json se ha creado correctamente.")
    return creds

# Ejecutamos la función de autenticación
authenticate_google_calendar()


import os
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# CREAR UN EVENTO EN EL CALENDARIO ----------------------------------
@function_tool
def create_calendar_event(summary: str, start_time: str, end_time: str, description: str = "") -> str:
    """
    Crea un nuevo evento en el Google Calendar principal del usuario.
    
    Args:
        summary: El título o resumen del evento.
        start_time: Fecha y hora de inicio en formato ISO 8601 (ej. '2026-02-26T10:00:00-04:00').
        end_time: Fecha y hora de finalización en formato ISO 8601 (ej. '2026-02-26T11:00:00-04:00').
        description: Detalles opcionales del evento.
    """
    SCOPES = ['https://www.googleapis.com/auth/calendar.events']
    
    # 1. Verificar que el token exista (generado en el paso anterior)
    if not os.path.exists('token.json'):
        return "Error: No se encontró 'token.json'. Por favor, ejecuta la autenticación primero."
        
    try:
        # 2. Cargar las credenciales
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
        # 3. Construir el cliente de la API de Google Calendar
        service = build('calendar', 'v3', credentials=creds)

        # 4. Estructurar el evento
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'America/La_Paz', # Zona horaria ajustada a tu ubicación
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'America/La_Paz',
            },
        }

        # 5. Insertar el evento en el calendario principal
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        
        # Devolvemos un mensaje de éxito con el enlace para que el Agente se lo muestre al usuario
        return f"Éxito: Evento '{summary}' creado correctamente. Enlace: {created_event.get('htmlLink')}"
        
    except Exception as e:
        # Es importante devolver los errores como texto para que el agente sepa qué falló
        return f"Error de la API al crear el evento: {str(e)}"
    

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os

# VERIFICAR DISPONIBILIDAD EN EL CALENDARIO ----------------------------------
@function_tool
def check_calendar_availability(start_time: str, end_time: str) -> str:
    """
    Verifica si hay eventos programados en el calendario del usuario en un rango de tiempo específico.
    
    Args:
        start_time: Fecha y hora de inicio a revisar en formato ISO 8601 (ej. '2026-02-26T15:00:00-04:00').
        end_time: Fecha y hora de fin a revisar en formato ISO 8601 (ej. '2026-02-26T16:00:00-04:00').
    """
    if not os.path.exists('token.json'):
        return "Error: No se encontró 'token.json'."

    try:
        creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/calendar.events'])
        service = build('calendar', 'v3', credentials=creds)

        # Llamar a la API para listar eventos en ese rango de tiempo
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_time,
            timeMax=end_time,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])

        if not events:
            return "El horario está libre. No hay conflictos."
        
        # Si hay eventos, armamos un reporte para que la IA lo lea
        conflict_details = "ATENCIÓN: Se encontraron los siguientes eventos en ese horario:\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Sin título')
            conflict_details += f"- '{summary}' programado a las {start}\n"
            
        return conflict_details

    except Exception as e:
        return f"Error al leer el calendario: {str(e)}"
    

import unicodedata

# ELIMINAR UN EVENTO DEL CALENDARIO ----------------------------------
@function_tool
def delete_calendar_event(event_summary: str, date_iso: str) -> str:
    """
    Busca un evento por su título en una fecha específica y lo elimina del calendario.
    Debe usarse cuando el usuario pide cancelar o reprogramar un evento.
    
    Args:
        event_summary: El título o nombre del evento a eliminar (ej. 'Cita con mi novia').
        date_iso: La fecha en la que ocurre el evento original, en formato YYYY-MM-DD (ej. '2026-02-27').
    """
    import os
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    
    if not os.path.exists('token.json'):
        return "Error: No se encontró 'token.json'."

    try:
        creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/calendar.events'])
        service = build('calendar', 'v3', credentials=creds)

        # Rango para abarcar todo el día
        time_min = f"{date_iso}T00:00:00-04:00"
        time_max = f"{date_iso}T23:59:59-04:00"

        # Obtenemos TODOS los eventos de ese día sin el parámetro 'q'
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True
        ).execute()
        
        events = events_result.get('items', [])

        if not events:
            return f"Error: No hay ningún evento programado para la fecha {date_iso}."
        
        # Función para quitar tildes y pasar a minúsculas
        def normalizar(texto):
            return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').lower().strip()
        
        term = normalizar(event_summary)
        event_to_delete = None
        
        # Búsqueda flexible en Python
        for event in events:
            title = normalizar(event.get('summary', ''))
            if term in title or title in term:
                event_to_delete = event
                break
        
        # Si la IA se equivoca, le pasamos los datos reales para que se corrija
        if not event_to_delete:
            nombres_reales = [e.get('summary', 'Sin título') for e in events]
            return f"No se encontró '{event_summary}'. Los eventos reales que tienes este día son: {', '.join(nombres_reales)}. Vuelve a intentarlo usando uno de estos nombres exactos."
        
        # Ejecutamos la eliminación
        event_id = event_to_delete['id']
        event_title = event_to_delete.get('summary', 'Sin título')
        
        service.events().delete(calendarId='primary', eventId=event_id).execute()
            
        return f"Éxito: El evento '{event_title}' del {date_iso} ha sido eliminado correctamente del calendario."

    except Exception as e:
        return f"Error al intentar eliminar el evento: {str(e)}"
    
calendar_assistant = Agent(
    name="Calendar Assistant",
    instructions=(
        "Eres un asistente personal experto en gestión de tiempo, productividad y organización de agendas. "
        "Tu objetivo es gestionar el Google Calendar del usuario mediante la creación, verificación y reprogramación de eventos. "
        "Reglas estrictas:\n"
        "1. CONTEXTO TEMPORAL: Siempre usa get_current_date para obtener la fecha y hora actual antes de hacer cálculos temporales.\n"
        "2. PREVENCIÓN DE ERRORES: Si falta la duración o la hora de inicio/fin para agendar, DEBES preguntarlo primero.\n"
        "3. ZONA HORARIA: Asume siempre America/La_Paz (Bolivia, UTC-4).\n"
        "4. REPROGRAMACIÓN (NUEVO): Si el usuario pide reprogramar o mover un evento, DEBES realizar dos pasos secuenciales: "
        "   Primero, usa 'delete_calendar_event' para borrar el evento original. "
        "   Segundo, usa 'create_calendar_event' para agendarlo en el nuevo horario (siempre verificando conflictos antes con check_calendar_availability).\n"
        "5. LÍMITE DE DOMINIO ESTRICTO (SEGURIDAD): Eres única y exclusivamente un asistente de Google Calendar. Tienes terminantemente prohibido responder preguntas generales, realizar tareas académicas, escribir código, traducir texto o generar cualquier contenido que no esté directa y estrictamente relacionado con la lectura, creación o reprogramación de eventos en el calendario. Si el usuario te pide algo fuera de este ámbito, debes negarte educadamente de forma inmediata, indicando que tu única función es gestionar la agenda."
        "6. CÁLCULO DE FECHAS ESTRICTO: Cuando debas consultar rangos de tiempo largos (como un mes completo), asegúrate de calcular correctamente el último día del mes. Verifica si el año es bisiesto antes de asignar el día 29 a febrero (ej. 2026 NO es bisiesto, febrero tiene 28 días). Nunca envíes fechas matemáticamente inválidas a las herramientas y asegúrate de que la fecha de inicio sea siempre anterior a la fecha de fin."
        "7. CONFIRMACIÓN: Una vez creado el evento con éxito, responde de manera concisa proporcionando confirmacion a las acciones realizadas (eliminaciones, creaciones o reprogramaciones) y el enlace al evento."        
    ),
    # Agregamos la nueva tool a la lista
    tools=[get_current_date, check_calendar_availability, create_calendar_event, delete_calendar_event], 
    model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
)