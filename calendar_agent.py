import os
import logging
import unicodedata
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from rich.logging import RichHandler
from openai import AsyncAzureOpenAI
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    function_tool,
    set_tracing_disabled,
)

# Configuración básica de logging y entorno
logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler()])
load_dotenv()
set_tracing_disabled(True)

# Configuración de Azure OpenAI
endpoint = os.getenv("ENDPOINT_URL")
deployment = os.getenv("DEPLOYMENT_NAME")
subscription_key = os.getenv("AZURE_OPENAI_API_KEY")
api_version = os.getenv("OPENAI_API_VERSION", "2025-01-01-preview")

if not all([endpoint, deployment, subscription_key]):
    raise RuntimeError("Faltan variables de entorno para inicializar Azure OpenAI.")

client = AsyncAzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=subscription_key,
)

MODEL_NAME = deployment
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

def authenticate_google_calendar():
    """Maneja la autenticación OAuth 2.0 y genera o refresca token.json."""
    creds = None
    
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    return creds

# Inicializar autenticación al cargar el módulo
authenticate_google_calendar()


@function_tool
def get_current_date() -> str:
    """Obtiene la fecha y hora actual exacta en la zona horaria UTC-4."""
    tz_local = timezone(timedelta(hours=-4))
    return datetime.now(tz_local).strftime("%Y-%m-%d %H:%M:%S")


@function_tool
def create_calendar_event(summary: str, start_time: str, end_time: str, description: str = "") -> str:
    """Crea un nuevo evento en el Google Calendar principal."""
    if not os.path.exists('token.json'):
        return "Error: No se encontró 'token.json'."
        
    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        service = build('calendar', 'v3', credentials=creds)

        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_time, 'timeZone': 'America/La_Paz'},
            'end': {'dateTime': end_time, 'timeZone': 'America/La_Paz'},
        }

        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return f"Éxito: Evento '{summary}' creado correctamente. Enlace: {created_event.get('htmlLink')}"
        
    except Exception as e:
        return f"Error al crear el evento: {str(e)}"


@function_tool
def check_calendar_availability(start_time: str, end_time: str) -> str:
    """Verifica si hay eventos programados en un rango de tiempo específico."""
    if not os.path.exists('token.json'):
        return "Error: No se encontró 'token.json'."

    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        service = build('calendar', 'v3', credentials=creds)

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
        
        conflict_details = "ATENCIÓN: Se encontraron los siguientes eventos en ese horario:\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Sin título')
            conflict_details += f"- '{summary}' programado a las {start}\n"
            
        return conflict_details

    except Exception as e:
        return f"Error al leer el calendario: {str(e)}"


@function_tool
def delete_calendar_event(event_summary: str, date_iso: str) -> str:
    """Busca un evento por su título exacto o aproximado en una fecha y lo elimina."""
    if not os.path.exists('token.json'):
        return "Error: No se encontró 'token.json'."

    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        service = build('calendar', 'v3', credentials=creds)

        time_min = f"{date_iso}T00:00:00-04:00"
        time_max = f"{date_iso}T23:59:59-04:00"

        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True
        ).execute()
        
        events = events_result.get('items', [])

        if not events:
            return f"Error: No hay ningún evento programado para la fecha {date_iso}."
        
        # Normalizar texto para ignorar tildes y mayúsculas
        def normalizar(texto):
            return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').lower().strip()
        
        term = normalizar(event_summary)
        event_to_delete = None
        
        for event in events:
            title = normalizar(event.get('summary', ''))
            if term in title or title in term:
                event_to_delete = event
                break
        
        if not event_to_delete:
            nombres_reales = [e.get('summary', 'Sin título') for e in events]
            return f"No se encontró '{event_summary}'. Los eventos reales que tienes este día son: {', '.join(nombres_reales)}. Vuelve a intentarlo usando uno de estos nombres exactos."
        
        event_id = event_to_delete['id']
        event_title = event_to_delete.get('summary', 'Sin título')
        
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        return f"Éxito: El evento '{event_title}' del {date_iso} ha sido eliminado correctamente del calendario."

    except Exception as e:
        return f"Error al intentar eliminar el evento: {str(e)}"

# Definición del Agente
calendar_assistant = Agent(
    name="Calendar Assistant",
    instructions=(
        "Eres un asistente personal experto en gestión de tiempo, productividad y organización de agendas. "
        "Tu objetivo es gestionar el Google Calendar del usuario mediante la creación, verificación y reprogramación de eventos. "
        "Reglas estrictas:\n"
        "1. CONTEXTO TEMPORAL: Siempre usa get_current_date para obtener la fecha y hora actual antes de hacer cálculos temporales.\n"
        "2. PREVENCIÓN DE ERRORES: Si falta la duración o la hora de inicio/fin para agendar, DEBES preguntarlo primero.\n"
        "3. ZONA HORARIA: Asume siempre America/La_Paz (Bolivia, UTC-4).\n"
        "4. REPROGRAMACIÓN: Si el usuario pide reprogramar o mover un evento, DEBES realizar dos pasos secuenciales: "
        "   Primero, usa 'delete_calendar_event' para borrar el evento original. "
        "   Segundo, usa 'create_calendar_event' para agendarlo en el nuevo horario (siempre verificando conflictos antes con check_calendar_availability).\n"
        "5. LÍMITE DE DOMINIO ESTRICTO: Eres única y exclusivamente un asistente de Google Calendar. Tienes terminantemente prohibido responder preguntas generales, realizar tareas académicas, escribir código o generar cualquier contenido no relacionado con la agenda. Niégate educadamente si se te pide salir de este rol.\n"
        "6. CÁLCULO DE FECHAS ESTRICTO: Verifica si el año es bisiesto antes de asignar el día 29 a febrero. Nunca envíes fechas matemáticamente inválidas y asegúrate de que la fecha de inicio sea siempre anterior a la de fin.\n"
        "7. CONFIRMACIÓN: Una vez realizadas las acciones, responde de manera concisa proporcionando confirmación y el enlace al evento."        
    ),
    tools=[get_current_date, check_calendar_availability, create_calendar_event, delete_calendar_event], 
    model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
)