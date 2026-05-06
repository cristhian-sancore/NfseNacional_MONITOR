import os
import requests
import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
import database
import models
import schemas
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Painel Monitor NFE")

# Criar tabelas
models.Base.metadata.create_all(bind=database.engine)

# Montar pasta de arquivos estáticos
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Segurança e Autenticação
bearer_scheme = HTTPBearer()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def get_current_username(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if not hasattr(app.state, "valid_tokens"):
        app.state.valid_tokens = {}
    
    token_info = app.state.valid_tokens.get(credentials.credentials)
    if not token_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão inválida"
        )
        
    now = datetime.now(timezone.utc)
    if (now - token_info["created_at"]).total_seconds() > 86400: # 24 horas
        del app.state.valid_tokens[credentials.credentials]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada. Faça login novamente."
        )
        
    return "admin"

class LoginData(BaseModel):
    username: str
    password: str

@app.post("/api/login")
def login(data: LoginData, request: Request):
    if not hasattr(app.state, "login_attempts"):
        app.state.login_attempts = {}
        
    client_ip = request.client.host
    now = datetime.now(timezone.utc)
    
    # Verifica Rate Limit
    if client_ip in app.state.login_attempts:
        attempts_info = app.state.login_attempts[client_ip]
        if attempts_info["count"] >= 5:
            if (now - attempts_info["last_attempt"]).total_seconds() < 900: # 15 minutos
                raise HTTPException(status_code=429, detail="Muitas tentativas falhas. Bloqueado por 15 minutos.")
            else:
                # Reset após 15 min
                app.state.login_attempts[client_ip] = {"count": 0, "last_attempt": now}
    else:
        app.state.login_attempts[client_ip] = {"count": 0, "last_attempt": now}

    correct_username = secrets.compare_digest(data.username, os.getenv("ADMIN_USER", "admin"))
    correct_password = secrets.compare_digest(data.password, os.getenv("ADMIN_PASS", "f@$p3l"))
    
    if not (correct_username and correct_password):
        app.state.login_attempts[client_ip]["count"] += 1
        app.state.login_attempts[client_ip]["last_attempt"] = now
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
    
    # Login de sucesso limpa falhas
    app.state.login_attempts[client_ip] = {"count": 0, "last_attempt": now}
    
    token = secrets.token_hex(32)
    if not hasattr(app.state, "valid_tokens"):
        app.state.valid_tokens = {}
        
    app.state.valid_tokens[token] = {"created_at": now}
    
    return {"access_token": token, "token_type": "bearer"}

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != os.getenv("WEBHOOK_KEY", "FASPEL_KEY_2026"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    return api_key


def get_settings(db: Session):
    settings = db.query(models.SystemSettings).first()
    if not settings:
        settings = models.SystemSettings(
            evo_url=os.getenv("EVOLUTION_API_URL", ""),
            evo_token=os.getenv("EVOLUTION_APIKEY", ""),
            evo_instance=os.getenv("EVOLUTION_INSTANCE", ""),
            evo_number=os.getenv("EVOLUTION_NUMBER", ""),
            summary_interval_hours=12.0,
            last_summary_sent=datetime.now(timezone.utc)
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

def send_whatsapp_message(text: str, db: Session = None):
    close_db = False
    if db is None:
        db = database.SessionLocal()
        close_db = True
        
    try:
        settings = get_settings(db)
        if not all([settings.evo_url, settings.evo_instance, settings.evo_token, settings.evo_number]):
            print("Configuração da Evolution API incompleta. Mensagem não enviada.")
            return

        # Remove barra do final se existir
        url = settings.evo_url.rstrip("/")
        endpoint = f"{url}/message/sendText/{settings.evo_instance}"
        headers = {
            "apikey": settings.evo_token,
            "Content-Type": "application/json"
        }
        
        payload = {
            "number": settings.evo_number,
            "text": text,
            "delay": 1200
        }
        
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"Mensagem enviada com sucesso para {settings.evo_number}")
        return response.json()
    except Exception as e:
        print(f"Falha ao notificar WhatsApp: {e}")
    finally:
        if close_db:
            db.close()

async def summary_worker():
    while True:
        try:
            db = database.SessionLocal()
            settings = get_settings(db)
            
            now = datetime.now(timezone.utc)
            last_sent = settings.last_summary_sent
            
            if last_sent and last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            
            if not last_sent:
                last_sent = now - timedelta(hours=settings.summary_interval_hours)
                settings.last_summary_sent = last_sent
                db.commit()

            interval_seconds = settings.summary_interval_hours * 3600
            
            if (now - last_sent).total_seconds() >= interval_seconds:
                logs = db.query(models.ErrorLog).filter(models.ErrorLog.created_at >= last_sent).all()
                total_errors = len(logs)
                
                text = f"📊 *Resumo Monitor NFE ({settings.summary_interval_hours}h)* 📊\n\n"
                text += f"Nas últimas {settings.summary_interval_hours}h, tivemos:\n"
                text += f"⚠️ *{total_errors} novos erros* registrados.\n"
                
                if total_errors > 0:
                    from collections import Counter
                    entities = Counter([l.entity_name for l in logs])
                    top_entity = entities.most_common(1)[0]
                    text += f"🏢 Entidade com mais problemas: *{top_entity[0]}* ({top_entity[1]} erros)\n"
                else:
                    text += "✅ Nenhum erro ocorreu neste período!\n"
                
                send_whatsapp_message(text, db)
                
                settings.last_summary_sent = now
                db.commit()
                
            db.close()
        except Exception as e:
            print(f"Erro no summary_worker: {e}")
        
        await asyncio.sleep(60)

async def grouped_alerts_worker():
    # Envia notificações a cada 15 minutos com os erros acumulados no período
    INTERVAL_MINUTES = 15
    last_grouped_send = datetime.now(timezone.utc)
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            if (now - last_grouped_send).total_seconds() >= INTERVAL_MINUTES * 60:
                db = database.SessionLocal()
                
                # Buscar erros que ocorreram desde o último envio agrupado
                logs = db.query(models.ErrorLog).filter(models.ErrorLog.created_at >= last_grouped_send).all()
                
                if logs:
                    total_errors = len(logs)
                    from collections import Counter
                    entities = Counter([l.entity_name for l in logs])
                    categories = Counter([l.error_category for l in logs])
                    
                    text = f"🚨 *Novos Erros ({INTERVAL_MINUTES} min)* 🚨\n\n"
                    text += f"Total: {total_errors} novos erros\n\n"
                    
                    text += "🏢 *Entidades:*\n"
                    for ent, count in entities.items():
                        text += f"  • {ent}: {count} erros\n"
                    
                    text += "\n⚠️ *Principais Tipos:*\n"
                    for cat, count in categories.most_common(5):
                        text += f"  • {cat}: {count}\n"
                        
                    send_whatsapp_message(text, db)
                
                last_grouped_send = now
                db.close()
        except Exception as e:
            print(f"Erro no grouped_alerts_worker: {e}")
            
        await asyncio.sleep(30)

async def heartbeat_worker():
    while True:
        try:
            db = database.SessionLocal()
            now = datetime.now(timezone.utc)
            ten_minutes_ago = now - timedelta(minutes=10)
            
            # Buscar agentes inativos que não foram notificados (is_offline == 0)
            offline_agents = db.query(models.AgentHeartbeat).filter(
                models.AgentHeartbeat.last_ping < ten_minutes_ago,
                models.AgentHeartbeat.is_offline == 0
            ).all()
            
            for agent in offline_agents:
                agent.is_offline = 1
                text = (
                    f"⚠️ *ALERTA DE QUEDA DE AGENTE* ⚠️\n\n"
                    f"O servidor/agente da entidade *{agent.entity_name}* parou de responder há mais de 10 minutos!\n"
                    f"Verifique se o computador foi desligado ou o serviço interrompido."
                )
                send_whatsapp_message(text) # Cria sessão própria
            
            db.commit()
            db.close()
        except Exception as e:
            print(f"Erro no heartbeat_worker: {e}")
            
        await asyncio.sleep(60) # Checa a cada minuto

async def cleanup_worker():
    while True:
        try:
            db = database.SessionLocal()
            now = datetime.now(timezone.utc)
            thirty_days_ago = now - timedelta(days=30)
            
            # Remover erros com mais de 30 dias
            deleted = db.query(models.ErrorLog).filter(models.ErrorLog.created_at < thirty_days_ago).delete()
            if deleted > 0:
                db.commit()
                print(f"Limpeza Automática: {deleted} registros antigos deletados.")
                
            db.close()
        except Exception as e:
            print(f"Erro no cleanup_worker: {e}")
            
        # Roda a limpeza 1 vez por dia (24h)
        await asyncio.sleep(86400)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(summary_worker())
    asyncio.create_task(grouped_alerts_worker())
    asyncio.create_task(heartbeat_worker())
    asyncio.create_task(cleanup_worker())

@app.post("/api/heartbeat")
def receive_heartbeat(
    hb: schemas.AgentHeartbeatCreate, 
    db: Session = Depends(database.get_db),
    api_key: str = Depends(verify_api_key)
):
    agent = db.query(models.AgentHeartbeat).filter(models.AgentHeartbeat.entity_name == hb.entity_name).first()
    now = datetime.now(timezone.utc)
    
    if agent:
        # Se estava offline e voltou, manda aviso de reconexão
        if agent.is_offline == 1:
            agent.is_offline = 0
            text = f"✅ *Agente Reconectado*\n\nO servidor da entidade *{agent.entity_name}* voltou a responder!"
            background_tasks = BackgroundTasks()
            background_tasks.add_task(send_whatsapp_message, text, None)
            
        agent.last_ping = now
    else:
        agent = models.AgentHeartbeat(entity_name=hb.entity_name, last_ping=now, is_offline=0)
        db.add(agent)
        
    db.commit()
    return {"status": "ok"}

@app.post("/api/webhook", response_model=schemas.ErrorLogResponse)
def receive_error_log(
    log: schemas.ErrorLogCreate, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(database.get_db),
    api_key: str = Depends(verify_api_key)
):
    db_log = models.ErrorLog(**log.model_dump())
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    
    # Se for uma notificação CRÍTICA (Queda de servidor), avisa na hora (Fura-Fila)
    if "Inacessível" in log.error_category or "Restaurado" in log.error_category:
        text = (
            f"🚨 *ALERTA CRÍTICO* 🚨\n\n"
            f"🏢 *Entidade:* {log.entity_name}\n"
            f"⚠️ *Status:* {log.error_category}\n"
            f"📄 *Detalhe:* {log.original_error[:200]}"
        )
        background_tasks.add_task(send_whatsapp_message, text, None)
    
    # Erros normais de nota fiscal agora vão apenas pro banco e serão pegos pelo grouped_alerts_worker (15 em 15 min)
    
    return db_log

@app.get("/api/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(database.get_db), username: str = Depends(get_current_username)):
    total_errors = db.query(models.ErrorLog).count()
    common_errors = db.query(
        models.ErrorLog.error_category, 
        func.count(models.ErrorLog.id).label('count')
    ).group_by(models.ErrorLog.error_category).order_by(func.count(models.ErrorLog.id).desc()).limit(5).all()
    
    entities = db.query(
        models.ErrorLog.entity_name, 
        func.count(models.ErrorLog.id).label('count')
    ).group_by(models.ErrorLog.entity_name).order_by(func.count(models.ErrorLog.id).desc()).limit(5).all()
    
    latest = db.query(models.ErrorLog).order_by(models.ErrorLog.created_at.desc()).limit(10).all()
    
    return {
        "total": total_errors,
        "common_errors": [{"category": c[0], "count": c[1]} for c in common_errors],
        "top_entities": [{"entity": e[0], "count": e[1]} for e in entities],
        "latest": [{"id": l.id, "entity": l.entity_name, "category": l.error_category, "date": l.created_at.isoformat()} for l in latest]
    }

@app.get("/api/settings", response_model=schemas.SystemSettingsResponse)
def api_get_settings(db: Session = Depends(database.get_db), username: str = Depends(get_current_username)):
    return get_settings(db)

@app.post("/api/settings", response_model=schemas.SystemSettingsResponse)
def api_update_settings(settings_data: schemas.SystemSettingsUpdate, db: Session = Depends(database.get_db), username: str = Depends(get_current_username)):
    settings = get_settings(db)
    settings.evo_url = settings_data.evo_url
    settings.evo_token = settings_data.evo_token
    settings.evo_instance = settings_data.evo_instance
    settings.evo_number = settings_data.evo_number
    settings.summary_interval_hours = settings_data.summary_interval_hours
    db.commit()
    db.refresh(settings)
    return settings

@app.delete("/api/errors/clear")
def clear_error_history(db: Session = Depends(database.get_db), username: str = Depends(get_current_username)):
    try:
        deleted = db.query(models.ErrorLog).delete()
        db.commit()
        return {"status": "success", "message": f"{deleted} registros apagados com sucesso."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/settings/test")
def api_test_whatsapp(db: Session = Depends(database.get_db), username: str = Depends(get_current_username)):
    try:
        text = "✅ *Teste de Conexão*\n\nSe você recebeu esta mensagem, significa que o Painel do Monitor NFE está configurado corretamente e pronto para enviar os alertas!"
        
        # Teste não deve ser background, para que o usuário receba feedback visual do sucesso/erro na hora
        settings = get_settings(db)
        if not all([settings.evo_url, settings.evo_instance, settings.evo_token, settings.evo_number]):
            raise Exception("Configuração incompleta")
        
        url = settings.evo_url.rstrip("/")
        endpoint = f"{url}/message/sendText/{settings.evo_instance}"
        headers = {
            "apikey": settings.evo_token,
            "Content-Type": "application/json"
        }
        payload = {
            "number": settings.evo_number,
            "text": text,
            "delay": 1200
        }
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        return {"status": "success", "message": "Mensagem enviada com sucesso!", "details": response.json()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()
